"""Postgres (Supabase) connection pool and database health check."""

import threading
from typing import Literal

import psycopg
from psycopg_pool import ConnectionPool

from app.config import get_settings

DatabaseState = Literal["not_configured", "ok", "schema_missing", "unreachable"]

_pool: ConnectionPool | None = None
# Sync endpoints run in a threadpool; without the lock two first requests could each create a pool.
_pool_lock = threading.Lock()


def get_pool() -> ConnectionPool | None:
    """Return the shared pool, creating it on first use. None if DATABASE_URL is unset."""
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            database_url = get_settings().database_url
            if not database_url:
                return None
            pool = ConnectionPool(
                database_url,
                min_size=1,
                max_size=5,
                open=False,
                # prepare_threshold=None: Supabase's transaction pooler does not support prepared statements.
                kwargs={"prepare_threshold": None, "connect_timeout": 5},
            )
            pool.open(wait=False)
            _pool = pool
    return _pool


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


def check_database() -> DatabaseState:
    pool = get_pool()
    if pool is None:
        return "not_configured"
    try:
        with pool.connection(timeout=5) as conn:
            schema_present = conn.execute("select to_regclass('dcc.document') is not null").fetchone()[0]
    except psycopg.Error:  # includes PoolTimeout
        return "unreachable"
    return "ok" if schema_present else "schema_missing"
