# University Rank Finder

**言語:** [English](Readme.md) | 日本語

RoR (Research Organization Registry) の大学データをベースに、QS・THE・ARWU の大学ランキングを
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
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
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

### 依存関係のバージョン管理と Docker

直接依存と、FastAPI の主要な依存先 (Starlette / Pydantic) は `pyproject.toml` で固定しています。
間接依存は固定していないため、クリーンインストール間で完全に同じ依存ツリーになる保証はありません。
依存バージョンを変更したときはテストを実行してください。

Docker は `pyproject.toml` から依存をインストールし、非rootユーザーで起動します。
Docker Compose の `APP_UID` / `APP_GID` は既定で `1000` です。`data/` の所有者と異なる環境では、
そのディレクトリの所有者に合わせて両変数を設定してからビルドしてください。`app/` と `static/` は
読み取り専用でマウントされ、コンテナのroot filesystemも読み取り専用です。Uvicornの同時処理数も100に制限します。

## マッチャーの仕組み

`python -m scripts.collect match` は、ランキングの大学名 (QS/THE/ARWU) を ROR の大学に
対応付けます (`app/collectors/matcher.py`)。各 ROR 組織は表示名に加えて別名 (alias)・略称
(acronym)・ラベルを含む**全表記** (search_names) を持ち、これを検索対象にします。例えば
ARWU の `"University of Munich"` が ROR の `"Ludwig-Maximilians-Universität München"` に
一致するのは、ROR レコードの aliases に `University of Munich` が含まれているためです。

### 1. 名前の正規化 (`normalize_name`)

ランキング側と ROR 側の双方に適用し、表記ゆれを吸収します。

- **逆順表記の並べ替え**: `"Essex, University of"` → `"University of Essex"`
- **Unicode 正規化 (NFKD) + 結合文字除去**: `é→e`, `ü→u`, `ō→o`
- **アポストロフィ**: 角括弧 `'` `’` を除去 (`Queen's→Queens`, `Chang'an→Changan`)
- **トルコ文字**: 点なし `ı→i`, `İ→I` (`Fırat→Firat`, `İstanbul→Istanbul`)
- **`&` 展開**: `& → and`
- **括弧除去**: `(VIT)` などを削除
- **州立大学システム名の展開 (SUNY)**: `SUNY` は State University of New York (ニューヨーク州立大学) の
  略称で、ランキングでは `"SUNY Stony Brook"` のように使われますが ROR は
  `"Stony Brook University, State University of New York"` とフル表記です。そこで
  照合前に `SUNY → "state university of new york"` へ展開し、両者を同じトークン列に揃えます。
- **種別語の表記ゆれ統一**: `University` / `College` / `Institute` / `School` / `Technology` という
  「機関の種別を表す語」は、言語・省略形によって見た目が異なります。すべて正規化前に
  **英語の代表形へ揃えます**。例:
  - `univ.`, `Universität` (独), `Université` (仏), `Universidad` (西), `Universidade` (葡),
    `universitesi` (トルコ語), `universitet` (北欧・露) → `university`
  - `inst.`, `institut` (独), `instituto` (西) → `institute`
  - `coll.` → `college`
  - `tech`, `technische` (独), `technika` → `technology`
  
  これにより、種別語以外が同じ大学は別言語表記でも一致します。例:
  - `"Universität Duisburg-Essen"` (独) と `"University of Duisburg-Essen"` (英) はどちらも
    `university duisburg essen` に正規化され、完全一致します
  - 逆に `"Université de Bretagne Occidentale"` (仏) と `"University of Western Brittany"` (英) は
    種別語の `university` は揃いますが、地名 `Bretagne Occidentale` / `Western Brittany` は
    別言語の訳語のため一致しません (訳語の翻訳は本ツールの対象外)。
- **ストップワード除去**: `of, the, and, de, der, le, la, van, von, di, el, o` など

### 2. 国名の解決 (`CountryIndex`)

ランキングの国名表記を ISO 3166-1 alpha-2 コードに解決し、一致候補の絞り込みに使います
(例: `UK→GB`, `Turkey/Türkiye→TR`, `China-Hong Kong→HK`, `China-Taiwan→TW`)。
ROR の国名から自動構築 + 別名テーブル (`COUNTRY_ALIASES`) で補完します。

### 3. 事前インデックス

全 ROR 大学から次の辞書を構築します。

- `_name_index`: 正規化名 → 大学リスト
- `_token_index`: トークン → 大学 ID 集合 (候補の絞り込み用)
- `_acronym_index`: 正規化略称 → 大学 ID リスト

### 4. 一致段階 (先に成功した段階で確定)

`match(org_name, country)` は以下の順で試みます。

| 段階 | 条件 | 例 |
|------|------|-----|
| **完全一致** | 正規化名が完全に一致 | `"Harvard University"` |
| **トークン集合一致** | 語順が違うだけ | `"Ulster University"` ↔ `"University of Ulster"` |
| **略称** | 略称 + 種別語のみ | `"HSE University"` (ROR acronym `HSE`) |
| **略称+都市 (ファジー)** | 略称が単一組織に解決し、0.85 以上で類似 | `"LMU Munich"`, `"ETH Zurich"` |
| **接頭辞包含** | 片方が他方のトークン接頭辞。トークン数差が最小の候補を優先 | `"University of Canterbury \| Te Whare Wānanga o Waitaha"` ↔ `"University of Canterbury"` |
| **ファジー一致** | SequenceMatcher 類似度 0.90 以上 | スペル揺れ・表記差 |

国コードが解決できた場合、各段階の候補は `country_code` が一致するものに絞られます
(例: `"Gordon College"` のフィリピン/米国判別)。

### 5. 結果ステータス

- **`matched`**: 一意に一致
- **`ambiguous`**: 同点候補が複数あり判定不能 (例: `"Gordon College"` を国なしで照合、
  `"Vietnam National University (Ho Chi Minh City)"` の括弧除去後)
- **`unmatched`**: 閾値に達する候補なし

### 現在の一致率

QS 2027 (1,504) + THE 2026 (3,118) + ARWU 2025 (1,000) = 5,622 件中 **約 5,400 件 (96%)** が一致。
残る未一致の多くは ROR 名と大きく異なる別名 (例: ドイツの `University of Mainz` ↔
ROR `Johannes Gutenberg-Universität Mainz`) です。

## テスト

```bash
python -m pytest tests/ -q
```

マッチャーのテストは `tests/test_matcher.py` にあります (正規化・各一致段階・国別判別・ambiguous 判定)。

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
