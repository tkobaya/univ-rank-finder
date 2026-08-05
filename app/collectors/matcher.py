import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher

from .ror import RorUniversity

STATUS_MATCHED = "matched"
STATUS_UNMATCHED = "unmatched"
STATUS_AMBIGUOUS = "ambiguous"

STOP_WORDS = {
    "the", "of", "and", "a", "an",
    "de", "der", "des", "die", "das", "del", "della", "du", "le", "la", "les",
    "un", "una", "van", "von", "zu", "zur", "zum", "el", "al", "di", "da", "en",
    "et", "und", "y", "i", "at", "o",
}

ABBR = {
    "univ": "university",
    "universite": "university",
    "universitat": "university",
    "universidad": "university",
    "universidade": "university",
    "universita": "university",
    "universiti": "university",
    "universitesi": "university",
    "universitet": "university",
    "inst": "institute",
    "institut": "institute",
    "instituto": "institute",
    "institute": "institute",
    "coll": "college",
    "college": "college",
    "schl": "school",
    "school": "school",
    "tech": "technology",
    "technik": "technology",
    "technika": "technology",
    "technische": "technology",
}

# 原文字列レベルで置換 (トークン化前に適用)
RAW_REPLACE = (
    (r"\bsuny\b", " state university of new york "),
    (r"\buniv\.\b", " university "),
    (r"\binst\.\b", " institute "),
    (r"\bcoll\.\b", " college "),
)

_KIND_WORDS = r"(University|College|Institute|School|Universidad|Universite|Universitat|Instituto)"

_ACRONYM_KIND_WORDS = {"university", "college", "institute", "school", "technology"}


def _maybe_reorder(name: str) -> str:
    """逆順表記 "Essex, University of" -> "University of Essex" に正規化。"""
    m = re.match(rf"^(?P<core>.+?),[ \t]*(?P<kind>{_KIND_WORDS})(?P<of>[ \t]+of)?$", name.strip())
    if m:
        core = m.group("core").strip()
        kind = m.group("kind")
        of = m.group("of")
        if len(core) <= 3:
            return name
        return f"{kind}{of} {core}" if of else f"{kind} {core}"
    return name


def _norm_name(name: str) -> str:
    name = _maybe_reorder(name)
    name = unicodedata.normalize("NFKD", name or "")
    name = "".join(c for c in name if not unicodedata.combining(c)).lower()
    name = name.replace("’", "'").replace("‘", "'")
    name = name.replace("ı", "i")
    name = name.replace("&", " and ")
    name = re.sub(r"\([^)]*\)", " ", name)
    name = name.replace("'", "")
    for pat, repl in RAW_REPLACE:
        name = re.sub(pat, repl, name)
    tokens = re.findall(r"[a-z0-9]+", name)
    keep = []
    for t in tokens:
        t = ABBR.get(t, t)
        if t in STOP_WORDS:
            continue
        keep.append(t)
    return " ".join(keep)


def normalize_name(name: str) -> str:
    return _norm_name(name)


def _norm_country(name: str) -> str:
    name = unicodedata.normalize("NFKD", name or "")
    name = "".join(c for c in name if not unicodedata.combining(c)).lower()
    name = re.sub(r"\([^)]*\)", " ", name)
    return " ".join(re.findall(r"[a-z0-9]+", name))


COUNTRY_ALIASES = {
    "uk": "GB", "great britain": "GB", "britain": "GB", "england": "GB",
    "scotland": "GB", "wales": "GB", "northern ireland": "GB",
    "united kingdom": "GB",
    "usa": "US", "us": "US", "u s": "US", "u s a": "US", "america": "US",
    "united states of america": "US",
    "south korea": "KR", "korea": "KR", "korea republic of": "KR",
    "russia": "RU", "russian federation": "RU",
    "turkey": "TR", "turkiye": "TR",
    "uae": "AE", "united arab emirates": "AE",
    "hong kong": "HK", "hong kong sar": "HK",
    "china": "CN", "china mainland": "CN", "mainland china": "CN",
    "china hong kong": "HK",
    "china taiwan": "TW", "china taiwan region": "TW",
    "china macau": "MO", "china macao": "MO",
    "macau": "MO", "macao": "MO",
    "taiwan": "TW",
    "czech republic": "CZ", "czechia": "CZ",
    "iran islamic republic of": "IR",
    "venezuela bolivarian republic of": "VE",
    "bolivia plurinational state of": "BO",
    "tanzania united republic of": "TZ",
    "moldova republic of": "MD",
    "syrian arab republic": "SY",
    "lao peoples democratic republic": "LA",
    "congo democratic republic of the": "CD",
    "democratic republic of the congo": "CD",
    "palestinian territory": "PS", "palestine": "PS",
    "myanmar": "MM",
    "brunei darussalam": "BN",
    "east timor": "TL", "timor leste": "TL",
    "cote divoire": "CI", "ivory coast": "CI",
    "cabo verde": "CV", "cape verde": "CV",
    "eswatini": "SZ", "swaziland": "SZ",
}


class CountryIndex:
    """ランキングの国名表記 -> ISO 3166-1 alpha-2 コード の解決。"""

    def __init__(self, universities: list[RorUniversity]):
        self._code_by_norm = {}
        for u in universities:
            if u.country and u.country_code:
                self._code_by_norm.setdefault(_norm_country(u.country), u.country_code)
        for alias, code in COUNTRY_ALIASES.items():
            self._code_by_norm.setdefault(_norm_country(alias), code)

    def resolve(self, country_name: str | None) -> str | None:
        if not country_name:
            return None
        return self._code_by_norm.get(_norm_country(country_name))


