"""IR-1 stage 2: pure mechanisms on handmade facts. No database, no retrieval.

The frozen request file is loaded only to check that stage-1 plans fit this module's inputs.
"""

import copy
import subprocess
import sys
from datetime import date
from pathlib import Path as FsPath

import pytest

from eval.experiments import ir1_engine as eng
from eval.experiments.ir1_engine import (Document, Facts, Link, LinkedDocument, Path, PoolEntry, Revision, Switches,
                                         UndefinedRuleError, best_match_revision, clue_matches, current_order,
                                         eligible_revisions, linked_documents, m2_order, m2_score, m3_order,
                                         recency_order, representing_revision, rev_code_rank, run, select_anchors)
from eval.experiments.ir1_request import (Relation, SoftClue, load_frozen_requests, parse_request, plan,
                                          plan_all)

REPO = FsPath(__file__).resolve().parent.parent
RAW = "WBS 320 the drawing letter report from the contractor at stage pond flow control about clay"
WBS_PARENT = {"300": None, "320": "300", "321": "320", "322": "321", "330": "300"}


def rev(rid, doc_id, code, day, stage="DD", sender=None, use=None, past=()):
    return Revision(rid, doc_id, code, date.fromisoformat(day), stage, sender, use, past)


def doc(did, revisions=None, doc_type="DR", discipline="D", wbs="320", originator="AAA", code=None):
    revisions = revisions or (rev(did * 10 + 1, did, "P01", "2025-01-01"),)
    return Document(did, code or f"DOC-{did:03d}", doc_type, discipline, wbs, originator, tuple(revisions))


def facts(*docs, links=()):
    return Facts({d.id: d for d in docs}, WBS_PARENT, tuple(links))


def soft(field, code, strength="likely", source="drawing"):
    return SoftClue(field, code, strength, strength, eng.LIKELY_BOOST if strength == "likely" else eng.CONTEXT_BOOST,
                    source)


def clue(field, code, strength, source):
    return {"field": field, "code": code, "strength": strength, "source": source}


def mk_plan(clues=(), relation=None, revision_state="best_match", document_state="any", text=RAW):
    item = {"id": "T", "raw_text": RAW, "text": text, "clues": list(clues), "revision_state": revision_state,
            "document_state": document_state, "approx": [], "verify": [], "withdrawn": []}
    if relation:
        item["relation"] = relation
    return plan(parse_request(item))


def pool_of(*doc_ids, scores=None):
    scores = scores or {d: 100.0 - i for i, d in enumerate(doc_ids)}       # positive, descending
    return tuple(PoolEntry(d, scores[d], d * 10 + 1) for d in doc_ids)


def rel(link_type="responds_to", target_side="from") -> Relation:
    return Relation(link_type, target_side, "anchor words", "drawing")


def ids(outcome):
    return [r.document_id for r in outcome.results]


# =============================================================================================
# M2
# =============================================================================================

def test_likely_context_and_nonmatch_boosts():
    d = doc(1)
    assert m2_score([soft("doc_type", "DR", "likely")], d, WBS_PARENT, 1.0).soft_boost == 0.5
    assert m2_score([soft("discipline", "D", "context")], d, WBS_PARENT, 1.0).soft_boost == 0.1
    s = m2_score([soft("doc_type", "LT", "likely")], d, WBS_PARENT, 1.0)
    assert (s.soft_boost, s.boosted_score, s.matches) == (0.0, 1.0, ())


def test_boosts_accumulate_per_clue_without_cap():
    d = doc(1, revisions=[rev(11, 1, "P01", "2025-01-01", stage="PD", sender="BBB")])
    same = [soft("doc_type", "DR"), soft("discipline", "D"), soft("stage", "PD")]
    assert m2_score(same, d, WBS_PARENT, 0.0).soft_boost == 0.5 * 3
    mixed = same + [soft("wbs", "320", "context"), soft("originator", "AAA", "context"),
                    soft("sender", "BBB", "context"), soft("wbs", "300", "context")]
    s = m2_score(mixed, d, WBS_PARENT, 2.0)
    assert s.soft_boost == 0.5 * 3 + 0.1 * 4 and s.boosted_score == 2.0 + (0.5 * 3 + 0.1 * 4)
    assert len(s.matches) == 7


