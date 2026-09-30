"""Evaluation runner tests. They never run the real query set: that is reserved for the frozen baseline run."""

from pathlib import Path

import pytest

from eval.run_eval import (Outcome, Query, QuerySetError, evaluate, known_doc_codes, load_queries,
                           markdown_report, summarise)

QUERIES = Path(__file__).resolve().parent.parent / "eval" / "queries"


def outcome(qid, category, rank, author="generated", expected_rev=None, matched_rev=None, named=None):
    exact = None if expected_rev is None or rank is None else matched_rev == expected_rev
    return Outcome(qid, author, category, "q", ["X"], expected_rev, rank, "X" if rank else None,
                   matched_rev, exact, named, [])


def test_committed_query_files_are_valid():
    queries, hashes = load_queries()
    assert set(hashes) == {"generated.yaml", "human.yaml"}
    generated = [q for q in queries if q.author == "generated"]
    assert len(generated) == 40
    assert {q.category for q in generated} == {
        "vague_topic", "partial_name", "old_revision", "cross_type", "date_anchored",
        "sender_anchored", "correct_not_latest", "related_chain", "status_anchored"}


@pytest.mark.parametrize("yaml_text, expected", [
    ("- {id: X1, author: robot, category: vague_topic, query: q, expected: [KVL-ADM-410-DR-S-0102]}", "author"),
    ("- {id: X1, author: human, category: guesswork, query: q, expected: [KVL-ADM-410-DR-S-0102]}", "unknown category"),
    ("- {id: X1, author: human, category: vague_topic, query: q, expected: [KVL-ADM-410-DR-S-9999]}", "unknown document"),
    ("- {id: X1, author: human, category: vague_topic, query: q, expected: [KVL-ADM-410-DR-S-0102], expected_rev: Z9}",
     "revision code"),
    ("- {id: X1, author: human, category: vague_topic, query: q, expected: [KVL-ADM-410-DR-S-0102], filters: {colour: red}}",
     "unknown filters"),
    ("- {id: X1, author: human, category: vague_topic, query: q, expected: [KVL-ADM-410-DR-S-0102]}\n"
     "- {id: X1, author: human, category: vague_topic, query: r, expected: [KVL-ADM-410-DR-S-0102]}", "duplicate"),
    ("- {id: X1, author: human, category: vague_topic, expected: [KVL-ADM-410-DR-S-0102]}", "missing"),
])
def test_invalid_queries_are_reported(tmp_path, yaml_text, expected):
    (tmp_path / "q.yaml").write_text(yaml_text, encoding="utf-8")
    with pytest.raises(QuerySetError) as error:
        load_queries(tmp_path, known_doc_codes())
    assert any(expected in p for p in error.value.problems), error.value.problems


def test_metrics():
    outcomes = [
        outcome("a", "vague_topic", 1),
        outcome("b", "vague_topic", 4),
        outcome("c", "old_revision", None, expected_rev="C01"),
        outcome("d", "old_revision", 2, expected_rev="C01", matched_rev="C02", named=True),
    ]
    s = summarise(outcomes)
    overall = s["overall"]
    assert (overall["hit@1"], overall["hit@3"], overall["hit@5"], overall["hit@10"]) == (0.25, 0.5, 0.75, 0.75)
    assert overall["mrr"] == round((1 + 1 / 4 + 1 / 2) / 4, 3)
    assert overall["rev"] == {"queries": 2, "found": 1, "exact": 0, "named": 1}
    assert s["by_category"]["vague_topic"]["hit@1"] == 0.5
    assert s["by_author"]["human"] == {"n": 0}


def test_markdown_report_lists_misses():
    outcomes = [outcome("a", "vague_topic", 1), outcome("b", "cross_type", None)]
    report = {"engine": "test", "created": "2026-01-01", "commit": None, "query_files": {"q.yaml": "0" * 64},
              "summary": summarise(outcomes), "outcomes": [o.__dict__ for o in outcomes]}
    text = markdown_report(report)
    assert "| **overall** | 2 | 0.50 |" in text
    assert "**b** (cross_type)" in text and "rank miss" in text


@pytest.mark.db
def test_evaluate_against_dev_data(data_conn):
    queries = [
        Query("T1", "generated", "partial_name", "pile schedule", ["KVL-ADM-410-SC-S-0003"]),
        Query("T2", "generated", "old_revision", "east abutment general arrangement",
              ["KVL-ADM-410-DR-S-0102"], expected_rev="C02"),
        Query("T3", "generated", "vague_topic", "zzzz qqqq", ["KVL-ADM-410-SC-S-0003"]),
    ]
    t1, t2, t3 = evaluate(data_conn, queries)
    assert t1.rank == 1 and t1.found == "KVL-ADM-410-SC-S-0003"
    assert t2.rank and t2.rev_named is True      # C02 is shown as latest for construction
    assert t3.rank is None and t3.rev_exact is None


def test_corpus_info_distinguishes_the_frozen_and_current_corpus():
    import json
    from eval.run_eval import CORPUS_FILES, REPORTS_DIR, corpus_info
    frozen = corpus_info(Path(__file__).resolve().parent.parent / "eval" / "frozen" / "corpus-v1",
                         {name: name.split("/")[-1] for name in CORPUS_FILES})
    assert (frozen["documents"], frozen["revisions"], frozen["files"]) == (47, 62, 64)
    first_run = json.loads((REPORTS_DIR / "baseline-fts-v1-2026-09-30.json").read_text(encoding="utf-8"))
    assert first_run["corpus"]["fingerprint"] == frozen["fingerprint"]

    current = corpus_info()
    assert current["documents"] == 100 and current["fingerprint"] != frozen["fingerprint"]


def test_comparison_names_both_runs_and_their_corpora():
    from eval.run_eval import compare
    outcomes = [outcome("a", "vague_topic", 1)]
    base = {"engine": "e", "created": "2026-01-01", "query_files": {"q.yaml": "0" * 64},
            "summary": summarise(outcomes), "outcomes": [o.__dict__ for o in outcomes]}
    small = {**base, "corpus": {"documents": 47, "revisions": 62, "files": 64, "fingerprint": "a" * 64}}
    large = {**base, "corpus": {"documents": 100, "revisions": 120, "files": 122, "fingerprint": "b" * 64}}
    text = compare(small, large, "run-47", "run-100")
    assert "**A** `run-47`: e, 2026-01-01, 47 documents" in text
    assert "**B** `run-100`: e, 2026-01-01, 100 documents" in text
    assert "Same queries: yes. Same corpus: no." in text
    assert "corpus not recorded" in compare(base, base)
