# API 仕様

FastAPI アプリの HTTP API。ベース URL は `http://127.0.0.1:8000`。
対話的ドキュメント (Swagger UI): `/docs`。

エンドポイント一覧:

| メソッド | パス | 説明 |
|----------|------|------|
| GET | `/api/stats` | データソース・一致件数の統計 |
| GET | `/api/rankings` | ランキング一覧 (QS/THE/ARWU) |
| GET | `/api/universities` | ROR 大学一覧 |
| GET | `/api/universities/{ror_id}` | ROR ID 指定で大学 + 一致ランキングを取得 |
| GET | `/api/ror/search` | RoR 大学名の部分一致検索 (ランキング不使用) |
| GET | `/api/countries` | 国名の列挙 |
| GET | `/docs/openapi` | OpenAPI ドキュメント (Swagger UI) |
| GET | `/openapi.json` | OpenAPI 3.1.0 仕様 (JSON) |
| GET | `/` | Web UI (HTML) |
| GET | `/static/*` | 静的ファイル |

エンコーディングは UTF-8、レスポンスは JSON。未認証・同一オリジン前提 (CORS 未設定)。

---

## 共通の型と規則

### match_status

- `matched`: ランキングの大学名が ROR に一意に一致
- `ambiguous`: 同点候補が複数あり判定不能
- `unmatched`: 候補なし (未一致)

### year パラメータ

`year` は整数のクエリパラメータ。**空文字 `year=` は 422 にならず None として扱われる**
(UI から空文字が送られるため `YearParam` で吸収)。

### ページング

- `limit`: 1〜1000 (デフォルト: `/api/rankings`=100, `/api/universities`=200)
- `offset`: 0 起点 (デフォルト 0)
- レスポンスの `total` はフィルタ適用後・ページング前の件数

### ソートと未順位 (NULL) の扱い

- `order=asc|desc`。rank/score 系のソートでは**未順位 (NULL) は asc/desc どちらでも常に末尾**
  (THE の `Reporter` など順位なしエントリ対策)。

---

## GET /api/stats

データソースのバージョン・件数と、ランキングの一致状況を返す。

```bash
curl http://127.0.0.1:8000/api/stats
```

```json
{
  "universities": 26837,
  "rankings": {
    "total": 5622,
    "matched": 5418
  },
  "rankings_by_source": {
    "qs":   [{"year": 2027, "count": 1504}],
    "the":  [{"year": 2026, "count": 3118}],
    "arwu": [{"year": 2025, "count": 1000}]
  },
  "datasets": [
    {
      "name": "arwu",
      "version": "ARWU2025",
      "year": 2025,
      "record_count": 1000,
      "published_at": "2025-08",
      "source_url": "https://www.shanghairanking.com/...",
      "notes": null,
      "imported_at": "2026-08-05T12:00:00"
    }
  ]
}
```

フィールド:

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `universities` | int | ROR 大学数 |
| `rankings.total` | int | ランキング総件数 |
| `rankings.matched` | int | match_status=matched の件数 |
| `rankings_by_source` | object | ソースごとの年度別件数 (`{source: [{year, count}]}`) |
| `datasets[]` | array | 取り込んだデータセット (`data_sources` テーブル) を新しい順に返す |

`datasets[]` の各要素: `name` (ror/qs/the/arwu), `version` (例 `v2.11-2026-08-03`, `QS2027`, `THE2026`, `ARWU2025`),
`year`, `record_count`, `published_at` (データが基準とする日付), `source_url`, `notes`, `imported_at` (ISO8601)。

---

## GET /api/rankings

ランキング行の一覧。

### クエリパラメータ

| パラメータ | 型 | 既定 | 説明 |
|-----------|-----|------|------|
| `source` | str | — | `qs` / `the` / `arwu` で絞り込み |
| `year` | int | — | 年度で絞り込み (空文字は無視) |
| `q` | str | — | `org_name` の部分一致 (大小無視) |
| `country` | str | — | 国名の完全一致 |
| `match_status` | str | — | `matched` / `unmatched` / `ambiguous` |
| `matched_only` | bool | `false` | true で matched のみ |
| `sort` | str | `source` | `source` / `year` / `rank` / `org_name` / `country` / `score` / `match_status` |
| `order` | str | `asc` | `asc` / `desc` |
| `limit` | int | `100` | 1〜1000 |
| `offset` | int | `0` | — |

