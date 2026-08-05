import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

from ..config import (
    QS_DEFAULT_ITEMS_PER_PAGE,
    QS_ENDPOINT_URL,
    USER_AGENT,
)
from .base import CollectorResult, RankingEntry, SOURCE_QS


def _scrape():
    import cloudscraper

    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True}
    )


# ---------------------------------------------------------------------------
# nid の自動検出 (ランキング年ごとに変わる Drupal ノード ID)
# ---------------------------------------------------------------------------

_QS_PAGE_CANDIDATES = (
    "https://www.topuniversities.com/world-university-rankings",
    "https://www.topuniversities.com/qs-world-university-rankings",
)


def discover_nid(page_url: str | None = None, session=None) -> tuple[str, str]:
    """ランキングページから nid とエディション年 (例: 2027) を検出する。

    Returns:
        (nid, edition_year)
    """
    session = session or _scrape()
    urls = [page_url] if page_url else list(_QS_PAGE_CANDIDATES)

    for url in urls:
        resp = session.get(url, timeout=60)
        if resp.status_code != 200:
            continue
        html = resp.text

        nid = None
        m = re.search(r'"qs_rankings_rest_api"\s*:\s*\{\s*"nid"\s*:\s*"(\d+)"', html)
        if m:
            nid = m.group(1)
        else:
            soup = BeautifulSoup(html, "html.parser")
            settings = soup.select_one('script[data-drupal-selector="drupal-settings-json"]')
            if settings:
                try:
                    payload = json.loads(settings.string or "")
                    nid = payload.get("qs_rankings_rest_api", {}).get("nid")
                except Exception:
                    nid = None

        if nid:
            year = None
            mm = re.search(r"QS World University Rankings[:\s-]*(\d{4})", html)
            if mm:
                year = mm.group(1)
            return str(nid), year

    raise RuntimeError(
        "QS page: could not find ranking nid (Cloudflare/HTML changed?). "
        "Use --nid to specify it manually."
    )


# ---------------------------------------------------------------------------
# ライブ取得
# ---------------------------------------------------------------------------


def fetch_rankings(
    year: int,
    max_entries: int = 2000,
    nid: str | None = None,
    items_per_page: int = QS_DEFAULT_ITEMS_PER_PAGE,
    session=None,
):
    """QS World University Rankings を公式エンドポイントから取得する。

    year はランキングエディション年 (例: 2027)。nid はページから自動検出するか
    明示的に渡す。

    Returns:
        CollectorResult (source=qs)
    """
    session = session or _scrape()

    if not nid:
        nid, auto_year = discover_nid(session=session)
        if not year and auto_year:
            year = int(auto_year)
    if not year:
        raise ValueError("year must be specified or auto-detected")

    entries = []
    page = 0  # QS エンドポイントは 0 起点ページング (page=0 が最上位)
    total = None
    while True:
        params = {
            "nid": nid,
            "page": page,
            "items_per_page": items_per_page,
            "tab": "indicators",
            "region": "",
            "countries": "",
            "sort_by": "rank",
            "order_by": "asc",
            "year": "",
        }
        resp = session.get(QS_ENDPOINT_URL, params=params, timeout=60)
        resp.raise_for_status()
        try:
            payload = resp.json()
        except Exception:
            raise RuntimeError(f"QS endpoint: non-JSON response (HTTP {resp.status_code})")

        total = int(payload.get("total_record", 0))
        nodes = payload.get("score_nodes") or []
        for node in nodes:
            entries.append(
                RankingEntry(
                    source=SOURCE_QS,
                    year=year,
                    rank_display=str(node.get("rank_display") or node.get("rank") or ""),
                    org_name=node.get("title") or "",
                    country=node.get("country"),
                    score=node.get("overall_score"),
                    url="https://www.topuniversities.com" + (node.get("path") or ""),
                    region=node.get("region"),
                    city=node.get("city"),
                )
            )
        total_pages = int(payload.get("total_pages", 1))
        if not nodes or len(entries) >= total or len(entries) >= max_entries:
            break
        page += 1

    entries = entries[:max_entries]
    return CollectorResult(
        source=SOURCE_QS,
        year=year,
        version=f"QS{year}",
        entries=entries,
        source_url="https://www.topuniversities.com/world-university-rankings",
        published_at=None,
        notes=f"live scrape, total records={total}",
    )


# ---------------------------------------------------------------------------
# 静的ファイル (Kaggle など) からの取り込み
# ---------------------------------------------------------------------------


_RANK_KEYS = (
    "rank",
    "overall rank",
    "rank display",
    "rank display 2025",
    "2025 rank",
    "2024 rank",
    "rank_display",
    "2025_rank",
    "2024_rank",
    "qs rank",
)
_NAME_KEYS = (
    "institution",
    "institution name",
    "university",
    "university name",
    "title",
    "name",
    "org name",
    "organization",
    "university 2025",
)
_COUNTRY_KEYS = ("location", "location full", "country", "location name")
_SCORE_KEYS = ("overall score", "overall_score", "score", "score scaled", "overall")


def _pick_column(headers: list[str], keys: tuple[str, ...]):
    lowered = {h: h.lower().strip() for h in headers}
    for key in keys:
        for h, hlow in lowered.items():
            if hlow == key or hlow.startswith(key + " "):
                return h
    return None


def load_from_file(
    path: str | Path,
    year: int,
    source: str = SOURCE_QS,
) -> CollectorResult:
    """静的 CSV/JSON ファイルからランキングを取り込む。year は必須 (明示)。"""
    path = Path(path)
    rows = _read_rows(path)

    if rows:
        headers = list(rows[0].keys())
        col_rank = _pick_column(headers, _RANK_KEYS)
        col_name = _pick_column(headers, _NAME_KEYS)
        col_country = _pick_column(headers, _COUNTRY_KEYS)
        col_score = _pick_column(headers, _SCORE_KEYS)
    else:
        col_rank = col_name = col_country = col_score = None

    entries = []
    for row in rows:
        name = (row.get(col_name) if col_name else row.get("name")) or ""
        if not name:
            continue
        rank = (row.get(col_rank) if col_rank else row.get("rank")) or ""
        score = (row.get(col_score) if col_score else row.get("score")) or ""
        country = (row.get(col_country) if col_country else row.get("location")) or ""
        entries.append(
            RankingEntry(
                source=source,
                year=year,
                rank_display=str(rank),
                org_name=str(name).strip(),
                country=str(country).strip() or None,
                score=str(score).strip() or None,
                extra={"filename": path.name},
            )
        )

    if not entries:
        raise ValueError(
            f"No rows parsed from {path}. Expected columns like "
            f"rank / institution name / location / overall score."
        )

    return CollectorResult(
        source=source,
        year=year,
        version=f"file:{path.name}:{year}",
        entries=entries,
        notes=f"loaded from static file {path.name} (year explicitly set to {year})",
    )


def _read_rows(path: Path) -> list[dict]:
    import csv

    if path.suffix.lower() in (".json", ".txt"):
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(raw, dict):
            raw = raw.get("data") or raw.get("score_nodes") or []
        return [dict(r) for r in raw]

    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [dict(r) for r in csv.DictReader(fh)]
