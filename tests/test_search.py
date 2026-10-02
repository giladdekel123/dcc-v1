"""Search smoke tests on the session-loaded dev data. These prove the engine works end to end;
they are not the evaluation set. Any index rebuild here is rolled back."""

import contextlib
import hashlib
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import db
from app.ingest.build_index import build_index
from app.main import app
from app.retrieval.base import Filters
from app.search import search

pytestmark = pytest.mark.db

ALLOWED_KINDS = {"metadata_match", "content_snippet", "revision_note", "status_note"}
ALLOWED_SOURCES = {"registered", "extracted", "derived"}


@pytest.fixture
def indexed(data_conn):
    return data_conn


def codes(response):
    return [r.document.doc_code for r in response.results]


def test_index_has_one_row_per_revision_and_rebuilds_identically(indexed):
    snapshot = "select revision_id, document_id, tsv::text, trgm_text from dcc.search_entry order by 1"
    first = indexed.execute(snapshot).fetchall()
    assert len(first) == 120
    build_index(indexed)
    assert indexed.execute(snapshot).fetchall() == first


@pytest.mark.parametrize("query, expected, within", [
    ("contractor question about piles and soft clay at the east abutment", "KVL-CGC-410-RI-S-0012", 3),
    ("east abutment general arrangement", "KVL-ADM-410-DR-S-0102", 1),
    ("response to RFI 12 piles", "KVL-ADM-410-LT-S-0031", 3),
    ("abutmnet piling layuot", "KVL-ADM-410-DR-S-0110", 3),
])
def test_smoke_queries(indexed, query, expected, within):
    assert expected in codes(search(indexed, query, Filters()))[:within]


def test_numeric_detail_finds_c02_era_documents(indexed):
    top = search(indexed, "pile toe level -11.15", Filters()).results[:3]
    assert all(r.revision.revision_date.isoformat() >= "2025-06-30" for r in top)


def test_revision_evidence_for_the_general_arrangement(indexed):
    ga = search(indexed, "east abutment general arrangement", Filters()).results[0]
    assert ga.revision.latest_rev_code == "P03"
    assert ga.revision.latest_by_use["construction"] == "C02"
    note = next(e.text for e in ga.evidence if e.kind == "revision_note")
    assert "Latest for construction: C02" in note


def test_filters(indexed):
    minutes = search(indexed, "", Filters(doc_type="MM"))
    # 12 sets of minutes exist; a filter-only search returns the 10 newest
    assert sorted(codes(minutes)) == [f"KVL-CGC-100-MM-G-{n:04d}" for n in range(3, 13)]
    assert {r.document.wbs.code for r in search(indexed, "", Filters(wbs="400")).results} == {"410"}
    early = search(indexed, "piles", Filters(date_to=date(2024, 12, 31)))
    assert early.results and all(r.revision.revision_date.year == 2024 for r in early.results)


def test_response_shape(indexed):
    response = search(indexed, "piles", Filters())
    assert 0 < len(response.results) <= 10
    assert len(set(codes(response))) == len(response.results)   # one result per document
    for r in response.results:
        assert r.location.open_url == f"/api/revisions/{r.revision.id}/file"
        assert {e.kind for e in r.evidence} <= ALLOWED_KINDS
        assert {e.source for e in r.evidence} <= ALLOWED_SOURCES
        assert "debug" not in r.model_dump()
    assert "score" in search(indexed, "piles", Filters(), debug=True).results[0].debug


def test_api_search_and_file(data_conn):
    db.close_pool()
    client = TestClient(app)
    response = client.get("/api/search", params={"q": "east abutment general arrangement", "limit": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["engine"] == "baseline-fts-v1" and len(body["results"]) <= 3
    assert all("debug" not in r and "score" not in r for r in body["results"])

    result = body["results"][0]
    file = client.get(result["location"]["open_url"])
    assert file.status_code == 200 and file.headers["content-type"] == "application/pdf"
    registered_sha = data_conn.execute(
        "select sha256 from dcc.revision_file where revision_id = %s and copy_role = 'primary'",
        (result["revision"]["id"],)).fetchone()[0]
    assert hashlib.sha256(file.content).hexdigest() == registered_sha
    assert client.get("/api/revisions/999999/file").status_code == 404
    assert client.get("/api/search", params={"limit": 11}).status_code == 422


def test_incremental_index_update_matches_a_full_rebuild(indexed):
    snapshot = "select revision_id, document_id, tsv::text, trgm_text from dcc.search_entry order by 1"
    full = indexed.execute(snapshot).fetchall()
    some = [row[0] for row in full[::7]]
    indexed.execute("delete from dcc.search_entry where revision_id = any(%s)", (some,))
    assert build_index(indexed, revision_ids=some) == len(some)
    assert indexed.execute(snapshot).fetchall() == full
    assert build_index(indexed, revision_ids=[]) == 0   # nothing to do, nothing removed
    assert indexed.execute(snapshot).fetchall() == full


class RoundTripCounter:
    """Wraps a connection and counts round trips: each execute outside a pipeline, and each pipeline."""

    def __init__(self, conn):
        self.conn, self.trips, self._in_pipeline = conn, 0, False

    def execute(self, *args, **kwargs):
        self.trips += not self._in_pipeline
        return self.conn.execute(*args, **kwargs)

    @contextlib.contextmanager
    def pipeline(self):
        self.trips += 1
        self._in_pipeline = True
        try:
            with self.conn.pipeline():
                yield
        finally:
            self._in_pipeline = False


def test_search_uses_a_fixed_number_of_round_trips(indexed):
    text = RoundTripCounter(indexed)
    assert len(search(text, "soft clay east abutment piles", Filters()).results) == 10
    assert text.trips == 3                     # ranking, evidence for all results, registered facts

    browse = RoundTripCounter(indexed)
    assert search(browse, "", Filters(doc_type="DR")).results
    assert browse.trips == 2                   # ranking, registered facts

    nothing = RoundTripCounter(indexed)
    assert search(nothing, "zzqxj", Filters()).results == []
    assert nothing.trips == 1


def test_trigram_candidates_cannot_miss_a_row_the_exact_condition_keeps():
    from app.retrieval import baseline_fts
    assert baseline_fts.TRIGRAM_CANDIDATE_MIN < baseline_fts.TRIGRAM_MIN


def test_materialized_scoring_ranks_exactly_like_inline_scoring(indexed):
    """Change set 2: materializing `scored` only avoids re-evaluating its expressions; the ranking
    (ids, order and every score) must be identical to the inline form for every evaluation case."""
    from app.retrieval import baseline_fts
    from eval.check_equivalence import cases

    inline = baseline_fts.RANK_SQL.replace("scored as materialized (", "scored as (")
    assert inline != baseline_fts.RANK_SQL
    indexed.execute(baseline_fts.SET_TRIGRAM_THRESHOLD_SQL, (str(baseline_fts.TRIGRAM_CANDIDATE_MIN),))
    compared = 0
    for case_id, text, f in cases():
        sql, params = baseline_fts.ranking_query(text, f, 10)
        where = " and ".join(baseline_fts.FILTER_SQL[k] for k in f.active()) or "true"
        expected = indexed.execute(inline.format(filters=where), params).fetchall()
        assert indexed.execute(sql, params).fetchall() == expected, case_id
        compared += bool(expected)
    assert compared > 150
