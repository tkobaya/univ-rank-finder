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


def test_import_ror_updates_single_datasource_version(db, monkeypatch):
    from app import services

    db.add_all(
        [
            DataSource(name="ror", version="2.11-2026-08-03", year=None, record_count=26837),
            DataSource(name="ror", version="2.15-2026-10-20", year=None, record_count=31140),
        ]
    )
    db.commit()
    monkeypatch.setattr(services, "parse_ror_dump", lambda _: ([], "2.16-2026-11-05"))

    services.import_ror(db, "unused.zip")

    rows = db.query(DataSource).filter_by(name="ror").all()
    assert len(rows) == 1
    assert rows[0].version == "2.16-2026-11-05"
    assert rows[0].record_count == 0


@pytest.mark.parametrize("query", ["東京", "東京科学大学"])
def test_ror_search_matches_labels(db, query):
    from app.api import search_ror

    db.add(
        University(
            ror_id="05dqf9946",
            name="Institute of Science Tokyo",
            aliases=["Science Tokyo", "科学大"],
            acronyms=["ISCT"],
            labels=["Institute of Science Tokyo", "東京科学大学"],
            country="Japan",
        )
    )
    db.commit()

    result = search_ror(q=query, country=None, limit=20, db=db)

    assert result["total"] == 1
    assert result["items"][0]["ror_id"] == "05dqf9946"
    assert result["items"][0]["matched_name"] == "東京科学大学"


def test_empty_source_and_match_status_filters_are_ignored(db):
    from app.database import get_db
    from app.main import app

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        assert client.get("/api/universities?source=").status_code == 200
        assert client.get("/api/rankings?source=&match_status=").status_code == 200
        assert client.get("/api/universities?limit=-1").status_code == 422
        assert client.get("/api/rankings?offset=-1").status_code == 422
        assert client.get("/api/universities?offset=1000001").status_code == 422
        assert client.get("/api/ror/search", params={"q": "x" * 201}).status_code == 422
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override


def test_university_list_search_matches_non_ascii_labels(db):
    from app.database import get_db
    from app.main import app

    db.add(
        University(
            ror_id="05dqf9946",
            name="Institute of Science Tokyo",
            aliases=["Science Tokyo", "科学大"],
            acronyms=["ISCT"],
            labels=["Institute of Science Tokyo", "東京科学大学"],
            country="Japan",
        )
    )
    db.commit()

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = lambda: db
    try:
        response = TestClient(app).get("/api/universities", params={"q": "東京科学大学"})
        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["ror_id"] == "05dqf9946"
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override


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
