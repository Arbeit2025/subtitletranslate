# subtitletranslate（字幕かんたん翻訳）
# 単一ファイル Flask アプリ。SRT字幕をアップロードし、訳文を編集して
# 時刻・番号を保ったまま SRT をダウンロードできる。
# 翻訳エンジン: Azure Translator（環境変数がある場合のみ）。
# 未設定の場合は手動編集モード。ファイルはサーバーに保存しない。DBなし。
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import List, Optional

from flask import Flask, request, redirect, url_for, flash, render_template_string, Response

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "subtitletranslate-dev-key")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # アップロード上限 2MB

DEFAULT_ENDPOINT = "https://api.cognitive.microsofttranslator.com"

LANGUAGES = [
    ("en", "英語"),
    ("ja", "日本語"),
    ("zh-Hans", "中国語（簡体字）"),
    ("ko", "韓国語"),
    ("fr", "フランス語"),
    ("de", "ドイツ語"),
    ("es", "スペイン語"),
]


# ============================
# SRT パース / 再構成
# ============================
class Cue:
    def __init__(self, index: str, start: str, end: str, text: str, translation: str = ""):
        self.index = index
        self.start = start
        self.end = end
        self.text = text
        self.translation = translation


def parse_srt(content: str) -> List[Cue]:
    """SRT文字列を Cue のリストに変換する。時刻文字列は原文のまま保持する。"""
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    blocks = [b for b in normalized.strip().split("\n\n") if b.strip()]
    cues: List[Cue] = []
    for block in blocks:
        lines = block.split("\n")
        if len(lines) < 2:
            continue
        index = lines[0].strip()
        timing = lines[1].strip()
        if "-->" not in timing:
            # 番号行が無い形式にも簡易対応する
            if "-->" in index:
                timing = index
                index = str(len(cues) + 1)
                text_lines = lines[1:]
            else:
                continue
        else:
            text_lines = lines[2:]
        parts = timing.split("-->")
        start = parts[0].strip()
        end = parts[1].strip().split(" ")[0] if len(parts) > 1 else ""
        cues.append(Cue(index=index, start=start, end=end, text="\n".join(text_lines)))
    return cues


def build_srt(cues: List[Cue], use_translation: bool = True) -> str:
    """Cue のリストから SRT 文字列を再構成する。番号・時刻はそのまま使う。"""
    out_blocks = []
    for cue in cues:
        body = cue.translation if (use_translation and cue.translation.strip()) else cue.text
        out_blocks.append(f"{cue.index}\n{cue.start} --> {cue.end}\n{body}")
    return "\n\n".join(out_blocks) + "\n"


# ============================
# Azure Translator（差し替え可能な翻訳関数）
# ============================
def azure_configured() -> bool:
    return bool(os.environ.get("AZURE_TRANSLATOR_KEY") and os.environ.get("AZURE_TRANSLATOR_REGION"))


def translate_texts(texts: List[str], from_lang: str, to_lang: str) -> List[str]:
    """Azure Translator で texts を一括翻訳する。テストでは差し替え可能。"""
    key = os.environ["AZURE_TRANSLATOR_KEY"]
    region = os.environ["AZURE_TRANSLATOR_REGION"]
    endpoint = os.environ.get("AZURE_TRANSLATOR_ENDPOINT", DEFAULT_ENDPOINT).rstrip("/")
    url = f"{endpoint}/translate?api-version=3.0&from={from_lang}&to={to_lang}"
    results: List[str] = []
    # API の要素数上限に合わせて 100 件ずつ送る
    for i in range(0, len(texts), 100):
        chunk = texts[i:i + 100]
        body = json.dumps([{"Text": t} for t in chunk]).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Ocp-Apim-Subscription-Key", key)
        req.add_header("Ocp-Apim-Subscription-Region", region)
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for item in data:
            results.append(item["translations"][0]["text"])
    return results


# ============================
# 画面（HTML テンプレート）
# ============================
BASE_STYLE = """
<style>
  body { font-family: sans-serif; margin: 2em auto; max-width: 860px; padding: 0 1em; line-height: 1.6; }
  h1 { font-size: 1.4em; }
  .mode { background: #fff3cd; border: 1px solid #e0c96a; padding: .6em 1em; border-radius: 6px; }
  .mode.ok { background: #e2f0d9; border-color: #9db98a; }
  .flash { background: #f8d7da; border: 1px solid #e0a3ab; padding: .6em 1em; border-radius: 6px; }
  table { border-collapse: collapse; width: 100%; margin: 1em 0; }
  th, td { border: 1px solid #ccc; padding: .4em .5em; vertical-align: top; text-align: left; }
  th { background: #f2f2f2; }
  textarea { width: 100%; box-sizing: border-box; }
  .time { white-space: nowrap; font-size: .85em; color: #555; }
  button { padding: .5em 1.2em; font-size: 1em; cursor: pointer; }
  pre { white-space: pre-wrap; margin: 0; }
</style>
"""

