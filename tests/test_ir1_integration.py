"""IR-1 integration adapter on synthetic rows and fake connections. No database, no .env, no retrieval.

Every ranking row, fact row and connection here is handmade. The frozen request file is read only
for load_request; no frozen plan is run.
"""

import contextlib
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from app.models import CodeLabel, DocumentInfo, Location, ResultItem, RevisionInfo, SearchResponse
from app.retrieval import baseline_fts
from app.retrieval.base import Filters
from eval.experiments import ir1_integration as ia
from eval.experiments.ir1_engine import Link, Switches
from eval.experiments.ir1_integration import RankRow
from eval.experiments.ir1_request import POOL_SIZE, parse_request, plan

REPO = Path(__file__).resolve().parent.parent
RAW = "WBS 320 the drawing letter report from the contractor at stage pond flow control"


def mk_plan(text=RAW, clues=(), relation=None, revision_state="best_match", document_state="any"):
    item = {"id": "T", "raw_text": RAW, "text": text, "clues": list(clues), "revision_state": revision_state,
            "document_state": document_state, "approx": [], "verify": [], "withdrawn": []}
    if relation:
        item["relation"] = relation
    return plan(parse_request(item))


def clue(field, code, strength, source):
    return {"field": field, "code": code, "strength": strength, "source": source}


RELATION = {"link_type": "responds_to", "target_side": "from", "anchor_text": "the reply letter", "source": "letter"}


def row(doc_id, score, rev_id=None, trigram=0.0, tsq="'pond'"):
    return RankRow(rev_id or doc_id * 10 + 1, doc_id, score, 0.5, score - 0.5, trigram, tsq)


class FakeRanker:
    def __init__(self, rows=(), anchors=()):
        self.rows, self.anchors, self.calls = tuple(rows), tuple(anchors), []

    def __call__(self, conn, query, filters, limit):
        self.calls.append((query, filters, limit))
        if limit == ia.ANCHOR_COUNT:
            return tuple(row(d, 1.0) for d in self.anchors[:limit])
        return self.rows[:limit]


# Synthetic registered rows for documents 1-3 (pool) and 9 (outside, linked to anchor 1).
DOC_ROWS = [(1, "DOC-001", "DR", "D", "321", "AAA"), (2, "DOC-002", "LT", "S", "330", "BBB"),
            (3, "DOC-003", "RP", "D", "320", "AAA"), (9, "DOC-009", "LT", "D", "320", "NVW")]
REV_ROWS = [(11, 1, "P01", date(2025, 1, 1), "DD", None, None),
            (21, 2, "P01", date(2025, 2, 1), "DD", "SND", "information"),
            (31, 3, "P01", date(2024, 3, 1), "PD", None, None),
            (32, 3, "C01", date(2025, 3, 1), "CN", None, "construction"),
            (91, 9, "P01", date(2024, 5, 1), "DD", None, None),
            (92, 9, "P02", date(2025, 5, 1), "DD", None, "information")]
LINK_ROWS = [(7, 9, 91, 1, None, "responds_to", "registered"), (8, 3, None, 2, None, "related_to", "extracted")]
WBS_ROWS = [("300", None), ("320", "300"), ("321", "320"), ("330", "300")]


def synthetic_facts():
    return ia.facts_from_rows(DOC_ROWS, REV_ROWS, LINK_ROWS, WBS_ROWS)


# --- A-D: pool conversion ----------------------------------------------------------------------

def test_pool_keeps_raw_scores_matched_revisions_and_row_order():
    rows = [row(3, 2.123456789, rev_id=32), row(1, 2.123456781), row(2, 0.000012345)]
    pool, kept = ia.conventional_pool(None, mk_plan(), Switches(), ranker=FakeRanker(rows))
    assert [(e.document_id, e.baseline_score, e.matched_revision_id) for e in pool] == \
        [(3, 2.123456789, 32), (1, 2.123456781, 11), (2, 0.000012345, 21)]           # A, B, C: unrounded
    assert kept == tuple(rows)


