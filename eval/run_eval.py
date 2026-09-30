"""Run the evaluation set through the same search path as the API and write a report.

    python -m eval.run_eval [--label NAME]
    python -m eval.run_eval --compare eval/reports/A.json eval/reports/B.json

Metrics are document-level hit@k and MRR, plus revision checks for queries with expected_rev.
Scores are never recorded: they aren't comparable between engines.
"""

import argparse
import csv
import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import psycopg
import yaml

from app.config import REPO_ROOT, get_settings
from app.retrieval.base import Filters
from app.search import RETRIEVER, search
from dcc_corpus import naming

QUERIES_DIR = REPO_ROOT / "eval" / "queries"
REPORTS_DIR = REPO_ROOT / "eval" / "reports"
DOCUMENTS_CSV = REPO_ROOT / "corpus" / "register" / "documents.csv"

AUTHORS = ("generated", "human")
CATEGORIES = ("vague_topic", "partial_name", "old_revision", "cross_type", "date_anchored",
              "sender_anchored", "correct_not_latest", "related_chain", "status_anchored")
K_VALUES = (1, 3, 5, 10)
FILTER_KEYS = set(Filters.__dataclass_fields__)


class QuerySetError(Exception):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__(f"{len(problems)} problem(s) in the query set:\n" + "\n".join(f"- {p}" for p in problems))


@dataclass
class Query:
    id: str
    author: str
    category: str
    query: str
    expected: list[str]
    expected_rev: str | None = None
    filters: dict = field(default_factory=dict)
    notes: str | None = None


@dataclass
class Outcome:
    id: str
    author: str
    category: str
    query: str
    expected: list[str]
    expected_rev: str | None
    rank: int | None                 # 1-based rank of the first expected document; None = not in top 10
    found: str | None                # the expected document that was found
    matched_rev: str | None
    rev_exact: bool | None           # None when the query has no expected_rev or the document wasn't found
    rev_named: bool | None
    top: list[str]                   # doc codes returned, in order


def known_doc_codes(documents_csv: Path = DOCUMENTS_CSV) -> set[str]:
    with open(documents_csv, encoding="utf-8", newline="") as f:
        return {row["doc_code"] for row in csv.DictReader(f)}


def load_queries(directory: Path = QUERIES_DIR, known_codes: set[str] | None = None) -> tuple[list[Query], dict[str, str]]:
    """All queries in directory/*.yaml, validated, plus a SHA-256 per file for traceability."""
    known_codes = known_doc_codes() if known_codes is None else known_codes
    queries: list[Query] = []
    hashes: dict[str, str] = {}
    problems: list[str] = []
    for path in sorted(directory.glob("*.yaml")):
        raw = path.read_bytes()
        hashes[path.name] = hashlib.sha256(raw).hexdigest()
        for item in yaml.safe_load(raw) or []:
            label = f"{path.name} {item.get('id', '?')}"
            missing = {"id", "author", "category", "query", "expected"} - set(item)
            unknown = set(item) - set(Query.__dataclass_fields__)
            if missing or unknown:
                problems.append(f"{label}: missing {sorted(missing)} / unknown {sorted(unknown)} fields")
                continue
            q = Query(**item)
            if q.author not in AUTHORS:
                problems.append(f"{label}: author must be one of {AUTHORS}")
            if q.category not in CATEGORIES:
                problems.append(f"{label}: unknown category {q.category}")
            if not q.query.strip():
                problems.append(f"{label}: empty query")
            if not q.expected:
                problems.append(f"{label}: expected is empty")
            problems += [f"{label}: unknown document {code}" for code in q.expected if code not in known_codes]
            if q.expected_rev:
                try:
                    naming.validate_rev(q.expected_rev)
                except ValueError as e:
                    problems.append(f"{label}: {e}")
            if set(q.filters) - FILTER_KEYS:
                problems.append(f"{label}: unknown filters {sorted(set(q.filters) - FILTER_KEYS)}")
            queries.append(q)
    seen: set[str] = set()
    for q in queries:
        if q.id in seen:
            problems.append(f"duplicate query id {q.id}")
        seen.add(q.id)
    if problems:
        raise QuerySetError(problems)
    return queries, hashes


def evaluate(conn: psycopg.Connection, queries: list[Query]) -> list[Outcome]:
    outcomes = []
    for q in queries:
        results = search(conn, q.query, Filters(**q.filters), limit=10).results
        top = [r.document.doc_code for r in results]
        rank = next((i for i, code in enumerate(top, 1) if code in q.expected), None)
        found = matched_rev = rev_exact = rev_named = None
        if rank:
            hit = results[rank - 1]
            found, matched_rev = hit.document.doc_code, hit.revision.rev_code
            if q.expected_rev:
                rev_exact = matched_rev == q.expected_rev
                shown = {matched_rev, hit.revision.latest_rev_code, *hit.revision.latest_by_use.values()}
                rev_named = q.expected_rev in shown
        outcomes.append(Outcome(q.id, q.author, q.category, q.query, q.expected, q.expected_rev,
                                rank, found, matched_rev, rev_exact, rev_named, top))
    return outcomes


def metrics(outcomes: list[Outcome]) -> dict:
    n = len(outcomes)
    if not n:
        return {"n": 0}
    result = {"n": n}
    for k in K_VALUES:
        result[f"hit@{k}"] = round(sum(1 for o in outcomes if o.rank and o.rank <= k) / n, 3)
    result["mrr"] = round(sum(1 / o.rank for o in outcomes if o.rank) / n, 3)
    with_rev = [o for o in outcomes if o.expected_rev]
    found_rev = [o for o in with_rev if o.rank]
    result["rev"] = {
        "queries": len(with_rev),
        "found": len(found_rev),
        "exact": sum(1 for o in found_rev if o.rev_exact),
        "named": sum(1 for o in found_rev if o.rev_named),
    }
    return result