def test_contribution_audit_lists_each_matching_clue():
    c1, c2, c3 = soft("doc_type", "DR"), soft("wbs", "320", "context", "WBS 320"), soft("doc_type", "LT")
    s = m2_score([c1, c2, c3], doc(1), WBS_PARENT, 1.25)
    assert [(m.field, m.code, m.strength, m.boost, m.source) for m in s.matches] == \
        [("doc_type", "DR", "likely", 0.5, "drawing"), ("wbs", "320", "context", 0.1, "WBS 320")]
    assert (s.baseline_score, s.soft_boost, s.boosted_score) == (1.25, 0.5 + 0.1, 1.25 + (0.5 + 0.1))


def test_stage_and_sender_match_any_revision():
    d = doc(1, revisions=[rev(11, 1, "P01", "2024-01-01", stage="PD"), rev(12, 1, "C01", "2025-01-01", stage="CN",
                                                                         sender="SND")])
    assert clue_matches(soft("stage", "PD"), d, WBS_PARENT) and clue_matches(soft("stage", "CN"), d, WBS_PARENT)
    assert not clue_matches(soft("stage", "HO"), d, WBS_PARENT)
    assert clue_matches(soft("sender", "SND"), d, WBS_PARENT)


def test_organisation_clues_use_the_existing_organisation_filter_meaning():
    d = doc(1, originator="ORG", revisions=[rev(11, 1, "P01", "2025-01-01", sender="SND")])
    for field in ("originator", "sender"):
        assert clue_matches(soft(field, "ORG"), d, WBS_PARENT)      # via the originator
        assert clue_matches(soft(field, "SND"), d, WBS_PARENT)      # via a revision's sender
        assert not clue_matches(soft(field, "XXX"), d, WBS_PARENT)


@pytest.mark.parametrize("wbs, matches", [
    ("320", True),        # the element
    ("321", True),        # a direct child
    ("322", False),       # a grandchild
    ("330", False),       # unrelated
    ("3201", False),      # looks numerically related, not in the hierarchy
    ("329", False),       # same numeric range, no parent link
])
def test_wbs_matches_element_and_direct_children_only(wbs, matches):
    assert clue_matches(soft("wbs", "320", "context"), doc(1, wbs=wbs), WBS_PARENT) is matches


def test_c1_wbs_from_the_plan_is_context():
    p = mk_plan(clues=[clue("wbs", "320", "confirmed", "WBS 320")])
    (c,) = p.soft_clues
    assert p.filters() == {} and m2_score(p.soft_clues, doc(1), WBS_PARENT, 0.0).soft_boost == 0.1


def test_soft_clues_never_exclude():
    world = facts(doc(1, doc_type="LT"), doc(2), doc(3, doc_type="RP"))
    pool = pool_of(1, 2, 3, scores={1: 1.0, 2: 0.9, 3: 0.8})
    out = run(mk_plan(clues=[clue("doc_type", "DR", "likely", "drawing")]), pool, world)
    assert ids(out) == [2, 1, 3]                                   # 2 boosted to 1.4; 1 and 3 stay


def test_m2_order_uses_unrounded_scores():
    world = facts(doc(1), doc(2))
    pool = (PoolEntry(1, 1.00001, 11), PoolEntry(2, 1.00004, 21))                # equal when rounded to 4 dp
    scores = {e.document_id: m2_score((), world.document(e.document_id), WBS_PARENT, e.baseline_score) for e in pool}
    assert m2_order(pool, scores, world) == (2, 1)


def test_m2_ties_break_on_matched_revision_date_then_document_id():
    world = facts(doc(5, [rev(51, 5, "P01", "2024-01-01")]), doc(3, [rev(31, 3, "P01", "2025-01-01")]),
                  doc(4, [rev(41, 4, "P01", "2024-01-01")]))
    pool = (PoolEntry(5, 1.0, 51), PoolEntry(3, 1.0, 31), PoolEntry(4, 1.0, 41))
    scores = {e.document_id: m2_score((), world.document(e.document_id), WBS_PARENT, 1.0) for e in pool}
    assert m2_order(pool, scores, world) == (3, 4, 5)


def test_no_boost_preserves_a_baseline_ordered_pool():
    world = facts(doc(1), doc(2), doc(3))
    pool = pool_of(2, 3, 1)
    scores = {e.document_id: m2_score((), world.document(e.document_id), WBS_PARENT, e.baseline_score) for e in pool}
    assert m2_order(pool, scores, world) == (2, 3, 1)


