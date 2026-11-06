from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BeforeValidator
from sqlalchemy import String, asc, cast, desc, func, select
from sqlalchemy.orm import Session

from .collectors.matcher import STATUS_MATCHED, normalize_name
from .database import DataSource, Ranking, University, get_db

router = APIRouter(prefix="/api")


def _empty_to_none(v):
    if isinstance(v, str) and not v.strip():
        return None
    return v


YearParam = Annotated[
    int | None,
    Query(description="Ranking edition year (e.g. 2026). An empty string is ignored"),
    BeforeValidator(_empty_to_none),
]
SourceParam = Annotated[
    Literal["qs", "the", "arwu"] | None,
    Query(description="Ranking source (qs / the / arwu). An empty string is ignored"),
    BeforeValidator(_empty_to_none),
]
MatchStatusParam = Annotated[
    Literal["matched", "unmatched", "ambiguous"] | None,
    Query(description="ROR matching status. An empty string is ignored"),
    BeforeValidator(_empty_to_none),
]


@router.get(
    "/stats",
    summary="Statistics",
    description="Returns data source versions, record counts, and the ROR matching status of the rankings.",
)
def stats(db: Session = Depends(get_db)):
    by_source = {}
    rows = db.execute(
        select(Ranking.source, Ranking.year, func.count(Ranking.id))
        .group_by(Ranking.source, Ranking.year)
        .order_by(Ranking.source, Ranking.year)
    ).all()
    for source, year, count in rows:
        by_source.setdefault(source, []).append({"year": year, "count": count})

    matched = db.execute(
        select(func.count(Ranking.id)).where(Ranking.match_status == STATUS_MATCHED)
    ).scalar()
    total_rank = db.execute(select(func.count(Ranking.id))).scalar()
    n_uni = db.execute(select(func.count(University.id))).scalar()

    datasets = db.execute(select(DataSource).order_by(DataSource.imported_at.desc())).scalars().all()
    return {
        "universities": n_uni,
        "rankings": {
            "total": total_rank,
            "matched": matched,
        },
        "rankings_by_source": by_source,
        "datasets": [
            {
                "name": d.name,
                "version": d.version,
                "year": d.year,
                "record_count": d.record_count,
                "published_at": d.published_at,
                "source_url": d.source_url,
                "notes": d.notes,
                "imported_at": d.imported_at.isoformat() if d.imported_at else None,
            }
            for d in datasets
        ],
    }


@router.get(
    "/rankings",
    summary="List Rankings",
    description=(
        "Lists ranking rows (university name, rank, score) from QS / THE / ARWU. "
        "Filter by source, year, country, search term, or matching status; supports column sorting and paging. "
        "When a ranking is matched, the corresponding ROR university info is included as `university`."
    ),
)
def list_rankings(
    source: str | None = Query(default=None, description="Ranking source (qs / the / arwu)"),
    year: YearParam = None,
    q: str | None = Query(default=None, description="Partial match on university name (org_name), case-insensitive"),
    country: str | None = Query(default=None, description="Exact match on country name"),
    match_status: MatchStatusParam = None,
    matched_only: bool = Query(default=False, description="If true, return only rows with status `matched`"),
    sort: Literal["source", "year", "rank", "org_name", "country", "score", "match_status"] = Query(
        default="source",
        description="Sort column. For `rank` / `score`, rows without a value (NULL) always sort last in both orders",
    ),
    order: Literal["asc", "desc"] = Query(default="asc", description="Sort order (asc / desc)"),
    limit: int = Query(default=100, le=1000, description="Number of rows to return (1-1000)"),
    offset: int = Query(default=0, description="Number of rows to skip (0-based)"),
    db: Session = Depends(get_db),
):
    sort_map = {
        "source": Ranking.source,
        "year": Ranking.year,
        "rank": Ranking.rank,
        "org_name": Ranking.org_name,
        "country": Ranking.country,
        "score": Ranking.score,
        "match_status": Ranking.match_status,
    }
    col = sort_map[sort]
    if order == "desc":
        order_col = col.desc()
    else:
        order_col = col.asc()
    if sort in ("rank", "score"):
        order_col = order_col.nulls_last()

    stmt = select(Ranking).order_by(
        order_col, Ranking.source, Ranking.year, Ranking.rank
    )
    if source:
        stmt = stmt.where(Ranking.source == source)
    if year:
        stmt = stmt.where(Ranking.year == year)
    if country:
        stmt = stmt.where(Ranking.country == country)
    if match_status:
        stmt = stmt.where(Ranking.match_status == match_status)
    if matched_only:
        stmt = stmt.where(Ranking.match_status == STATUS_MATCHED)
    if q:
        stmt = stmt.where(Ranking.org_name.ilike(f"%{q}%"))

    rows = db.execute(stmt.offset(offset).limit(limit)).scalars().all()
    uni_ids = {r.university_id for r in rows if r.university_id}
    unis = {
        u.id: u
        for u in db.execute(select(University).where(University.id.in_(uni_ids))).scalars().all()
    } if uni_ids else {}

    return {
        "total": db.execute(select(func.count()).select_from(stmt.subquery())).scalar(),
        "items": [
            {
                "id": r.id,
                "source": r.source,
                "year": r.year,
                "rank": r.rank,
                "rank_display": r.rank_display,
                "score": r.score,
                "org_name": r.org_name,
                "country": r.country,
                "url": r.url,
                "match_status": r.match_status,
                "university": _uni_dict(unis[r.university_id]) if r.university_id else None,
            }
            for r in rows
        ],
    }


