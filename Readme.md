# University Rank Finder

**Languages:** English | [日本語](Readme-ja.md)

A FastAPI application that collects QS, THE, and ARWU university rankings, matches them against university data from the Research Organization Registry (ROR), and displays the results.

## Data sources

| Source | Version format | How data is obtained |
|--------|----------------|----------------------|
| ROR | Official dump ZIP (e.g. `v2.11-2026-08-03-ror-data.zip`) | Download from https://doi.org/10.5281/zenodo.6347574 |
| QS | `QS{year}` (e.g. `QS2027`) | Official QS Web API (using `cloudscraper`) |
| THE | `THE{year}` (e.g. `THE2026`) | Official THE JSON API |
| ARWU | `ARWU{year}` (e.g. `ARWU2025`) | Official API at shanghairanking.com (`/api/pub/v1/arwu/rank?version={year}`) |

- Dataset versions, years, publication dates, and record counts are stored in the `data_sources` table and available from `/api/stats`.
- QS is scraped with `cloudscraper` to handle Cloudflare. The `--nid` value changes by edition and must be identified from the source of the relevant page at `https://www.topuniversities.com/qs-world-university-rankings` (automatic detection does not work with the current page structure).
- QS pagination starts at zero (`page=0` contains the top-ranked entries); the collector handles pagination automatically.

## Setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

Place the ROR dump at `data/v2.11-2026-08-03-ror-data.zip`.

## Usage

```bash
# Import ROR data (education organizations only; 26,837 records)
python -m scripts.collect ror --file data/v2.11-2026-08-03-ror-data.zip

# Collect QS rankings (specify the edition-specific nid)
python -m scripts.collect qs --year 2027 --nid 4153156

# Import QS data from a local CSV file (e.g. downloaded from Kaggle)
python -m scripts.collect qs-file --file path/to/qs.csv --year 2027

# Collect THE rankings
python -m scripts.collect the --year 2026

# Collect ARWU rankings (top 1,000; latest available edition is 2025)
python -m scripts.collect arwu --year 2025

# Match university names against ROR
python -m scripts.collect match

# Show statistics
python -m scripts.collect stats

# Run all of the above
python -m scripts.collect all
```

Start the server:

```bash
uvicorn app.main:app --port 8000
```

Web UI: http://127.0.0.1:8000/<br>
API: `/api/stats`, `/api/rankings`, `/api/universities`, `/api/countries`

### Dependency versions and Docker

Direct dependencies and FastAPI's main dependencies (Starlette and Pydantic) are pinned in `pyproject.toml`. Transitive dependencies are not pinned, so clean installs are not guaranteed to resolve to exactly the same dependency tree. Run the tests whenever dependency versions are changed.

Docker installs dependencies from `pyproject.toml` and runs as a non-root user. Docker Compose defaults `APP_UID` and `APP_GID` to `1000`. If these do not match the owner of `data/`, set both variables to the directory owner's IDs before building. The `app/` and `static/` directories are mounted read-only, and the container root filesystem is read-only. Uvicorn's concurrency is limited to 100 requests.

## How matching works

`python -m scripts.collect match` matches university names in QS/THE/ARWU rankings to ROR universities (`app/collectors/matcher.py`). Each ROR organization has searchable names consisting of its display name, aliases, acronyms, and labels. For example, ARWU's `University of Munich` matches ROR's `Ludwig-Maximilians-Universität München` because the ROR record includes `University of Munich` as an alias.

### 1. Name normalization (`normalize_name`)

Normalization is applied to both ranking names and ROR names to account for spelling variations.