# =============================================================================================
# M3
# =============================================================================================

def test_at_most_three_anchors_in_ranking_order():
    assert select_anchors([7, 3, 9, 1, 5]) == (7, 3, 9) and select_anchors([4]) == (4,)
    assert select_anchors([7, 7, 3, 9, 1]) == (7, 3, 9)


@pytest.mark.parametrize("relation, expected", [
    (rel("responds_to", "from"), [10]),          # wanted responds_to anchor
    (rel("responds_to", "to"), [11]),            # anchor responds_to wanted
    (rel("supersedes", "from"), [12]),           # requested type only
    (rel("any", "from"), [10, 12]),              # every type, side kept
    (rel("any", "to"), [11]),
])
def test_link_type_and_target_side(relation, expected):
    links = [Link(10, 1, "responds_to"), Link(1, 11, "responds_to"), Link(12, 1, "supersedes")]
    assert [d.document_id for d in linked_documents((1,), links, relation)] == expected


def test_one_hop_registered_links_only():
    links = [Link(10, 1, "responds_to"), Link(20, 10, "responds_to"),         # 20 is two hops away
             Link(30, 1, "responds_to", provenance="extracted")]
    assert [d.document_id for d in linked_documents((1,), links, rel())] == [10]
    assert linked_documents((), links, rel()) == () and linked_documents((1,), (), rel()) == ()


def test_all_paths_are_kept_merged_and_ordered_for_evidence():
    links = [Link(10, 3, "responds_to", id=7), Link(10, 1, "related_to", id=9), Link(10, 1, "responds_to", id=8),
             Link(10, 1, "responds_to", id=8),                                  # identical path: merged
             Link(10, 1, "responds_to", from_revision_id=101, id=6)]
    (d,) = linked_documents((1, 2, 3), links, rel("any"))
    assert d.anchor_rank == 1
    assert [(p.anchor_rank, p.link_type, p.link_id, p.wanted_revision_id) for p in d.paths] == \
        [(1, "related_to", 9, None), (1, "responds_to", 6, 101), (1, "responds_to", 8, None), (3, "responds_to", 7, None)]


def test_anchor_can_be_linked_and_outside_pool_documents_are_admitted():
    links = [Link(2, 1, "responds_to"), Link(99, 1, "responds_to")]
    assert [d.document_id for d in linked_documents((1, 2), links, rel())] == [2, 99]


def ld(doc_id, anchor_rank):
    return LinkedDocument(doc_id, anchor_rank, ())


CODES = {d: f"DOC-{d:03d}" for d in range(1, 100)}


def test_m3_order_keys_and_m2_order_for_the_rest():
    m2 = [1, 2, 3, 4, 5]
    scores = {1: 3.0, 2: 2.5, 3: 2.0, 4: 1.5, 5: 1.0}
    linked = [ld(5, 1), ld(4, 2), ld(3, 1), ld(99, 1)]
    boost = {5: 0.0, 4: 0.5, 3: 0.0, 99: 0.0}
    assert m3_order(m2, linked, boost, scores, CODES) == (4, 3, 5, 99, 1, 2)


def test_m3_final_tie_break_is_code_then_id_ascending():
    assert m3_order([], [ld(7, 1), ld(8, 1)], {7: 0.1, 8: 0.1}, {}, {7: "B-2", 8: "A-9"}) == (8, 7)
    assert m3_order([], [ld(9, 1), ld(8, 1)], {9: 0.0, 8: 0.0}, {}, {9: "SAME", 8: "SAME"}) == (8, 9)


def test_m3_inputs_are_not_defaulted():
    with pytest.raises(ValueError, match="missing"):
        m3_order([1], [ld(2, 1)], {}, {1: 1.0}, CODES)


def test_hard_filters_reject_linked_documents():
    p = mk_plan(clues=[clue("doc_type", "DR", "confirmed", "drawing")],
                relation={"link_type": "responds_to", "target_side": "from", "anchor_text": "a", "source": "drawing"})
    world = facts(doc(1), doc(2), doc(10, doc_type="LT"), doc(11), links=[Link(10, 2, "responds_to"),
                                                                          Link(11, 2, "responds_to")])
    out = run(p, pool_of(1), world, anchor_ranking=[2])
    assert out.rejected_linked == (10,) and [d.document_id for d in out.linked] == [11]
    assert ids(out) == [11, 1]                                     # anchor 2 is not in the pool


