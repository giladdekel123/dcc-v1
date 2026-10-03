"""IR-1b unit tests on synthetic plans, rows and facts. No database, no retrieval, no frozen-58 result."""

import pytest

from app.retrieval.base import Filters
from eval.experiments import ir1_engine, ir1_integration as ia, ir1_request
from eval.experiments import ir1b
from eval.experiments.ir1_engine import Switches
from eval.experiments.ir1_request import PlanError, parse_request, plan
from tests.test_ir1_integration import FakeRanker, row, synthetic_facts

RAW = "WBS 320 Pond 2 East. I need the flow control drawing letter from the contractor at stage pond."


def mk_plan(raw=RAW, text="Pond 2 East flow control", clues=(), relation=None, revision_state="best_match",
            document_state="any"):
    item = {"id": "B1", "raw_text": raw, "text": text, "clues": list(clues), "revision_state": revision_state,
            "document_state": document_state, "approx": [], "verify": [], "withdrawn": []}
    if relation:
        item["relation"] = relation
    return plan(parse_request(item))


def clue(field, code, strength, source):
    return {"field": field, "code": code, "strength": strength, "source": source}


CLUES = [clue("wbs", "320", "confirmed", "WBS 320"), clue("discipline", "D", "context", "Pond"),
         clue("doc_type", "LT", "likely", "letter")]
RELATION = {"link_type": "responds_to", "target_side": "from", "anchor_text": "the reply letter", "source": "letter"}


# --- the preregistered matrix and constants ----------------------------------------------------

def test_conditions_match_the_preregistration():
    expected = {  # base, boost, delete, relationships, revisions (preregistration section 4)
        "1": ("text", 1, 1, 1, 1), "2": ("raw", 0, 0, 0, 0), "3": ("text", 0, 0, 0, 0), "4": ("raw", 1, 0, 0, 0),
        "5": ("raw", 0, 1, 0, 0), "6": ("raw", 1, 1, 0, 0), "7": ("raw", 0, 0, 1, 0), "8": ("raw", 0, 0, 0, 1),
        "9": ("raw", 1, 0, 1, 1), "10": ("raw", 1, 1, 1, 1), "11": ("raw", 0, 0, 1, 1),
        "12": ("raw", 1, 0, 0, 1), "13": ("raw", 1, 0, 1, 0), "9r": ("raw", 1, 0, 1, 1)}
    got = {k: (c.base, int(c.boost), int(c.delete), int(c.relationships), int(c.revisions))
           for k, c in ir1b.CONDITIONS.items()}
    assert got == expected and ir1b.BASELINE == "0" and set(ir1b.NAMES) == set(expected) | {"0"}
    assert len(expected) == 14                                    # 13 IR-1b configs + 9r; condition 0 separate


def test_frozen_constants_are_unchanged():
    assert (ir1_request.POOL_SIZE, ir1_engine.OUTPUT_SIZE, ir1_request.ANCHOR_COUNT,
            ir1_request.LIKELY_BOOST, ir1_request.CONTEXT_BOOST) == (50, 10, 3, 0.5, 0.1)


def test_switch_mapping_keeps_boost_and_deletion_independent():
    for c in ir1b.CONDITIONS.values():
        assert c.switches() == Switches(m2=c.boost, m3=c.relationships, m4=c.revisions)
    with pytest.raises(ValueError):
        ir1b.IR1bConfig("both", False, False, False, False)


# --- lexical query ------------------------------------------------------------------------------

def test_wording_choice_without_deletion_is_exact():
    p = mk_plan(clues=CLUES)
    assert ir1b.lexical_query(p, ir1b.CONDITIONS["2"]).text == RAW
    assert ir1b.lexical_query(p, ir1b.CONDITIONS["3"]).text == "Pond 2 East flow control"
    for k in ("4", "7", "8", "9", "11", "12", "13"):                # boosts/relationships/revisions: wording kept
        assert ir1b.lexical_query(p, ir1b.CONDITIONS[k]).text == RAW


def test_deletion_on_original_wording_removes_only_context_sources():
    p = mk_plan(clues=CLUES)
    q = ir1b.lexical_query(p, ir1b.CONDITIONS["5"])
    assert q.text == "2 East. I need the flow control drawing letter from the contractor at stage ."
    assert set(q.removed_phrases) == {"WBS 320", "Pond"} and not q.fallback        # C1: WBS is context
    assert "letter" in q.text                                                      # likely source kept
    assert ir1b.lexical_query(p, ir1b.CONDITIONS["6"]) == q == ir1b.lexical_query(p, ir1b.CONDITIONS["10"])


def test_condition_1_wording_is_the_frozen_ir1_pool_text():
    for clues in (CLUES, [clue("discipline", "D", "context", "Pond")], []):
        p = mk_plan(clues=clues)
        assert ir1b.lexical_query(p, ir1b.CONDITIONS["1"]).text == p.pool_text


def test_deletion_fallback_when_wording_would_be_empty():
    p = mk_plan(raw="pond", text="pond", clues=[clue("discipline", "D", "context", "pond")])
    q = ir1b.lexical_query(p, ir1b.CONDITIONS["5"])
    assert (q.text, q.fallback, q.removed_phrases) == ("pond", True, ("pond",))


def test_overlapping_sources_on_original_wording_raise_the_frozen_error():
    p = mk_plan(raw="the drainage layer report", text="report",
                clues=[clue("discipline", "D", "context", "drainage"), clue("discipline", "S", "context",
                                                                             "drainage layer")])
    assert ir1b.lexical_query(p, ir1b.CONDITIONS["4"]).text == "the drainage layer report"   # no deletion
    with pytest.raises(PlanError, match="overlap"):
        ir1b.lexical_query(p, ir1b.CONDITIONS["5"])


