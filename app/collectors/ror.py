import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from ..config import DEFAULT_ROR_ZIP, EDUCATION_TYPES


@dataclass
class RorUniversity:
    ror_id: str
    name: str
    aliases: list = field(default_factory=list)
    acronyms: list = field(default_factory=list)
    labels: list = field(default_factory=list)
    country: str | None = None
    country_code: str | None = None
    region: str | None = None
    website: str | None = None
    wikipedia_url: str | None = None
    types: list = field(default_factory=list)

    @property
    def search_names(self) -> list[str]:
        """マッチングに使う全表記 (表示名・別名・略称・ラベル)。"""
        names = [self.name]
        names += self.aliases
        names += self.acronyms
        names += self.labels
        return [n for n in dict.fromkeys(names) if n]


def derive_version_from_filename(path: str | Path) -> str:
    """v2.11-2026-08-03-ror-data.zip のようなファイル名からバージョン文字列を抽出。"""
    name = Path(path).name
    m = re.search(r"v?(\d+\.\d+[-_]\d{4}-\d{2}-\d{2})", name)
    if m:
        return m.group(1)
    return Path(path).stem


def _pick(names: list[dict], wanted: str) -> list[str]:
    out = []
    for n in names:
        types = n.get("types") or []
        if wanted in types and n.get("value"):
            out.append(n["value"])
    return out


def _display_name(names: list[dict]) -> str | None:
    for n in names:
        types = n.get("types") or []
        if "ror_display" in types and n.get("value"):
            return n["value"]
    for n in names:
        types = n.get("types") or []
        if "label" in types and n.get("lang") == "en" and n.get("value"):
            return n["value"]
    for n in names:
        if n.get("value"):
            return n["value"]
    return None


def _first_link(links: list[dict], link_type: str) -> str | None:
    for l in links:
        if l.get("type") == link_type and l.get("value"):
            return l["value"]
    return None


def parse_ror_dump(zip_path: str | Path = DEFAULT_ROR_ZIP) -> tuple[list[RorUniversity], str]:
    """ROR データダンプの ZIP を読み、Education 組織のみ抽出する。"""
    zip_path = Path(zip_path)
    version = derive_version_from_filename(zip_path)

    with zipfile.ZipFile(zip_path) as zf:
        json_name = next(
            (f for f in zf.namelist() if f.endswith(".json")),
            None,
        )
        if json_name is None:
            raise ValueError(f"No JSON file found in {zip_path}")
        with zf.open(json_name) as fh:
            records = json.load(fh)

    universities: list[RorUniversity] = []
    for rec in records:
        types = [str(t).lower() for t in (rec.get("types") or [])]
        if not any(t in EDUCATION_TYPES for t in types):
            continue

        names = rec.get("names") or []
        name = _display_name(names)
        if not name:
            continue

        loc = (rec.get("locations") or [{}])[0]
        geo = loc.get("geonames_details") or {}

        universities.append(
            RorUniversity(
                ror_id=rec.get("id", "").replace("https://ror.org/", ""),
                name=name,
                aliases=_pick(names, "alias"),
                acronyms=_pick(names, "acronym"),
                labels=[n["value"] for n in names if "label" in (n.get("types") or [])],
                country=geo.get("country_name"),
                country_code=geo.get("country_code"),
                region=geo.get("continent_name"),
                website=_first_link(rec.get("links") or [], "website"),
                wikipedia_url=_first_link(rec.get("links") or [], "wikipedia"),
                types=types,
            )
        )

    return universities, version