- **Reordering inverted names**: `Essex, University of` → `University of Essex`
- **Unicode normalization (NFKD) and combining-mark removal**: `é→e`, `ü→u`, `ō→o`
- **Apostrophes**: straight and curly apostrophes are removed (`Queen's→Queens`, `Chang'an→Changan`)
- **Turkish characters**: dotless `ı→i`, `İ→I` (`Fırat→Firat`, `İstanbul→Istanbul`)
- **Expanding `&`**: `& → and`
- **Removing parenthetical text**: e.g. `(VIT)`
- **Expanding state university system names (SUNY)**: `SUNY` is an abbreviation for State University of New York. Rankings may say `SUNY Stony Brook`, while ROR uses the full name `Stony Brook University, State University of New York`. Before matching, `SUNY` is expanded to `state university of new york` so both names have the same token sequence.
- **Normalizing institution-type terms**: Terms such as `University`, `College`, `Institute`, `School`, and `Technology` vary by language and abbreviation. They are normalized to representative English forms before matching. Examples:
  - `univ.`, `Universität` (German), `Université` (French), `Universidad` (Spanish), `Universidade` (Portuguese), `universitesi` (Turkish), `universitet` (Nordic/Slavic) → `university`
  - `inst.`, `institut` (German), `instituto` (Spanish) → `institute`
  - `coll.` → `college`
  - `tech`, `technische` (German), `technika` → `technology`

  This lets names match across languages when the non-type terms are the same. For example, `Universität Duisburg-Essen` and `University of Duisburg-Essen` both normalize to `university duisburg essen` and match exactly. By contrast, `Université de Bretagne Occidentale` and `University of Western Brittany` do not match: although the type term is normalized, the place names are translations of each other, which this tool does not translate.
- **Removing stop words**: terms such as `of, the, and, de, der, le, la, van, von, di, el, o`

### 2. Country resolution (`CountryIndex`)

Ranking country names are resolved to ISO 3166-1 alpha-2 codes to narrow matching candidates (e.g. `UK→GB`, `Turkey/Türkiye→TR`, `China-Hong Kong→HK`, `China-Taiwan→TW`). The index is built from ROR country names and supplemented by `COUNTRY_ALIASES`.

### 3. Prebuilt indexes

The matcher builds these indexes from all ROR universities:

- `_name_index`: normalized name → universities
- `_token_index`: token → set of university IDs (for narrowing candidates)
- `_acronym_index`: normalized acronym → list of universities

### 4. Matching stages

`match(org_name, country)` tries the following stages in order and stops at the first successful stage.

| Stage | Condition | Example |
|-------|-----------|---------|
| **Exact match** | Normalized names are identical | `Harvard University` |
| **Token-set match** | Only the word order differs | `Ulster University` ↔ `University of Ulster` |
| **Acronym** | Acronym plus institution type only | `HSE University` (ROR acronym `HSE`) |
| **Acronym + city (fuzzy)** | Acronym resolves to one organization and similarity is at least 0.85 | `LMU Munich`, `ETH Zurich` |
| **Prefix containment** | One side's tokens are a prefix of the other; the smallest token-count difference is preferred | `University of Canterbury \| Te Whare Wānanga o Waitaha` ↔ `University of Canterbury` |
| **Fuzzy match** | `SequenceMatcher` similarity is at least 0.90 | Spelling and formatting variations |

When a country code can be resolved, candidates at each stage are restricted to that country (e.g. to distinguish Gordon Colleges in the Philippines and the United States).

### 5. Match statuses

- **`matched`**: a unique match was found
- **`ambiguous`**: multiple candidates tie (e.g. `Gordon College` without a country, or after parenthetical text is removed from `Vietnam National University (Ho Chi Minh City)`)
- **`unmatched`**: no candidate met the threshold

### Current match rate

About **5,400 of 5,622 records (96%)** match across QS 2027 (1,504), THE 2026 (3,118), and ARWU 2025 (1,000). Many remaining unmatched names differ substantially from their ROR names, such as `University of Mainz` versus `Johannes Gutenberg-Universität Mainz`.

## Tests

```bash
python -m pytest tests/ -q
```

Matcher tests are in `tests/test_matcher.py` and cover normalization, matching stages, country disambiguation, and ambiguous matches.

## Project structure

```
app/collectors/ror.py     Parse ROR dumps
app/collectors/qs.py      Collect QS data and import CSV files
app/collectors/the.py     Collect THE data
app/collectors/arwu.py    Collect ARWU data
app/collectors/matcher.py Match university names
app/services.py           Persist matches and data-source metadata
app/api.py                Statistics and listing APIs
scripts/collect.py        CLI
static/index.html         Web UI
```
