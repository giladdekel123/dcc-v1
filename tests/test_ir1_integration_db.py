"""IR-1 integration adapter against real SQL, on a synthetic register.

Each test empties the project tables inside a rolled-back transaction (`empty_conn`), loads a small
synthetic register, builds the search index and runs the adapter. Nothing persists; no corpus
document and no frozen query is used.
"""

from datetime import date

import pytest

from app.ingest.build_index import build_index
from app.retrieval import baseline_fts
from app.retrieval.base import Filters
from app.search import search
from eval.experiments import ir1_integration as ia
from eval.experiments.ir1_engine import Switches
from eval.experiments.ir1_request import parse_request, plan

pytestmark = pytest.mark.db


def mk_plan(raw, text=None, clues=(), relation=None, revision_state="best_match", document_state="any"):
    item = {"id": "SYN", "raw_text": raw, "text": text or raw, "clues": list(clues),
            "revision_state": revision_state, "document_state": document_state,
            "approx": [], "verify": [], "withdrawn": []}
    if relation:
        item["relation"] = relation
    return plan(parse_request(item))


def _document(conn, code, title, wbs, discipline, doc_type, originator):
    return conn.execute("""insert into dcc.document (doc_code, title, wbs_code, discipline_code, doc_type_code,
                           originator_code) values (%s, %s, %s, %s, %s, %s) returning id""",
                        (code, title, wbs, discipline, doc_type, originator)).fetchone()[0]


def _revision(conn, doc_id, code, rev, day, stage, sender=None, status=None, description=None):
    rev_id = conn.execute("""insert into dcc.revision (document_id, rev_code, revision_date, stage_code, sender_code,
                             description) values (%s, %s, %s, %s, %s, %s) returning id""",
                          (doc_id, rev, date.fromisoformat(day), stage, sender, description)).fetchone()[0]
    conn.execute("""insert into dcc.revision_file (revision_id, copy_role, filename, original_location, storage_path,
                    file_format, size_bytes, sha256) values (%s, 'primary', %s, 'Synthetic/Register', %s, 'pdf', 1, %s)""",
                 (rev_id, f"{code}_{rev}.pdf", f"synthetic/{code}/{rev}.pdf", "0" * 64))
    if status:
        conn.execute("insert into dcc.revision_status (revision_id, status_code, effective_date) values (%s, %s, %s)",
                     (rev_id, status, date.fromisoformat(day)))
    return rev_id


@pytest.fixture
def reg(empty_conn):
    """Synthetic register: WBS 300 > 320, 330; documents 1-5; one registered and one extracted link."""
    conn = empty_conn
    conn.execute("insert into dcc.wbs_element (code, name) values ('300', 'Synthetic drainage')")
    conn.execute("insert into dcc.wbs_element (code, name, parent_code) values ('320', 'Synthetic pond', '300'), "
                 "('330', 'Synthetic culvert', '300')")
    conn.execute("insert into dcc.organisation (code, name, role) values ('AAA', 'Synthetic Designer', 'designer'), "
                 "('BBB', 'Synthetic Contractor', 'contractor'), ('NVW', 'Synthetic Water', 'utility')")
    ids = {}
    ids["d1"] = _document(conn, "SYN-DR-001", "Pond flow control chamber drawing", "320", "D", "DR", "AAA")
    ids["r1a"] = _revision(conn, ids["d1"], "SYN-DR-001", "P01", "2024-01-10", "DD", status="RV")
    ids["r1b"] = _revision(conn, ids["d1"], "SYN-DR-001", "C01", "2025-01-10", "CN", status="FC")
    ids["d2"] = _document(conn, "SYN-LT-002", "Pond outfall consent letter", "320", "D", "LT", "BBB")
    ids["r2"] = _revision(conn, ids["d2"], "SYN-LT-002", "P01", "2025-02-01", "DD", sender="NVW", status="IS")
    ids["d3"] = _document(conn, "SYN-RP-003", "Culvert water main survey report", "330", "U", "RP", "NVW")
    ids["r3"] = _revision(conn, ids["d3"], "SYN-RP-003", "P01", "2024-05-01", "DD", status="IS")
    ids["d4"] = _document(conn, "SYN-LT-004", "Reply on outfall consent", "320", "D", "LT", "NVW")
    ids["r4a"] = _revision(conn, ids["d4"], "SYN-LT-004", "P01", "2025-03-01", "DD", status="IS")
    ids["r4b"] = _revision(conn, ids["d4"], "SYN-LT-004", "P02", "2025-04-01", "DD", status="IS")
    ids["d5"] = _document(conn, "SYN-SB-005", "Culvert headwall submittal", "330", "C", "SB", "BBB")
    ids["r5"] = _revision(conn, ids["d5"], "SYN-SB-005", "P01", "2025-01-05", "DD", status="IS")
    ids["link"] = conn.execute("""insert into dcc.information_link (from_document_id, from_revision_id, to_document_id,
                                  link_type, provenance) values (%s, %s, %s, 'responds_to', 'registered')
                                  returning id""", (ids["d4"], ids["r4a"], ids["d2"])).fetchone()[0]
    ids["xlink"] = conn.execute("""insert into dcc.information_link (from_document_id, to_document_id, link_type,
                                   provenance) values (%s, %s, 'related_to', 'extracted') returning id""",
                                (ids["d5"], ids["d3"])).fetchone()[0]
    build_index(conn)
    return conn, ids


