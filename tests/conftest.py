from pathlib import Path

import psycopg
import pytest

from app import db
from app.config import get_settings
from app.ingest.build_index import build_index
from app.ingest.extract_content import extract_all
from app.ingest.load_register import PROJECT_TABLES, load

CORPUS = Path(__file__).resolve().parent.parent / "corpus"


def _database_url() -> str:
    database_url = get_settings().database_url
    if not database_url:
        pytest.skip("DATABASE_URL not set")
    return database_url


@pytest.fixture(autouse=True)
def fresh_pool():
    """Each test starts and ends without a shared pool, so env changes take effect."""
    db.close_pool()
    yield
    db.close_pool()


@pytest.fixture(scope="session")
def rebuilt_db():
    """Rebuild the dev database from the committed corpus once per test session, and commit it.

    Tests then read that data through short, rolled-back `conn` transactions instead of each
    reloading the corpus. Only tests that exercise loading, extraction or indexing run those steps.
    """
    with psycopg.connect(_database_url(), prepare_threshold=None, connect_timeout=10) as connection:
        load(connection, CORPUS)
        extract_all(connection, CORPUS)
        build_index(connection)
        connection.commit()


@pytest.fixture
def conn():
    """A connection whose work is always rolled back. Skips when no database is configured."""
    with psycopg.connect(_database_url(), prepare_threshold=None, connect_timeout=10) as connection:
        with connection.transaction(force_rollback=True):
            yield connection


@pytest.fixture
def data_conn(rebuilt_db, conn):
    """Like conn, on a database holding the committed corpus (registered, extracted and indexed)."""
    return conn


@pytest.fixture
def empty_conn(conn):
    """Like conn, but with all project data removed inside the rolled-back transaction."""
    conn.execute("truncate " + ", ".join(f"dcc.{t}" for t in PROJECT_TABLES) + " restart identity")
    return conn
