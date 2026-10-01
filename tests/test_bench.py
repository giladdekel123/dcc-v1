"""Benchmark harness: the dev-database guard (no database), and a tiny load on the benchmark database."""

import json

import psycopg
import pytest

from eval.bench.run_bench import same_database

DEV = "postgresql://postgres.devref:secret@aws-1-eu-central-1.pooler.supabase.com:5432/postgres"


def test_guard_recognises_the_same_database():
    assert same_database(DEV, DEV.replace("secret", "other-password"))
    assert not same_database(DEV, DEV.replace("devref", "benchref"))
    assert not same_database(DEV, None) and not same_database(None, None)


@pytest.fixture(scope="module")
def bench_conn():
    import os

    import psycopg
    from dotenv import load_dotenv

    from app.config import REPO_ROOT
    load_dotenv(REPO_ROOT / ".env")
    if not os.getenv("BENCH_DATABASE_URL"):
        pytest.skip("BENCH_DATABASE_URL not set")
    from eval.bench.run_bench import bench_database_url
    with psycopg.connect(bench_database_url(), prepare_threshold=None, connect_timeout=20) as connection:
        yield connection


@pytest.mark.bench
def test_tiny_scale_load_index_and_incremental_update(bench_conn):
    from app.ingest.build_index import build_index
    from app.retrieval.base import Filters
    from app.search import search
    from eval.bench.run_bench import corpus_counts, insert_synthetic, load_scale
    from eval.bench.synthetic import generate

    timings = load_scale(bench_conn, 150)
    counts = corpus_counts(bench_conn)
    synthetic = generate(50)
    assert counts["documents"] == 150
    assert counts["revisions"] == 120 + sum(len(d.revisions) for d in synthetic)
    assert timings["index_rows"] == counts["revisions"]

    title = synthetic[5].title
    assert synthetic[5].doc_code in [r.document.doc_code for r in search(bench_conn, title, Filters()).results]

    added = generate(60)[50:]
    revision_ids = insert_synthetic(bench_conn, added)
    assert build_index(bench_conn, revision_ids=revision_ids) == len(revision_ids)
    bench_conn.commit()
    indexed = bench_conn.execute("select count(*) from dcc.search_entry").fetchone()[0]
    assert indexed == counts["revisions"] + len(revision_ids)


class FakeConnection:
    closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def fake_session(monkeypatch):
    """A Session whose connections are fakes; connect attempts and sleeps are recorded, not performed."""
    from eval.bench import run_bench

    state = {"connects": 0, "fail_connects": 0, "sleeps": []}

    def connect(self):
        state["connects"] += 1
        if state["fail_connects"]:
            state["fail_connects"] -= 1
            raise psycopg.OperationalError("failed to resolve host 'pooler': getaddrinfo failed")
        return FakeConnection()

    monkeypatch.setattr(run_bench.Session, "_connect", connect)
    monkeypatch.setattr(run_bench.time, "sleep", lambda seconds: state["sleeps"].append(seconds))

    def make(**kwargs):
        return run_bench.Session("postgresql://unused", **kwargs), state
    return make


def test_session_reconnects_after_a_dropped_connection(fake_session):
    session, _ = fake_session()
    calls = []

    def flaky(conn):
        calls.append(conn)
        if len(calls) == 1:
            raise psycopg.OperationalError("server closed the connection unexpectedly")
        return "ok"

    assert session.call(flaky) == "ok"
    assert session.reconnects == 1 and session.stalls == 0
    assert calls[0] is not calls[1] and calls[0].closed
    assert [e["kind"] for e in session.events] == ["error"]


def test_a_call_that_never_returns_is_abandoned_and_retried(fake_session):
    """The real failure: nothing ever comes back, so nothing in the network layer would end the wait."""
    import threading
    import time

    session, _ = fake_session(stall_timeout=0.5)
    never = threading.Event()
    calls = []

    def hangs_once(conn):
        calls.append(conn)
        if len(calls) == 1:
            never.wait()                                   # blocks forever, like the stalled searches
        return "ok"

    t = time.perf_counter()
    assert session.call(hangs_once) == "ok"
    assert time.perf_counter() - t < 2
    assert session.stalls == 1 and session.reconnects == 1
    assert not calls[0].closed                             # still owned by the stuck thread; never touched
    assert session.events[0]["kind"] == "stall" and "no result within 0.5 s" in session.events[0]["detail"]


def test_reconnect_retries_with_increasing_waits_through_a_dns_outage(fake_session):
    session, state = fake_session()
    state["fail_connects"] = 3

    def drops(conn):
        if state["connects"] == 1:
            raise psycopg.OperationalError("server closed the connection unexpectedly")
        return "ok"

    assert session.call(drops) == "ok"
    assert state["sleeps"] == [5.0, 10.0, 20.0]
    assert [e["kind"] for e in session.events] == ["error", "connect-failed", "connect-failed", "connect-failed"]


def test_reconnect_gives_up_after_reconnect_for(fake_session):
    session, state = fake_session(reconnect_for=30)
    state["fail_connects"] = 100

    def drops(conn):
        raise psycopg.OperationalError("server closed the connection unexpectedly")

    with pytest.raises(psycopg.OperationalError, match="getaddrinfo"):
        session.call(drops)
    assert state["sleeps"] == [5.0, 10.0]                  # a third wait (20 s) would pass the 30 s limit
    assert "giving up" in session.events[-1]["detail"]


