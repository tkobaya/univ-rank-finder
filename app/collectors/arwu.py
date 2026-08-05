import requests

from ..config import ARWU_RANK_URL, USER_AGENT
from .base import CollectorResult, RankingEntry, SOURCE_ARWU


def fetch_rankings(year: int, max_entries: int = 2000, timeout: int = 90) -> CollectorResult:
    """ARWU (ShanghaiRanking Academic Ranking of World Universities) を公式 API から取得する。

    https://www.shanghairanking.com/api/pub/v1/arwu/rank?version={year}
    上位 1000 校 (1-100, 101-150 ... 901-1000) が公開されている。
    """
    url = f"{ARWU_RANK_URL}?version={year}"
    resp = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Referer": f"https://www.shanghairanking.com/rankings/arwu/{year}",
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 200:
        raise RuntimeError(f"ARWU API error for year {year}: {payload.get('msg') or payload.get('message')}")

    entries = []
    for row in (payload.get("data") or {}).get("rankings") or []:
        name = row.get("univNameEn") or ""
        if not name:
            continue
        slug = row.get("univUp") or ""
        entries.append(
            RankingEntry(
                source=SOURCE_ARWU,
                year=year,
                rank_display=str(row.get("ranking") or ""),
                org_name=name,
                country=row.get("region"),
                score=str(row.get("score")) if row.get("score") is not None else None,
                url=f"https://www.shanghairanking.com/institution/{slug}" if slug else None,
                extra={
                    "univ_code": row.get("univCode"),
                    "region_ranking": row.get("regionRanking"),
                },
            )
        )

    entries = entries[:max_entries]
    return CollectorResult(
        source=SOURCE_ARWU,
        year=year,
        version=f"ARWU{year}",
        entries=entries,
        source_url=url,
        published_at=None,
        notes="live scrape from shanghairanking.com API, top 1000",
    )