```bash
curl "http://127.0.0.1:8000/api/rankings?source=arwu&sort=rank&order=asc&limit=5"
```

```json
{
  "total": 1000,
  "items": [
    {
      "id": 4623,
      "source": "arwu",
      "year": 2025,
      "rank": 1,
      "rank_display": "1",
      "score": "100",
      "org_name": "Harvard University",
      "country": "United States",
      "url": "https://www.shanghairanking.com/institution/harvard-university",
      "match_status": "matched",
      "university": {
        "ror_id": "03vek6s52",
        "name": "Harvard University",
        "country": "United States",
        "country_code": "US"
      }
    }
  ]
}
```

フィールドの注意:

- `rank` は整数 (未順位は null)。`rank_display` は表示用文字列 (例 `1`, `901-1000`)。
- `score` は文字列 (ソースにより `100.0` / `–` 等)。null あり。
- `university` は一致時に ROR 情報、未一致は `null`。
- `total` はフィルタ適用後・ページング前の件数。`sort=rank|score` のとき NULL は末尾。

---

## GET /api/universities

ROR 大学の一覧。各大学に一致したランキングを同梱する。

### クエリパラメータ

| パラメータ | 型 | 既定 | 説明 |
|-----------|-----|------|------|
| `q` | str | — | ROR 大学名・別名 (aliases) の部分一致 |
| `country` | str | — | 国名の完全一致 |
| `source` | str | — | `qs` / `the` / `arwu` でランキング絞り込み |
| `year` | int | — | 年度で絞り込み (空文字は無視) |
| `matched_only` | bool | `false` | true でランキングに一致した大学のみ |
| `sort` | str | `name` | `name` / `country` / `rank` / `rank:qs` / `rank:the` / `rank:arwu` / `matches` |
| `order` | str | `asc` | `asc` / `desc` |
| `limit` | int | `200` | 1〜1000 |
| `offset` | int | `0` | — |

`sort` の意味:

| 値 | 基準 |
|----|------|
| `rank` | 全ソースの最良順位 (3 ソース中最良) |
| `rank:qs` / `rank:the` / `rank:arwu` | 指定ソース内の最良順位 |
| `matches` | 一致ランキング件数の多い順 |

`rank` 系のソートでは未順位の大学は常に末尾 (`_sort_rank`)。

```bash
curl "http://127.0.0.1:8000/api/universities?matched_only=true&sort=rank:qs&order=asc&limit=3"
```

```json
{
  "total": 1504,
  "items": [
    {
      "ror_id": "042nb2s44",
      "name": "Massachusetts Institute of Technology",
      "country": "United States",
      "country_code": "US",
      "region": "North America",
      "website": "https://web.mit.edu",
      "wikipedia_url": "http://en.wikipedia.org/wiki/Massachusetts_Institute_of_Technology",
      "types": ["education", "funder"],
      "ror_version": "2.11-2026-08-03",
      "rankings": [
        {
          "source": "qs",
          "year": 2027,
          "rank": 1,
          "rank_display": "1",
          "score": "100",
          "org_name": "Massachusetts Institute of Technology (MIT)"
        },
        {
          "source": "the",
          "year": 2026,
          "rank": 2,
          "rank_display": "2",
          "score": "97.7",
          "org_name": "Massachusetts Institute of Technology"
        }
      ]
    }
  ]
}
```

フィールド:

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `ror_id` | str | ROR 組織 ID |
| `name` / `aliases`* | str | 表示名 (`aliases` は q 検索にのみ使用、レスポンスには含まれない) |
| `country` / `country_code` | str | 国名 / ISO 3166-1 alpha-2 コード |
| `region` | str | 地域 (ROR の region) |
| `website` / `wikipedia_url` | str | URL (null あり) |
| `types` | array | ROR の組織タイプ (`["education"]`, `["education", "funder"]` 等) |
| `ror_version` | str | 投入した ROR ダンプのバージョン |
| `rankings[]` | array | 一致したランキング (`source`, `year`, `rank`, `rank_display`, `score`, `org_name`)。source→year 順にソート済み。`source`/`year` で絞り込み時はその分のみ |

注意:

- `total` は絞り込み (matched_only / source) 適用後の件数で、`offset`/`limit` はソート後に適用される。
- `matched_only=false` (既定) ではランキング未一致の大学も返る。
- `q` は `name` と `aliases` の両方を対象とする (SQLite で `cast(aliases, String)` を使用)。

