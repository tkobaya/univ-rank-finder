from pathlib import Path

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .api import router as api_router
from .database import init_db

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="University Rank Finder", version="0.1.0")
app.include_router(api_router)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/docs/openapi", include_in_schema=False)
def openapi_docs() -> HTMLResponse:
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - OpenAPI",
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
