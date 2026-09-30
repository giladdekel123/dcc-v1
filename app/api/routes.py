from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app import __version__
from app.config import get_settings

router = APIRouter(prefix="/api")


class HealthResponse(BaseModel):
    status: Literal["ok"]
    app: str
    version: str
    # Only reports whether DATABASE_URL is set; no connection is attempted yet.
    database: Literal["configured", "not_configured"]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        app="DCC V1",
        version=__version__,
        database="configured" if settings.database_url else "not_configured",
    )
