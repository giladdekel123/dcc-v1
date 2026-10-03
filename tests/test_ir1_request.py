"""IR-1 stage 1: frozen request loader and deterministic planner. No database, no retrieval.

Synthetic requests exercise the rules; the frozen file is only loaded, fingerprinted and planned.
Nothing here reads expected answers, the corpus or any evaluation result.
"""

import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from eval.experiments import ir1_request as ir1
from eval.experiments.ir1_request import (Plan, PlanError, Relation, RequestError, Unresolved, is_default,
                                          load_frozen_requests, parse_document, parse_request, plan,
                                          remove_context_sources)

REPO = Path(__file__).resolve().parent.parent


def item(**overrides) -> dict:
    """A valid synthetic request mapping; overrides replace fields (None removes one)."""
    base = {"id": "T1", "source_file": "synthetic", "raw_text": "the Pond 2 East flow control drawing",
            "text": "Pond 2 East flow control", "clues": [], "revision_state": "best_match",
            "document_state": "any", "approx": [], "verify": [], "withdrawn": []}
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def clue(field, code, strength, source) -> dict:
    return {"field": field, "code": code, "strength": strength, "source": source}


def req(**overrides):
    return parse_request(item(**overrides))


def default_req(raw="some remembered words"):
    return parse_request({"id": "D1", "raw_text": raw, "text": raw, "clues": [], "revision_state": "best_match",
                          "document_state": "any", "approx": [], "verify": [], "withdrawn": []})


# --- frozen file ------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def frozen():
    return load_frozen_requests()


def test_frozen_fingerprint_is_accepted(frozen):
    assert frozen.sha256 == ir1.FROZEN_SHA256 == "5b68dab1e8eff7c2c82aa6e9e07d5686ce47ee7a06c27aae9bd3e706e577f860"


def test_altered_file_is_rejected_before_parsing(tmp_path):
    altered = tmp_path / "ir1_frozen58_annotations.yaml"
    altered.write_bytes(b"{{{")                                  # not YAML: parsing it would raise yaml.YAMLError
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(altered.read_bytes())
    with pytest.raises(RequestError, match="SHA-256"):
        load_frozen_requests(altered)


def test_appended_comment_is_rejected(tmp_path):
    altered = tmp_path / "ir1_frozen58_annotations.yaml"
    altered.write_bytes(ir1.FROZEN_PATH.read_bytes() + b"# appended comment\n")    # still valid YAML
    with pytest.raises(RequestError, match="SHA-256"):
        load_frozen_requests(altered)


def test_wrong_expected_fingerprint_is_rejected():
    with pytest.raises(RequestError, match="SHA-256"):
        load_frozen_requests(expected_sha256="0" * 64)


def test_exactly_58_unique_requests_load(frozen):
    ids = [r.id for r in frozen.requests]
    assert len(ids) == 58 == len(set(ids))
    assert sum(i.startswith("G") for i in ids) == 40 and sum(i.startswith("H") for i in ids) == 18


def test_raw_frozen_values_are_preserved(frozen):
    data = yaml.safe_load(ir1.FROZEN_PATH.read_bytes())
    for r, raw in zip(frozen.requests, data["requests"]):
        assert json.loads(r.raw_json) == raw
        assert (r.id, r.raw_text, r.text) == (raw["id"], raw["raw_text"], raw["text"])
    assert len(frozen.unresolved) == len(data["unresolved_vocabulary"])


def test_every_frozen_request_plans(frozen):
    plans = ir1.plan_all(frozen)
    assert len(plans) == 58
    assert all(p.hard_filters == () for p in plans)          # the only confirmed clues are wbs (C1)
    wbs = [c for p in plans for c in p.soft_clues if c.field == "wbs"]
    assert len(wbs) == 18 and all(c.strength == "context" and c.reclassified == "C1" for c in wbs)


def test_frozen_plans_are_deterministic(frozen):
    assert ir1.plan_all(frozen) == ir1.plan_all(load_frozen_requests())


# --- schema validation ------------------------------------------------------------------------