def test_pool_limit_is_fifty():
    ranker = FakeRanker([row(i, 100.0 - i) for i in range(1, 80)])
    pool, _ = ia.conventional_pool(None, mk_plan(), Switches(), ranker=ranker)
    assert POOL_SIZE == 50 and ranker.calls[0][2] == 50 and len(pool) == 50          # D


# --- E-H: query text and filters ---------------------------------------------------------------

def test_lexical_query_follows_the_m2_switch():
    p = mk_plan(text="pond flow control", clues=[clue("discipline", "D", "context", "pond")])
    on, off = FakeRanker(), FakeRanker()
    ia.conventional_pool(None, p, Switches(), ranker=on)
    ia.conventional_pool(None, p, Switches(m2=False), ranker=off)
    assert on.calls[0][0] == "flow control" == p.pool_text                            # E: C2 pool_text
    assert off.calls[0][0] == "pond flow control" == p.audit.text                     # F: frozen text


def test_m1_filters_become_existing_filters():
    p = mk_plan(clues=[clue("doc_type", "DR", "confirmed", "drawing"), clue("originator", "AAA", "confirmed",
                                                                             "contractor")])
    ranker = FakeRanker()
    ia.conventional_pool(None, p, Switches(), ranker=ranker)
    assert ranker.calls[0][1] == Filters(doc_type="DR", org="AAA")                    # G


def test_conventional_only_filters_reach_ranking_but_not_stage2():
    p = mk_plan()
    extra = Filters(wbs="320", date_from=date(2025, 1, 1))
    ranker = FakeRanker([row(1, 1.0)])
    pool, _ = ia.conventional_pool(None, p, Switches(), extra_filters=extra, ranker=ranker)
    assert ranker.calls[0][1] == extra                                                 # H: ranking sees them
    outcome = ia.execute_ir1(p, pool, synthetic_facts(), (), Switches())
    assert outcome.filters == {} and p.filters() == {}                                 # H: Stage 2 does not


def test_conflicting_plan_and_conventional_filters_are_rejected():
    p = mk_plan(clues=[clue("doc_type", "DR", "confirmed", "drawing")])
    assert ia.conventional_filters(p, Filters(doc_type="DR")) == Filters(doc_type="DR")
    with pytest.raises(ValueError, match="doc_type"):
        ia.conventional_filters(p, Filters(doc_type="LT"))


# --- I: anchors ---------------------------------------------------------------------------------

def test_anchor_ranking_uses_anchor_text_no_filters_three_documents():
    p = mk_plan(clues=[clue("doc_type", "DR", "confirmed", "drawing")], relation=RELATION)
    ranker = FakeRanker(anchors=[5, 6, 7, 8])
    assert ia.anchor_ranking(None, p, Switches(), ranker) == (5, 6, 7)
    assert ranker.calls == [("the reply letter", Filters(), 3)]
    assert ia.anchor_ranking(None, p, Switches(m3=False), ranker) == ()
    assert ia.anchor_ranking(None, mk_plan(), Switches(), ranker) == ()               # no relation
    assert len(ranker.calls) == 1


# --- J-L: fact mapping --------------------------------------------------------------------------

def test_link_rows_map_every_field():
    link = ia.link_from_row((7, 9, 91, 1, None, "responds_to", "registered"))
    assert link == Link(from_document_id=9, to_document_id=1, link_type="responds_to", provenance="registered",
                        from_revision_id=91, to_revision_id=None, id=7)              # J
    assert ia.link_from_row((8, 3, None, 2, 22, "related_to", "extracted")).provenance == "extracted"


def test_document_and_revision_rows_map_every_field():
    facts = synthetic_facts()
    d2 = facts.document(2)
    assert (d2.doc_code, d2.doc_type, d2.discipline, d2.wbs, d2.originator) == ("DOC-002", "LT", "S", "330", "BBB")
    (r21,) = d2.revisions
    assert (r21.id, r21.rev_code, r21.revision_date, r21.stage, r21.sender, r21.permitted_use) == \
        (21, "P01", date(2025, 2, 1), "DD", "SND", "information")                    # K
    assert [r.rev_code for r in facts.document(3).revisions] == ["P01", "C01"]
    assert facts.document(3).revisions[1].permitted_use == "construction"