def test_writes_are_not_retried_and_failures_end_after_the_last_attempt(fake_session):
    session, _ = fake_session(attempts=3)
    calls = []

    def fails(conn):
        calls.append(conn)
        raise psycopg.OperationalError("server closed the connection unexpectedly")

    with pytest.raises(psycopg.OperationalError):
        session.call(fails, retry=False)
    assert len(calls) == 1 and session.reconnects == 1     # replaced the connection, did not repeat the write

    calls.clear()
    with pytest.raises(psycopg.OperationalError):
        session.call(fails)
    assert len(calls) == 3


def test_workload_checkpoints_partial_results_before_a_crash():
    from eval.bench.run_bench import run_workload

    class CrashingSession:
        reconnects = 0

        def __init__(self):
            self.searches = 0

        def call(self, fn, *args, **kwargs):
            self.searches += 1
            if self.searches > 2 * 25:                      # warm-up + 1 timed run per query; crash in query 26
                raise psycopg.OperationalError("failed to resolve host")

    results, saved = {}, []
    with pytest.raises(psycopg.OperationalError):
        run_workload(CrashingSession(), 1, 98, 30, 20, results=results,
                     checkpoint=lambda: saved.append(json.loads(json.dumps(results, default=str))))
    assert len(saved) == 2                                 # after queries 10 and 20
    assert saved[-1]["text_only"]["queries"] == 20 and saved[-1]["text_only"]["complete"] is False


def test_report_lists_connection_events_and_incomplete_sets():
    from eval.bench.run_bench import markdown

    report = {
        "label": "x", "engine": "e", "created": "2026-10-01", "database_region": "eu-west-1",
        "corpus": {"documents": 200, "revisions": 1, "files": 1}, "round_trip_ms": 80, "reconnects": 1, "stalls": 1,
        "stall_timeout_s": 60, "workload": {"text": 1, "text_plus_filters": 0, "filters_only": 0, "reps": 1},
        "latency": {"text_only": {"queries": 5, "p50_ms": 1, "p95_ms": 2, "max_ms": 3, "complete": False},
                    "excluded_samples": []},
        "ranking_explain": {"queries": 1, "p50_ms": 1, "p95_ms": 1, "search_entry_access": {}},
        "load": {"load_real_corpus_s": 1.0, "insert_synthetic_s": 1.0, "generate_s": 0.0,
                 "full_index_build_s": 1.0, "index_rows": 1},
        "storage": {"database_mb": 1, "dcc_total_mb": 1, "indexes_mb": 1, "tables_mb": {}},
        "incremental": {"batch": 1, "add_documents_insert_s": 1, "add_documents_index_s": 1,
                        "add_revisions_insert_s": 1, "add_revisions_index_s": 1},
        "known_items": {"hit@1": 1, "hit@10": 1},
        "connection_events": [{"time": "16:04:32", "kind": "stall", "call": "search", "detail": "no result within 60 s"}],
    }
    text = markdown(report)
    assert "| text_only (incomplete) | 5 |" in text
    assert "- 16:04:32 stall during search: no result within 60 s" in text


@pytest.mark.bench
def test_incremental_change_adds_and_indexes_revisions_in_bulk(bench_conn):
    from eval.bench.run_bench import incremental

    before = bench_conn.execute("select count(*) from dcc.revision").fetchone()[0]
    result = incremental(bench_conn, 160, batch=20)
    assert result["batch"] == 20 and result["add_revisions_indexed"] == 20
    added = bench_conn.execute("""
        select count(distinct r.id), count(distinct s.revision_id), count(distinct e.revision_id),
               count(distinct f.id), count(distinct seg.revision_file_id)
        from dcc.revision r
        left join dcc.revision_status s on s.revision_id = r.id
        left join dcc.search_entry e on e.revision_id = r.id
        left join dcc.revision_file f on f.revision_id = r.id and f.copy_role = 'primary'
        left join dcc.content_segment seg on seg.revision_file_id = f.id
        where r.rev_code = 'P09'""").fetchone()
    assert added == (20, 20, 20, 20, 20)     # status, index entry, primary file and copied text for each
    after = bench_conn.execute("select count(*) from dcc.revision").fetchone()[0]
    assert after > before + 20                       # the 20 new documents brought their own revisions too


def _bench_session(stall_timeout):
    import os

    from dotenv import load_dotenv

    from app.config import REPO_ROOT
    load_dotenv(REPO_ROOT / ".env")
    if not os.getenv("BENCH_DATABASE_URL"):
        pytest.skip("BENCH_DATABASE_URL not set")
    from eval.bench.run_bench import Session, bench_database_url
    return Session(bench_database_url(), stall_timeout=stall_timeout)


@pytest.mark.bench
def test_session_connections_use_tcp_keepalives():
    session = _bench_session(60)
    try:
        params = session.conn.info.get_parameters()
        assert params.get("keepalives") == "1" and params.get("keepalives_idle") == "10"
    finally:
        session.close()


@pytest.mark.bench
def test_a_stalled_statement_on_the_benchmark_database_is_abandoned_and_retried():
    import time

    session = _bench_session(stall_timeout=2)
    attempts = []

    def stalls_once(conn):
        attempts.append(conn)
        seconds = 8 if len(attempts) == 1 else 0           # first attempt: no result within the time limit
        return conn.execute("select pg_sleep(%s), 42", (seconds,)).fetchone()[1]

    try:
        t = time.perf_counter()
        assert session.call(stalls_once) == 42
        assert time.perf_counter() - t < 7                   # abandoned after ~2 s, not awaited
        assert session.reconnects == 1 and session.stalls == 1
        assert attempts[0] is not attempts[1]
        assert session.conn.execute("select 1").fetchone()[0] == 1   # the new connection is healthy
    finally:
        session.close()
