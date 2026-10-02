"""Equivalence check for search changes that must not change results.

    python -m eval.check_equivalence capture --db dev   --out golden-dev.json
    python -m eval.check_equivalence compare --db dev   --golden golden-dev.json
    python -m eval.check_equivalence capture --db bench --load-scale 2000 --out golden-bench.json

`capture` records the complete search response (results, order, evidence, locations and the
debug scores) for a fixed set of cases; `compare` re-runs the same cases and reports every
difference. Responses are compared as JSON with object keys sorted (key order carries no meaning);
everything else, including list order and score values, must be identical.

Cases: the 58 frozen evaluation queries with their filters, the 40 generic benchmark queries,
every benchmark filter on its own, each filter combined with three text queries, and edge cases.
Read-only, except --load-scale, which reloads the benchmark database (never the dev database).
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import yaml

from app.config import get_settings
from app.retrieval.base import Filters
from app.search import search
from eval.bench.run_bench import BENCH_DIR, Session, bench_database_url, keep_awake, load_scale, progress, spread
from eval.run_eval import load_queries

EDGE_CASES = [
    "",                                   # browse
    "the of and",                         # stop words only: no terms, trigram only
    "--",                                 # punctuation only
    "x",                                  # one character
    "contractor's question",              # apostrophe
    "back\\slash 'quoted' \"double\"",    # quoting characters
    "C02",                                # revision-like code
    "KVL-ADM-410",                        # code fragment
    "piles piles piles",                  # repeated term
    "retaning wal reinforcment",          # typos
    "a very long query about the soft clay found under the east abutment of the river bridge piles",
]


def _filters(spec: dict) -> Filters:
    return Filters(**{k: (date.fromisoformat(v) if k.startswith("date") and isinstance(v, str) else v)
                      for k, v in spec.items()})


def cases() -> list[tuple[str, str, Filters]]:
    workload = yaml.safe_load((BENCH_DIR / "workload.yaml").read_text(encoding="utf-8"))
    frozen, _ = load_queries()
    filters = [_filters(f) for f in workload["filters"]]
    texts = [q.query for q in frozen] + workload["generic_queries"]
    out = [(f"frozen {q.id}", q.query, _filters(q.filters)) for q in frozen]
    out += [(f"generic {i}", t, Filters()) for i, t in enumerate(workload["generic_queries"])]
    out += [(f"filter {i}", "", f) for i, f in enumerate(filters)]
    out += [(f"filter {i} + text {j}", t, f) for i, f in enumerate(filters) for j, t in enumerate(spread(texts, 3))]
    out += [(f"edge {i}", t, Filters()) for i, t in enumerate(EDGE_CASES)]
    return out


def run(session: Session) -> dict[str, dict]:
    out = {}
    all_cases = cases()
    for n, (case_id, text, f) in enumerate(all_cases, 1):
        response = session.call(search, text, f, debug=True)
        out[case_id] = {"query": text, "filters": {k: str(v) for k, v in f.active().items()},
                        "response": json.loads(response.model_dump_json())}
        if n % 25 == 0 or n == len(all_cases):
            progress(f"{n}/{len(all_cases)} cases")
    return out


def differences(a, b, path="") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        diffs = [f"{path}.{k}: only in {'golden' if k in a else 'new'}" for k in sorted(set(a) ^ set(b))]
        for k in sorted(set(a) & set(b)):
            diffs += differences(a[k], b[k], f"{path}.{k}")
        return diffs
    if isinstance(a, list) and isinstance(b, list):
        diffs = [f"{path}: length {len(a)} != {len(b)}"] if len(a) != len(b) else []
        for i, (x, y) in enumerate(zip(a, b)):
            diffs += differences(x, y, f"{path}[{i}]")
        return diffs
    return [] if a == b else [f"{path}: {a!r} != {b!r}"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["capture", "compare"])
    parser.add_argument("--db", choices=["dev", "bench"], required=True)
    parser.add_argument("--out", type=Path, help="capture: where to write the golden file")
    parser.add_argument("--golden", type=Path, help="compare: the golden file to compare against")
    parser.add_argument("--load-scale", type=int, help="bench only: reload the benchmark database at this scale first")
    args = parser.parse_args()
    keep_awake()

    if args.db == "dev":
        if args.load_scale:
            raise SystemExit("--load-scale is for the benchmark database only")
        url = get_settings().database_url
        if not url:
            raise SystemExit("DATABASE_URL is not set")
    else:
        url = bench_database_url()
    session = Session(url, stall_timeout=120)
    try:
        if args.load_scale:
            progress(f"loading the benchmark database at scale {args.load_scale}")
            session.call(load_scale, args.load_scale, timeout=3600, retry=False)
        counts = session.conn.execute("select (select count(*) from dcc.document), "
                                      "(select count(*) from dcc.search_entry)").fetchone()
        progress(f"{args.db} database: {counts[0]} documents, {counts[1]} index rows")
        responses = run(session)
    finally:
        session.close()

    if args.action == "capture":
        args.out.write_text(json.dumps({"db": args.db, "documents": counts[0], "index_rows": counts[1],
                                        "cases": responses}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"captured {len(responses)} cases to {args.out}")
        return

    golden = json.loads(args.golden.read_text(encoding="utf-8"))
    if (golden["documents"], golden["index_rows"]) != tuple(counts):
        raise SystemExit(f"the database changed since capture: {golden['documents']}/{golden['index_rows']} "
                         f"vs {counts[0]}/{counts[1]}")
    new = json.loads(json.dumps(responses, sort_keys=True))
    mismatched = {c: differences(golden["cases"][c], new.get(c)) for c in golden["cases"]}
    mismatched = {c: d for c, d in mismatched.items() if d}
    results = sum(len(v["response"]["results"]) for v in new.values())
    print(f"{len(golden['cases'])} cases, {results} results compared; {len(mismatched)} cases differ")
    for case_id, diffs in mismatched.items():
        print(f"- {case_id}: {len(diffs)} difference(s)")
        for d in diffs[:5]:
            print(f"    {d}")
    sys.exit(1 if mismatched else 0)


if __name__ == "__main__":
    main()