INDEX_HTML = """<!DOCTYPE html>
<html lang="ja">
<head><meta charset="utf-8"><title>字幕かんたん翻訳</title>""" + BASE_STYLE + """</head>
<body>
<h1>🎬 字幕かんたん翻訳</h1>
{% with messages = get_flashed_messages() %}
  {% for m in messages %}<p class="flash">{{ m }}</p>{% endfor %}
{% endwith %}
{% if azure %}
<p class="mode ok">自動翻訳モード：Azure Translator で翻訳します。</p>
{% else %}
<p class="mode">翻訳キー未設定：手動編集モード（訳文は次の画面で手で編集できます）</p>
{% endif %}
<p>SRT字幕ファイル（.srt、2MBまで）をアップロードしてください。ファイルはサーバーに保存されません。</p>
<form method="post" action="{{ url_for('upload') }}" enctype="multipart/form-data">
  <p><input type="file" name="file" accept=".srt" required></p>
  <p>
    翻訳元:
    <select name="from_lang">
      {% for code, name in languages %}<option value="{{ code }}" {% if code == 'en' %}selected{% endif %}>{{ name }}</option>{% endfor %}
    </select>
    →
    翻訳先:
    <select name="to_lang">
      {% for code, name in languages %}<option value="{{ code }}" {% if code == 'ja' %}selected{% endif %}>{{ name }}</option>{% endfor %}
    </select>
  </p>
  <p><button type="submit">アップロードして編集へ</button></p>
</form>
</body>
</html>
"""

EDIT_HTML = """<!DOCTYPE html>
<html lang="ja">
<head><meta charset="utf-8"><title>訳文の編集｜字幕かんたん翻訳</title>""" + BASE_STYLE + """</head>
<body>
<h1>✏️ 訳文の編集</h1>
{% with messages = get_flashed_messages() %}
  {% for m in messages %}<p class="flash">{{ m }}</p>{% endfor %}
{% endwith %}
{% if azure %}
<p class="mode ok">自動翻訳モード：Azure Translator の訳文が入っています。必要に応じて直してください。</p>
{% else %}
<p class="mode">翻訳キー未設定：手動編集モード（訳文欄に自分で入力してください。空欄の行は原文のまま出力されます）</p>
{% endif %}
<p>{{ cues|length }} 件の字幕があります。時刻と番号は原文のまま保持されます。</p>
<form method="post" action="{{ url_for('download') }}">
<table>
<tr><th>番号</th><th>時刻</th><th>原文</th><th>訳文</th></tr>
{% for cue in cues %}
<tr>
  <td>{{ cue.index }}</td>
  <td class="time">{{ cue.start }}<br>→ {{ cue.end }}</td>
  <td><pre>{{ cue.text }}</pre></td>
  <td>
    <textarea name="trans_{{ loop.index0 }}" rows="3">{{ cue.translation }}</textarea>
    <input type="hidden" name="index_{{ loop.index0 }}" value="{{ cue.index }}">
    <input type="hidden" name="start_{{ loop.index0 }}" value="{{ cue.start }}">
    <input type="hidden" name="end_{{ loop.index0 }}" value="{{ cue.end }}">
    <textarea name="orig_{{ loop.index0 }}" style="display:none">{{ cue.text }}</textarea>
  </td>
</tr>
{% endfor %}
</table>
<p><button type="submit">SRTをダウンロード</button></p>
</form>
<p><a href="{{ url_for('index') }}">← 最初に戻る</a></p>
</body>
</html>
"""


# ============================
# ルート
# ============================
@app.route("/", methods=["GET"])
def index():
    return render_template_string(INDEX_HTML, azure=azure_configured(), languages=LANGUAGES)


@app.route("/healthz", methods=["GET"])
def healthz():
    return {"status": "ok"}


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("file")
    if file is None or file.filename == "":
        flash("ファイルが選択されていません。")
        return redirect(url_for("index"))
    if not file.filename.lower().endswith(".srt"):
        flash("SRTファイル（.srt）のみアップロードできます。")
        return redirect(url_for("index"))
    raw = file.read()
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        flash("ファイルの文字コードが UTF-8 ではありません。")
        return redirect(url_for("index"))
    cues = parse_srt(content)
    if not cues:
        flash("字幕データを読み取れませんでした。SRT形式か確認してください。")
        return redirect(url_for("index"))
    if azure_configured():
        from_lang = request.form.get("from_lang", "en")
        to_lang = request.form.get("to_lang", "ja")
        try:
            translated = translate_texts([c.text for c in cues], from_lang, to_lang)
            for cue, text in zip(cues, translated):
                cue.translation = text
        except Exception:
            flash("自動翻訳に失敗しました。手動編集モードで続行します。")
    return render_template_string(EDIT_HTML, cues=cues, azure=azure_configured())


@app.route("/download", methods=["POST"])
def download():
    cues: List[Cue] = []
    i = 0
    while f"index_{i}" in request.form:
        cues.append(Cue(
            index=request.form[f"index_{i}"],
            start=request.form[f"start_{i}"],
            end=request.form[f"end_{i}"],
            text=request.form.get(f"orig_{i}", ""),
            translation=request.form.get(f"trans_{i}", ""),
        ))
        i += 1
    if not cues:
        flash("ダウンロードする字幕がありません。")
        return redirect(url_for("index"))
    srt = build_srt(cues, use_translation=True)
    return Response(
        srt,
        mimetype="text/plain; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=translated.srt"},
    )


@app.errorhandler(413)
def too_large(_e):
    flash("ファイルが大きすぎます。上限は2MBです。")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
