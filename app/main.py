import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .api import router as api_router
from .database import init_db

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# External URL prefix when the app is served behind a reverse proxy
# (e.g. https://host/webapp/univ-rank-finder -> ROOT_PATH=/webapp/univ-rank-finder).
ROOT_PATH = os.getenv("ROOT_PATH", "").rstrip("/")

app = FastAPI(
    title="University Rank Finder",
    version="0.1.0",
    root_path=ROOT_PATH,
    docs_url=None,
    redoc_url=None,
)
app.include_router(api_router)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


def _openapi_url() -> str:
    url = app.openapi_url or "/openapi.json"
    return f"{ROOT_PATH}{url}" if ROOT_PATH else url


@app.get("/docs", include_in_schema=False)
@app.get("/docs/openapi", include_in_schema=False)
def openapi_docs() -> HTMLResponse:
    return get_swagger_ui_html(
        openapi_url=_openapi_url(),
        title=f"{app.title} - OpenAPI",
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
