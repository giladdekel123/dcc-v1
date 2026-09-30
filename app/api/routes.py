from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app import __version__
from app.db import DatabaseState, check_database

router = APIRouter(prefix="/api")


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