# =============================================================================================
# M4
# =============================================================================================

HISTORY = (rev(100, 1, "P01", "2024-06-01", stage="PD"), rev(101, 1, "P02", "2024-09-01", stage="DD"),
           rev(102, 1, "C01", "2025-01-10", stage="CN", use="construction"),
           rev(103, 1, "C02", "2025-04-02", stage="CN", use="construction"),
           rev(104, 1, "P03", "2025-06-01", stage="DD", use="review", past=("construction",)))
HDOC = doc(1, HISTORY)


def test_rev_code_rank_and_recency_order():
    assert (rev_code_rank("P07"), rev_code_rank("C02"), rev_code_rank("A10")) == (1007, 2002, 3010)
    same_day = (rev(1, 1, "P02", "2025-01-01"), rev(2, 1, "C01", "2025-01-01"), rev(3, 1, "P01", "2024-01-01"))
    assert [r.rev_code for r in recency_order(same_day)] == ["C01", "P02", "P01"]


@pytest.mark.parametrize("state, expected", [
    ("best_match", "P02"), ("latest", "P03"), ("earliest", "P01"),
    ("latest_for_construction", "C02"), ("earliest_for_construction", "C01"),
])
def test_all_five_revision_states(state, expected):
    choice = representing_revision(state, HDOC, {}, baseline_revision_id=101)
    assert (choice.revision.rev_code, choice.satisfied) == (expected, True)


def test_only_current_permitted_use_qualifies_for_construction():
    d = doc(2, [rev(20, 2, "P01", "2024-01-01", use="review", past=("construction",)),
                rev(21, 2, "P02", "2025-01-01", use="information")])
    choice = representing_revision("latest_for_construction", d, {}, baseline_revision_id=20)
    assert (choice.revision.id, choice.satisfied) == (20, False)            # history does not count
    assert "could not be satisfied" in choice.note


def test_in_pool_fallback_is_the_baseline_revision():
    d = doc(2, [rev(20, 2, "P01", "2024-01-01"), rev(21, 2, "P02", "2025-01-01")])
    choice = representing_revision("earliest_for_construction", d, {}, baseline_revision_id=21)
    assert (choice.revision.id, choice.satisfied, choice.requested_state) == (21, False, "earliest_for_construction")


def path(wanted_rev=None, anchor=5, rank=1, link_id=None):
    return Path(anchor, rank, "responds_to", wanted_rev, None, link_id)


def test_outside_pool_best_match_from_paths():
    assert best_match_revision(HDOC, HISTORY, None, [path(102), path(102, anchor=6)]).id == 102   # agreeing
    assert best_match_revision(HDOC, HISTORY, None, [path(None), path(101)]).id == 101            # mixed
    assert best_match_revision(HDOC, HISTORY, None, [path(None)]).id == 104                       # latest
    assert best_match_revision(HDOC, HISTORY, None, []).id == 104
    with pytest.raises(UndefinedRuleError, match="different eligible revisions"):
        best_match_revision(HDOC, HISTORY, None, [path(101), path(102)])
    with pytest.raises(ValueError, match="not a revision"):
        best_match_revision(HDOC, HISTORY, None, [path(999)])


def test_outside_pool_unsatisfied_state_falls_back_to_s33_best_match():
    d = doc(3, [rev(30, 3, "P01", "2024-01-01"), rev(31, 3, "P02", "2025-01-01")])
    choice = representing_revision("latest_for_construction", d, {}, None, [path(30)])
    assert (choice.revision.id, choice.satisfied) == (30, False)


def test_revision_level_hard_filters_constrain_the_representing_revision():
    stage_cn = {"stage": "CN"}
    assert [r.id for r in eligible_revisions(HDOC, stage_cn)] == [102, 103]
    assert representing_revision("latest", HDOC, stage_cn, 102).revision.id == 103          # not P03
    assert representing_revision("earliest", HDOC, stage_cn, 102).revision.id == 102        # not P01
    # an ineligible path revision cannot represent the document; the latest eligible one does
    assert best_match_revision(HDOC, eligible_revisions(HDOC, stage_cn), None, [path(104)]).id == 103


