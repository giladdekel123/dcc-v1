"""IR-1b runner tests with fake search functions only. Nothing is retrieved; the frozen 58 are not run."""

from dataclasses import asdict
from pathlib import Path

import pytest

from eval.experiments import ir1_integration as ia
from eval.experiments import ir1b, ir1b_run as rr
from eval.experiments.ir1_engine import Switches
from eval.experiments.ir1_request import parse_request, plan
from eval.run_eval import Query, load_queries
from tests.test_ir1_integration import response_with


def mk_plan(qid, text):
    return plan(parse_request({"id": qid, "raw_text": text, "text": text, "clues": [], "revision_state": "best_match",
                               "document_state": "any", "approx": [], "verify": [], "withdrawn": []}))


QUERIES = [Query("G001", "generated", "vague_topic", "alpha", ["DOC-001"]),
           Query("H001", "human", "vague_topic", "beta", ["DOC-001"])]
PLANS = {"alpha": mk_plan("G001", "alpha"), "beta": mk_plan("H001", "beta")}


class Fakes:
    """Fake searches; `vary` lets a test change one condition's response."""

    def __init__(self, vary=None):
        self.calls, self.vary = [], vary or {}

    def _response(self, engine, key):
        r = response_with(engine)
        if key in self.vary:
            self.vary[key](r)
        return r

    def conventional(self, conn, query, filters, limit=10):
        self.calls.append(("conventional", query))
        return self._response("baseline-fts-v1", "0")

    def frozen_ir1(self, conn, plan_, switches):
        self.calls.append(("frozen_ir1", plan_.request_id, switches))
        return ia.IR1Response(self._response(ia.ENGINE_LABEL, "1"), {"engine": ia.ENGINE_LABEL})

    def ir1b_search(self, conn, plan_, config, condition):
        self.calls.append(("ir1b", condition, config))
        return ia.IR1Response(self._response(ir1b.ENGINE_LABEL, condition), {"condition": condition})


def references(fakes=None):
    f = fakes or Fakes()
    c0 = rr.run_condition(None, "0", QUERIES, PLANS, f.conventional, f.frozen_ir1, f.ir1b_search)
    c1 = rr.run_condition(None, "1", QUERIES, PLANS, f.conventional, f.frozen_ir1, f.ir1b_search)
    return c0["outcomes"], c1["outcomes"], {q: v["response_sha256"] for q, v in c1["per_query"].items()}


def run(fakes, refs=None, into=None):
    base, ir1_out, ir1_hash = refs or references()
    return rr.run_experiment(None, QUERIES, PLANS, base, ir1_out, ir1_hash, fakes.conventional, fakes.frozen_ir1,
                             fakes.ir1b_search, into=into)


# --- conditions and dispatch ---------------------------------------------------------------

def test_all_15_conditions_exactly_once():
    assert len(rr.CONDITION_IDS) == 15 == len(set(rr.CONDITION_IDS))
    assert set(rr.CONDITION_IDS) == set(ir1b.CONDITIONS) | {"0"} and rr.CONTROLS == ("0", "1", "2")
    defs = rr.condition_definitions()
    assert set(defs) == set(rr.CONDITION_IDS) and defs["0"]["config"] is None and defs["1"]["config"] is None
    assert defs["9r"]["config"] == defs["9"]["config"] == asdict(ir1b.CONDITIONS["9"])
    assert defs["1"]["switches"] == asdict(Switches())


def test_dispatch_kinds():
    assert rr.dispatch_kind("0") == "conventional" and rr.dispatch_kind("1") == "frozen_ir1"
    assert all(rr.dispatch_kind(c) == "ir1b" for c in rr.CONDITION_IDS if c not in ("0", "1"))
    with pytest.raises(KeyError):
        rr.dispatch_kind("14")


def test_each_condition_calls_the_right_search_with_the_right_config():
    f = Fakes()
    result = run(f)
    assert set(result["conditions"]) == set(rr.CONDITION_IDS)
    by_condition = {}
    for call in f.calls:
        by_condition.setdefault(call[0] if call[0] != "ir1b" else call[1], []).append(call)
    assert [c[1] for c in by_condition["conventional"]] == ["alpha", "beta"]       # condition 0 only
    assert all(c[2] == Switches() for c in by_condition["frozen_ir1"])
    for c in rr.CONDITION_IDS:
        if c not in ("0", "1"):
            assert [call[2] for call in by_condition[c]] == [ir1b.CONDITIONS[c]] * 2


def test_controls_and_determinism_pass_on_consistent_fakes():
    result = run(Fakes())
    assert result["controls"]["passed"] and result["determinism"]["passed"]
    assert result["regressions_vs_0"]["9"] == {"baseline_rank1_moved_down": [], "exact_revision_regressions": [],
                                               "left_top10": []}


