# University Rank Finder

RoR (Research Organization Registry) の大学データをベースに、QS と THE の大学ランキングを
収集・マッチングして一覧表示する FastAPI アプリです。

## データソース

| ソース | バージョン管理 | 取得方法 |
|--------|----------------|----------|
| RoR | 公式ダンプ ZIP (例: `v2.11-2026-08-03-ror-data.zip`) | https://doi.org/10.5281/zenodo.6347574 からダウンロード |
| QS | `QS{年度}` (例: QS2027) | QS 公式 Web API (cloudscraper 使用) |
| THE | `THE{年度}` (例: THE2026) | THE 公式 JSON API |
| ARWU | `ARWU{年度}` (例: ARWU2025) | shanghairanking.com 公式 API (`/api/pub/v1/arwu/rank?version={year}`) |

- バージョン・年度・公開日・取得件数は `data_sources` テーブルに記録され、`/api/stats` で確認できます。
- QS は Cloudflare 対策のため `cloudscraper` でスクレイピングします。`--nid` は年版ごとに
  `https://www.topuniversities.com/qs-world-university-rankings` のページソースから特定してください
  (自動検出は現行ページ構造では失敗するため手動指定が必須です)。
- QS のページングは 0 起点です (`page=0` が 1 位〜)。コレクタは自動で処理します。

## セットアップ

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e .
```

RoR ダンプを `data/v2.11-2026-08-03-ror-data.zip` として配置します。

## 使い方

```bash
# RoR データベース投入 (Education 組織のみ 26,837 件)
python -m scripts.collect ror --file data/v2.11-2026-08-03-ror-data.zip

# QS ランキング取得 (nid は年版ごとの数字を指定)
python -m scripts.collect qs --year 2027 --nid 4153156

# QS をローカルの CSV から投入 (例: Kaggle ダウンロード)
python -m scripts.collect qs-file --file path/to/qs.csv --year 2027

# THE ランキング取得
python -m scripts.collect the --year 2026

# ARWU ランキング取得 (上位 1000 校、最新版は 2025)
python -m scripts.collect arwu --year 2025

# 大学名マッチング実行 (RoR との対応付け)
python -m scripts.collect match

# 統計表示
python -m scripts.collect stats

# 上記を一括実行
python -m scripts.collect all
```

サーバー起動:

```bash
uvicorn app.main:app --port 8000
```

Web UI: http://127.0.0.1:8000/
API: `/api/stats`, `/api/rankings`, `/api/universities`, `/api/countries`

## テスト

```bash
python -m pytest tests/ -q
```

マッチャーの正規化ルール (逆順表記、SUNY 展開、トルコ文字・角括弧アクセント、訳語/別名) は
`app/collectors/matcher.py` に、テストは `tests/test_matcher.py` にあります。

## ディレクトリ構成

```
app/collectors/ror.py     ROR ダンプのパース
app/collectors/qs.py      QS API 収集・CSV 取込
app/collectors/the.py     THE API 収集
app/collectors/arwu.py    ARWU API 収集
app/collectors/matcher.py 大学名マッチング
app/services.py           マッチング結果・DataSource 管理の DB 投入
app/api.py                統計・一覧 API
scripts/collect.py        CLI
static/index.html         Web UI
```