def test_sender_constrains_revisions_but_originator_does_not():
    d = doc(4, originator="ORG", revisions=[rev(40, 4, "P01", "2024-01-01", sender="SND"),
                                             rev(41, 4, "P02", "2025-01-01")])
    assert [r.id for r in eligible_revisions(d, {"org": "ORG"})] == [40, 41]                 # originator: all
    assert [r.id for r in eligible_revisions(d, {"org": "SND"})] == [40]                     # sender: that one
    assert representing_revision("latest", d, {"org": "SND"}, 40).revision.id == 40
    assert eligible_revisions(d, {"org": "XXX"}) == () and eligible_revisions(d, {"doc_type": "LT"}) == ()


def test_document_without_an_eligible_revision_is_not_eligible():
    with pytest.raises(ValueError, match="no revision satisfying"):
        representing_revision("latest", HDOC, {"stage": "HO"}, None)


def test_baseline_revision_failing_a_hard_filter_is_rejected():
    with pytest.raises(ValueError, match="fails a hard filter"):
        best_match_revision(HDOC, eligible_revisions(HDOC, {"stage": "CN"}), 100)


def sup(new, old, **kw):
    return Link(new, old, "supersedes", **kw)


def test_supersession_moves_down_or_up_and_handles_chains():
    assert current_order([5, 2, 9, 1], [sup(1, 2)]) == (5, 9, 1, 2)
    assert current_order([1, 5, 9, 2], [sup(1, 2)]) == (1, 2, 5, 9)
    assert current_order([3, 2, 1, 7], [sup(1, 2), sup(2, 3)]) == (1, 2, 3, 7)
    assert current_order([3, 2], [sup(40, 3)]) == (3, 2)
    assert current_order([2, 1], [sup(1, 2, provenance="extracted"), Link(1, 2, "responds_to")]) == (2, 1)
    assert current_order([2, 1], [sup(1, 2, from_revision_id=11, to_revision_id=21)]) == (1, 2)


@pytest.mark.parametrize("links, message", [
    ([sup(1, 3), sup(2, 3)], "superseded by two"),
    ([sup(1, 2), sup(1, 3)], "supersedes two"),
    ([sup(1, 2), sup(2, 1)], "superseded by two|supersedes two|cycle"),
    ([sup(1, 2), sup(2, 3), sup(3, 1)], "cycle"),
])
def test_undefined_supersession_shapes_stop(links, message):
    with pytest.raises(UndefinedRuleError, match=message):
        current_order([1, 2, 3], links)


# =============================================================================================
# Orchestration (S4) and ablations (S5)
# =============================================================================================

RELATION = {"link_type": "responds_to", "target_side": "from", "anchor_text": "the letter", "source": "letter"}


def world12(extra_links=()):
    """Twelve pool documents 1..12 (scores 12..1), document 50 outside the pool."""
    docs = [doc(i) for i in range(1, 13)] + [doc(50, doc_type="LT", wbs="330",
                                                 revisions=[rev(501, 50, "P01", "2024-01-01"),
                                                            rev(502, 50, "C01", "2025-01-01", use="construction")])]
    return facts(*docs, links=extra_links)


POOL12 = pool_of(*range(1, 13))


def test_s4_order_m2_then_m3_then_current_then_cut_then_m4():
    p = mk_plan(clues=[clue("doc_type", "LT", "likely", "letter")], relation=RELATION,
                document_state="current", revision_state="latest_for_construction")
    world = world12([Link(50, 7, "responds_to"), sup(50, 3)])
    pool = pool_of(*range(1, 13), scores={i: 13.0 - i for i in range(1, 13)})
    out = run(p, pool, world, anchor_ranking=[7])
    # M3 puts 50 first (boost 0.5 as a letter); current places 3 directly below 50; then the rest.
    assert out.order[:4] == (50, 3, 1, 2) and len(out.order) == 13
    assert ids(out) == list(out.order[:10])
    first = out.results[0]
    assert (first.document_id, first.in_pool, first.revision.revision.rev_code, first.revision.satisfied) == \
        (50, False, "C01", True)
    assert [p_.anchor_document_id for p_ in first.paths] == [7]
    assert all(r.revision.satisfied is False for r in out.results[1:])     # pool docs have no construction rev


