"""Register validation without a database: bad values are reported, never raised or looped on."""

import csv
import shutil
from pathlib import Path

import pytest

from app.ingest.load_register import read_register, validate
from dcc_corpus import naming

CORPUS = Path(__file__).resolve().parent.parent / "corpus"
VOCAB = {
    "discipline": set(naming.DISCIPLINES), "doc_type": set(naming.DOC_TYPES),
    "stage": set(naming.STAGES), "status": set(naming.STATUSES),
}


def edit_csv(path: Path, change):
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    fields = list(rows[0])
    change(rows)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def set_wbs_parents(parents: dict[str, str]):
    def change(rows):
        for row in rows:
            if row["code"] in parents:
                row["parent_code"] = parents[row["code"]]
    return change


@pytest.fixture
def corpus_copy(tmp_path):
    target = tmp_path / "corpus"
    shutil.copytree(CORPUS, target)
    return target


def test_committed_register_is_valid():
    assert validate(read_register(CORPUS), CORPUS, VOCAB) == []


@pytest.mark.parametrize("csv_name, change, expected", [
    ("register/wbs.csv", set_wbs_parents({"410": "410"}), "WBS 410: parent chain loops back on itself"),
    ("register/wbs.csv", set_wbs_parents({"100": "200", "200": "100"}), "WBS 100: parent chain loops back on itself"),
    ("register/revision_status.csv", lambda rows: rows[0].update(effective_date="2025-13-40"), "invalid date"),
    ("register/revision_files.csv", lambda rows: rows[0].update(size_bytes="12kB"), "invalid size"),
    ("register/revision_files.csv", lambda rows: rows[0].update(copy_role="backup"), "copy role"),
    ("links.csv", lambda rows: rows[0].update(link_type="mentions"), "unknown link type"),
    ("links.csv", lambda rows: rows[0].update(provenance="guessed"), "unknown provenance"),
])
def test_bad_values_are_reported(corpus_copy, csv_name, change, expected):
    edit_csv(corpus_copy / csv_name, change)
    problems = validate(read_register(corpus_copy), corpus_copy, VOCAB)
    assert any(expected in p for p in problems), problems