# --- 1, 2: ranking_query, raw scores, matched revision ----------------------------------------

def test_rank_matches_the_retriever_with_unrounded_scores(reg):
    conn, ids = reg
    rows = ia.rank(conn, "pond flow control", Filters(), ia.POOL_SIZE)
    matches = baseline_fts.BaselineFtsRetriever().search(conn, "pond flow control", Filters(), 10)
    assert rows and [(r.document_id, r.revision_id) for r in rows[:10]] == [(m.document_id, m.revision_id)
                                                                            for m in matches]
    assert [round(r.score, 4) for r in rows[:10]] == [m.scores["score"] for m in matches]
    assert all(isinstance(r.score, float) for r in rows)
    assert rows[0].document_id == ids["d1"] and rows[0].revision_id in (ids["r1a"], ids["r1b"])


def test_pool_keeps_conventional_rows_and_filters_restrict_sql(reg):
    conn, ids = reg
    p = mk_plan("pond culvert drawing letter report", clues=[{"field": "doc_type", "code": "LT",
                                                             "strength": "confirmed", "source": "letter"}])
    pool, rows = ia.conventional_pool(conn, p, Switches())
    assert [(e.document_id, e.baseline_score, e.matched_revision_id) for e in pool] == \
        [(r.document_id, r.score, r.revision_id) for r in rows]
    assert {e.document_id for e in pool} <= {ids["d2"], ids["d4"]} and pool               # LT documents only


# --- 3, 4: Stage-2 facts from real rows -------------------------------------------------------

def test_stage2_facts_load_documents_revisions_links_and_wbs(reg):
    conn, ids = reg
    pool = (ia.PoolEntry(ids["d1"], 1.0, ids["r1b"]),)
    facts = ia.load_stage2_facts(conn, pool, anchors=(ids["d2"],))
    assert set(facts.documents) == {ids["d1"], ids["d2"], ids["d4"]}            # d4 is one link from anchor d2
    d1 = facts.document(ids["d1"])
    assert (d1.doc_code, d1.doc_type, d1.discipline, d1.wbs, d1.originator) == ("SYN-DR-001", "DR", "D", "320", "AAA")
    uses = {r.rev_code: (r.stage, r.permitted_use, r.revision_date) for r in d1.revisions}
    assert uses == {"P01": ("DD", "review", date(2024, 1, 10)), "C01": ("CN", "construction", date(2025, 1, 10))}
    assert facts.document(ids["d2"]).revisions[0].sender == "NVW"
    (link,) = facts.links
    assert (link.id, link.from_document_id, link.from_revision_id, link.to_document_id, link.to_revision_id,
            link.link_type, link.provenance) == (ids["link"], ids["d4"], ids["r4a"], ids["d2"], None,
                                                 "responds_to", "registered")
    assert dict(facts.wbs_parent) == {"300": None, "320": "300", "330": "300"}


def test_extracted_links_are_loaded_as_facts_with_their_provenance(reg):
    conn, ids = reg
    facts = ia.load_stage2_facts(conn, (ia.PoolEntry(ids["d3"], 1.0, ids["r3"]),), anchors=())
    assert [(l.from_document_id, l.provenance) for l in facts.links] == [(ids["d5"], "extracted")]
    assert ids["d5"] in facts.documents                                          # engine filters provenance


