from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .collectors.base import CollectorResult
from .collectors.matcher import STATUS_MATCHED, UniversityMatcher
from .collectors.ror import RorUniversity, parse_ror_dump
from .database import DataSource, Ranking, University


def _upsert_datasource(
    db: Session,
    name: str,
    version: str,
    year: int | None,
    record_count: int,
    source_url: str | None = None,
    published_at: str | None = None,
    notes: str | None = None,
) -> DataSource:
    row = db.execute(
        select(DataSource).where(
            DataSource.name == name,
            DataSource.version == version,
            DataSource.year == year,
        )
    ).scalar_one_or_none()
    if row is None:
        row = DataSource(name=name, version=version, year=year)
        db.add(row)
    row.record_count = record_count
    row.source_url = source_url or row.source_url
    row.published_at = published_at or row.published_at
    row.notes = notes or row.notes
    row.imported_at = datetime.utcnow()
    db.flush()
    return row


def import_ror(db: Session, zip_path: str, version_hint: str | None = None) -> dict:
    universities, version = parse_ror_dump(zip_path)
    parts = version.split("-")
    published = "-".join(parts[-3:]) if len(parts) >= 3 else None

    existing = {
        r.ror_id: r
        for r in db.execute(select(University)).scalars().all()
    }
    created = updated = 0
    for u in universities:
        rec = existing.get(u.ror_id)
        if rec is None:
            rec = University(ror_id=u.ror_id)
            db.add(rec)
            created += 1
        else:
            updated += 1
        rec.name = u.name
        rec.aliases = u.aliases
        rec.acronyms = u.acronyms
        rec.labels = u.labels
        rec.country = u.country
        rec.country_code = u.country_code
        rec.region = u.region
        rec.website = u.website
        rec.wikipedia_url = u.wikipedia_url
        rec.types = u.types
        rec.ror_version = version

    _upsert_datasource(
        db,
        name="ror",
        version=version,
        year=None,
        record_count=len(universities),
        source_url=f"https://doi.org/10.5281/zenodo.6347574",
        published_at=published,
        notes="ROR data dump (education organizations only)",
    )
    db.commit()
    return {"version": version, "universities": len(universities), "created": created, "updated": updated}


def import_rankings(db: Session, result: CollectorResult) -> dict:
    db.execute(
        Ranking.__table__.delete().where(
            Ranking.source == result.source, Ranking.year == result.year
        )
    )
    for e in result.entries:
        db.add(
            Ranking(
                source=e.source,
                year=e.year,
                rank=e.rank,
                rank_display=e.rank_display,
                score=e.score,
                org_name=e.org_name,
                country=e.country,
                url=e.url,
                region=e.region,
                city=e.city,
                match_status="unmatched",
            )
        )

    _upsert_datasource(
        db,
        name=result.source,
        version=result.version,
        year=result.year,
        record_count=len(result.entries),
        source_url=result.source_url,
        published_at=result.published_at,
        notes=result.notes,
    )
    db.commit()
    return {"source": result.source, "year": result.year, "records": len(result.entries)}


def run_matcher(db: Session) -> dict:
    universities = [
        RorUniversity(
            ror_id=u.ror_id,
            name=u.name,
            aliases=u.aliases,
            acronyms=u.acronyms,
            labels=u.labels,
            country=u.country,
            country_code=u.country_code,
            region=u.region,
            website=u.website,
            wikipedia_url=u.wikipedia_url,
            types=u.types,
        )
        for u in db.execute(select(University)).scalars().all()
    ]
    if not universities:
        return {"matched": 0, "total": 0}

    matcher = UniversityMatcher(universities)
    id_by_ror = {u.ror_id: u.id for u in db.execute(select(University)).scalars().all()}

    rankings = list(db.execute(select(Ranking)).scalars().all())
    matched = 0
    for r in rankings:
        uni, status = matcher.match(r.org_name, r.country)
        r.match_status = status
        r.university_id = id_by_ror.get(uni.ror_id) if uni else None
        if status == STATUS_MATCHED:
            matched += 1
    db.commit()
    return {"matched": matched, "total": len(rankings)}
