"""Guard for the frozen evaluation baseline: the corpus may grow, but what the frozen queries were
judged against (eval/frozen/corpus-v1) and the query files themselves must never change."""

import csv
import hashlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FROZEN = ROOT / "eval" / "frozen"
CORPUS = ROOT / "corpus"
FROZEN_TABLES = sorted(p.name for p in (FROZEN / "corpus-v1").glob("*.csv"))


def rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def current_path(name: str) -> Path:
    return CORPUS / ("links.csv" if name == "links.csv" else f"register/{name}")


def test_frozen_snapshot_is_complete():
    assert FROZEN_TABLES == sorted([
        "documents.csv", "links.csv", "organisations.csv", "people.csv", "revision_files.csv",
        "revision_status.csv", "revisions.csv", "wbs.csv"])
    documents = rows(FROZEN / "corpus-v1" / "documents.csv")
    files = rows(FROZEN / "corpus-v1" / "revision_files.csv")
    assert (len(documents), len(rows(FROZEN / "corpus-v1" / "revisions.csv")), len(files)) == (47, 62, 64)


@pytest.mark.parametrize("name", FROZEN_TABLES)
def test_every_frozen_row_still_exists_unchanged(name):
    frozen = rows(FROZEN / "corpus-v1" / name)
    columns = list(frozen[0])
    current = {tuple(row.get(c) for c in columns) for row in rows(current_path(name))}
    missing = [row for row in frozen if tuple(row[c] for c in columns) not in current]
    assert not missing, f"{len(missing)} frozen row(s) in {name} changed or removed, e.g. {missing[0]}"


def test_frozen_files_keep_their_bytes():
    changed = []
    for row in rows(FROZEN / "corpus-v1" / "revision_files.csv"):
        path = CORPUS / row["storage_path"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            changed.append(row["storage_path"])
    assert not changed, f"frozen files changed or missing: {changed}"


def test_query_files_are_unchanged():
    for line in (FROZEN / "queries.sha256").read_text(encoding="utf-8").splitlines():
        expected, name = line.split(maxsplit=1)
        actual = hashlib.sha256((ROOT / "eval" / "queries" / name).read_bytes()).hexdigest()
        assert actual == expected, f"{name} has changed since it was frozen"