@router.get(
    "/universities",
    summary="List Universities",
    description=(
        "Lists ROR universities with the rankings (QS / THE / ARWU) matched to each one. "
        "Search by university name, alias, acronym, or label; filter by country, source, or year; and optionally show only "
        "universities that have a matched ranking (matched_only). `rank`-type sorts are based on the best rank "
        "within that source (universities without a rank always sort last)."
    ),
)
def list_universities(
    q: str | None = Query(
        default=None,
        description="Partial match on ROR university name, aliases, acronyms, or labels (case-insensitive)",
    ),
    country: str | None = Query(default=None, description="Exact match on country name"),
    source: SourceParam = None,
    year: YearParam = None,
    matched_only: bool = Query(default=False, description="If true, return only universities with a matched ranking"),
    sort: Literal["name", "country", "rank", "rank:qs", "rank:the", "rank:arwu", "matches"] = Query(
        default="name",
        description=(
            "Sort key. `rank` = best rank across all sources; `rank:qs` / `rank:the` / `rank:arwu` = best rank "
            "within that source; `matches` = number of matched rankings"
        ),
    ),
    order: Literal["asc", "desc"] = Query(default="asc", description="Sort order (asc / desc)"),
    limit: int = Query(default=200, le=1000, description="Number of rows to return (1-1000)"),
    offset: int = Query(default=0, description="Number of rows to skip (0-based)"),
    db: Session = Depends(get_db),
):
    stmt = select(University)
    if q:
        if q.isascii():
            stmt = stmt.where(
                (University.name.ilike(f"%{q}%"))
                | (cast(University.aliases, String).ilike(f"%{q}%"))
                | (cast(University.acronyms, String).ilike(f"%{q}%"))
                | (cast(University.labels, String).ilike(f"%{q}%"))
            )
    if country:
        stmt = stmt.where(University.country == country)

    uni_rows = db.execute(stmt).scalars().all()
    if q and not q.isascii():
        q_folded = q.casefold()
        uni_rows = [
            u
            for u in uni_rows
            if any(
                q_folded in value.casefold()
                for value in [u.name, *(u.aliases or []), *(u.acronyms or []), *(u.labels or [])]
            )
        ]
    ids = [u.id for u in uni_rows]

    # ランキングを一括ロードして結合
    r_stmt = select(Ranking).where(Ranking.university_id.in_(ids))
    if source:
        r_stmt = r_stmt.where(Ranking.source == source)
    if year:
        r_stmt = r_stmt.where(Ranking.year == year)
    rank_rows = db.execute(r_stmt).scalars().all()

    by_uni: dict[int, list] = {}
    for r in rank_rows:
        by_uni.setdefault(r.university_id, []).append(r)

    items = []
    for u in uni_rows:
        rs = by_uni.get(u.id, [])
        if matched_only and not rs:
            continue
        if source and not any(r.source == source for r in rs):
            continue
        items.append(
            {
                "ror_id": u.ror_id,
                "name": u.name,
                "country": u.country,
                "country_code": u.country_code,
                "region": u.region,
                "website": u.website,
                "wikipedia_url": u.wikipedia_url,
                "types": u.types,
                "ror_version": u.ror_version,
                "rankings": [
                    {
                        "source": r.source,
                        "year": r.year,
                        "rank": r.rank,
                        "rank_display": r.rank_display,
                        "score": r.score,
                        "org_name": r.org_name,
                    }
                    for r in sorted(rs, key=lambda x: (x.source, x.year))
                ],
            }
        )

    def _sort_items(key):
        items.sort(key=key)
        if order == "desc":
            items.reverse()

    if sort == "name":
        _sort_items(lambda x: (x["name"] or "", x["country"] or ""))
    elif sort == "country":
        _sort_items(lambda x: (x["country"] or "", x["name"]))
    elif sort == "rank":
        _sort_rank(_mixed_rank, order, items)
    elif sort == "rank:qs":
        _sort_rank(lambda x: _min_rank(x, "qs"), order, items)
    elif sort == "rank:the":
        _sort_rank(lambda x: _min_rank(x, "the"), order, items)
    elif sort == "rank:arwu":
        _sort_rank(lambda x: _min_rank(x, "arwu"), order, items)
    elif sort == "matches":
        _sort_items(lambda x: (-len(x["rankings"]), x["name"]))
    total = len(items)
    return {"total": total, "items": items[offset : offset + limit]}