# --- 5-7, 9: default request through to_response equals the conventional response -----------

@pytest.mark.parametrize("query", ["pond flow control", "culvert water main", "outfall consent letter"])
def test_default_request_response_equals_conventional_search(reg, query):
    conn, _ = reg
    default = mk_plan(query)
    assert default.is_default
    got = ia.search_ir1(conn, default, Switches(), debug=True)
    expected = search(conn, query, Filters(), debug=True)
    assert got.response.engine == ia.ENGINE_LABEL and expected.engine == baseline_fts.NAME
    assert ia.gate_a_view(got.response) == ia.gate_a_view(expected)
    assert got.interpretation["engine"] == ia.ENGINE_LABEL


def test_conventional_only_filters_reach_ranking_and_evidence(reg):
    conn, _ = reg
    default, extra = mk_plan("pond culvert"), Filters(wbs="300")
    got = ia.search_ir1(conn, default, Switches(), extra_filters=extra, debug=True)
    assert ia.gate_a_view(got.response) == ia.gate_a_view(search(conn, "pond culvert", extra, debug=True))
    assert got.interpretation["hard_filters"] == {}


# --- 8: substituted revisions and the repeated trigram expression ----------------------------

def test_trigram_sql_matches_the_ranking_trigram(reg):
    conn, _ = reg
    for query in ("pond flow control", "culvrt watr", "outfall"):
        rows = ia.rank(conn, query, Filters(), ia.POOL_SIZE)
        got = dict(conn.execute(ia.TRIGRAM_SQL, {"q": query, "ids": [r.revision_id for r in rows]}).fetchall())
        assert got == {r.revision_id: r.trigram for r in rows}


def test_m4_substituted_revision_gets_evidence_without_changing_rank(reg):
    conn, ids = reg
    query = "pond flow control drawing"
    base = ia.search_ir1(conn, mk_plan(query), Switches(), debug=True)
    first_base = base.response.results[0]
    assert first_base.document.id == ids["d1"] and first_base.debug
    # request the revision the baseline did NOT match, so a substitution always happens
    state, wanted = (("earliest", ids["r1a"]) if first_base.revision.id == ids["r1b"] else ("latest", ids["r1b"]))
    other = ia.search_ir1(conn, mk_plan(query, revision_state=state), Switches(), debug=True)
    assert [r.document.id for r in base.response.results] == [r.document.id for r in other.response.results]
    first = other.response.results[0]
    assert first.revision.id == wanted != first_base.revision.id
    assert first.debug == {}                                            # no ranking scores for that revision
    assert any(e.kind == "metadata_match" and e.field == "title" for e in first.evidence)
    assert first.revision.latest_rev_code == "C01"                      # load_facts for the chosen revision
    assert other.interpretation["revisions"][0]["basis"] == "m4"
    assert other.interpretation["revisions"][0]["revision_id"] == wanted


def test_outside_pool_m3_document_is_represented_with_related_evidence(reg):
    conn, ids = reg
    relation = {"link_type": "responds_to", "target_side": "from", "anchor_text": "pond outfall consent letter",
                "source": "letter"}
    # "survey" matches only d3's title (vocabulary aliases make "culvert"/"water" match every D or NVW doc)
    p = mk_plan("survey letter", text="survey", relation=relation)
    pool, _ = ia.conventional_pool(conn, p, Switches())
    assert ids["d4"] not in {e.document_id for e in pool}
    assert ia.anchor_ranking(conn, p, Switches())[0] == ids["d2"]
    got = ia.search_ir1(conn, p, Switches(), debug=True)
    first = got.response.results[0]
    assert first.document.id == ids["d4"] and first.revision.id == ids["r4a"]          # S3.3: the link's revision
    related = [e for e in first.evidence if e.kind == "related_document"]
    assert [(e.link_type, e.text) for e in related] == [("responds_to", "Linked to SYN-LT-002 (responds_to)")]
    assert first.debug == {} and got.interpretation["revisions"][0]["in_pool"] is False
    off = ia.search_ir1(conn, p, Switches(m4=False), debug=True).response.results[0]
    assert (off.document.id, off.revision.id) == (ids["d4"], ids["r4b"])                 # A1: latest, not the link's