@pytest.mark.parametrize("overrides, message", [
    ({"text": None}, "missing"),
    ({"extra": 1}, "unknown"),
    ({"text": 5}, "expected a string"),
    ({"approx": "x"}, "expected a list"),
    ({"revision_state": "newest"}, "revision_state"),
    ({"document_state": "superseded"}, "document_state"),
    ({"clues": [clue("owner", "X", "likely", "Pond")]}, "field"),
    ({"clues": [clue("wbs", "320", "certain", "Pond")]}, "strength"),
    ({"clues": [clue("wbs", "320", "context", "Lake")]}, "literal substring"),
    ({"clues": [{"field": "wbs", "code": "320", "strength": "context"}]}, "missing"),
    ({"relation": {"link_type": "replaces", "target_side": "from", "anchor_text": "a", "source": "the"}}, "link_type"),
    ({"relation": {"link_type": "any", "target_side": "both", "anchor_text": "a", "source": "the"}}, "target_side"),
    ({"relation": {"link_type": "any", "target_side": "from", "anchor_text": "a", "source": "nope"}}, "literal substring"),
])
def test_schema_violations_are_rejected(overrides, message):
    with pytest.raises(RequestError, match=message):
        req(**overrides)


@pytest.mark.parametrize("overrides", [
    {"clues": [clue("wbs", "320", "context", "")]},
    {"clues": [clue("wbs", "320", "context", "  ")]},
    {"clues": [clue("wbs", "", "context", "Pond")]},
    {"clues": [clue("wbs", " \t", "context", "Pond")]},
    {"text": ""}, {"text": "   "},
    {"raw_text": ""}, {"raw_text": " \n "},
])
def test_blank_values_are_rejected(overrides):
    with pytest.raises(RequestError, match="empty or whitespace"):
        parse_request({**item(), **overrides})


def relation(source) -> dict:
    return {"link_type": "responds_to", "target_side": "from", "anchor_text": "the flow control drawing",
            "source": source}


@pytest.mark.parametrize("source", ["", "   ", "\t\n"])
def test_blank_relation_source_is_rejected(source):
    with pytest.raises(RequestError, match=r"relation\.source: must not be empty or whitespace"):
        parse_request({**item(), "relation": relation(source)})


def test_nonblank_literal_relation_source_is_accepted():
    assert parse_request({**item(), "relation": relation("flow control")}).relation.source == "flow control"
    with pytest.raises(RequestError, match="literal substring"):                 # literal rule still applies
        parse_request({**item(), "relation": relation("not in the text")})


def test_explicit_null_relation_is_rejected():
    with pytest.raises(RequestError, match="omitted, not null"):
        parse_request({**item(), "relation": None})
    assert parse_request(item()).relation is None                  # omitted: no relation


def test_document_level_validation():
    two = [item(id="A"), item(id="B")]
    assert len(parse_document({"requests": two, "unresolved_vocabulary": []}, "x", expected_count=2).requests) == 2
    with pytest.raises(RequestError, match="expected 58"):
        parse_document({"requests": two, "unresolved_vocabulary": []}, "x")
    with pytest.raises(RequestError, match="duplicate"):
        parse_document({"requests": [item(id="A"), item(id="A")], "unresolved_vocabulary": []}, "x", expected_count=2)
    with pytest.raises(RequestError, match="unknown request id"):
        parse_document({"requests": two, "unresolved_vocabulary": [
            {"id": "Z", "field": "wbs", "source": "s", "reason": "r"}]}, "x", expected_count=2)
    with pytest.raises(RequestError, match="unknown"):
        parse_document({"requests": two, "unresolved_vocabulary": [], "notes": []}, "x", expected_count=2)


# --- M1 and C1 --------------------------------------------------------------------------------

@pytest.mark.parametrize("field, key", [("doc_type", "doc_type"), ("discipline", "discipline"),
                                        ("stage", "stage"), ("originator", "org"), ("sender", "org")])
def test_confirmed_non_wbs_clue_is_a_hard_filter(field, key):
    p = plan(req(clues=[clue(field, "XX", "confirmed", "drawing")]))
    assert p.filters() == {key: "XX"} and p.soft_clues == ()