# --- pipeline on a fake ranker and synthetic facts --------------------------------------------

ROWS = [row(1, 2.0, rev_id=11), row(2, 1.9, rev_id=21), row(3, 1.0, rev_id=31)]


def pipeline(p, key, anchors=(1,)):
    ranker = FakeRanker(ROWS, anchors=anchors)
    out = ir1b.run_pipeline(None, p, ir1b.CONDITIONS[key], ranker, lambda conn, pool, a: synthetic_facts())
    return out, ranker.calls


def order(out):
    return [(r.document_id, r.revision.revision.id) for r in out.outcome.results]


@pytest.mark.parametrize("key", list(ir1b.CONDITIONS))
def test_every_condition_ranks_its_wording_with_pool_50_and_maps_switches(key):
    p = mk_plan(clues=CLUES, relation=RELATION, revision_state="latest")
    out, calls = pipeline(p, key)
    config = ir1b.CONDITIONS[key]
    assert calls[0] == (ir1b.lexical_query(p, config).text, Filters(), 50)
    assert (len(calls) == 2) is config.relationships                       # anchors only with relationships
    if config.relationships:
        assert calls[1] == ("the reply letter", Filters(), 3)
    assert out.outcome.switches == config.switches()


def test_condition_2_reproduces_the_conventional_ranking():
    out, _ = pipeline(mk_plan(clues=CLUES, relation=RELATION, revision_state="latest"), "2")
    assert order(out) == [(r.document_id, r.revision_id) for r in ROWS]


def test_condition_1_equals_the_frozen_ir1_pipeline():
    p = mk_plan(clues=CLUES, relation=RELATION, revision_state="latest")
    out, calls = pipeline(p, "1")
    frozen_ranker = FakeRanker(ROWS, anchors=(1,))
    pool, _ = ia.conventional_pool(None, p, Switches(), ranker=frozen_ranker)
    anchors = ia.anchor_ranking(None, p, Switches(), frozen_ranker)
    frozen = ia.execute_ir1(p, pool, synthetic_facts(), anchors, Switches())
    assert out.outcome == frozen and calls == frozen_ranker.calls


def test_boost_only_and_deletion_only_change_different_things():
    p = mk_plan(clues=[clue("discipline", "D", "context", "Pond"), clue("doc_type", "LT", "likely", "letter")])
    neither, c2 = pipeline(p, "2")
    boost, c4 = pipeline(p, "4")
    delete, c5 = pipeline(p, "5")
    both, c6 = pipeline(p, "6")
    assert c2[0][0] == c4[0][0] == RAW and c5[0][0] == c6[0][0] != RAW               # deletion: wording only
    assert order(neither) == order(delete) == [(1, 11), (2, 21), (3, 31)]          # no boosts: conventional
    assert order(boost)[0] == order(both)[0] == (2, 21)                            # LT boosted +0.5 to first


def test_relationships_only_and_revisions_only():
    p = mk_plan(clues=CLUES, relation=RELATION, revision_state="latest")
    rel, _ = pipeline(p, "7")
    assert order(rel)[0] == (9, 92) and rel.outcome.linked         # outside-pool doc 9 first; A1: latest (M4 off)
    rev, _ = pipeline(p, "8")
    assert [d for d, _ in order(rev)] == [1, 2, 3] and dict(order(rev))[3] == 32    # latest revision of 3
    assert not rev.outcome.linked


@pytest.mark.parametrize("key, has_boost, has_rel, has_rev", [
    ("9", True, True, True), ("11", False, True, True), ("12", True, False, True), ("13", True, True, False),
    ("10", True, True, True)])
def test_additive_and_leave_one_out_configurations(key, has_boost, has_rel, has_rev):
    p = mk_plan(clues=CLUES, relation=RELATION, revision_state="latest")
    out, _ = pipeline(p, key)
    assert bool(out.outcome.linked) is has_rel
    assert any(s.soft_boost for s in out.outcome.m2_scores) is has_boost
    third = dict(order(out)).get(3)
    assert third == (32 if has_rev else 31)
    assert all(r.revision.basis == ("m4" if has_rev else "conventional_baseline")
               for r in out.outcome.results if r.in_pool)


def test_audit_record_names_the_wording_actually_sent():
    p = mk_plan(clues=CLUES, relation=RELATION)
    out, _ = pipeline(p, "5")
    record = ir1b.interpretation_record(p, ir1b.CONDITIONS["5"], "5", out)
    assert record["lexical_query"] == out.query.text != RAW and record["original_text"] == RAW
    assert record["interpreted_text"] == "Pond 2 East flow control"
    assert record["config"] == {"base": "raw", "boost": False, "delete": True, "relationships": False,
                                "revisions": False}
    assert record["condition_name"] == "Original minus clue phrases" and "lexical_query" not in record["ir1"]
    assert set(record["deleted_phrases"]) == {"WBS 320", "Pond"}


def test_deletion_check_reports_categories_without_retrieval():
    plans = [mk_plan(clues=CLUES), mk_plan(clues=[clue("doc_type", "LT", "likely", "letter")]),
             mk_plan(raw="pond", text="pond", clues=[clue("discipline", "D", "context", "pond")]),
             mk_plan(raw="the drainage layer report", text="report",
                     clues=[clue("discipline", "D", "context", "drainage"),
                            clue("discipline", "S", "context", "drainage layer")])]
    result = ir1b.deletion_check(plans)
    assert result["plans"] == 4 and result["with_deletion"] == ["B1"] and result["no_context_sources"] == ["B1"]
    assert result["fallback"] == ["B1"] and list(result["errors"]) == ["B1"]
