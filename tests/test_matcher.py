import os
import tempfile

import pytest

os.environ["UNIV_RANK_DB"] = "test"  # noqa: E402 (placeholder; DB path overridden below)

from app.collectors.matcher import (  # noqa: E402
    STATUS_AMBIGUOUS,
    STATUS_MATCHED,
    STATUS_UNMATCHED,
    CountryIndex,
    UniversityMatcher,
    normalize_name,
)
from app.collectors.ror import RorUniversity  # noqa: E402


def make_uni(ror_id, name, cc=None, country=None, aliases=(), acronyms=(), labels=()):
    return RorUniversity(
        ror_id=ror_id,
        name=name,
        country=country or "Testland",
        country_code=cc or "XX",
        aliases=list(aliases),
        acronyms=list(acronyms),
        labels=list(labels),
    )


UNIVERSITIES = [
    make_uni("a1", "University of Oxford", "GB", "United Kingdom"),
    make_uni("a2", "Massachusetts Institute of Technology", "US", "United States", acronyms=["MIT"]),
    make_uni("a3", "Imperial College London", "GB", "United Kingdom"),
    make_uni("a4", "Radboud University Nijmegen", "NL", "Netherlands"),
    make_uni("a5", "Queen's University", "CA", "Canada"),
    make_uni("a6", "University of Essex", "GB", "United Kingdom"),
    make_uni("a7", "Ulster University, Derry-Londonderry Campus", "GB", "United Kingdom"),
    make_uni("a8", "University of Ulster", "GB", "United Kingdom"),
    make_uni("a9", "Sciences Po Lille", "FR", "France"),
    make_uni("a10", "National Research University Higher School of Economics", "RU", "Russia", acronyms=["HSE"]),
    make_uni("a11", "Symbiosis International University", "IN", "India"),
    make_uni("a12", "Gordon College", "PH", "Philippines"),
    make_uni("a13", "Gordon College", "US", "United States"),
    make_uni("a14", "University of Canterbury", "NZ", "New Zealand"),
]


@pytest.fixture
def matcher():
    return UniversityMatcher(UNIVERSITIES)


def test_normalize_name_basic():
    assert normalize_name("University of Oxford") == "university oxford"
    assert normalize_name("The University of Cambridge") == "university cambridge"
    assert normalize_name("MIT") == "mit"


def test_normalize_name_reversed():
    assert normalize_name("Essex, University of") == "university essex"


def test_normalize_name_special_chars():
    assert normalize_name("Rutgers University–New Brunswick") == "rutgers university new brunswick"
    assert normalize_name("Queen's University at Kingston") == "queens university kingston"
    assert normalize_name("University of Canterbury | Te Whare") == "university canterbury te whare"


def test_normalize_name_turkish_and_curly_quote():
    assert normalize_name("Fırat University") == "firat university"
    assert normalize_name("İstanbul Topkapı University") == "istanbul topkapi university"
    assert normalize_name("Chang’an University") == "changan university"


def test_exact_match_with_country(matcher):
    uni, status = matcher.match("University of Oxford", "United Kingdom")
    assert status == STATUS_MATCHED
    assert uni.ror_id == "a1"


def test_exact_match_ignores_country_when_unique(matcher):
    uni, status = matcher.match("Imperial College London", None)
    assert status == STATUS_MATCHED
    assert uni.ror_id == "a3"


def test_acronym_match(matcher):
    uni, status = matcher.match("MIT", "United States")
    assert status == STATUS_MATCHED
    assert uni.ror_id == "a2"


def test_ror_longer_name_prefix(matcher):
    uni, status = matcher.match("Radboud University", "Netherlands")
    assert status == STATUS_MATCHED
    assert uni.ror_id == "a4"


def test_ranking_longer_name_prefix(matcher):
    uni, status = matcher.match("University at Buffalo SUNY", "United States")
    assert uni is None  # 対象外の大学
    uni, status = matcher.match("Queen's University at Kingston", "Canada")
    assert status == STATUS_MATCHED
    assert uni.ror_id == "a5"


def test_reversed_name(matcher):
    uni, status = matcher.match("Essex, University of", "United Kingdom")
    assert status == STATUS_MATCHED
    assert uni.ror_id == "a6"


def test_token_order_swap(matcher):
    uni, status = matcher.match("Ulster University", "United Kingdom")
    assert status == STATUS_MATCHED
    assert uni.ror_id == "a8"  # University of Ulster (トークン集合一致)


def test_country_disambiguation_ambiguous(matcher):
    uni, status = matcher.match("Gordon College", "Philippines")
    assert status == STATUS_MATCHED
    assert uni.ror_id == "a12"
    uni, status = matcher.match("Gordon College", None)
    assert status == STATUS_AMBIGUOUS
    assert uni is None


def test_no_match(matcher):
    uni, status = matcher.match("Definitely Not A University 12345", "Japan")
    assert uni is None
    assert status == STATUS_UNMATCHED


def test_hse_acronym(matcher):
    uni, status = matcher.match("HSE University", "Russia")
    assert status == STATUS_MATCHED
    assert uni.ror_id == "a10"


def test_deemed_university_suffix(matcher):
    uni, status = matcher.match("Symbiosis International (Deemed University)", "India")
    assert status == STATUS_MATCHED
    assert uni.ror_id == "a11"


def test_prefix_match_with_extra_tokens(matcher):
    uni, status = matcher.match("University of Canterbury | Te Whare Wānanga o Waitaha", "New Zealand")
    assert status == STATUS_MATCHED
    assert uni.ror_id == "a14"


def test_country_index():
    ci = CountryIndex(UNIVERSITIES)
    assert ci.resolve("United Kingdom") == "GB"
    assert ci.resolve("UK") == "GB"
    assert ci.resolve("usa") == "US"
    assert ci.resolve("South Korea") == "KR"
    assert ci.resolve(None) is None
