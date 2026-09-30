"""Application settings, read from environment variables (optionally via .env)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = REPO_ROOT / "web"

load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    corpus_root: Path


def get_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL") or None,
        corpus_root=REPO_ROOT / os.getenv("CORPUS_ROOT", "corpus"),
    )