def test_cut_to_ten_happens_after_document_state_ordering():
    p = mk_plan(document_state="current")
    out = run(p, POOL12, world12([sup(11, 3)]))
    assert 3 not in ids(out) and out.order.index(3) == out.order.index(11) + 1 == 10
    assert ids(out) == [1, 2, 4, 5, 6, 7, 8, 9, 10, 11]


def test_revision_choice_never_changes_document_rank():
    a = run(mk_plan(revision_state="best_match"), POOL12, world12())
    b = run(mk_plan(revision_state="earliest"), POOL12, world12())
    assert ids(a) == ids(b)


def test_lexical_query_choice_follows_m2_switch():
    p = mk_plan(clues=[clue("discipline", "D", "context", "pond")], text="pond flow control")
    assert eng.lexical_query(p, Switches()) == "flow control"                         # C2 pool text
    assert eng.lexical_query(p, Switches(m2=False)) == "pond flow control"            # frozen text
    assert run(p, pool_of(1), facts(doc(1)), switches=Switches(m2=False)).lexical_query == "pond flow control"


def test_m2_disabled_no_boosts_pool_order_and_zero_boost_for_m3():
    p = mk_plan(clues=[clue("doc_type", "LT", "likely", "letter")], relation=RELATION)
    world = world12([Link(50, 7, "responds_to"), Link(12, 7, "responds_to")])
    on = run(p, POOL12, world, anchor_ranking=[7])
    off = run(p, POOL12, world, anchor_ranking=[7], switches=Switches(m2=False))
    assert on.order[:2] == (50, 12)                    # 50 has the letter boost
    assert off.order[:2] == (12, 50)                   # boost 0: baseline score decides (50 is outside: 0)
    assert all(s.soft_boost == 0 and s.matches == () for s in off.m2_scores + off.linked_scores)
    assert off.order[2:] == tuple(range(1, 12))


def test_m3_disabled_no_anchors_no_expansion():
    p = mk_plan(relation=RELATION)
    world = world12([Link(50, 7, "responds_to")])
    out = run(p, POOL12, world, switches=Switches(m3=False))
    assert out.anchor_query is None and out.linked == () and ids(out) == list(range(1, 11))
    with pytest.raises(ValueError, match="anchor ranking was supplied"):
        run(p, POOL12, world, anchor_ranking=[7], switches=Switches(m3=False))


def test_m4_disabled_no_reordering_and_baseline_revisions():
    p = mk_plan(document_state="current", revision_state="latest")
    world = world12([sup(5, 1)])
    out = run(p, POOL12, world, switches=Switches(m4=False))
    assert ids(out) == list(range(1, 11))
    assert all(r.revision.revision.id == r.document_id * 10 + 1 and r.revision.requested_state == "latest"
               and r.revision.satisfied is None and r.revision.basis == "conventional_baseline"
               for r in out.results)
    assert ids(run(p, POOL12, world)) == [2, 3, 4, 5, 1, 6, 7, 8, 9, 10]


@pytest.mark.parametrize("switches", [Switches(m2=a, m3=b, m4=c) for a in (True, False) for b in (True, False)
                                      for c in (True, False)])
def test_every_switch_combination_runs_independently(switches):
    p = mk_plan(clues=[clue("doc_type", "LT", "likely", "letter")], relation=RELATION, document_state="current")
    world = world12([Link(50, 7, "responds_to", from_revision_id=501), sup(5, 1)])   # link names older 501
    out = run(p, POOL12, world, anchor_ranking=[7] if switches.m3 else (), switches=switches)
    assert (50 in out.order) is switches.m3
    assert (out.order.index(1) == out.order.index(5) + 1) is switches.m4
    assert any(s.soft_boost for s in out.linked_scores) is (switches.m2 and switches.m3)
    if switches.m3:
        (r50,) = [r for r in out.results if r.document_id == 50]
        if switches.m4:                         # S3.3: the link's revision
            assert (r50.revision.revision.id, r50.revision.basis, r50.revision.satisfied) == (501, "m4", True)
        else:                                   # addendum A1: latest eligible, link revision ignored
            assert (r50.revision.revision.id, r50.revision.basis, r50.revision.satisfied) == \
                (502, "m4_off_default", None)


