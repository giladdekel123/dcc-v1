"""Register loader tests against the dev database. Every load is rolled back."""

import csv
import shutil
from pathlib import Path

import pytest

from app.ingest.load_register import RegisterError, load

pytestmark = pytest.mark.db

CORPUS = Path(__file__).resolve().parent.parent / "corpus"
GA = "KVL-ADM-410-DR-S-0102"


def scalar(conn, sql, params=None):
    return conn.execute(sql, params).fetchone()[0]


def snapshot(conn):
    return {
        table: conn.execute(f"select * from dcc.{table} order by id").fetchall()
        for table in ("document", "revision", "revision_status", "revision_file", "information_link")
    }


@pytest.fixture
def loaded(data_conn):
    return data_conn


@pytest.fixture
def corpus_copy(tmp_path):
    target = tmp_path / "corpus"
    shutil.copytree(CORPUS, target)
    return target


def edit_csv(path: Path, change):
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    fields = list(rows[0])
    change(rows)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_counts(loaded):
    counts = {t: scalar(loaded, f"select count(*) from dcc.{t}") for t in (
        "wbs_element", "organisation", "person", "document", "revision",
        "revision_status", "revision_file", "information_link")}
    assert counts == {
        "wbs_element": 14, "organisation": 6, "person": 14, "document": 47, "revision": 62,
        "revision_status": 73, "revision_file": 64, "information_link": 36,
    }


def test_views_on_real_data(loaded):
    def latest(doc_code, use=None):
        return scalar(loaded, """
            select s.rev_code from dcc.revision_summary s join dcc.document d on d.id = s.document_id
            where d.doc_code = %s and (case when %s::text is null then s.is_latest
                                            else s.is_latest_for_use and s.permitted_use_code = %s end)""",
                      (doc_code, use, use))

    def current_status(doc_code):
        return scalar(loaded, """
            select s.status_code from dcc.revision_summary s join dcc.document d on d.id = s.document_id
            where d.doc_code = %s and s.is_latest""", (doc_code,))

    assert latest(GA) == "P03"
    assert latest(GA, "construction") == "C02"
    assert current_status("KVL-CGC-410-SB-S-0004") == "AN"
    assert current_status("KVL-CGC-410-RI-S-0012") == "CL"
    superseded = {r[0] for r in loaded.execute("""
        select r.rev_code from dcc.revision_file f join dcc.revision r on r.id = f.revision_id
        join dcc.document d on d.id = r.document_id
        where d.doc_code = %s and f.storage_path like 'KVL Project/99 Superseded/%%'""", (GA,))}
    assert superseded == {"P02", "C01"}


def test_link_targets_a_specific_revision(loaded):
    row = loaded.execute("""
        select r.rev_code from dcc.information_link l
        join dcc.document f on f.id = l.from_document_id
        join dcc.document t on t.id = l.to_document_id
        join dcc.revision r on r.id = l.to_revision_id
        where f.doc_code = 'KVL-CGC-410-RI-S-0012' and t.doc_code = %s and l.link_type = 'affects'""",
                         (GA,)).fetchall()
    assert row == [("C02",)]


def test_reload_is_identical(loaded):
    first = snapshot(loaded)
    load(loaded, CORPUS)
    assert snapshot(loaded) == first
    assert scalar(loaded, "select min(id) from dcc.document") == 1


def test_ground_truth_is_not_needed(conn, corpus_copy):
    shutil.rmtree(corpus_copy / "ground_truth")
    load(conn, corpus_copy)
    assert scalar(conn, "select count(*) from dcc.document") == 47


def test_unresolvable_wbs_raises_instead_of_looping(conn, corpus_copy, monkeypatch):
    # validate() normally rejects cycles; bypass it to prove the insert loop itself cannot spin.
    monkeypatch.setattr("app.ingest.load_register.validate", lambda *args: [])
    edit_csv(corpus_copy / "register/wbs.csv",
             lambda rows: [r.update(parent_code={"100": "200", "200": "100"}[r["code"]])
                           for r in rows if r["code"] in ("100", "200")])
    with pytest.raises(RegisterError) as error:
        load(conn, corpus_copy)
    assert any("parent cannot be resolved" in p for p in error.value.problems)


@pytest.mark.parametrize("corrupt, expected", [
    (lambda c: edit_csv(c / "register/revision_files.csv", lambda rows: rows[0].update(sha256="0" * 64)),
     "SHA-256 does not match"),
    (lambda c: edit_csv(c / "register/revision_status.csv", lambda rows: rows[0].update(status_code="FC")),
     "not allowed for document type"),
    (lambda c: edit_csv(c / "links.csv", lambda rows: rows[0].update(to_rev_code="C09")),
     "unresolved"),
    (lambda c: next((c / "KVL Project").rglob("*.docx")).unlink(),
     "file not found"),
])
def test_invalid_register_writes_nothing(conn, corpus_copy, corrupt, expected):
    before = snapshot(conn)
    corrupt(corpus_copy)
    with pytest.raises(RegisterError) as error:
        load(conn, corpus_copy)
    assert any(expected in p for p in error.value.problems)
    assert snapshot(conn) == before
