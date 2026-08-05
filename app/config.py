from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "university_rankings.db"

DEFAULT_ROR_ZIP = DATA_DIR / "v2.11-2026-08-03-ror-data.zip"

QS_PAGE_URL = "https://www.topuniversities.com/world-university-rankings"
QS_ENDPOINT_URL = "https://www.topuniversities.com/rankings/endpoint"
QS_DEFAULT_ITEMS_PER_PAGE = 150

THE_RANKINGS_URL = (
    "https://www.timeshighereducation.com/json/ranking_tables/world_university_rankings"
)

ARWU_RANK_URL = "https://www.shanghairanking.com/api/pub/v1/arwu/rank"

ROR_CONCEPT_RECORD_URL = "https://zenodo.org/api/records/6347574"

HTTP_TIMEOUT = 60
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

EDUCATION_TYPES = ("education", "Education")