def test_all_mechanisms_off_or_default_plan_is_the_conventional_result():
    world = world12()
    for p, sw in ((mk_plan(clues=[clue("doc_type", "LT", "likely", "letter")], revision_state="earliest",
                           document_state="current"), Switches(False, False, False)),
                  (plan(parse_request({"id": "D", "raw_text": "flow control", "text": "flow control", "clues": [],
                                       "revision_state": "best_match", "document_state": "any", "approx": [],
                                       "verify": [], "withdrawn": []})), Switches())):
        out = run(p, POOL12, world, switches=sw)
        assert ids(out) == list(range(1, 11))
        assert [r.revision.revision.id for r in out.results] == [e.matched_revision_id for e in POOL12[:10]]


def test_run_validates_inputs_and_does_not_mutate_them():
    p = mk_plan(clues=[clue("doc_type", "LT", "likely", "letter")], relation=RELATION, document_state="current")
    world = world12([Link(50, 7, "responds_to")])
    before_world, before_pool = copy.deepcopy(world), copy.deepcopy(POOL12)
    run(p, POOL12, world, anchor_ranking=[7])
    assert world == before_world and POOL12 == before_pool
    with pytest.raises(ValueError, match="at most 50"):
        run(p, pool_of(*range(1, 52)), facts(*[doc(i) for i in range(1, 52)]))
    with pytest.raises(ValueError, match="no facts"):
        run(p, pool_of(99), world)
    with pytest.raises(ValueError, match="fails the hard filters"):
        run(mk_plan(clues=[clue("doc_type", "LT", "confirmed", "letter")]), pool_of(1), facts(doc(1)))


def test_runs_are_deterministic():
    p = mk_plan(clues=[clue("doc_type", "LT", "likely", "letter")], relation=RELATION, document_state="current")
    world = world12([Link(50, 7, "responds_to"), sup(5, 1)])
    assert run(p, POOL12, world, anchor_ranking=[7]) == run(p, POOL12, world, anchor_ranking=[7])


# =============================================================================================
# Ablation addendum A1: M4 off, M3 document from outside the pool
# =============================================================================================

def addendum_world(pool_stage="DD", pool_originator="AAA", link_rev=601):
    """Pool documents 1-3; document 60 outside the pool, linked to anchor 1 (link names `link_rev`).
    60's revisions: 601 (oldest, DD, sender SND), 602 (CN, construction), 603 (latest, DD, sender OTH)."""
    pool_docs = [doc(i, [rev(i * 10 + 1, i, "P01", "2025-01-01", stage=pool_stage)], originator=pool_originator)
                 for i in (1, 2, 3)]
    d60 = doc(60, originator="ORG", revisions=[
        rev(601, 60, "P01", "2024-01-01", stage="DD", sender="SND"),
        rev(602, 60, "P02", "2024-06-01", stage="CN", use="construction"),
        rev(603, 60, "C01", "2025-01-01", stage="DD", sender="OTH")])
    return facts(*pool_docs, d60, links=[Link(60, 1, "responds_to", from_revision_id=link_rev)])


M4_OFF = Switches(m4=False)


def r60(out):
    (r,) = [r for r in out.results if r.document_id == 60]
    return r


def test_a1_latest_revision_ignores_link_revision_and_requested_state():                       # A, G
    for state in ("best_match", "latest", "earliest", "earliest_for_construction"):
        out = run(mk_plan(relation=RELATION, revision_state=state), pool_of(1, 2, 3), addendum_world(),
                  anchor_ranking=[1], switches=M4_OFF)
        r = r60(out)
        assert (r.revision.revision.id, r.revision.basis, r.revision.satisfied) == (603, "m4_off_default", None)
        assert r.revision.requested_state == state and "not evaluated" in r.revision.note
        assert [p.wanted_revision_id for p in r.paths] == [601]          # the link's revision stays evidence


def test_a1_hard_stage_filter_constrains_the_default():                                        # B
    p = mk_plan(clues=[clue("stage", "CN", "confirmed", "stage")], relation=RELATION)
    r = r60(run(p, pool_of(1, 2, 3), addendum_world(pool_stage="CN"), anchor_ranking=[1], switches=M4_OFF))
    assert (r.revision.revision.id, r.revision.revision.stage) == (602, "CN")    # not the latest (603, DD)


