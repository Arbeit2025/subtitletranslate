# subtitletranslate（字幕かんたん翻訳）

SRT字幕ファイルをアップロードして、訳文を編集し、番号と時刻を原文のまま保持して SRT をダウンロードできる小さな Web ツールです。単一ファイル Flask アプリ（`app.py`）で、データベースは使いません。アップロードされたファイルはサーバーに保存されず、メモリ上だけで処理します。

## できること

- SRTファイル（.srt、2MBまで）をアップロードし、「番号・時刻・原文」の一覧を表示
- 訳文を画面上で編集し、編集結果で SRT を再構成してダウンロード（番号・時刻は原文のまま）
- Azure Translator のキーが設定されている場合は自動翻訳（既定は英語→日本語、画面で言語を選択可能）
- キーが未設定の場合は「翻訳キー未設定：手動編集モード」と表示され、訳文を手で編集する運用になります（空欄の行は原文のまま出力されます）

## ローカル起動

```bash
pip install -r requirements.txt
python app.py
# http://localhost:5000
```

## テスト

```bash
python -m unittest discover -s tests
```

## Azure Translator の設定（任意）

自動翻訳を使う場合は、Azure Translator のキー等を**環境変数**で渡します。キー自体をコードや Git リポジトリに書くことはありません。

| 環境変数 | 内容 |
|---|---|
| `AZURE_TRANSLATOR_KEY` | Azure Translator リソースのキー |
| `AZURE_TRANSLATOR_REGION` | リソースのリージョン（例: `japaneast`） |
| `AZURE_TRANSLATOR_ENDPOINT` | エンドポイント（任意。未設定時は `https://api.cognitive.microsofttranslator.com`） |

Render にデプロイした場合は、Render のダッシュボード（対象サービス → Environment）で、**運用者本人が**上記の環境変数を設定してください。設定するまでは手動編集モードで動作します。

## デプロイ（Render）

`render.yaml` を使って Web Service（Free）としてデプロイできます。起動コマンドは `gunicorn app:app`、ヘルスチェックは `/healthz` です。

## 注意

- 対応形式は SRT のみです。他の字幕形式（VTT、ASSなど）には対応していません。
- 文字コードは UTF-8 を想定しています（BOM付き可）。
- 自動翻訳の結果は下書きです。公開・配布前に内容を確認してください。
