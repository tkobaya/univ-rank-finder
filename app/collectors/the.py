import requests

from ..config import THE_RANKINGS_URL, USER_AGENT
from .base import CollectorResult, RankingEntry, SOURCE_THE


def fetch_rankings(year: int, max_entries: int = 5000, timeout: int = 90) -> CollectorResult:
    """THE World University Rankings を公式 JSON API から取得する。

    https://www.timeshighereducation.com/json/ranking_tables/world_university_rankings/{year}
    """
    url = f"{THE_RANKINGS_URL}/{year}"
    resp = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()

    entries = []
    for row in payload.get("data") or []:
        rank_display = str(row.get("rank") or "")
        rank_order = row.get("rank_order")
        if rank_order:
            rank_display = f"={rank_order}" if rank_display.startswith("=") else rank_display
        entries.append(
            RankingEntry(
                source=SOURCE_THE,
                year=year,
                rank_display=rank_display,
                org_name=row.get("name") or "",
                country=row.get("location"),
                score=row.get("scores_overall"),
                url="https://www.timeshighereducation.com" + (row.get("url") or ""),
                extra={"iid": row.get("iid"), "nid": row.get("nid")},
            )
        )

    entries = entries[:max_entries]
    return CollectorResult(
        source=SOURCE_THE,
        year=year,
        version=f"THE{year}",
        entries=entries,
        source_url=url,
        published_at=None,
        notes=f"live scrape, total records={len(entries)}",
    )
