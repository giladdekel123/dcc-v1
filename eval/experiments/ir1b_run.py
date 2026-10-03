"""IR-1b evaluation runner: the 15 preregistered runs on the frozen 58 (IR1B_PREREGISTRATION.md,
IR1B_CLARIFICATIONS.md).

    python -m eval.experiments.ir1b_run --controls-only --out eval/experiments/reports/ir1b-controls-<date>.json
    python -m eval.experiments.ir1b_run --out eval/experiments/reports/ir1b-frozen58-<date>.json

--controls-only runs conditions 0, 1 and 2, checks them and stops: it stays before the IR-1b
observation boundary. A full run crosses that boundary and needs explicit approval.

Dispatch (preregistration section 4):
- condition 0: ordinary conventional search, app.search.search, as eval/run_eval.py runs it;
- condition 1: the frozen IR-1 path, ir1_integration.search_ir1 with full Switches(), an independent
  historical reference (not IR-1b code imitating IR-1);
- conditions 2-13 and 9r: ir1b.search_ir1b with the preregistered config.

Every condition is scored by eval/run_eval.py's evaluate and summarise, unchanged. The controls run
first (0, 1, 2) and are enforced before any non-control condition runs:
- 0 must reproduce the frozen baseline report outcome for outcome;
- 1 must reproduce the recorded frozen IR-1 result: outcomes and response hashes;
- 2 must equal 0: outcomes, and responses compared without the engine label.
9 and 9r must be identical (outcomes and response hashes). A failed control stops the run; the raw
file records the failure. Output is written once, LF only, and is never overwritten.
"""

import argparse
import datetime
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

import eval.run_eval as run_eval
from app.config import REPO_ROOT
from eval.experiments import ir1_integration as ia
from eval.experiments import ir1b
from eval.experiments.ir1_engine import Switches
from eval.experiments.ir1_request import load_frozen_requests, plan_all

