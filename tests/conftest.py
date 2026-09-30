import psycopg
import pytest

from app import db
from app.config import get_settings
from app.ingest.load_register import PROJECT_TABLES


@pytest.fixture(autouse=True)
def fresh_pool():
    """Each test starts and ends without a shared pool, so env changes take effect."""
    db.close_pool()
    yield
    db.close_pool()


@pytest.fixture
def conn():
    """A connection whose work is always rolled back. Skips when no database is configured."""
    database_url = get_settings().database_url
    if not database_url:
        pytest.skip("DATABASE_URL not set")
    with psycopg.connect(database_url, prepare_threshold=None, connect_timeout=10) as connection:
        with connection.transaction(force_rollback=True):
            yield connection


@pytest.fixture
def empty_conn(conn):
    """Like conn, but with all project data removed inside the rolled-back transaction."""
    conn.execute("truncate " + ", ".join(f"dcc.{t}" for t in PROJECT_TABLES) + " restart identity")
    return conn
