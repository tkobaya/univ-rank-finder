import csv
import io
import json
import zipfile

import pytest

from app.collectors.arwu import fetch_rankings
from app.collectors.base import RankingEntry
from app.collectors.ror import RorUniversity, derive_version_from_filename, parse_ror_dump
from app.collectors.qs import load_from_file

SAMPLE_ROR = [
    {
        "id": "https://ror.org/02jx3x895",
        "names": [
            {"value": "University of Oxford", "types": ["ror_display", "label"], "lang": "en"},
            {"value": "Oxf.", "types": ["acronym"], "lang": None},
            {"value": "University of Oxford", "types": ["alias"], "lang": None},
        ],
        "types": ["education"],
        "locations": [
            {
                "geonames_id": 2640729,
                "geonames_details": {
                    "continent_code": "EU",
                    "continent_name": "Europe",
                    "country_code": "GB",
                    "country_name": "United Kingdom",
                    "name": "Oxford",
                },
            }
        ],
        "links": [
            {"type": "website", "value": "https://www.ox.ac.uk/"},
            {"type": "wikipedia", "value": "http://en.wikipedia.org/wiki/University_of_Oxford"},
        ],
        "status": "active",
    },
    {
        "id": "https://ror.org/03kk7td41",
        "names": [
            {"value": "Big Pharma Corp", "types": ["ror_display", "label"], "lang": "en"},
        ],
        "types": ["company"],
        "locations": [],
        "status": "active",
    },
]


def _zip_with(json_records: list, version: str) -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"v{version}-ror-data.json", json.dumps(json_records))
    import tempfile

    fd, path = tempfile.mkstemp(suffix=f".zip", prefix=f"v{version}-ror-data-")
    with open(fd, "wb") as fh:
        fh.write(buf.getvalue())
    return path


def test_derive_version_from_filename():
    assert derive_version_from_filename("v2.11-2026-08-03-ror-data.zip") == "2.11-2026-08-03"
    assert derive_version_from_filename("ror-data.zip") == "ror-data"


def test_parse_ror_dump_filters_types():
    path = _zip_with(SAMPLE_ROR, "9.9-2026-01-01")
    unis, version = parse_ror_dump(path)
    assert version == "9.9-2026-01-01"
    assert len(unis) == 1
    u = unis[0]
    assert u.ror_id == "02jx3x895"
    assert u.name == "University of Oxford"
    assert u.acronyms == ["Oxf."]
    assert u.country_code == "GB"
    assert u.country == "United Kingdom"
    assert u.region == "Europe"
    assert u.website == "https://www.ox.ac.uk/"
    assert "education" in u.types


def test_load_qs_from_csv(tmp_path):
    csv_text = "2025 Rank,Institution Name,Location,Overall Score\n" \
               "1,Massachusetts Institute of Technology (MIT),United States,100\n" \
               "2,University of Oxford,United Kingdom,99\n"
    p = tmp_path / "qs2025.csv"
    p.write_text(csv_text, encoding="utf-8")
    result = load_from_file(p, year=2025)
    assert result.year == 2025
    assert result.source == "qs"
    assert len(result.entries) == 2
    e = result.entries[0]
    assert e.org_name == "Massachusetts Institute of Technology (MIT)"
    assert e.rank_display == "1"
    assert e.country == "United States"


def test_ranking_entry_rank_parsing():
    assert RankingEntry("qs", 2027, "1", "x").rank == 1
    assert RankingEntry("qs", 2027, "=2", "x").rank == 2
    assert RankingEntry("the", 2026, "201-300", "x").rank == 201
    assert RankingEntry("the", 2026, "1501+", "x").rank == 1501
    assert RankingEntry("qs", 2027, "", "x").rank is None


def test_fetch_arwu_rankings(monkeypatch):
    payload = {
        "code": 200,
        "msg": "success",
        "data": {
            "rankings": [
                {
                    "ranking": "1",
                    "univNameEn": "Harvard University",
                    "univUp": "harvard-university",
                    "region": "United States",
                    "regionRanking": "1",
                    "score": 100,
                },
                {
                    "ranking": "101-150",
                    "univNameEn": "Some University",
                    "univUp": "some-university",
                    "region": "Japan",
                    "regionRanking": "5",
                    "score": 30.5,
                },
            ]
        },
    }

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    def fake_get(url, headers=None, timeout=None):
        assert "version=2025" in url
        return FakeResp()

    monkeypatch.setattr("app.collectors.arwu.requests.get", fake_get)
    result = fetch_rankings(2025)
    assert result.source == "arwu"
    assert result.version == "ARWU2025"
    assert len(result.entries) == 2
    e0 = result.entries[0]
    assert e0.rank_display == "1"
    assert e0.org_name == "Harvard University"
    assert e0.country == "United States"
    assert e0.url == "https://www.shanghairanking.com/institution/harvard-university"
    e1 = result.entries[1]
    assert e1.rank == 101
    assert e1.score == "30.5"


def test_fetch_arwu_api_error(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"code": -1, "msg": "Parameter error"}

    monkeypatch.setattr("app.collectors.arwu.requests.get", lambda url, **kw: FakeResp())
    with pytest.raises(RuntimeError):
        fetch_rankings(2099)