CONDITION_IDS = ("0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "9r")
CONTROLS = ("0", "1", "2")
FROZEN_IDS = frozenset([f"G{i:03d}" for i in range(1, 41)] + [f"H{i:03d}" for i in range(1, 19)])
BASELINE_REPORT = "eval/reports/baseline-fts-v1-2026-09-30-corpus-v2.json"
IR1_RESULT = "eval/experiments/reports/ir1-frozen58-2026-10-03.json"
HASHED_FILES = (
    "eval/experiments/IR1_PREREGISTRATION.md", "eval/experiments/IR1_CLARIFICATIONS.md",
    "eval/experiments/IR1_STAGE2_CLARIFICATIONS.md", "eval/experiments/IR1_STAGE2_ABLATION_ADDENDUM.md",
    "eval/experiments/IR1B_PREREGISTRATION.md", "eval/experiments/IR1B_CLARIFICATIONS.md",
    "eval/experiments/ir1_frozen58_annotations.yaml", "eval/experiments/ir1_request.py",
    "eval/experiments/ir1_engine.py", "eval/experiments/ir1_integration.py", "eval/experiments/ir1b.py",
    "eval/experiments/ir1b_run.py", "eval/queries/generated.yaml", "eval/queries/human.yaml",
    BASELINE_REPORT, IR1_RESULT,
)
# IR1B_CLARIFICATIONS.md: targeted classes and the measure each uses.
CLASSES = {"relationship_chain": ("rank", ("G016", "G018", "G019", "G026", "G032")),
           "supersession": ("rank", ("G031", "H017")),
           "requested_revision": ("revision", ("G012", "G015", "G029", "H008")),
           "soft_clue": ("rank", ("H006",))}


class ControlFailure(RuntimeError):
    """A preregistered control did not reproduce; the run stops."""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dispatch_kind(condition: str) -> str:
    if condition not in CONDITION_IDS:
        raise KeyError(condition)
    return {"0": "conventional", "1": "frozen_ir1"}.get(condition, "ir1b")


def condition_definitions() -> dict:
    out = {}
    for c in CONDITION_IDS:
        kind = dispatch_kind(c)
        config = None if kind != "ir1b" else asdict(ir1b.CONDITIONS[c])
        out[c] = {"name": ir1b.NAMES[c], "dispatch": kind, "config": config,
                  "switches": asdict(Switches()) if kind == "frozen_ir1" else None}
    return out


def response_hashes(response) -> tuple[str, str]:
    """The full response hash and the hash of the response without its engine label."""
    view = json.dumps(ia.gate_a_view(response), sort_keys=True, ensure_ascii=False)
    return sha(response.model_dump_json().encode()), sha(view.encode())


def make_search(condition: str, plans_by_text: dict, per_query: dict, conventional: Callable,
                frozen_ir1: Callable, ir1b_search: Callable) -> Callable:
    """A search function for run_eval.evaluate that routes this condition and records each response."""
    kind = dispatch_kind(condition)

    def search(conn, query, filters, limit=10):
        if filters.active() or limit != 10:
            raise ValueError("frozen-58 queries carry no filters and are evaluated at limit 10")
        p = plans_by_text[query]
        if kind == "conventional":
            response, record = conventional(conn, query, filters, limit=limit), None
        elif kind == "frozen_ir1":
            r = frozen_ir1(conn, p, Switches())
            response, record = r.response, r.interpretation
        else:
            r = ir1b_search(conn, p, ir1b.CONDITIONS[condition], condition)
            response, record = r.response, r.interpretation
        full, view = response_hashes(response)
        per_query[p.request_id] = {"response_sha256": full, "response_without_engine_sha256": view,
                                   "interpretation": record}
        return response
    return search


@contextmanager
def evaluated_with(search):
    """run_eval.evaluate calls the module's `search`; swap it for the duration of one condition."""
    real = run_eval.search
    run_eval.search = search
    try:
        yield
    finally:
        run_eval.search = real


def run_condition(conn, condition, queries, plans_by_text, conventional, frozen_ir1, ir1b_search) -> dict:
    per_query: dict = {}
    with evaluated_with(make_search(condition, plans_by_text, per_query, conventional, frozen_ir1, ir1b_search)):
        outcomes = run_eval.evaluate(conn, queries)
    return {"outcomes": [asdict(o) for o in outcomes], "summary": run_eval.summarise(outcomes),
            "per_query": per_query}


def outcome_differences(a: list[dict], b: list[dict]) -> list[str]:
    """Query ids whose outcome records differ in any field (or that are missing on one side)."""
    da, db = {o["id"]: o for o in a}, {o["id"]: o for o in b}
    return sorted(q for q in da.keys() | db.keys() if da.get(q) != db.get(q))


def hash_differences(a: dict, b: dict, key: str) -> list[str]:
    return sorted(q for q in a.keys() | b.keys() if (a.get(q) or {}).get(key) != (b.get(q) or {}).get(key))


def check_controls(conditions: dict, baseline_outcomes: list[dict], ir1_outcomes: list[dict],
                   ir1_response_hashes: dict) -> dict:
    """Preregistration section 11, criteria 1-2, plus the baseline reproduction (condition 0)."""
    c0, c1, c2 = conditions["0"], conditions["1"], conditions["2"]
    checks = {
        "0_reproduces_frozen_baseline": outcome_differences(c0["outcomes"], baseline_outcomes),
        "1_reproduces_recorded_ir1_outcomes": outcome_differences(c1["outcomes"], ir1_outcomes),
        "1_reproduces_recorded_ir1_responses": hash_differences(
            c1["per_query"], {q: {"response_sha256": h} for q, h in ir1_response_hashes.items()}, "response_sha256"),
        "2_equals_0_outcomes": outcome_differences(c2["outcomes"], c0["outcomes"]),
        "2_equals_0_responses": hash_differences(c2["per_query"], c0["per_query"], "response_without_engine_sha256"),
    }
    return {"passed": not any(checks.values()), "differing_queries": checks}


def check_determinism(conditions: dict) -> dict:
    c9, c9r = conditions["9"], conditions["9r"]
    checks = {"outcomes": outcome_differences(c9["outcomes"], c9r["outcomes"]),
              "responses": hash_differences(c9["per_query"], c9r["per_query"], "response_sha256")}
    return {"passed": not any(checks.values()), "differing_queries": checks}


def regressions(baseline: list[dict], outcomes: list[dict]) -> dict:
    """Preregistration section 10, relative to condition 0."""
    b = {o["id"]: o for o in baseline}
    moved, revs, left = [], [], []
    for o in outcomes:
        base = b[o["id"]]
        if base["rank"] == 1 and (o["rank"] is None or o["rank"] > 1):
            moved.append({"id": o["id"], "baseline_rank": 1, "rank": o["rank"]})
        if base["rev_exact"] is True and o["rev_exact"] is not True:
            revs.append({"id": o["id"], "baseline_rev": base["matched_rev"], "matched_rev": o["matched_rev"]})
        if base["rank"] is not None and o["rank"] is None:
            left.append({"id": o["id"], "baseline_rank": base["rank"]})
    return {"baseline_rank1_moved_down": moved, "exact_revision_regressions": revs, "left_top10": left}


def class_movement(baseline: list[dict], outcomes: list[dict]) -> dict:
    """IR1B_CLARIFICATIONS.md: per-query movement and whether each targeted class improved."""
    b, n = {o["id"]: o for o in baseline}, {o["id"]: o for o in outcomes}
    rank = lambda r: 11 if r is None else r                  # outside the top 10 is worse than any rank
    out = {}
    for name, (measure, ids) in CLASSES.items():
        moves = {}
        for q in ids:
            if measure == "rank":
                old, new = rank(b[q]["rank"]), rank(n[q]["rank"])
                moves[q] = "improves" if new < old else "worsens" if new > old else "unchanged"
            else:
                old, new = b[q]["rev_exact"] is True, n[q]["rev_exact"] is True
                moves[q] = "improves" if new and not old else "worsens" if old and not new else "unchanged"
        out[name] = {"measure": measure, "queries": moves,
                     "improved": "improves" in moves.values() and "worsens" not in moves.values()}
    return out


def frozen_plans_by_text(queries) -> dict:
    """The frozen plans keyed by query text; the query set must be exactly the frozen 58."""
    if {q.id for q in queries} != FROZEN_IDS or len(queries) != 58:
        raise ValueError("the query set is not exactly the frozen 58 (G001-G040, H001-H018)")
    plans = {p.request_id: p for p in plan_all(load_frozen_requests())}
    if set(plans) != FROZEN_IDS:
        raise ValueError("the frozen plans are not exactly the frozen 58")
    by_text = {}
    for q in queries:
        if q.filters or plans[q.id].audit.raw_text != q.query:
            raise ValueError(f"{q.id}: query text or filters do not match the frozen request")
        by_text[q.query] = plans[q.id]
    if len(by_text) != 58:
        raise ValueError("query texts are not unique")
    return by_text


def run_experiment(conn, queries, plans_by_text: dict, baseline_outcomes: list[dict], ir1_outcomes: list[dict],
                   ir1_response_hashes: dict, conventional: Callable, frozen_ir1: Callable = ia.search_ir1,
                   ir1b_search: Callable = ir1b.search_ir1b, progress: Callable = lambda msg: None,
                   into: dict | None = None, controls_only: bool = False) -> dict:
    """Controls first and enforced; then the non-control conditions; then determinism and regressions.
    Results accumulate in `into` (if given), so a stopped run still records what ran. With
    `controls_only`, the run stops after the control checks: no non-control condition runs, so the run
    stays before the IR-1b observation boundary (preregistration section 13)."""
    conditions: dict = {}
    result = {} if into is None else into
    result["controls_only"] = controls_only
    result["conditions"] = conditions
    for c in CONTROLS:
        conditions[c] = run_condition(conn, c, queries, plans_by_text, conventional, frozen_ir1, ir1b_search)
        progress(f"condition {c}: {len(conditions[c]['outcomes'])} queries")
    result["controls"] = check_controls(conditions, baseline_outcomes, ir1_outcomes, ir1_response_hashes)
    if not result["controls"]["passed"]:
        result["stopped"] = "control failure: no non-control condition was run"
        raise ControlFailure(json.dumps(result["controls"]["differing_queries"]))
    if controls_only:
        return result
    for c in CONDITION_IDS:
        if c not in conditions:
            conditions[c] = run_condition(conn, c, queries, plans_by_text, conventional, frozen_ir1, ir1b_search)
            progress(f"condition {c}: {len(conditions[c]['outcomes'])} queries")
    result["determinism"] = check_determinism(conditions)
    base = conditions["0"]["outcomes"]
    result["regressions_vs_0"] = {c: regressions(base, conditions[c]["outcomes"]) for c in CONDITION_IDS if c != "0"}
    class_ids = {q for _, ids in CLASSES.values() for q in ids}
    if class_ids <= {o["id"] for o in base}:                  # always so for the frozen 58
        result["targeted_classes_vs_0"] = {c: class_movement(base, conditions[c]["outcomes"])
                                           for c in CONDITION_IDS if c != "0"}
    else:
        result["targeted_classes_vs_0"] = "not applicable: the query set lacks the targeted-class queries"
    return result


def serialize(report: dict) -> bytes:
    """Deterministic UTF-8 JSON with LF line endings only."""
    return (json.dumps(report, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def write_once(path: Path, report: dict) -> str:
    """Write the raw result exactly once (LF bytes, no newline translation); returns its sha256."""
    data = serialize(report)
    with open(path, "xb") as f:                       # binary + exclusive: no CRLF, never overwrite
        f.write(data)
    return sha(data)


def provenance(argv: list[str]) -> dict:
    git = lambda *a: subprocess.run(["git", *a], capture_output=True, text=True, cwd=REPO_ROOT,
                                    check=True).stdout.strip()
    return {"commit": git("rev-parse", "HEAD"), "git_status_porcelain": git("status", "--porcelain"),
            "command": " ".join([Path(sys.executable).name, "-m", "eval.experiments.ir1b_run", *argv]),
            "files_sha256": {f: sha((REPO_ROOT / f).read_bytes()) for f in HASHED_FILES},
            "corpus": run_eval.corpus_info()}


def load_references() -> tuple[list[dict], list[dict], dict]:
    baseline = json.loads((REPO_ROOT / BASELINE_REPORT).read_text(encoding="utf-8"))["outcomes"]
    ir1 = json.loads((REPO_ROOT / IR1_RESULT).read_text(encoding="utf-8"))["conditions"]["ir1_full"]
    return baseline, ir1["outcomes"], {q: v["response_sha256"] for q, v in ir1["per_query"].items()}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--controls-only", action="store_true",
                        help="run only the controls (0, 1, 2) and stop before the IR-1b observation boundary")
    return parser


def main() -> None:                                                       # pragma: no cover - not run yet
    args = build_parser().parse_args()
    out = args.out if args.out.is_absolute() else REPO_ROOT / args.out
    if out.exists():
        raise SystemExit(f"{out} exists; raw results are never overwritten")
    import psycopg
    from app.config import get_settings
    from app.search import search
    from eval.bench.run_bench import keep_awake
    keep_awake()
    report = {"experiment": "IR-1b frozen-58" + (" (controls only)" if args.controls_only else ""),
              "started_utc": _now(), **provenance(sys.argv[1:]), "condition_definitions": condition_definitions(),
              "controls_only": args.controls_only}
    queries, report["query_files"] = run_eval.load_queries()
    plans_by_text = frozen_plans_by_text(queries)
    baseline, ir1_outcomes, ir1_hashes = load_references()
    try:
        with psycopg.connect(get_settings().database_url, prepare_threshold=None) as conn:
            run_experiment(conn, queries, plans_by_text, baseline, ir1_outcomes, ir1_hashes, search,
                           progress=lambda m: print(m, flush=True), into=report,
                           controls_only=args.controls_only)
    except ControlFailure:
        raise                                                   # report["stopped"] and controls already set
    except Exception as e:
        report["error"] = f"{type(e).__name__}: {e}"
        raise
    finally:
        report["finished_utc"] = _now()
        print(f"raw results: {out} sha256 {write_once(out, report)}", flush=True)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


if __name__ == "__main__":
    main()
