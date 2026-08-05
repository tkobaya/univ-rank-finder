# AGENTS.md

RoR (Research Organization Registry) の大学データをベースに、QS・THE・ARWU の大学ランキングを
収集・マッチングして一覧表示する FastAPI アプリ。開発作業の継続用メモ。

## セットアップとコマンド

```bash
. .venv/bin/activate

# ランキング収集
python -m scripts.collect ror --file data/v2.11-2026-08-03-ror-data.zip   # RoR (Education 26,837 件)
python -m scripts.collect qs --year 2027 --nid 4153156                    # QS (nid は年版ごとに要変更)
python -m scripts.collect the --year 2026                                 # THE
python -m scripts.collect arwu --year 2025                                # ARWU (最新は 2025)
python -m scripts.collect qs-file --file path.csv --year 2027             # QS を静的ファイルから
python -m scripts.collect match                                           # マッチング実行
python -m scripts.collect all                                             # ror+the+qs+arwu+match
python -m scripts.collect stats                                           # 統計

# サーバー
uvicorn app.main:app --port 8000
# 再起動 (pkill は時々 timeout するので注意):
#   pkill -9 -f "uvicorn app.main"; sleep 1; \
#   (uvicorn app.main:app --port 8000 > /tmp/opencode/uvicorn.log 2>&1 &)

# テスト
python -m pytest tests/ -q    # 現状 26 件
```

DB は SQLite (`data/university_rankings.db`)。`data/*.db` は .gitignore 済み。

## データソースの仕様 (重要)

| ソース | バージョン管理 | 取得方法と注意 |
|--------|----------------|----------------|
| RoR | 公式ダンプ ZIP | https://doi.org/10.5281/zenodo.6347574 (Education 組織のみ投入) |
| QS | `QS{年度}` | QS 公式 Web API (cloudscraper 使用)。**ページングは 0 起点** (`page=0`=1位〜) |
| THE | `THE{年度}` | 公式 JSON API `.../json/ranking_tables/world_university_rankings/{year}` |
| ARWU | `ARWU{年度}` | `https://www.shanghairanking.com/api/pub/v1/arwu/rank?version={year}`。**最新は 2025** (`version=2026` は code=-1 を返す)。`.cn` 版は英語名が無いため不使用 |

- バージョン・年度・件数は `data_sources` テーブルに記録され `/api/stats` で確認可能。
- QS の `--nid` は年版ごとに https://www.topuniversities.com/qs-world-university-rankings の
  ページソースから特定する (自動検出 `discover_nid` は現行ページ構造で失敗するため手動必須)。
- 現在のデータ: QS 2027=1,504 / THE 2026=3,118 / ARWU 2025=1,000。

## マッチャー (`app/collectors/matcher.py`)

- `RorUniversity.search_names` = 表示名 + **aliases (別名)** + acronyms + labels。マッチの主要な
  受け皿なので「aliases に無い別名」だけが未一致になる。
- `normalize_name`: 逆順表記、NFKD + 結合文字除去 (`é→e`)、角括弧アポストロフィ除去 (`Queen's→Queens`)、
  トルコ文字 `ı→i` / `İ→I`、`&→and`、括弧除去、SUNY 展開 (`SUNY→state university of new york`)、
  種別語を英語代表形へ統一 (Universität/Université/Universidad/Universidade/universitesi/universitet→university 等)、
  ストップワード除去 (`of, the, and, de, der, le, la, van, von, di, el, o`)。
- `CountryIndex`: 国名→ISO alpha-2 コード。`COUNTRY_ALIASES` で補完 (UK→GB, Turkey/Türkiye→TR,
  China-Hong Kong→HK, China-Taiwan→TW, China-Macau→MO 等)。国コードが解けた場合は候補を国で絞り込む。
- 一致段階 (先勝ち): 完全一致 → トークン集合一致 → 略称 (`_acronym`) → 略称+都市ファジー
  (`_acronym_fuzzy`, 0.85 閾値: `LMU Munich`, `ETH Zurich`) → 接頭辞包含 (`_prefix`, トークン数差最小を優先)
  → ファジー (`_fuzzy`, SequenceMatcher 0.90。**同点は ambiguous 扱い**)。
- ステータス: `matched` / `ambiguous` / `unmatched`。
- 一致率: 5,622 件中約 5,400 件 (96%)。未一致の多くは ROR 名と大きく異なる別名
  (例: `University of Mainz` ↔ ROR `Johannes Gutenberg-Universität Mainz`)。

## API (`app/api.py`) の落とし穴 (修正済みだが再発注意)

- `year=` を空文字で送ると 422 になる → `YearParam` (`BeforeValidator` で空文字→None) を使う。
- `University.aliases.astext` は SQLite でクラッシュする → `cast(aliases, String)` を使う。
- rank/score ソートは未順位 (NULL) が先頭に来る → `_sort_rank` で asc/desc とも NULL を常に末尾へ。
- `/api/universities` の sort オプション: `name / country / rank / rank:qs / rank:the / rank:arwu / matches`、
  `order=asc|desc`。`/api/rankings` は `source / year / rank / org_name / country / score / match_status`。
- クエリ: `q`, `country`, `source`, `year`, `match_status`, `matched_only` (デフォルト false)、
  `limit` (default 100/200, le=1000), `offset`。

## Web UI (`static/index.html`)

- 2 タブ (ランキング一覧 / 大学一覧)。**タブ切替時に両パネルをトグルする実装**。
- 両タブの列ヘッダーはソートボタン (▲/▼・アクティブ強調・`f-sort` ドロップダウンと同期)。
- 大学一覧に QS/THE/ARWU 列 + 緑 ARWU バッジ、ソースフィルタ、`matched_only` チェックボックス。

## 作業フロー / 検証

1. matcher.py を変更したら `python -m scripts.collect match` を再実行して DB に反映し、一致率を確認。
2. `python -m pytest tests/ -q` で全件実行 (`tests/test_matcher.py` に正規化・各段階のテストあり)。
3. UI/API を変えたらサーバーを再起動し、http://127.0.0.1:8000/ で確認。

## 残タスク・留意点

- `_acronym_fuzzy` 追加後、`python -m scripts.collect match` の再実行とそのテスト追加が未実施
  (LMU Munich / ETH Zurich のテストを `tests/test_matcher.py` に追加する)。
- Sciences Po は未一致のまま。ROR に `Sciences Po Lille/Rennes/Lyon/Bordeaux` はあるが
  パリ本校 (Institut d'études politiques de Paris) のレコードは見つからず調査中断。
- git は初期コミット未実施 (全ファイル untracked のまま)。

## ディレクトリ構成

```
app/collectors/ror.py     ROR ダンプのパース
app/collectors/qs.py      QS API 収集・CSV 取込 (page=0, nid 手動)
app/collectors/the.py     THE API 収集
app/collectors/arwu.py    ARWU API 収集
app/collectors/matcher.py 大学名マッチング (6 段階 + CountryIndex)
app/services.py           マッチング結果・DataSource 管理の DB 投入
app/api.py                統計・一覧 API
app/config.py             DEFAULT_ROR_ZIP, DATA_DIR, ARWU_RANK_URL
app/database.py           SQLAlchemy モデル (University / Ranking / DataSource)
scripts/collect.py        CLI (ror/qs/qs-file/the/arwu/match/all/stats)
static/index.html         Web UI
tests/                    test_matcher.py / test_collectors.py / test_services.py
```