@router.get(
    "/universities/{ror_id}",
    summary="Get University by ROR ID",
    description=(
        "Returns a single ROR university identified by its ROR ID, together with the rankings (QS / THE / ARWU) "
        "matched to it across all sources and years. Optionally filter the rankings by source or year."
    ),
    responses={404: {"description": "ROR organization not found"}},
)
def get_university(
    ror_id: Annotated[str, Path(description="ROR organization ID (e.g. 05591te55)")],
    source: SourceParam = None,
    year: YearParam = None,
    db: Session = Depends(get_db),
):
    u = db.execute(select(University).where(University.ror_id == ror_id)).scalars().first()
    if u is None:
        raise HTTPException(status_code=404, detail=f"ROR organization not found: {ror_id}")

    r_stmt = select(Ranking).where(Ranking.university_id == u.id)
    if source:
        r_stmt = r_stmt.where(Ranking.source == source)
    if year:
        r_stmt = r_stmt.where(Ranking.year == year)
    rankings = db.execute(r_stmt.order_by(Ranking.source, Ranking.year)).scalars().all()

    return {
        "ror_id": u.ror_id,
        "name": u.name,
        "country": u.country,
        "country_code": u.country_code,
        "region": u.region,
        "website": u.website,
        "wikipedia_url": u.wikipedia_url,
        "types": u.types,
        "ror_version": u.ror_version,
        "rankings": [
            {
                "source": r.source,
                "year": r.year,
                "rank": r.rank,
                "rank_display": r.rank_display,
                "score": r.score,
                "org_name": r.org_name,
            }
            for r in rankings
        ],
    }