def test_wbs_parent_mapping_is_preserved():
    assert dict(synthetic_facts().wbs_parent) == {"300": None, "320": "300", "321": "320", "330": "300"}   # L


class FakeConn:
    """Answers the adapter's read-only fact queries from the synthetic rows."""

    def __init__(self):
        self.queries = []

    def execute(self, sql, params=None):
        self.queries.append((sql, params))
        if sql is ia.LINKS_SQL:
            ids = set(params["ids"])
            rows = [r for r in LINK_ROWS if r[1] in ids or r[3] in ids]
        elif sql is ia.DOCUMENTS_SQL:
            rows = [r for r in DOC_ROWS if r[0] in params[0]]
        elif sql is ia.REVISIONS_SQL:
            rows = [r for r in REV_ROWS if r[1] in params[0]]
        elif sql is ia.WBS_SQL:
            rows = WBS_ROWS
        else:
            raise AssertionError("unexpected SQL")
        return type("Cursor", (), {"fetchall": lambda self: list(rows)})()


def test_load_stage2_facts_reaches_linked_documents_and_only_reads():
    conn = FakeConn()
    pool = (ia.PoolEntry(2, 1.0, 21), ia.PoolEntry(3, 0.9, 31))
    facts = ia.load_stage2_facts(conn, pool, anchors=(1,))
    assert set(facts.documents) == {1, 2, 3, 9}                     # 9 is one link from anchor 1
    assert all(sql.lstrip().lower().startswith("select") for sql, _ in conn.queries)
    assert {l.id for l in facts.links} == {7, 8}


# --- M-O: response conversion and the default path ---------------------------------------------

def test_m4_or_outside_pool_revisions_get_evidence_without_rank_scores():
    p = mk_plan(relation=RELATION, revision_state="latest")
    rows = (row(3, 2.0, rev_id=31, trigram=0.42), row(2, 1.0, rev_id=21, trigram=0.1))
    pool = tuple(ia.PoolEntry(r.document_id, r.score, r.revision_id) for r in rows)
    outcome = ia.execute_ir1(p, pool, synthetic_facts(), (1,), Switches())
    assert [r.document_id for r in outcome.results] == [9, 3, 2]
    matches, need = ia.matches_for(outcome, rows)
    by_doc = {m.document_id: m for m in matches}
    assert by_doc[3].revision_id == 32 and by_doc[3].scores == {}                     # M4 chose C01, not 31
    assert by_doc[9].revision_id == 92 and by_doc[9].scores == {}                     # outside the pool
    assert by_doc[2].scores == ia._rounded(rows[1])                                   # unchanged revision
    assert sorted(need) == [32, 92]
    assert [m.document_id for m in matches] == [9, 3, 2]                              # rank unchanged


def test_related_document_evidence_names_anchor_and_link_type():
    p = mk_plan(relation=RELATION)
    pool = (ia.PoolEntry(2, 1.0, 21),)
    facts = synthetic_facts()
    outcome = ia.execute_ir1(p, pool, facts, (1,), Switches())
    (item,) = ia.related_evidence(outcome.results[0], facts)
    assert (item.kind, item.source, item.link_type, item.text) == \
        ("related_document", "registered", "responds_to", "Linked to DOC-001 (responds_to)")