# --- control failures stop the run ----------------------------------------------------------

def _bump_revision(r):
    r.results[0].revision.rev_code = "P09"


@pytest.mark.parametrize("vary, key", [
    ({"0": _bump_revision}, "0_reproduces_frozen_baseline"),
    ({"1": _bump_revision}, "1_reproduces_recorded_ir1_outcomes"),
    ({"2": _bump_revision}, "2_equals_0_outcomes"),
])
def test_control_mismatch_aborts_before_any_non_control_condition(vary, key):
    refs = references()                                           # references from unaltered fakes
    f, into = Fakes(vary), {}
    with pytest.raises(rr.ControlFailure):
        run(f, refs, into)
    assert into["controls"]["passed"] is False and into["controls"]["differing_queries"][key] == ["G001", "H001"]
    assert set(into["conditions"]) == set(rr.CONTROLS) and "stopped" in into
    assert not any(call[0] == "ir1b" and call[1] not in rr.CONTROLS for call in f.calls)


def test_ir1_response_hash_mismatch_aborts():
    base, ir1_out, ir1_hash = references()
    ir1_hash = {**ir1_hash, "H001": "0" * 64}
    with pytest.raises(rr.ControlFailure):
        run(Fakes(), (base, ir1_out, ir1_hash))


def test_condition_2_response_difference_beyond_engine_label_aborts():
    def evidence(r):
        r.results[0].location.filename = "other.pdf"              # same outcome fields, different response
    into = {}
    with pytest.raises(rr.ControlFailure):
        run(Fakes({"2": evidence}), references(), into)
    assert into["controls"]["differing_queries"]["2_equals_0_responses"] == ["G001", "H001"]
    assert into["controls"]["differing_queries"]["2_equals_0_outcomes"] == []


def test_determinism_mismatch_is_detected():
    result = run(Fakes({"9r": _bump_revision}))
    assert result["determinism"]["passed"] is False
    assert result["determinism"]["differing_queries"]["outcomes"] == ["G001", "H001"]


# --- regressions and classes ------------------------------------------------------------------

def outcome(qid, rank, rev_exact=None, matched="P01"):
    return {"id": qid, "rank": rank, "rev_exact": rev_exact, "matched_rev": matched}


def test_regression_lists():
    base = [outcome("A", 1), outcome("B", 3, True), outcome("C", 2)]
    new = [outcome("A", 2), outcome("B", 3, False, "P02"), outcome("C", None)]
    r = rr.regressions(base, new)
    assert r["baseline_rank1_moved_down"] == [{"id": "A", "baseline_rank": 1, "rank": 2}]
    assert r["exact_revision_regressions"] == [{"id": "B", "baseline_rev": "P01", "matched_rev": "P02"}]
    assert r["left_top10"] == [{"id": "C", "baseline_rank": 2}]


def test_class_movement_follows_the_clarification():
    ids = [q for _, qs in rr.CLASSES.values() for q in qs]
    base = [outcome(q, 2, False) for q in ids]
    new = {q: outcome(q, 2, False) for q in ids}
    new["G016"] = outcome("G016", 1)                              # relationship chain improves...
    new["G032"] = outcome("G032", None)                           # ...but another leaves the top 10
    new["G031"] = outcome("G031", 1)                              # supersession improves, none worsens
    new["G012"] = outcome("G012", 2, True)                        # revision becomes exact
    moves = rr.class_movement(base, list(new.values()))
    assert moves["relationship_chain"]["improved"] is False and moves["relationship_chain"]["queries"]["G032"] == "worsens"
    assert moves["supersession"]["improved"] is True and moves["requested_revision"]["improved"] is True
    assert moves["soft_clue"]["improved"] is False


# --- output -------------------------------------------------------------------------------------

def test_serialization_is_deterministic_and_lf_only():
    a = {"b": [1, {"y": "two\nlines", "x": None}], "a": "é"}
    b = {"a": "é", "b": [1, {"x": None, "y": "two\nlines"}]}
    assert rr.serialize(a) == rr.serialize(b) and b"\r" not in rr.serialize(a)
    assert rr.serialize(a).endswith(b"}\n")


def test_write_once_is_byte_exact_lf_and_never_overwrites(tmp_path: Path):
    path = tmp_path / "raw.json"
    digest = rr.write_once(path, {"z": 1, "a": [1, 2]})
    data = path.read_bytes()
    assert digest == rr.sha(data) and b"\r" not in data and data == rr.serialize({"a": [1, 2], "z": 1})
    with pytest.raises(FileExistsError):
        rr.write_once(path, {"other": True})
    assert path.read_bytes() == data