@router.get(
    "/ror/search",
    summary="Search ROR Universities",
    description=(
        "Searches ROR universities by partial name. Matches the display name, aliases, acronyms, and labels, "
        "ranks the results by relevance, and returns the ROR ID and the matched spelling. "
        "Intended to power a ROR ID picker / validator for university name input."
    ),
)
def search_ror(
    q: str = Query(..., min_length=1, description="Partial match on ROR university name, alias, acronym, or label"),
    country: str | None = Query(default=None, description="ROR country name for exact-match filtering"),
    limit: int = Query(default=20, ge=1, le=100, description="Number of results to return (1-100)"),
    db: Session = Depends(get_db),
):
    nq = normalize_name(q)
    stmt = select(University)
    if q.isascii():
        stmt = stmt.where(
            (University.name.ilike(f"%{q}%"))
            | (cast(University.aliases, String).ilike(f"%{q}%"))
            | (cast(University.acronyms, String).ilike(f"%{q}%"))
            | (cast(University.labels, String).ilike(f"%{q}%"))
        )
    if country:
        stmt = stmt.where(University.country == country)
    # SQLite JSON text escapes non-ASCII characters, so Japanese queries cannot
    # be prefiltered against aliases/labels in SQL. Scan those candidates in Python.
    if q.isascii():
        stmt = stmt.limit(500)
    rows = db.execute(stmt).scalars().all()

    scored = []
    for u in rows:
        name_n = normalize_name(u.name)
        aliases_n = [normalize_name(a) for a in u.aliases or []]
        acronyms_n = [normalize_name(a) for a in u.acronyms or []]
        labels_n = [normalize_name(label) for label in u.labels or []]

        if nq and name_n == nq:
            score, matched = 0, u.name
        elif nq and nq in aliases_n:
            score, matched = 1, (u.aliases or [])[aliases_n.index(nq)]
        elif nq and nq in acronyms_n:
            score, matched = 1, (u.acronyms or [])[acronyms_n.index(nq)]
        elif nq and nq in labels_n:
            score, matched = 1, (u.labels or [])[labels_n.index(nq)]
        elif nq and name_n.startswith(nq):
            score, matched = 2, u.name
        elif nq and any(a.startswith(nq) for a in aliases_n):
            score, matched = 3, (u.aliases or [])[next(i for i, a in enumerate(aliases_n) if a.startswith(nq))]
        elif nq and any(a.startswith(nq) for a in acronyms_n):
            score, matched = 3, (u.acronyms or [])[next(i for i, a in enumerate(acronyms_n) if a.startswith(nq))]
        elif nq and any(label.startswith(nq) for label in labels_n):
            score, matched = 3, (u.labels or [])[next(i for i, label in enumerate(labels_n) if label.startswith(nq))]
        elif nq and nq in name_n:
            score, matched = 4, u.name
        elif nq and any(nq in a for a in aliases_n):
            score, matched = 5, (u.aliases or [])[next(i for i, a in enumerate(aliases_n) if nq in a)]
        elif nq and any(nq in label for label in labels_n):
            score, matched = 5, (u.labels or [])[next(i for i, label in enumerate(labels_n) if nq in label)]
        else:
            q_folded = q.casefold()
            raw_names = [u.name, *(u.aliases or []), *(u.acronyms or []), *(u.labels or [])]
            raw_matches = [name for name in raw_names if q_folded in name.casefold()]
            if not raw_matches:
                continue
            matched = min(
                raw_matches,
                key=lambda name: (
                    0 if name.casefold() == q_folded else 2 if name.casefold().startswith(q_folded) else 5,
                    len(name),
                ),
            )
            score = 0 if matched.casefold() == q_folded else 2 if matched.casefold().startswith(q_folded) else 5
        scored.append((score, len(matched), u.name.lower(), u, matched))

    scored.sort(key=lambda x: (x[0], x[1], x[2]))
    items = [
        {
            "ror_id": u.ror_id,
            "name": u.name,
            "country": u.country,
            "country_code": u.country_code,
            "region": u.region,
            "types": u.types,
            "matched_name": matched,
        }
        for _, _, _, u, matched in scored[:limit]
    ]
    return {"q": q, "total": len(scored), "items": items}


@router.get(
    "/countries",
    summary="List Countries",
    description="Lists country names present in the universities table (ROR `country` values) in alphabetical order.",
)
def list_countries(db: Session = Depends(get_db)):
    rows = db.execute(select(University.country).distinct().order_by(University.country)).scalars().all()
    return {"items": [c for c in rows if c]}


def _uni_dict(u: University) -> dict:
    return {
        "ror_id": u.ror_id,
        "name": u.name,
        "country": u.country,
        "country_code": u.country_code,
    }


def _min_rank(u: dict, source: str) -> int | None:
    ranks = [r["rank"] for r in u["rankings"] if r["source"] == source and r["rank"]]
    return min(ranks) if ranks else None


def _mixed_rank(u: dict) -> int | None:
    vals = [_min_rank(u, s) for s in ("qs", "the", "arwu")]
    vals = [v for v in vals if v is not None]
    return min(vals) if vals else None


def _sort_rank(getter, order: str, items: list):
    """ランク順ソート。未順位 (None) は asc/desc とも常に末尾にする。"""
    if order == "desc":
        items.sort(key=lambda x: (getter(x) is None, -(getter(x) or 0), x["name"] or ""))
    else:
        items.sort(key=lambda x: (getter(x) is None, getter(x) or 0, x["name"] or ""))