def test_confirmed_wbs_is_effective_context_never_a_hard_filter():
    p = plan(req(raw_text="WBS 320 Pond 2 East. flow control", clues=[clue("wbs", "320", "confirmed", "WBS 320")]))
    assert p.hard_filters == () and p.filters() == {}
    (c,) = p.soft_clues
    assert (c.field, c.code, c.frozen_strength, c.strength, c.boost, c.reclassified) == \
        ("wbs", "320", "confirmed", "context", ir1.CONTEXT_BOOST, "C1")


@pytest.mark.parametrize("strength", ["likely", "context"])
def test_wbs_of_any_frozen_strength_behaves_as_context(strength):
    (c,) = plan(req(clues=[clue("wbs", "320", strength, "Pond")])).soft_clues
    assert c.strength == "context" and c.boost == 0.1 and c.frozen_strength == strength


def test_confirmed_clues_on_the_same_filter_with_different_codes_are_not_combined():
    with pytest.raises(PlanError, match="M1 does not define"):
        plan(req(clues=[clue("originator", "AAA", "confirmed", "the"), clue("sender", "BBB", "confirmed", "drawing")]))


def test_repeated_identical_confirmed_clue_gives_one_filter():
    p = plan(req(clues=[clue("originator", "AAA", "confirmed", "the"), clue("sender", "AAA", "confirmed", "drawing")]))
    assert p.filters() == {"org": "AAA"} and len(p.hard_filters) == 1


# --- M2 ----------------------------------------------------------------------------------------

def test_constants_are_the_preregistered_values():
    assert (ir1.POOL_SIZE, ir1.LIKELY_BOOST, ir1.CONTEXT_BOOST, ir1.ANCHOR_COUNT) == (50, 0.5, 0.1, 3)
    assert not hasattr(ir1, "main") and "argparse" not in Path(ir1.__file__).read_text(encoding="utf-8")


def test_constant_maps_are_read_only():
    assert dict(ir1.BOOST) == {"likely": 0.5, "context": 0.1}
    assert dict(ir1.HARD_FILTER_KEY) == {"doc_type": "doc_type", "discipline": "discipline", "stage": "stage",
                                         "originator": "org", "sender": "org"}
    for mapping, key in ((ir1.BOOST, "likely"), (ir1.HARD_FILTER_KEY, "wbs")):
        with pytest.raises(TypeError):
            mapping[key] = "changed"


def test_likely_and_context_clues_stay_soft_with_their_boosts():
    p = plan(req(clues=[clue("doc_type", "DR", "likely", "drawing"), clue("discipline", "D", "context", "Pond")]))
    assert p.hard_filters == ()
    assert [(c.field, c.strength, c.boost, c.reclassified) for c in p.soft_clues] == \
        [("doc_type", "likely", 0.5, None), ("discipline", "context", 0.1, None)]


# --- C2 ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, sources, expected", [
    ("Pond 2 East flow control", ("pond",), "2 East flow control"),                 # case-insensitive
    ("POND pond Pond", ("Pond",), None),                                             # every occurrence -> empty
    ("drainage strategy ponds", ("pond",), "drainage strategy ponds"),               # whole word only
    ("respond to the pond", ("pond",), "respond to the"),
    ("Mill Lane Culvert Northvale Water protecting existing water main", ("water main",),
     "Mill Lane Culvert Northvale Water protecting existing"),                       # phrase, not 'Water'
    ("water supply main", ("water main",), "water supply main"),                     # constituents stay
    ("east  abutment   piles", ("abutment",), "east piles"),                         # whitespace normalised
    ("a water\tmain b", ("water main",), "a b"),                                     # any internal whitespace
    ("cost variation clash", ("cost", "clash"), "variation"),
    ("unchanged text", (), "unchanged text"),
])
def test_context_source_removal(text, sources, expected):
    result, removed, fallback = remove_context_sources(text, sources)
    if expected is None:
        assert (result, fallback) == (text, True)
    else:
        assert (result, fallback) == (expected, False)
        assert set(removed) <= set(sources)