def test_a1_sender_based_organisation_filter_constrains_the_default():                         # C
    p = mk_plan(clues=[clue("sender", "SND", "confirmed", "contractor")], relation=RELATION)
    world = addendum_world(pool_originator="SND", link_rev=None)
    r = r60(run(p, pool_of(1, 2, 3), world, anchor_ranking=[1], switches=M4_OFF))
    assert (r.revision.revision.id, r.revision.revision.sender) == (601, "SND")  # 603 has sender OTH


def test_a1_originator_only_match_does_not_constrain_the_default():                            # D
    p = mk_plan(clues=[clue("originator", "ORG", "confirmed", "contractor")], relation=RELATION)
    r = r60(run(p, pool_of(1, 2, 3), addendum_world(pool_originator="ORG"), anchor_ranking=[1], switches=M4_OFF))
    assert r.revision.revision.id == 603


def test_a1_no_eligible_revision_is_an_invariant_error_and_never_displayed():                  # E
    with pytest.raises(ValueError, match="addendum A1 item 9"):
        eng.m4_off_default_revision(addendum_world().document(60), {"stage": "HO"})
    p = mk_plan(clues=[clue("stage", "HO", "confirmed", "stage")], relation=RELATION)
    out = run(p, pool_of(1, 2, 3), addendum_world(pool_stage="HO"), anchor_ranking=[1], switches=M4_OFF)
    assert out.rejected_linked == (60,) and 60 not in ids(out)               # S2.2 keeps it out


def test_a1_in_pool_documents_keep_the_baseline_revision():                                    # F
    world = facts(doc(1, [rev(11, 1, "P01", "2024-01-01"), rev(12, 1, "P02", "2025-01-01")]), doc(2))
    pool = (PoolEntry(1, 2.0, 11), PoolEntry(2, 1.0, 21))
    out = run(mk_plan(revision_state="latest"), pool, world, switches=M4_OFF)
    first = out.results[0]
    assert (first.revision.revision.id, first.revision.basis, first.revision.satisfied) == \
        (11, "conventional_baseline", None)
    assert run(mk_plan(revision_state="latest"), pool, world).results[0].revision.revision.id == 12   # M4 on


def test_a1_default_does_not_change_document_order():                                         # H
    world, p = addendum_world(), mk_plan(relation=RELATION, revision_state="earliest")
    on = run(p, pool_of(1, 2, 3), world, anchor_ranking=[1])
    off = run(p, pool_of(1, 2, 3), world, anchor_ranking=[1], switches=M4_OFF)
    assert on.order == off.order and ids(on) == ids(off) == [60, 1, 2, 3]


def test_m4_on_keeps_s33_and_s35_for_outside_pool_documents():                                # I
    world = addendum_world()
    best = r60(run(mk_plan(relation=RELATION), pool_of(1, 2, 3), world, anchor_ranking=[1]))
    assert (best.revision.revision.id, best.revision.basis, best.revision.satisfied) == (601, "m4", True)
    built = r60(run(mk_plan(relation=RELATION, revision_state="earliest_for_construction"), pool_of(1, 2, 3),
                    world, anchor_ranking=[1]))
    assert (built.revision.revision.id, built.revision.satisfied) == (602, True)
    staged = r60(run(mk_plan(clues=[clue("stage", "CN", "confirmed", "stage")], relation=RELATION),
                     pool_of(1, 2, 3), addendum_world(pool_stage="CN"), anchor_ranking=[1]))
    assert staged.revision.revision.id == 602                    # S3.5: link's 601 is not stage CN


# =============================================================================================
# Stage-1 compatibility and isolation
# =============================================================================================

def test_stage1_plans_fit_stage2_inputs():
    for p in plan_all(load_frozen_requests()):
        assert p.revision_state in eng.REVISION_STATES
        assert set(p.filters()) <= set(eng.FILTER_KEYS)
        assert all(c.strength in ("likely", "context") for c in p.soft_clues)
        if p.relation is not None:
            assert p.relation.link_type in eng.REGISTERED_LINK_TYPES + ("any",)
            assert p.relation.target_side in ("from", "to")


def test_module_imports_nothing_that_retrieves_or_reads_answers():
    code = ("import sys, eval.experiments.ir1_engine; "
            "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('app', 'psycopg', 'dcc_corpus') "
            "or m in ('eval.run_eval', 'eval.check_equivalence')); print(bad)")
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
