"""IR-1b against real SQL on the rolled-back synthetic register (no corpus document, no frozen query)."""

import pytest

from app.retrieval.base import Filters
from app.search import search
from eval.experiments import ir1_integration as ia
from eval.experiments import ir1b
from eval.experiments.ir1_engine import Switches
from tests.test_ir1_integration_db import mk_plan, reg  # noqa: F401  (synthetic register fixture)

pytestmark = pytest.mark.db

RELATION = {"link_type": "responds_to", "target_side": "from", "anchor_text": "pond outfall consent letter",
            "source": "letter"}


@pytest.mark.parametrize("raw, text, source", [("pond flow control drawing", "flow control", "pond"),
                                               ("WBS 320 outfall consent letter", "outfall consent", "WBS 320")])
def test_condition_2_response_equals_conventional_search(reg, raw, text, source):  # noqa: F811
    conn, _ = reg
    p = mk_plan(raw, text=text, clues=[{"field": "wbs", "code": "320", "strength": "confirmed", "source": source}])
    got = ir1b.search_ir1b(conn, p, ir1b.CONDITIONS["2"], "2", debug=True)
    assert ia.gate_a_view(got.response) == ia.gate_a_view(search(conn, raw, Filters(), debug=True))
    assert ia.gate_a_view(ir1b.baseline_response(conn, p, debug=True)) == ia.gate_a_view(got.response)
    assert got.response.engine == ir1b.ENGINE_LABEL and got.interpretation["lexical_query"] == raw


def test_condition_1_response_equals_frozen_ir1(reg):  # noqa: F811
    conn, _ = reg
    p = mk_plan("survey letter about the pond", text="survey pond",
                clues=[{"field": "discipline", "code": "D", "strength": "context", "source": "pond"},
                       {"field": "doc_type", "code": "LT", "strength": "likely", "source": "letter"}],
                relation=RELATION, revision_state="latest")
    got = ir1b.search_ir1b(conn, p, ir1b.CONDITIONS["1"], "1", debug=True)
    frozen = ia.search_ir1(conn, p, Switches(), debug=True)
    assert ia.gate_a_view(got.response) == ia.gate_a_view(frozen.response)
    assert got.interpretation["lexical_query"] == p.pool_text == "survey"


def test_additive_candidate_keeps_original_wording_and_adds_mechanisms(reg):  # noqa: F811
    conn, ids = reg
    p = mk_plan("the survey reply letter", text="survey",
                clues=[{"field": "doc_type", "code": "LT", "strength": "likely", "source": "letter"}],
                relation=RELATION, revision_state="latest")
    got = ir1b.search_ir1b(conn, p, ir1b.CONDITIONS["9"], "9", debug=True)
    assert got.response.query == "the survey reply letter" == got.interpretation["lexical_query"]
    first = got.response.results[0]
    assert first.document.id == ids["d4"] and any(e.kind == "related_document" for e in first.evidence)
    assert got.interpretation["config"]["delete"] is False and got.interpretation["deletion_fallback"] is False
    again = ir1b.search_ir1b(conn, p, ir1b.CONDITIONS["9r"], "9r", debug=True)
    assert ia.gate_a_view(again.response) == ia.gate_a_view(got.response)