def test_empty_result_falls_back_to_frozen_text():
    p = plan(req(raw_text="the pond letter", text="pond", clues=[clue("discipline", "D", "context", "pond")]))
    assert p.pool_text == "pond" and p.audit.pool_text_fallback and p.audit.removed_phrases == ("pond",)


def test_only_context_sources_are_removed():
    p = plan(req(clues=[clue("doc_type", "DR", "likely", "drawing"), clue("discipline", "D", "likely", "flow control")]))
    assert p.pool_text == "Pond 2 East flow control" and p.audit.removed_phrases == ()


def test_wbs_source_is_removed_as_a_context_source():
    p = plan(req(raw_text="WBS 320 Pond 2 East", text="WBS 320 Pond 2 East",
                 clues=[clue("wbs", "320", "confirmed", "WBS 320")]))
    assert p.pool_text == "Pond 2 East" and p.audit.removed_phrases == ("WBS 320",)


def test_removal_uses_the_frozen_text_so_removals_do_not_cascade():
    assert remove_context_sources("water x main", ("x", "water main"))[0] == "water main"


def test_overlapping_context_sources_are_not_resolved():
    with pytest.raises(PlanError, match="overlap"):
        remove_context_sources("abutment drainage layer", ("drainage", "drainage layer"))


@pytest.mark.parametrize("sources", [("Pond", "pond"), ("pond", "POND", "Pond"), ("water main", "Water  Main")])
def test_sources_that_normalise_to_one_phrase_are_one_source(sources):
    text = "Pond 2 East pond" if "pond" in sources[0].lower() else "Northvale Water water main slab"
    result, removed, _ = remove_context_sources(text, sources)
    assert removed == (sources[0],)                              # first spelling kept for the audit record
    assert result == remove_context_sources(text, sources[:1])[0]


def test_duplicate_context_sources_across_clues_plan():
    p = plan(req(raw_text="Pond 2 East pond drawing", text="Pond 2 East pond",
                 clues=[clue("discipline", "D", "context", "Pond"), clue("wbs", "320", "confirmed", "pond")]))
    assert p.pool_text == "2 East" and p.audit.removed_phrases == ("Pond",)


def test_different_phrases_with_overlapping_spans_still_raise():
    with pytest.raises(PlanError, match="overlap"):
        remove_context_sources("Water Main works", ("water main", "MAIN WORKS"))


def test_no_other_text_rewriting():
    p = plan(req(text="Flow-control piles, PSV  60", raw_text="Flow-control piles, PSV  60",
                 clues=[clue("doc_type", "SB", "likely", "piles")]))
    assert p.pool_text == "Flow-control piles, PSV  60"                              # nothing removed: untouched


# --- relation, state and audit-only fields ----------------------------------------------------

PLAN_FIELDS = {"request_id", "is_default", "hard_filters", "soft_clues", "pool_text", "relation",
               "revision_state", "document_state", "audit"}


def test_plan_holds_intent_only():
    """The plan's fields are exactly the stage-1 intent: no anchors, links, candidates, revisions or order."""
    assert {f.name for f in dataclasses.fields(Plan)} == PLAN_FIELDS


def test_relation_intent_is_preserved_not_resolved():
    rel = {"link_type": "responds_to", "target_side": "from", "anchor_text": "the flow control drawing",
           "source": "flow control"}
    p = plan(req(relation=rel))
    assert p.relation == Relation(**rel) and isinstance(p.relation, Relation)
    assert {f.name for f in dataclasses.fields(Relation)} == {"link_type", "target_side", "anchor_text", "source"}


def test_revision_and_document_state_are_preserved_not_executed():
    p = plan(req(revision_state="earliest_for_construction", document_state="current", state_source=["the"]))
    assert (p.revision_state, p.document_state) == ("earliest_for_construction", "current")
    assert isinstance(p.revision_state, str) and isinstance(p.document_state, str)   # intent values, not revisions


def _with_clue(**overrides):
    return req(clues=[clue("discipline", "D", "context", "Pond")], **overrides)