def summarise(outcomes: list[Outcome]) -> dict:
    return {
        "overall": metrics(outcomes),
        "by_author": {a: metrics([o for o in outcomes if o.author == a]) for a in AUTHORS},
        "by_category": {c: metrics([o for o in outcomes if o.category == c]) for c in CATEGORIES},
    }


def _metric_row(name: str, m: dict) -> str:
    if not m.get("n"):
        return f"| {name} | 0 | | | | | | |"
    rev = m["rev"]
    rev_text = f"{rev['exact']}/{rev['named']} of {rev['found']} found ({rev['queries']})" if rev["queries"] else ""
    return (f"| {name} | {m['n']} | {m['hit@1']:.2f} | {m['hit@3']:.2f} | {m['hit@5']:.2f} | "
            f"{m['hit@10']:.2f} | {m['mrr']:.2f} | {rev_text} |")


def markdown_report(report: dict) -> str:
    header = "| | n | hit@1 | hit@3 | hit@5 | hit@10 | MRR | revision exact/named |\n|---|---|---|---|---|---|---|---|"
    s = report["summary"]
    lines = [
        f"# Evaluation report: {report['engine']}",
        "",
        f"- Date: {report['created']}  ",
        f"- Code commit: {report['commit'] or 'unknown'}  ",
        f"- Query files: " + ", ".join(f"`{name}` ({sha[:12]})" for name, sha in report["query_files"].items()),
        "",
        "## Summary",
        "",
        header,
        _metric_row("**overall**", s["overall"]),
        *[_metric_row(a, m) for a, m in s["by_author"].items()],
        "",
        "## By category",
        "",
        header,
        *[_metric_row(c, m) for c, m in s["by_category"].items()],
        "",
        "## Per query",
        "",
        "| id | category | query | expected | rank | revision |",
        "|---|---|---|---|---|---|",
    ]
    for o in report["outcomes"]:
        rev = ""
        if o["expected_rev"]:
            rev = (f"wanted {o['expected_rev']}, matched {o['matched_rev']}"
                   + (" (shown)" if o["rev_named"] else "") if o["rank"] else f"wanted {o['expected_rev']}")
        lines.append(f"| {o['id']} | {o['category']} | {o['query']} | {', '.join(o['expected'])} | "
                     f"{o['rank'] or 'miss'} | {rev} |")
    misses = [o for o in report["outcomes"] if not o["rank"] or o["rank"] > 3]
    lines += ["", "## Not in the top 3", ""]
    lines += [f"- **{o['id']}** ({o['category']}): \"{o['query']}\" - rank {o['rank'] or 'miss'}; "
              f"top 3 were {', '.join(o['top'][:3]) or 'nothing'}" for o in misses] or ["None."]
    return "\n".join(lines) + "\n"


def compare(a: dict, b: dict) -> str:
    """Markdown comparison of two reports (b relative to a)."""
    lines = [f"# {b['engine']} ({b['created']}) vs {a['engine']} ({a['created']})", "",
             "| | hit@1 | hit@3 | hit@10 | MRR |", "|---|---|---|---|---|"]
    groups = [("overall", a["summary"]["overall"], b["summary"]["overall"])]
    groups += [(c, a["summary"]["by_category"][c], b["summary"]["by_category"][c]) for c in CATEGORIES]
    for name, ma, mb in groups:
        if ma.get("n") and mb.get("n"):
            cells = [f"{mb[k]:.2f} ({mb[k] - ma[k]:+.2f})" for k in ("hit@1", "hit@3", "hit@10", "mrr")]
            lines.append(f"| {name} | " + " | ".join(cells) + " |")
    ranks_a = {o["id"]: o["rank"] for o in a["outcomes"]}
    changed = [(o["id"], ranks_a.get(o["id"]), o["rank"]) for o in b["outcomes"] if ranks_a.get(o["id"]) != o["rank"]]
    lines += ["", "## Rank changes", ""]
    lines += [f"- {qid}: {ra or 'miss'} -> {rb or 'miss'}" for qid, ra, rb in changed] or ["None."]
    return "\n".join(lines) + "\n"


def _commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              cwd=REPO_ROOT, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the DCC evaluation set.")
    parser.add_argument("--label", help="report name (default: <engine>-<date>)")
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("A.json", "B.json"))
    args = parser.parse_args()

    if args.compare:
        a, b = (json.loads(p.read_text(encoding="utf-8")) for p in args.compare)
        print(compare(a, b))
        return

    try:
        queries, hashes = load_queries()
    except QuerySetError as e:
        raise SystemExit(str(e)) from None
    database_url = get_settings().database_url
    if not database_url:
        raise SystemExit("DATABASE_URL is not set")
    with psycopg.connect(database_url, prepare_threshold=None) as conn:
        outcomes = evaluate(conn, queries)

    report = {
        "engine": RETRIEVER.name,
        "created": date.today().isoformat(),
        "commit": _commit(),
        "query_files": hashes,
        "summary": summarise(outcomes),
        "outcomes": [asdict(o) for o in outcomes],
    }
    label = args.label or f"{RETRIEVER.name}-{report['created']}"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / f"{label}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (REPORTS_DIR / f"{label}.md").write_text(markdown_report(report), encoding="utf-8")
    o = report["summary"]["overall"]
    print(f"{len(outcomes)} queries: hit@1 {o['hit@1']:.2f}, hit@3 {o['hit@3']:.2f}, hit@10 {o['hit@10']:.2f}, "
          f"MRR {o['mrr']:.2f}. Report: eval/reports/{label}.md")


if __name__ == "__main__":
    main()