def test_provenance_records_commit_and_all_frozen_hashes():
    p = rr.provenance(["--out", "x.json"])
    assert len(p["commit"]) == 40 and "command" in p and p["corpus"]["fingerprint"]
    for f in ("eval/experiments/IR1B_PREREGISTRATION.md", "eval/experiments/IR1B_CLARIFICATIONS.md",
              "eval/experiments/IR1_PREREGISTRATION.md", "eval/experiments/ir1_frozen58_annotations.yaml",
              "eval/experiments/ir1b.py", "eval/experiments/ir1b_run.py", "eval/experiments/ir1_integration.py",
              "eval/queries/generated.yaml", "eval/queries/human.yaml", rr.IR1_RESULT, rr.BASELINE_REPORT):
        assert len(p["files_sha256"][f]) == 64
    assert p["files_sha256"]["eval/experiments/IR1B_PREREGISTRATION.md"] == \
        "9432b13cc014127c3078b230b40287f70dd4f52a5c8804053143f118e63d5eb4"


# --- controls-only mode -------------------------------------------------------------------------

def test_controls_only_runs_exactly_conditions_0_1_2_and_stops():
    f = Fakes()
    result = rr.run_experiment(None, QUERIES, PLANS, *references(), f.conventional, f.frozen_ir1, f.ir1b_search,
                               controls_only=True)
    assert result["controls_only"] is True and set(result["conditions"]) == {"0", "1", "2"}
    assert result["controls"]["passed"] is True
    assert {call[1] for call in f.calls if call[0] == "ir1b"} == {"2"}                 # only the control
    assert not any(k in result for k in ("determinism", "regressions_vs_0", "targeted_classes_vs_0"))


def test_controls_only_failure_stops_and_keeps_the_controls_run():
    f, into = Fakes({"1": _bump_revision}), {}
    with pytest.raises(rr.ControlFailure):
        rr.run_experiment(None, QUERIES, PLANS, *references(), f.conventional, f.frozen_ir1, f.ir1b_search,
                          into=into, controls_only=True)
    assert set(into["conditions"]) == {"0", "1", "2"} and into["controls"]["passed"] is False
    assert into["controls_only"] is True and "stopped" in into
    assert {call[1] for call in f.calls if call[0] == "ir1b"} == {"2"}


def test_successful_controls_only_report_is_valid_lf_only_json(tmp_path: Path):
    import json
    f = Fakes()
    report = {"experiment": "IR-1b frozen-58 (controls only)", "controls_only": True}
    rr.run_experiment(None, QUERIES, PLANS, *references(), f.conventional, f.frozen_ir1, f.ir1b_search,
                      into=report, controls_only=True)
    path = tmp_path / "controls.json"
    digest = rr.write_once(path, report)
    data = path.read_bytes()
    assert b"\r" not in data and digest == rr.sha(data)
    loaded = json.loads(data.decode("utf-8"))
    assert loaded["controls_only"] is True and set(loaded["conditions"]) == {"0", "1", "2"}
    assert all({"outcomes", "summary", "per_query"} <= set(c) for c in loaded["conditions"].values())


def test_full_mode_is_unchanged_and_schedules_all_15_runs():
    f = Fakes()
    result = rr.run_experiment(None, QUERIES, PLANS, *references(), f.conventional, f.frozen_ir1, f.ir1b_search)
    assert result["controls_only"] is False and list(result["conditions"]) == list(rr.CONDITION_IDS)
    assert {call[1] for call in f.calls if call[0] == "ir1b"} == set(rr.CONDITION_IDS) - {"0", "1"}
    assert "determinism" in result and "regressions_vs_0" in result


def test_command_line_option():
    parser = rr.build_parser()
    assert parser.parse_args(["--out", "x.json", "--controls-only"]).controls_only is True
    assert parser.parse_args(["--out", "x.json"]).controls_only is False


# --- query set guard and blind-set isolation ----------------------------------------------------

def test_query_set_must_be_exactly_the_frozen_58():
    queries, _ = load_queries()
    by_text = rr.frozen_plans_by_text(queries)
    assert len(by_text) == 58 and {p.request_id for p in by_text.values()} == rr.FROZEN_IDS
    with pytest.raises(ValueError, match="frozen 58"):
        rr.frozen_plans_by_text(queries + [Query("S01", "human", "vague_topic", "x", ["DOC"])])
    with pytest.raises(ValueError, match="frozen 58"):
        rr.frozen_plans_by_text(queries[:-1])


def test_no_blind_set_loading_path():
    source = Path(rr.__file__).read_text(encoding="utf-8")
    assert not any(token in source for token in ("S01", "S12", "blind", "sealed"))
    assert not any(q.startswith("S") for q in rr.FROZEN_IDS)
    assert all(not f.startswith(("eval/blind", "blind")) for f in rr.HASHED_FILES)
