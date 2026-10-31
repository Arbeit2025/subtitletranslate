import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module

SAMPLE_SRT = """1
00:00:01,000 --> 00:00:03,500
Hello, world.

2
00:00:04,000 --> 00:00:06,000
This is a test.
Second line here.

3
00:00:07,250 --> 00:00:09,000
Goodbye.
"""


class ParseTest(unittest.TestCase):
    def test_parse_basic_and_timestamps_preserved(self):
        cues = app_module.parse_srt(SAMPLE_SRT)
        self.assertEqual(len(cues), 3)
        self.assertEqual(cues[0].index, "1")
        self.assertEqual(cues[0].start, "00:00:01,000")
        self.assertEqual(cues[0].end, "00:00:03,500")
        self.assertEqual(cues[0].text, "Hello, world.")
        self.assertEqual(cues[2].start, "00:00:07,250")
        self.assertEqual(cues[2].end, "00:00:09,000")

    def test_parse_multiline_text(self):
        cues = app_module.parse_srt(SAMPLE_SRT)
        self.assertEqual(cues[1].text, "This is a test.\nSecond line here.")

    def test_roundtrip(self):
        cues = app_module.parse_srt(SAMPLE_SRT)
        rebuilt = app_module.build_srt(cues, use_translation=False)
        self.assertEqual(rebuilt, SAMPLE_SRT)


class WebTest(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        # テスト中は Azure 未設定の状態を既定にする
        env_patcher = mock.patch.dict(os.environ, {}, clear=False)
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        for k in ("AZURE_TRANSLATOR_KEY", "AZURE_TRANSLATOR_REGION", "AZURE_TRANSLATOR_ENDPOINT"):
            os.environ.pop(k, None)

    def test_index_ok(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)

    def test_healthz(self):
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "ok")

    def test_index_shows_manual_mode_without_key(self):
        resp = self.client.get("/")
        body = resp.get_data(as_text=True)
        self.assertIn("翻訳キー未設定：手動編集モード", body)

    def test_upload_shows_cues_and_manual_mode(self):
        data = {"file": (io.BytesIO(SAMPLE_SRT.encode("utf-8")), "sample.srt")}
        resp = self.client.post("/upload", data=data, content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertIn("Hello, world.", body)
        self.assertIn("00:00:01,000", body)
        self.assertIn("翻訳キー未設定：手動編集モード", body)

    def test_reject_non_srt(self):
        data = {"file": (io.BytesIO(b"hello"), "note.txt")}
        resp = self.client.post("/upload", data=data, content_type="multipart/form-data",
                                follow_redirects=True)
        self.assertIn("SRTファイル", resp.get_data(as_text=True))

    def test_reject_too_large(self):
        big = b"1\n00:00:01,000 --> 00:00:02,000\n" + b"a" * (2 * 1024 * 1024 + 10)
        data = {"file": (io.BytesIO(big), "big.srt")}
        resp = self.client.post("/upload", data=data, content_type="multipart/form-data",
                                follow_redirects=True)
        self.assertIn("2MB", resp.get_data(as_text=True))

    def test_download_reconstructs_with_edited_translation(self):
        data = {
            "index_0": "1", "start_0": "00:00:01,000", "end_0": "00:00:03,500",
            "orig_0": "Hello, world.", "trans_0": "こんにちは、世界。",
            "index_1": "2", "start_1": "00:00:04,000", "end_1": "00:00:06,000",
            "orig_1": "This is a test.\nSecond line here.", "trans_1": "",
        }
        resp = self.client.post("/download", data=data)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment", resp.headers.get("Content-Disposition", ""))
        body = resp.get_data(as_text=True)
        self.assertIn("1\n00:00:01,000 --> 00:00:03,500\nこんにちは、世界。", body)
        # 空欄の訳文は原文のまま出力される
        self.assertIn("This is a test.\nSecond line here.", body)

    def test_auto_translate_uses_injected_translator(self):
        fake_env = {
            "AZURE_TRANSLATOR_KEY": "dummy-key",
            "AZURE_TRANSLATOR_REGION": "japaneast",
        }
        with mock.patch.dict(os.environ, fake_env):
            with mock.patch.object(app_module, "translate_texts",
                                   lambda texts, a, b: ["［訳］" + t.split("\n")[0] for t in texts]) as _:
                data = {"file": (io.BytesIO(SAMPLE_SRT.encode("utf-8")), "sample.srt"),
                        "from_lang": "en", "to_lang": "ja"}
                resp = self.client.post("/upload", data=data, content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertIn("［訳］Hello, world.", body)
        self.assertIn("自動翻訳モード", body)


if __name__ == "__main__":
    unittest.main()
