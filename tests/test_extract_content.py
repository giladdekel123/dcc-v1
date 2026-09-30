"""Extraction into the dev database. Every run is rolled back."""

import shutil
from pathlib import Path

import pytest

from app.ingest.extract_content import extract_all
from app.ingest.load_register import load

pytestmark = pytest.mark.db

CORPUS = Path(__file__).resolve().parent.parent / "corpus"
REGISTERED = ("document", "revision", "revision_status", "revision_file", "information_link")


def registered_snapshot(conn):
    return {t: conn.execute(f"select * from dcc.{t} order by id").fetchall() for t in REGISTERED}


def extracted_snapshot(conn):
    return (
        conn.execute("select revision_file_id, outcome, error, unit_count, extracted_fields "
                     "from dcc.extraction order by 1").fetchall(),
        conn.execute("select revision_file_id, seq, locator, body from dcc.content_segment order by 1, 2").fetchall(),
    )


@pytest.fixture
def loaded(conn):
    load(conn, CORPUS)
    return conn


def test_every_file_extracted_and_registered_data_untouched(loaded):
    before = registered_snapshot(loaded)
    results = extract_all(loaded, CORPUS)
    assert len(results) == 64 and {r.outcome for r in results.values()} == {"ok"}
    assert loaded.execute("select count(*) from dcc.extraction where outcome = 'ok'").fetchone()[0] == 64
    no_segments = loaded.execute("""
        select count(*) from dcc.extraction e
        where not exists (select 1 from dcc.content_segment s where s.revision_file_id = e.revision_file_id)
    """).fetchone()[0]
    assert no_segments == 0
    assert registered_snapshot(loaded) == before


def test_rerun_is_identical(loaded):
    extract_all(loaded, CORPUS)
    first = extracted_snapshot(loaded)
    extract_all(loaded, CORPUS)
    assert extracted_snapshot(loaded) == first


def test_extracted_status_can_disagree_with_registered_status(loaded):
    extract_all(loaded, CORPUS)
    registered, extracted = loaded.execute("""
        select cs.status_code, e.extracted_fields ->> 'status_code'
        from dcc.document d
        join dcc.revision r on r.document_id = d.id and r.rev_code = 'P03'
        join dcc.revision_current_status cs on cs.revision_id = r.id
        join dcc.revision_file f on f.revision_id = r.id and f.copy_role = 'primary'
        join dcc.extraction e on e.revision_file_id = f.id
        where d.doc_code = 'KVL-ADM-410-DR-S-0102'
    """).fetchone()
    assert (registered, extracted) == ("RV", "FC")


def test_changed_file_is_recorded_as_failed(loaded, tmp_path):
    corpus = tmp_path / "corpus"
    shutil.copytree(CORPUS, corpus)
    changed = next((corpus / "KVL Project").rglob("*.xlsx"))
    changed.write_bytes(changed.read_bytes() + b"tampered")
    results = extract_all(loaded, corpus)
    failed = {path: r for path, r in results.items() if r.outcome == "failed"}
    assert len(failed) == 1 and "SHA-256 mismatch" in next(iter(failed.values())).error
    assert sum(r.outcome == "ok" for r in results.values()) == 63