---

## GET /api/universities/{ror_id}

ROR ID を指定して大学 1 件を取得し、一致したランキングを全ソース・全年度ぶん同梱して返す。
(「この RoR は各ランキングで何位か」を引くための API)

### パス / クエリパラメータ

| パラメータ | 型 | 説明 |
|-----------|-----|------|
| `ror_id` | str (path) | ROR 組織 ID (例: `05591te55`) |
| `source` | str | 同梱するランキングのソースで絞り込み (`qs` / `the` / `arwu`) |
| `year` | int | 同梱するランキングの年度で絞り込み (空文字は無視) |

存在しない ROR ID は **404**。

```bash
curl "http://127.0.0.1:8000/api/universities/05591te55"
```

```json
{
  "ror_id": "05591te55",
  "name": "Ludwig-Maximilians-Universität München",
  "country": "Germany",
  "country_code": "DE",
  "region": "Western Europe",
  "website": "https://www.lmu.de",
  "wikipedia_url": "...",
  "types": ["education"],
  "ror_version": "2.11-2026-08-03",
  "rankings": [
    { "source": "arwu", "year": 2025, "rank": 42, "rank_display": "42", "score": "44.8", "org_name": "University of Munich" },
    { "source": "qs", "year": 2027, "rank": 61, "rank_display": "61", "score": "74.4", "org_name": "Ludwig-Maximilians-Universität München" }
  ]
}
```

フィールドは `/api/universities` の 1 件分と同じ形式 (rankings は source → year 順)。

---

## GET /api/ror/search

RoR 大学のみを対象にした検索。ランキング情報は一切使わない。
大学名入力フォームから RoR ID を選ぶバリデータ / ピッカー用途を想定する。

### クエリパラメータ

| パラメータ | 型 | 既定 | 説明 |
|-----------|-----|------|------|
| `q` | str | (必須) | 大学名・別名 (alias)・略称 (acronym) の部分一致。1 文字以上 |
| `country` | str | — | ROR の国名で完全一致絞り込み |
| `limit` | int | `20` | 返す候補数 (1〜100) |

### 一致の優先順位 (関連度順)

1. 正式名称の完全一致
2. 別名・略称の完全一致
3. 正式名称の前方一致
4. 別名・略称の前方一致
5. 正式名称の部分一致
6. 別名の部分一致

正規化 (`normalize_name`) を適用するため、`é→e`・逆順表記・トルコ文字などの表記ゆれは吸収される。
内部では最大 500 件の SQL LIKE 候補を取得し、上記スコアで並べ替える。

```bash
curl "http://127.0.0.1:8000/api/ror/search?q=university+of+munich&limit=3"
```

```json
{
  "q": "university of munich",
  "total": 2,
  "items": [
    {
      "ror_id": "05591te55",
      "name": "Ludwig-Maximilians-Universität München",
      "country": "Germany",
      "country_code": "DE",
      "region": "Western Europe",
      "types": ["education"],
      "matched_name": "University of Munich"
    }
  ]
}
```

フィールド:

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `q` | str | 検索語 (エコーバック) |
| `total` | int | 関連度スコアを持つ候補の総数 |
| `items[]` | array | 上位 `limit` 件 (関連度順) |
| `items[].ror_id` | str | RoR 組織 ID (`https://ror.org/{ror_id}` で参照可) |
| `items[].name` | str | 正式名称 |
| `items[].country` / `country_code` | str | 所在国 / ISO 3166-1 alpha-2 |
| `items[].region` | str | ROR の地域 |
| `items[].types` | array | ROR の組織タイプ |
| `items[].matched_name` | str | 一致した表記 (正式名称または別名・略称)。UI の「Alias」列に使用 |

`country` で絞り込むことで、同名大学 (例: `"Gordon College"` のフィリピン/米国) を判別できる。

---

## GET /api/countries

大学テーブルに存在する国名の一覧 (辞書順、null 除外)。

```bash
curl http://127.0.0.1:8000/api/countries
```

```json
{
  "items": ["Afghanistan", "Albania", "Algeria", "..." ]
}
```

---

## エラー

- パラメータの enum 違反 (例 `sort=foo`) や `limit=2000` は **422 Validation Error** (FastAPI 既定の形式)。
- `year=` 空文字は前述のとおり None 扱いでエラーにならない。
- 未定義のパスは **404**。
