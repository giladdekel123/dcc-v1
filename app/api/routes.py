from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import __version__
from app.config import get_settings
from app.db import DatabaseState, check_database, get_pool
from app.facets import load_facets
from app.models import FacetsResponse, SearchResponse
from app.retrieval.base import Filters
from app.search import MAX_RESULTS, search

router = APIRouter(prefix="/api")

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class HealthResponse(BaseModel):
    status: Literal["ok"]
    app: str
    version: str
    database: DatabaseState


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        app="DCC V1",
        version=__version__,
        database=check_database(),
    )


def _pool():
    pool = get_pool()
    if pool is None:
        raise HTTPException(503, "Database is not configured")
    return pool


@router.get("/search", response_model=SearchResponse)
def search_documents(
    q: str = Query("", max_length=500, description="What you remember about the document"),
    discipline: str | None = None,
    doc_type: str | None = None,
    stage: str | None = None,
    org: str | None = Query(None, description="Originator or sender organisation code"),
    wbs: str | None = Query(None, description="WBS code; includes child elements"),
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(MAX_RESULTS, ge=1, le=MAX_RESULTS),
    debug: bool = Query(False, description="Include score breakdown (evaluation only)"),
) -> SearchResponse:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from is later than date_to")
    filters = Filters(discipline, doc_type, stage, org, wbs, date_from, date_to)
    with _pool().connection() as conn:
        return search(conn, q, filters, limit, debug)


@router.get("/facets", response_model=FacetsResponse)
def facets() -> FacetsResponse:
    with _pool().connection() as conn:
        return load_facets(conn)


@router.get("/revisions/{revision_id}/file")
def open_file(revision_id: int) -> FileResponse:
    with _pool().connection() as conn:
        row = conn.execute(
            "select storage_path, filename, file_format from dcc.revision_file "
            "where revision_id = %s and copy_role = 'primary'", (revision_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Unknown revision")
    storage_path, filename, file_format = row
    root = get_settings().corpus_root.resolve()
    path = (root / storage_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404, "File not available")
    return FileResponse(path, media_type=MEDIA_TYPES[file_format], filename=filename,
                        content_disposition_type="inline")