class UniversityMatcher:
    """ROR の大学データセットに対してランキングの大学名をマッチングする。

    一致は以下の順で試みる:
      1. 正規化後の完全一致
      2. トークン集合が完全一致 (語順違い)
      3. 接頭辞の包含関係 (都市名・キャンパス名の後置)
      4. ファジー一致 (SequenceMatcher)
    """

    def __init__(self, universities: list[RorUniversity]):
        self.countries = CountryIndex(universities)
        self._by_ror: dict[str, RorUniversity] = {u.ror_id: u for u in universities}
        self._name_index: dict[str, list[RorUniversity]] = defaultdict(list)
        self._token_index: dict[str, set] = defaultdict(set)
        self._acronym_index: dict[str, list[str]] = defaultdict(list)
        for u in universities:
            for n in u.search_names:
                norm = normalize_name(n)
                if not norm:
                    continue
                self._name_index[norm].append(u)
                for tok in norm.split():
                    self._token_index[tok].add(u.ror_id)
            for a in u.acronyms:
                na = normalize_name(a)
                if na:
                    self._acronym_index[na].append(u.ror_id)

    def match(self, org_name: str, country_name: str | None = None):
        """(RorUniversity | None, status) を返す。"""
        norm = normalize_name(org_name)
        if not norm:
            return None, STATUS_UNMATCHED

        cc = self.countries.resolve(country_name) if country_name else None

        hit = self._exact(norm, cc)
        if hit:
            return hit, STATUS_MATCHED

        hit = self._token_equal(norm, cc)
        if hit:
            return hit, STATUS_MATCHED

        hit = self._acronym(norm, cc)
        if hit:
            return hit, STATUS_MATCHED

        hit = self._prefix(norm, cc)
        if hit:
            return hit, STATUS_MATCHED

        hit = self._fuzzy(norm, cc)
        if hit:
            uni, ambiguous = hit
            if ambiguous:
                return None, STATUS_AMBIGUOUS
            return uni, STATUS_MATCHED

        return None, STATUS_UNMATCHED

    def _exact(self, norm: str, cc: str | None):
        candidates = self._name_index.get(norm, [])
        if not candidates:
            return None
        if cc:
            for u in candidates:
                if u.country_code == cc:
                    return u
        if len(candidates) == 1:
            return candidates[0]
        return None

    def _token_equal(self, norm: str, cc: str | None):
        qset = set(norm.split())
        if len(qset) < 2:
            return None
        cand_ids: set = set()
        for tok in qset:
            cand_ids |= self._token_index.get(tok, set())
        hits = []
        for rid in cand_ids:
            u = self._by_ror[rid]
            if cc and u.country_code and u.country_code != cc:
                continue
            for n in u.search_names:
                un = normalize_name(n)
                if un and set(un.split()) == qset:
                    hits.append(u)
                    break
        if len(hits) == 1:
            return hits[0]
        return None

    def _acronym(self, norm: str, cc: str | None):
        tokens = set(norm.split())
        if len(tokens) > 3:
            return None
        remaining = tokens - _ACRONYM_KIND_WORDS
        if len(remaining) != 1:
            return None
        hits = []
        for rid in self._acronym_index.get(next(iter(remaining)), []):
            u = self._by_ror[rid]
            if cc and u.country_code and u.country_code != cc:
                continue
            hits.append(u)
        if len(hits) == 1:
            return hits[0]
        return None

    def _prefix(self, norm: str, cc: str | None):
        q = norm.split()
        if len(q) < 2:
            return None
        cand_ids: set = set()
        for tok in q[:2]:
            cand_ids |= self._token_index.get(tok, set())
        hits = set()
        for rid in cand_ids:
            u = self._by_ror[rid]
            if cc and u.country_code and u.country_code != cc:
                continue
            for n in u.search_names:
                un = normalize_name(n)
                if not un:
                    continue
                r = un.split()
                if len(r) < 2:
                    continue
                if (len(q) <= len(r) and q == r[: len(q)]) or (
                    len(r) <= len(q) and r == q[: len(r)]
                ):
                    hits.add((abs(len(q) - len(r)), rid))
        if not hits:
            return None
        min_diff = min(d for d, _ in hits)
        best_ids = [rid for d, rid in hits if d == min_diff]
        if len(best_ids) == 1:
            return self._by_ror[best_ids[0]]
        return None

    def _fuzzy(self, norm: str, cc: str | None):
        tokens = set(norm.split())
        if not tokens:
            return None
        cand_ids: set = set()
        for tok in tokens:
            cand_ids |= self._token_index.get(tok, set())

        scores: dict[str, float] = {}
        for rid in cand_ids:
            u = self._by_ror[rid]
            if cc and u.country_code and u.country_code != cc:
                continue
            best = 0.0
            for n in u.search_names:
                un = normalize_name(n)
                if not un:
                    continue
                best = max(best, SequenceMatcher(None, norm, un).ratio())
            if best > 0:
                scores[rid] = best

        if not scores:
            return None
        best_rid, best_score = max(scores.items(), key=lambda kv: kv[1])
        if best_score < 0.90:
            return None
        tied = [rid for rid, s in scores.items() if s >= best_score]
        if len(tied) > 1:
            return None, True
        return self._by_ror[best_rid], False
