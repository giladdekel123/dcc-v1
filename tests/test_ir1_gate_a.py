"""Gate A harness tests. The real 189 cases are only counted and classified here, never executed;
end-to-end checks run on the rolled-back synthetic register from test_ir1_integration_db."""

from collections import Counter
from datetime import date

import pytest

from app.models import SearchResponse
from app.retrieval.base import Filters
from eval.check_equivalence import cases as equivalence_cases
from eval.experiments import ir1_gate_a as ga
from eval.experiments import ir1_integration as ia
from eval.experiments.ir1_engine import Switches
from eval.experiments.ir1_request import RequestError
from tests.test_ir1_integration import response_with
from tests.test_ir1_integration_db import reg  # noqa: F401  (synthetic register fixture)


# --- the 189 cases: source and classification only ---------------------------------------------

def test_the_189_cases_and_their_execution_paths():
    cases = equivalence_cases()
    assert len(cases) == 189 == len({c[0] for c in cases})
    family = lambda cid: "filter+text" if " + " in cid else cid.split(" ")[0]
    counts = Counter((family(cid), ga.category(text)) for cid, text, _ in cases)
    assert counts == {("frozen", "text"): 58, ("generic", "text"): 40, ("filter+text", "text"): 60,
                      ("edge", "text"): 10, ("filter", "blank"): 20, ("edge", "blank"): 1}
    assert Counter(ga.category(t) for _, t, _ in cases) == {"text": 168, "blank": 21}


# --- Stage-1 treatment ------------------------------------------------------------------------

def test_text_cases_become_validated_default_plans():
    p = ga.default_plan("generic 0", "pond flow control")
    assert p.is_default and p.pool_text == "pond flow control" and p.filters() == {}


@pytest.mark.parametrize("text", ["", "   ", "\t"])
def test_blank_cases_are_never_stage1_requests(text):
    assert ga.category(text) == ga.BLANK
    with pytest.raises(RequestError, match="empty or whitespace"):
        ga.default_plan("filter 0", text)


class Recorder:
    def __init__(self):
        self.calls = []

    def ir1(self, conn, plan_, switches, extra_filters, debug):
        self.calls.append(("ir1", plan_.audit.raw_text, switches, extra_filters, debug))
        return ia.IR1Response(response_with(ia.ENGINE_LABEL), {})

    def conventional(self, conn, text, filters, debug):
        self.calls.append(("conventional", text, filters, debug))
        return response_with(ia.ENGINE_LABEL)


def test_routing_text_through_ir1_and_blank_below_stage1(monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("blank cases must not plan or run Stage 2")

    rec = Recorder()
    f = Filters(wbs="320", date_from=date(2025, 1, 1))
    ga.harness_response(None, "filter 1 + text 0", "pond", f, search_ir1=rec.ir1,
                        conventional_response=rec.conventional)
    monkeypatch.setattr(ga, "plan", forbidden)
    monkeypatch.setattr(ga, "parse_request", forbidden)
    monkeypatch.setattr("eval.experiments.ir1_engine.run", forbidden)
    ga.harness_response(None, "filter 1", "", f, search_ir1=rec.ir1, conventional_response=rec.conventional)
    assert rec.calls == [("ir1", "pond", Switches(), f, True), ("conventional", "", f, True)]


# --- comparison -----------------------------------------------------------------------------

def test_comparison_removes_only_the_engine_label_and_reports_paths_not_values():
    base = response_with("baseline-fts-v1")
    assert ga.compare(response_with(ia.ENGINE_LABEL), base) == []
    changed = response_with(ia.ENGINE_LABEL)
    changed.results[0].debug = {"score": 1.5}
    changed.results[0].revision.rev_code = "P02"
    diffs = ga.compare(changed, base)
    assert diffs == [".results[0].debug.score", ".results[0].revision.rev_code"]
    assert not any("1.5" in d or "P02" in d for d in diffs)
    longer = SearchResponse(query="q", filters={}, engine="x", results=base.results * 2)
    assert ga.compare(longer, base) == [".results"]                          # length differs


def test_report_counts_and_failures_without_a_database():
    rec = Recorder()
    cases = [("generic 0", "pond", Filters()), ("filter 0", "", Filters(doc_type="LT"))]
    ok = ga.run_gate_a(None, cases, search=lambda c, t, f, debug: response_with("baseline-fts-v1"),
                       search_ir1=rec.ir1, conventional_response=rec.conventional)
    assert (ok.cases, dict(ok.by_category), ok.differing, ok.passed) == (2, {"text": 1, "blank": 1}, {}, True)

    def other(c, t, f, debug):
        r = response_with("baseline-fts-v1")
        r.results[0].revision.id = 99
        return r

    bad = ga.run_gate_a(None, cases, search=other, search_ir1=rec.ir1, conventional_response=rec.conventional)
    assert not bad.passed and set(bad.differing) == {"generic 0", "filter 0"}
    assert bad.differing["generic 0"] == [".results[0].revision.id"]
    assert not ga.run_gate_a(None, [], search=other).passed                  # no cases is not a pass


# --- end to end on the synthetic register (not Gate A) ----------------------------------------

SYNTHETIC_CASES = [
    ("generic a", "pond flow control", Filters()),
    ("generic b", "outfall consent letter", Filters()),
    ("filter+text", "pond culvert", Filters(wbs="300")),
    ("filter+text date", "pond", Filters(date_from=date(2025, 1, 1))),
    ("edge stopwords", "the of and", Filters()),
    ("edge punctuation", "--", Filters()),
    ("edge typo", "outfal consnt", Filters()),
    ("browse", "", Filters()),
    ("filter only", "", Filters(doc_type="LT")),
    ("filter only wbs", "", Filters(wbs="320")),
]


@pytest.mark.db
def test_harness_passes_on_the_synthetic_register(reg):  # noqa: F811
    conn, _ = reg
    report = ga.run_gate_a(conn, SYNTHETIC_CASES)
    assert report.cases == 10 and dict(report.by_category) == {"text": 7, "blank": 3}
    assert report.differing == {} and report.passed


@pytest.mark.db
def test_harness_detects_a_real_difference_on_the_synthetic_register(reg):  # noqa: F811
    conn, _ = reg

    def shifted(conn_, text, filters, debug):                          # conventional, one revision changed
        from app.search import search
        r = search(conn_, text, filters, debug=debug)
        if r.results:
            r.results[0].revision.rev_code = "Z99"
        return r

    report = ga.run_gate_a(conn, SYNTHETIC_CASES[:1], search=shifted)
    assert report.differing == {"generic a": [".results[0].revision.rev_code"]}


@pytest.mark.db
def test_blank_conventional_response_equals_search(reg):  # noqa: F811
    from app.search import search
    conn, _ = reg
    for filters in (Filters(), Filters(doc_type="LT"), Filters(stage="CN")):
        got = ia.conventional_response(conn, "", filters, debug=True)
        assert ga.compare(got, search(conn, "", filters, debug=True)) == []
