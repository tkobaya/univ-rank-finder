import re
from dataclasses import dataclass, field

SOURCE_QS = "qs"
SOURCE_THE = "the"
SOURCE_ARWU = "arwu"


@dataclass
class RankingEntry:
    """A single ranked university as reported by QS / THE."""

    source: str
    year: int
    rank_display: str
    org_name: str
    country: str | None = None
    score: str | None = None
    url: str | None = None
    region: str | None = None
    city: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def rank(self) -> int | None:
        """数値ランク。帯 (例: 201-300) や同等 (例: =2) は可能な限り先頭の数値を返す。"""
        m = re.match(r"[=~]?\s*(\d{1,4})", str(self.rank_display or "").strip())
        if not m:
            return None
        return int(m.group(1))


@dataclass
class CollectorResult:
    source: str
    year: int
    version: str
    entries: list = field(default_factory=list)
    source_url: str | None = None
    published_at: str | None = None
    notes: str | None = None