@pytest.mark.parametrize("overrides", [
    {"approx": ["2 East"]}, {"verify": ["flow control"]}, {"withdrawn": ["Pond"]},
    {"source_file": "elsewhere.yaml"}, {"state_source": ["drawing"]},
])
def test_audit_only_fields_do_not_change_retrieval_signals(overrides):
    assert plan(_with_clue(**overrides)).retrieval_signature() == plan(_with_clue()).retrieval_signature()


def test_audit_record_keeps_audit_only_fields():
    u = Unresolved("T1", "sender", "Pond", "no vocabulary")
    p = plan(req(approx=["2 East"], verify=["flow control"], withdrawn=["drawing"]), (u, Unresolved("X", "f", "s", "r")))
    a = p.audit
    assert (a.approx, a.verify, a.withdrawn, a.unresolved, a.source_file) == \
        (("2 East",), ("flow control",), ("drawing",), (u,), "synthetic")


def test_withdrawn_is_never_activated():
    """Withdrawn entries never become a hard filter, soft clue, relation or lexical rewrite."""
    clues = [clue("doc_type", "DR", "likely", "drawing"), clue("discipline", "D", "context", "flow control")]
    without = plan(req(clues=clues))
    withdrawn = plan(req(clues=clues, withdrawn=["Pond 2 East", "drawing", "flow control"]))
    assert withdrawn.hard_filters == without.hard_filters == ()
    assert withdrawn.soft_clues == without.soft_clues
    assert withdrawn.relation is None
    assert withdrawn.pool_text == without.pool_text == "Pond 2 East"   # only the context source was removed
    assert withdrawn.audit.removed_phrases == ("flow control",)
    assert withdrawn.audit.withdrawn == ("Pond 2 East", "drawing", "flow control")


def test_approx_verify_withdrawn_affect_only_default_detection():
    """M-2: on a genuinely default request, any entry makes it non-default and changes nothing else."""
    base = default_req("the remembered words")
    assert plan(base).is_default
    for name in ("approx", "verify", "withdrawn"):
        changed = parse_request({**json.loads(base.raw_json), name: ["remembered"]})
        before, after = plan(base).retrieval_signature(), plan(changed).retrieval_signature()
        assert after[0] is False and before[0] is True
        assert after[1:] == before[1:]


def test_unresolved_vocabulary_is_not_a_retrieval_signal():
    a = plan(_with_clue(), (Unresolved("T1", "originator", "Pond", "r"),))
    assert a.retrieval_signature() == plan(_with_clue()).retrieval_signature()


# --- default requests (M0 detection only) -----------------------------------------------------

def test_default_request_detection():
    assert plan(default_req()).is_default
    assert is_default(parse_request({**item(raw_text="words", text="words"), "source_file": "x", "state_source": []}))


@pytest.mark.parametrize("overrides", [
    {"text": "Pond 2 East"},                                                      # text differs from raw_text
    {"clues": [clue("doc_type", "DR", "likely", "drawing")]},
    {"relation": {"link_type": "any", "target_side": "from", "anchor_text": "a", "source": "the"}},
    {"revision_state": "latest"}, {"document_state": "current"},
    {"approx": ["the"]}, {"verify": ["the"]}, {"withdrawn": ["the"]},
])
def test_non_default_requests(overrides):
    base = item(raw_text="the Pond 2 East flow control drawing", text="the Pond 2 East flow control drawing")
    assert not is_default(parse_request({**base, **overrides}))


def test_same_request_gives_identical_plan():
    r = _with_clue(relation={"link_type": "any", "target_side": "to", "anchor_text": "x", "source": "the"},
                   revision_state="latest")
    assert plan(r) == plan(r) and repr(plan(r)) == repr(plan(r))
    assert plan(r) == plan(parse_request(json.loads(r.raw_json)))


# --- isolation --------------------------------------------------------------------------------

def test_module_imports_nothing_that_retrieves_or_reads_answers():
    code = ("import sys, eval.experiments.ir1_request; "
            "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('app', 'psycopg', 'dcc_corpus') "
            "or m in ('eval.run_eval', 'eval.check_equivalence')); print(bad)")
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
