import os
import tempfile
from pathlib import Path

os.environ["UNIV_RANK_DB"] = "test"  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.collectors.base import CollectorResult, RankingEntry  # noqa: E402
from app.database import Base, DataSource, Ranking, University  # noqa: E402


@pytest.fixture
def db(tmp_path):
    from app import services
    from app.database import SessionLocal, engine, init_db

    # 一時 DB に差し替え
    db_path = tmp_path / "test.db"
    test_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(test_engine)
    test_session = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)

    # engine / SessionLocal を差し替え (テスト用)
    import app.database as database_mod

    original_engine = database_mod.engine
    original_session = database_mod.SessionLocal
    database_mod.engine = test_engine
    database_mod.SessionLocal = test_session

    db = test_session()
    yield db
    db.close()
    database_mod.engine = original_engine
    database_mod.SessionLocal = original_session


def test_import_ror_and_match(db):
    from app import services
    from app.collectors.matcher import STATUS_MATCHED

    ror_unis = [
        {
            "ror_id": "a1", "name": "University of Oxford", "aliases": [], "acronyms": [],
            "labels": [], "country": "United Kingdom", "country_code": "GB",
            "region": "Europe", "types": ["education"],
        },
    ]
    for u in ror_unis:
        db.add(University(**u))
    db.commit()

    result = CollectorResult(
        source="qs",
        year=2027,
        version="QS2027",
        entries=[
            RankingEntry(source="qs", year=2027, rank_display="4", org_name="University of Oxford", country="United Kingdom"),
            RankingEntry(source="qs", year=2027, rank_display="999", org_name="No Such University", country="Japan"),
        ],
    )
    services.import_rankings(db, result)

    info = services.run_matcher(db)
    assert info["matched"] == 1
    assert info["total"] == 2

    oxford = db.query(Ranking).filter_by(org_name="University of Oxford").one()
    assert oxford.match_status == STATUS_MATCHED
    assert oxford.university.ror_id == "a1"

    ds = db.query(DataSource).filter_by(name="qs").one()
    assert ds.version == "QS2027"
    assert ds.year == 2027
    assert ds.record_count == 2


def test_import_rankings_replaces_same_year(db):
    from app import services

    r1 = CollectorResult(source="the", year=2026, version="THE2026",
                         entries=[RankingEntry("the", 2026, "1", "Uni A")])
    r2 = CollectorResult(source="the", year=2026, version="THE2026",
                         entries=[RankingEntry("the", 2026, "2", "Uni B")])
    services.import_rankings(db, r1)
    services.import_rankings(db, r2)
    assert db.query(Ranking).count() == 1
    assert db.query(Ranking).one().org_name == "Uni B"


def test_datasource_unique_per_version(db):
    from app import services

    r = CollectorResult(source="qs", year=2025, version="QS2025",
                        entries=[RankingEntry("qs", 2025, "1", "Uni")])
    services.import_rankings(db, r)
    services.import_rankings(db, r)
    assert db.query(DataSource).filter_by(name="qs", year=2025).count() == 1
