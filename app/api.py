from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BeforeValidator
from sqlalchemy import String, asc, cast, desc, func, select
from sqlalchemy.orm import Session

from .collectors.matcher import STATUS_MATCHED
from .database import DataSource, Ranking, University, get_db

router = APIRouter(prefix="/api")


def _empty_to_none(v):
    if isinstance(v, str) and not v.strip():
        return None
    return v


YearParam = Annotated[int | None, Query(), BeforeValidator(_empty_to_none)]


@router.get("/stats")
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


@router.get("/rankings")
def list_rankings(
    source: str | None = Query(default=None),
    year: YearParam = None,
    q: str | None = Query(default=None, description="大学名の部分一致"),
    country: str | None = Query(default=None),
    match_status: str | None = Query(default=None, choices=["matched", "unmatched", "ambiguous"]),
    matched_only: bool = Query(default=False),
    sort: str = Query(default="source", choices=["source", "year", "rank", "org_name", "country", "score", "match_status"]),
    order: str = Query(default="asc", choices=["asc", "desc"]),
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0),
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


@router.get("/universities")
def list_universities(
    q: str | None = Query(default=None, description="ROR 大学名の部分一致"),
    country: str | None = Query(default=None),
    source: str | None = Query(default=None, choices=["qs", "the", "arwu"]),
    year: YearParam = None,
    matched_only: bool = Query(default=False, description="ランキング一致分のみ"),
    sort: str = Query(default="name", choices=["name", "country", "rank", "rank:qs", "rank:the", "rank:arwu", "matches"]),
    order: str = Query(default="asc", choices=["asc", "desc"]),
    limit: int = Query(default=200, le=1000),
    offset: int = Query(default=0),
    db: Session = Depends(get_db),
):
    stmt = select(University)
    if q:
        stmt = stmt.where(
            (University.name.ilike(f"%{q}%"))
            | (cast(University.aliases, String).ilike(f"%{q}%"))
        )
    if country:
        stmt = stmt.where(University.country == country)

    uni_rows = db.execute(stmt).scalars().all()
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


@router.get("/countries")
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