def response_with(engine):
    info = DocumentInfo(id=1, doc_code="DOC-001", title="t", doc_type=CodeLabel(code="DR", label="Drawing"),
                        discipline=CodeLabel(code="D", label="Drainage"), wbs=CodeLabel(code="320", label="w"),
                        originator=CodeLabel(code="AAA", label="a"))
    rev = RevisionInfo(id=11, rev_code="P01", revision_date=date(2025, 1, 1), stage=CodeLabel(code="DD", label="d"),
                       current_status=None, permitted_use=None, sender=None, is_latest=True, latest_rev_code="P01",
                       latest_by_use={}, revision_count=1)
    item = ResultItem(rank=1, document=info, revision=rev, location=Location(original_location="x", filename="f",
                      open_url="/u", other_locations=[]), evidence=[], debug={"score": 1.0})
    return SearchResponse(query="q", filters={}, engine=engine, results=[item])


def test_interpretation_is_separate_and_gate_a_drops_only_the_engine_label():
    ir1, conventional = response_with(ia.ENGINE_LABEL), response_with(baseline_fts.NAME)
    assert ia.gate_a_view(ir1) == ia.gate_a_view(conventional)                        # N
    view = ia.gate_a_view(ir1)
    assert set(view) == {"query", "filters", "results"} and view["results"][0]["debug"] == {"score": 1.0}
    assert "interpretation" not in SearchResponse.model_fields
    p = mk_plan()
    outcome = ia.execute_ir1(p, (ia.PoolEntry(1, 1.0, 11),), synthetic_facts(), (), Switches())
    record = ia.interpretation_record(p, outcome)
    assert record["engine"] == ia.ENGINE_LABEL and record["revisions"][0]["basis"] == "m4"


def test_default_request_reproduces_the_conventional_order_and_revisions():
    default = plan(parse_request({"id": "D", "raw_text": "flow control", "text": "flow control", "clues": [],
                                  "revision_state": "best_match", "document_state": "any", "approx": [],
                                  "verify": [], "withdrawn": []}))
    assert default.is_default
    # conventional rows in RANK_SQL order: score desc, matched revision date desc, document id
    # (2 and 3 tie on score; 2's matched revision is newer, so RANK_SQL puts it first)
    rows = [row(2, 2.0, rev_id=21), row(3, 2.0, rev_id=31), row(1, 1.5, rev_id=11)]
    ranker = FakeRanker(rows)
    pool, kept = ia.conventional_pool(None, default, Switches(), ranker=ranker)
    outcome = ia.execute_ir1(default, pool, synthetic_facts(), ia.anchor_ranking(None, default, Switches(), ranker),
                             Switches())
    assert [(r.document_id, r.revision.revision.id) for r in outcome.results] == \
        [(r.document_id, r.revision_id) for r in rows]                                # O
    assert ranker.calls == [("flow control", Filters(), 50)]


# --- conventional ranking is called, not rewritten -------------------------------------------

class PipelineConn:
    def __init__(self, rows):
        self.rows, self.executed = rows, []

    @contextlib.contextmanager
    def pipeline(self):
        yield

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return _Cursor(self.rows)


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return list(self.rows)


def test_rank_runs_the_existing_ranking_query_unchanged():
    conn = PipelineConn([(11, 1, 1.23456789, 0.5, 0.7, 0.03, "'pond'")])
    rows = ia.rank(conn, "pond", Filters(doc_type="DR"), 50)
    sql, params = baseline_fts.ranking_query("pond", Filters(doc_type="DR"), 50)
    assert conn.executed[0] == (baseline_fts.SET_TRIGRAM_THRESHOLD_SQL, (str(baseline_fts.TRIGRAM_CANDIDATE_MIN),))
    assert conn.executed[1] == (sql, params)
    assert rows == (RankRow(11, 1, 1.23456789, 0.5, 0.7, 0.03, "'pond'"),)


def test_load_request_builds_the_frozen_plan():
    request, p = ia.load_request("G001")
    assert request.id == p.request_id == "G001"
    with pytest.raises(KeyError):
        ia.load_request("NOPE")


def test_adapter_reads_no_settings_and_opens_no_connection():
    code = ("import sys, eval.experiments.ir1_integration; "
            "bad = sorted(m for m in sys.modules if m in ('app.config', 'app.db', 'app.search', 'dotenv', "
            "'eval.run_eval', 'eval.check_equivalence')); print(bad)")
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
