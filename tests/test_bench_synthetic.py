"""Synthetic benchmark records: deterministic, prefix-stable across scales, and valid for the schema."""

import csv
from collections import Counter
from pathlib import Path

import pytest

from dcc_corpus import naming
from eval.bench.synthetic import DOCS_PER_PROJECT, LATEST_DATE, generate

REAL_CODES = {row["doc_code"] for row in csv.DictReader(
    open(Path(__file__).resolve().parent.parent / "corpus" / "register" / "documents.csv", encoding="utf-8"))}
N = 2 * DOCS_PER_PROJECT + 100   # spans three projects


@pytest.fixture(scope="module")
def docs():
    return generate(N)


def fingerprint(documents):
    return [(d.doc_code, d.title, [(r["rev_code"], r["revision_date"], r["statuses"], r["segments"]) for r in d.revisions],
             d.links) for d in documents]


def test_deterministic_and_prefix_stable(docs):
    assert fingerprint(generate(N)) == fingerprint(docs)
    assert fingerprint(generate(500)) == fingerprint(docs[:500])   # a smaller scale is a prefix of a larger one


def test_codes_unique_and_distinct_from_the_real_corpus(docs):
    codes = [d.doc_code for d in docs]
    assert len(codes) == len(set(codes))
    assert not REAL_CODES & set(codes)
    assert {d.project for d in docs} == {"BRL", "CAL", "DUL"}


def test_revisions_statuses_and_files_are_valid(docs):
    paths = Counter()
    for d in docs:
        assert d.doc_type_code in naming.DOC_TYPES and d.discipline_code in naming.DISCIPLINES
        dates = [r["revision_date"] for r in d.revisions]
        assert dates == sorted(dates) and dates[-1] <= LATEST_DATE
        assert len({r["rev_code"] for r in d.revisions}) == len(d.revisions)
        for r in d.revisions:
            naming.validate_rev(r["rev_code"])
            for status, when in r["statuses"]:
                assert naming.status_allowed(d.doc_type_code, status), (d.doc_code, status)
                assert when >= r["revision_date"]
            assert 2 <= len(r["segments"]) <= 4
            paths[r["file"]["storage_path"]] += 1
    assert set(paths.values()) == {1}


def test_links_point_to_earlier_documents_in_the_same_project(docs):
    first = {d.doc_code: (d.project, d.revisions[0]["revision_date"]) for d in docs}
    links = [(d, link) for d in docs for link in d.links]
    assert links
    for d, link in links:
        project, when = first[link["to_doc_code"]]
        assert project == d.project and when < d.revisions[0]["revision_date"]


def test_register_shape_is_realistic(docs):
    revisions = sum(len(d.revisions) for d in docs)
    assert 1.2 <= revisions / len(docs) <= 1.4
    single_revision_types = {"LT", "RI", "MM", "CT"}
    assert all(len(d.revisions) == 1 for d in docs if d.doc_type_code in single_revision_types)
    minutes = [d for d in docs if d.project == "BRL" and d.doc_type_code == "MM"]
    assert [d.revisions[0]["revision_date"] for d in minutes] == sorted(d.revisions[0]["revision_date"] for d in minutes)
