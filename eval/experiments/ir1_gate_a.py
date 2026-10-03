"""IR-1 Gate A (preregistration section 10, item 2): default requests through the IR-1 integration
give 0 differences against conventional retrieval on the 189 cases of eval/check_equivalence.py.

    python -m eval.experiments.ir1_gate_a --db dev      # NOT run yet; needs explicit approval

Gate A only proves that the integration plumbing leaves ordinary conventional retrieval unchanged.
It is not an IR-1 effectiveness test and computes no metric.

Cases come from eval.check_equivalence.cases() unchanged. Two execution paths (harness only; no
IR-1 rule is changed):
- text-bearing cases: a default Stage-1 request (text = raw_text, no clues, relation or state) is
  validated by Stage 1, planned, and run through the full integration (ranking, Stage 2, response);
  the case's filters are conventional-only filters, never Stage-2 M1 filters;
- blank-query cases (browse/filter-only): Stage 1 rejects blank text, so no Plan is made and Stage 2
  is not called; the adapter's below-Stage-1 conventional_response is compared instead.

Each response is compared with app.search.search(conn, text, filters, debug=True) on the same
connection, as JSON, field by field (eval.check_equivalence.differences). The only field removed
is the response's `engine` label (ir1_integration.gate_a_view); the interpretation record is never
part of the response. The report holds case ids, paths and counts only, never response values.
"""

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field

from app.models import SearchResponse
from app.retrieval.base import Filters
from eval.check_equivalence import cases as equivalence_cases
from eval.check_equivalence import differences
from eval.experiments import ir1_integration as ia
from eval.experiments.ir1_engine import Switches
from eval.experiments.ir1_request import Plan, parse_request, plan

TEXT, BLANK = "text", "blank"


def category(text: str) -> str:
    return TEXT if text.strip() else BLANK


def default_plan(case_id: str, text: str) -> Plan:
    """A default request for a text-bearing case, built and validated by Stage 1 (blank text raises)."""
    request = parse_request({"id": case_id, "raw_text": text, "text": text, "clues": [],
                             "revision_state": "best_match", "document_state": "any",
                             "approx": [], "verify": [], "withdrawn": []})
    p = plan(request)
    if not p.is_default:
        raise AssertionError(f"{case_id}: a Gate A request must be a default request")
    return p


def harness_response(conn, case_id: str, text: str, filters: Filters, search_ir1=ia.search_ir1,
                     conventional_response=ia.conventional_response) -> SearchResponse:
    """The response the integration produces for one case, by its execution path."""
    if category(text) == TEXT:
        return search_ir1(conn, default_plan(case_id, text), Switches(), extra_filters=filters, debug=True).response
    return conventional_response(conn, text, filters, debug=True)


def compare(got: SearchResponse, expected: SearchResponse) -> list[str]:
    """Paths that differ between the two responses, after removing only the engine label."""
    a = json.loads(json.dumps(ia.gate_a_view(expected), sort_keys=True))
    b = json.loads(json.dumps(ia.gate_a_view(got), sort_keys=True))
    return [d.split(":")[0] for d in differences(a, b)]          # paths only, never values


@dataclass
class GateAReport:
    cases: int = 0
    by_category: Counter = field(default_factory=Counter)
    differing: dict[str, list[str]] = field(default_factory=dict)   # case id -> differing paths

    @property
    def passed(self) -> bool:
        return self.cases > 0 and not self.differing


def run_gate_a(conn, cases=None, search=None, **paths) -> GateAReport:
    """Every case: harness response vs conventional search on the same connection."""
    if search is None:
        from app.search import search                                    # imported only when run
    report = GateAReport()
    for case_id, text, filters in (equivalence_cases() if cases is None else cases):
        report.cases += 1
        report.by_category[category(text)] += 1
        diffs = compare(harness_response(conn, case_id, text, filters, **paths),
                        search(conn, text, filters, debug=True))
        if diffs:
            report.differing[case_id] = diffs
    return report


def main() -> None:                                                      # pragma: no cover - not run yet
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", choices=["dev"], required=True)
    parser.parse_args()
    import psycopg
    from app.config import get_settings
    url = get_settings().database_url
    if not url:
        raise SystemExit("DATABASE_URL is not set")
    with psycopg.connect(url, prepare_threshold=None) as conn:
        report = run_gate_a(conn)
    print(f"{report.cases} cases ({dict(report.by_category)}); {len(report.differing)} differ")
    for case_id, diffs in report.differing.items():
        print(f"- {case_id}: {len(diffs)} differing path(s): {', '.join(diffs[:5])}")
    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
