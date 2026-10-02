"""Experiment 2C: two-stage ranking against the current ranking. Evaluation only.

    python -m eval.experiments.two_stage profile --load-scale 10000      # phase 0: cost profile
    python -m eval.experiments.two_stage check-dev                       # every arm == current on dev
    python -m eval.experiments.two_stage run --stage1 ts_rank --label two-stage-10k
    python -m eval.experiments.two_stage run --stage1 cov_ts_rank,cov_rank_cd --limits 1000,2000,4000 \
        --label two-stage-v2-40k                                       # 2C-v2

Two-stage ranking (experimental, not used by the app): stage 1 keeps the top N full-text matches
by a cheap score; every trigram (spelling) candidate is kept as well; stage 2 is today's exact
score, collapse and top 10 on those candidates. The SQL is built from the retriever's RANK_SQL, so
stage 2 is the current scoring unchanged and N >= matches gives exactly the current result.

Design, arms and decision criteria were fixed before running (see the session notes / report).
Frozen queries and ground truth are used unchanged; nothing is tuned on the results.
"""

import argparse
import hashlib
import json
import re
import statistics
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import psycopg

import eval.run_eval as run_eval
from app.config import REPO_ROOT, get_settings
from app.evidence.builder import build_result
from app.evidence.facts import load_facts
from app.models import SearchResponse
from app.retrieval import baseline_fts
from app.retrieval.base import Filters, RawMatch
from app.search import MAX_RESULTS
from eval.bench.run_bench import Session, bench_database_url, keep_awake, load_scale, percentile, progress
from eval.check_equivalence import cases as equivalence_cases

REPORTS = REPO_ROOT / "eval" / "experiments" / "reports"
LIMITS = [250, 500, 1000, 2000]                    # 2C-v1; 2C-v2 uses --limits 1000,2000,4000
WEIGHTS = "'{{0.1, 0.2, 0.4, 1.0}}'"               # doubled braces: the SQL goes through str.format
# The final score's own coverage and full-text rank expressions (as in RANK_SQL).
_COVERAGE = ("coalesce((select count(*) from unnest((select term_queries from q)) t where e.tsv @@ t)::float"
             " / nullif(cardinality((select terms from q)), 0), 0)")
_RANK_CD = f"coalesce(ts_rank_cd({WEIGHTS}, e.tsv, (select tsq from q), 32), 0)"
STAGE1 = {                                         # stage-1 ORDER BY (ties: revision id)
    # 2C-v1 shortlist, chosen by cost alone in phase 0
    "ts_rank": f"ts_rank({WEIGHTS}, e.tsv, (select tsq from q)) desc",
    "term_count": "(select count(*) from unnest((select term_queries from q)) t where e.tsv @@ t) desc",
    # 2C-v2: aligned with the final score, which coverage dominates
    "cov_ts_rank": f"{_COVERAGE} desc, ts_rank({WEIGHTS}, e.tsv, (select tsq from q)) desc",   # A
    "cov_rank_cd": f"{_COVERAGE} + {_RANK_CD} desc",                                           # B
}
ARMS: list[str] = []                               # set by set_arms()
ARM_SPEC: dict[str, tuple[str, int]] = {}          # arm -> (stage 1, limit)
ARM_SQLS: dict[str, str] = {}                      # stage 1 -> SQL
TIMING_RUNS = 3

# The ranking this experiment was designed and run against: the change-set-2 RANK_SQL (b7a0878;
# reports record its hash 5a46199225a937f9). Pinned here because change set 3 replaced it in the app
# with arm A of this experiment at N=2000; "current" below means this exhaustive ranking.
RANK_SQL = """
with q as materialized (
  select terms, terms::tsquery[] as term_queries,
         nullif(array_to_string(terms, ' | '), '') as tsq_text,
         nullif(array_to_string(terms, ' | '), '')::tsquery as tsq
  from (select array(select '''' || replace(replace(lexeme, '\\', '\\\\'), '''', '''''') || ''''
                     from unnest(tsvector_to_array(to_tsvector('english', %(q)s))) with ordinality as t(lexeme, n)
                     order by n) as terms) quoted
),
scored as materialized (
  select e.revision_id, e.document_id, r.revision_date, r.rev_code,
         coalesce((select count(*) from unnest((select term_queries from q)) t where e.tsv @@ t)::float
                  / nullif(cardinality((select terms from q)), 0), 0) as coverage,
         coalesce(ts_rank_cd('{{0.1, 0.2, 0.4, 1.0}}', e.tsv, (select tsq from q), 32), 0) as fts_rank,
         case when %(q)s = '' then 0 else extensions.word_similarity(%(q)s, e.trgm_text) end as trigram
  from dcc.search_entry e
  join dcc.revision r on r.id = e.revision_id
  join dcc.document d on d.id = e.document_id
  where {filters}
    and (%(browse)s
         or e.tsv @@ (select tsq from q)
         or %(q)s operator(extensions.<%%) e.trgm_text)
),
ranked as (
  select *, coverage + fts_rank + 0.5 * trigram as score,
         row_number() over (partition by document_id
                            order by coverage + fts_rank + 0.5 * trigram desc,
                                     revision_date desc, dcc.rev_code_rank(rev_code) desc) as pos_in_document
  from scored
  where %(browse)s or coverage > 0 or trigram >= %(trigram_min)s
)
select revision_id, document_id, score, coverage, fts_rank, trigram, (select tsq_text from q) as tsq
from ranked
where pos_in_document = 1
order by score desc, revision_date desc, document_id
limit %(limit)s
"""
_Q_END = RANK_SQL.index("),\nscored as") + 3       # end of the `q` CTE
_JOINS = """from dcc.search_entry e
  join dcc.revision r on r.id = e.revision_id
  join dcc.document d on d.id = e.document_id"""
_CANDIDATE_WHERE = """  where {filters}
    and (%(browse)s
         or e.tsv @@ (select tsq from q)
         or %(q)s operator(extensions.<%%) e.trgm_text)"""


def _replace_once(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, f"expected exactly one occurrence of: {old[:60]!r}"
    return text.replace(old, new)


def two_stage_sql(stage1: str) -> str:
    """RANK_SQL with scoring restricted to stage-1 candidates (top N matches + all trigram candidates)."""
    q_end = _Q_END
    stages = f"""first_stage as (
  select e.revision_id
  {_JOINS}
  where {{filters}} and e.tsv @@ (select tsq from q)
  order by {STAGE1[stage1]}, e.revision_id
  limit %(stage1_limit)s
),
candidates as (
  select revision_id from first_stage
  union
  select e.revision_id
  {_JOINS}
  where {{filters}} and %(q)s operator(extensions.<%%) e.trgm_text
),
"""
    sql = RANK_SQL[:q_end] + stages + RANK_SQL[q_end:]
    sql = _replace_once(sql, f"  {_JOINS}\n{_CANDIDATE_WHERE}",
                        "  from candidates c\n  join dcc.search_entry e on e.revision_id = c.revision_id\n"
                        "  join dcc.revision r on r.id = e.revision_id\n  join dcc.document d on d.id = e.document_id")
    return sql


def _between(sql: str, start: str, end: str, new: str) -> str:
    i = sql.index(start) + len(start)
    j = sql.index(end, i)
    return sql[:i] + new + sql[j:]


PROFILE_VARIANTS = {
    "full": RANK_SQL,
    "no_coverage": _between(RANK_SQL, "r.rev_code,\n", " as coverage", "         0::float"),
    "no_fts_rank": _between(RANK_SQL, "as coverage,\n", " as fts_rank", "         0::float"),
    "no_trigram": _between(RANK_SQL, "as fts_rank,\n", " as trigram", "         0::real"),
    "no_collapse": _between(RANK_SQL, "as score,\n", " as pos_in_document", "         1"),
    "matches_only": RANK_SQL[:_Q_END]
    + f"m as (select e.revision_id\n  {_JOINS}\n{_CANDIDATE_WHERE})\nselect count(*) from m",
}
for _name, _expr in STAGE1.items():
    PROFILE_VARIANTS[f"stage1_{_name}_1000"] = (
        two_stage_sql(_name)[:two_stage_sql(_name).index("candidates as (")].rstrip().rstrip(",")
        + "\nselect count(*) from first_stage")


# ---------------------------------------------------------------------------------------------

def set_arms(stage1s: list[str], limits: list[int]) -> None:
    """Arms: current, then every stage 1 x limit ("N=1000" when there is a single stage 1)."""
    ARMS[:] = ["current"]
    ARM_SPEC.clear()
    ARM_SQLS.clear()
    for stage1 in stage1s:
        ARM_SQLS[stage1] = two_stage_sql(stage1)
        for n in limits:
            arm = f"N={n}" if len(stage1s) == 1 else f"{stage1} N={n}"
            ARMS.append(arm)
            ARM_SPEC[arm] = (stage1, n)


def params(text: str, f: Filters, arm: str) -> tuple[str, dict]:
    _, p = baseline_fts.ranking_query(text, f, MAX_RESULTS)
    active = f.active()
    where = " and ".join(baseline_fts.FILTER_SQL[k] for k in active) or "true"
    if arm == "current":
        return RANK_SQL.format(filters=where), p
    stage1, n = ARM_SPEC[arm]
    return ARM_SQLS[stage1].format(filters=where), {**p, "stage1_limit": n}


def rank(conn, text: str, f: Filters, arm: str) -> list[tuple]:
    sql, p = params(text, f, arm)
    conn.execute(baseline_fts.SET_TRIGRAM_THRESHOLD_SQL, (str(baseline_fts.TRIGRAM_CANDIDATE_MIN),))
    return conn.execute(sql, p).fetchall()


def server_ms(conn, sql: str, p: dict) -> float:
    conn.execute(baseline_fts.SET_TRIGRAM_THRESHOLD_SQL, (str(baseline_fts.TRIGRAM_CANDIDATE_MIN),))
    plan = conn.execute("explain (analyze, timing off, format json) " + sql, p).fetchone()[0][0]
    return plan["Execution Time"]


def search_with(arm: str):
    """app.search.search with the arm's ranking; evidence and facts exactly as the app builds them."""
    retriever = baseline_fts.BaselineFtsRetriever()

    def search(conn, query, filters, limit=MAX_RESULTS, debug=False):
        query = query.strip()
        rows = rank(conn, query, filters, arm)[:min(limit, MAX_RESULTS)]
        matches = [RawMatch(rid, did, scores={"score": round(s, 4)}) for rid, did, s, *_ in rows]
        if query and rows:
            tsq = rows[0][6]
            fields, passages = retriever._evidence(conn, [m.revision_id for m in matches], tsq)
            for match, row in zip(matches, rows):
                match.field_hits = retriever._field_hits(fields.get(match.revision_id, []), trigram=row[5])
                match.snippets = passages.get(match.revision_id, []) if tsq else []
        facts = load_facts(conn, [m.revision_id for m in matches])
        return SearchResponse(query=query, filters={k: str(v) for k, v in filters.active().items()},
                              engine=f"experiment-2c-{arm}",
                              results=[build_result(i, m, facts[m.revision_id], filters, debug)
                                       for i, m in enumerate(matches, 1)])
    return search


def text_cases() -> list[tuple[str, str, Filters]]:
    """The equivalence-check cases with query text (frozen, generic, filter + text): 158."""
    return [c for c in equivalence_cases() if c[1].strip() and not c[0].startswith("edge")]


# ---------------------------------------------------------------------------------------------

def profile(session: Session) -> dict:
    frozen, _ = run_eval.load_queries()
    cases = text_cases()[:len(frozen) + 40]                    # frozen + generic, no extra filters
    out = {name: [] for name in PROFILE_VARIANTS}
    out["matches"] = []
    for n, (case_id, text, f) in enumerate(cases, 1):
        sql, p = baseline_fts.ranking_query(text, f, MAX_RESULTS)
        where = " and ".join(baseline_fts.FILTER_SQL[k] for k in f.active()) or "true"
        session.call(server_ms, sql, p)                        # warm-up
        for name, variant in PROFILE_VARIANTS.items():
            out[name].append(session.call(server_ms, variant.format(filters=where), {**p, "stage1_limit": 1000}))
        out["matches"].append(session.call(
            lambda c: (c.execute(baseline_fts.SET_TRIGRAM_THRESHOLD_SQL, ("0.29",)),
                       c.execute(PROFILE_VARIANTS["matches_only"].format(filters=where), p).fetchone()[0])[1]))
        if n % 20 == 0 or n == len(cases):
            progress(f"profile: {n}/{len(cases)} queries")
    summary = {name: {"p50_ms": round(percentile(v, 50), 1), "p95_ms": round(percentile(v, 95), 1),
                      "mean_ms": round(statistics.mean(v), 1)} for name, v in out.items() if name != "matches"}
    m = out["matches"]
    summary["matches"] = {"p50": percentile(m, 50), "p95": percentile(m, 95), "max": max(m),
                          "over_250": sum(x > 250 for x in m), "over_500": sum(x > 500 for x in m),
                          "over_1000": sum(x > 1000 for x in m), "over_2000": sum(x > 2000 for x in m),
                          "queries": len(m)}
    return summary


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def run(session: Session, stage1s: list[str], limits: list[int], checkpoint: Path, scale_info: str) -> dict:
    """The comparison, saved to `checkpoint` after each quality arm and every 5 cases. A rerun with
    the same data, stage 1, limits and SQL resumes from the checkpoint instead of starting over."""
    set_arms(stage1s, limits)
    cases = text_cases()
    frozen, _ = run_eval.load_queries()
    meta = {"scale": scale_info, "stage1": stage1s, "limits": limits, "timing_runs": TIMING_RUNS,
            "rank_sql": _sha(RANK_SQL), "two_stage_sql": {k: _sha(v) for k, v in ARM_SQLS.items()},
            "cases": len(cases)}
    state = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() else {}
    if state.get("meta") != meta:
        if state:
            progress("checkpoint is for different data or SQL; starting over")
        state = {"meta": meta, "quality": {}, "outcomes": {},
                 "tops": {arm: {} for arm in ARMS}, "times_ms": {arm: {} for arm in ARMS}}
    else:
        progress(f"resuming: {len(state['quality'])} quality arms and "
                 f"{len(state['times_ms']['current'])} timing cases already done")

    def save():
        checkpoint.write_text(json.dumps(state, indent=1, default=str) + "\n", encoding="utf-8")

    # Quality on the frozen set, through run_eval's own evaluate() with each arm's search.
    for arm in ARMS:
        if arm in state["quality"]:
            continue
        run_eval.search = search_with(arm)
        try:
            outcomes = []
            for q in frozen:
                outcomes += session.call(run_eval.evaluate, [q])
        finally:
            run_eval.search = run_eval._original_search
        state["quality"][arm] = run_eval.summarise(outcomes)
        state["outcomes"][arm] = {o.id: {"rank": o.rank, "found": o.found} for o in outcomes}
        save()
        progress(f"quality: {arm} done")

    # Agreement and server time on all text cases; arms interleaved per case.
    for n, (case_id, text, f) in enumerate(cases, 1):
        if all(case_id in state["times_ms"][arm] for arm in ARMS):
            continue
        for arm in ARMS:
            state["tops"][arm][case_id] = [row[1] for row in session.call(rank, text, f, arm)]
        session.call(server_ms, *params(text, f, "current"))   # warm-up
        for arm in ARMS:
            state["times_ms"][arm][case_id] = statistics.median(
                session.call(server_ms, *params(text, f, arm)) for _ in range(TIMING_RUNS))
        if n % 5 == 0 or n == len(cases):
            save()
        if n % 10 == 0 or n == len(cases):
            progress(f"agreement and timing: {n}/{len(cases)} cases")

    if "real_document_ids" not in state:                     # which returned documents are real KVL ones
        returned = sorted({d for arm in ARMS for top in state["tops"][arm].values() for d in top})
        state["real_document_ids"] = [row[0] for row in session.call(lambda c: c.execute(
            "select id from dcc.document where id = any(%s) and doc_code like 'KVL-%%'", (returned,)).fetchall())]
        save()
    return {"stage1": ", ".join(stage1s), "arms": list(ARMS), "cases": len(cases), "frozen": len(frozen),
            "meta": meta, "quality": state["quality"], "outcomes": state["outcomes"],
            "tops": state["tops"], "times_ms": state["times_ms"],
            "real_document_ids": state["real_document_ids"]}


# ---------------------------------------------------------------------------------------------

def evaluate_criteria(r: dict) -> dict:
    """The decision criteria fixed before the run."""
    cur_q = r["quality"]["current"]["overall"]
    cur_out = r["outcomes"]["current"]
    cur_t = list(r["times_ms"]["current"].values())
    cur_p50, cur_p95 = percentile(cur_t, 50), percentile(cur_t, 95)
    verdicts = {}
    real = set(r.get("real_document_ids", []))
    for arm in r.get("arms", ARMS)[1:]:
        q = r["quality"][arm]["overall"]
        out = r["outcomes"][arm]
        lost = [k for k, o in cur_out.items() if o["rank"] and o["rank"] <= 10 and not (out[k]["rank"])]
        moved = {k: (o["rank"], out[k]["rank"]) for k, o in cur_out.items() if o["rank"] != out[k]["rank"]}
        same = sum(r["tops"][arm][c] == r["tops"]["current"][c] for c in r["tops"]["current"])
        overlap = statistics.mean(len(set(r["tops"][arm][c]) & set(r["tops"]["current"][c])) /
                                  max(1, len(r["tops"]["current"][c])) for c in r["tops"]["current"])
        t = list(r["times_ms"][arm].values())
        p50, p95 = percentile(t, 50), percentile(t, 95)
        hit1_drop = round((cur_q["hit@1"] - q["hit@1"]) * r["frozen"])
        first_diff, dropped = [], []
        for c, base in r["tops"]["current"].items():
            other = r["tops"][arm][c]
            if other != base:
                first_diff.append(next(i for i, (x, y) in enumerate(zip(base + [None] * 10, other + [None] * 10), 1)
                                       if x != y))
                dropped += [d for d in base if d not in other]
        checks = {
            "Q1 no frozen query leaves the top 10": not lost,
            "Q2 MRR >= current - 0.01 and hit@1 down <= 1 query": q["mrr"] >= cur_q["mrr"] - 0.01 and hit1_drop <= 1,
            "Q3 >= 90% identical top 10": same / r["cases"] >= 0.9,
            "S1 p95 -40% and p50 -30%": p95 <= 0.6 * cur_p95 and p50 <= 0.7 * cur_p50,
        }
        verdicts[arm] = {"checks": checks, "passes": all(checks.values()), "lost_from_top10": lost,
                         "rank_changes": moved, "identical_top10": same, "mean_overlap": round(overlap, 3),
                         "p50_ms": round(p50, 1), "p95_ms": round(p95, 1), "max_ms": round(max(t), 1),
                         "p50_change": round(p50 / cur_p50 - 1, 3), "p95_change": round(p95 / cur_p95 - 1, 3),
                         "first_diff_positions": sorted(first_diff), "dropped": len(dropped),
                         "dropped_real": sum(d in real for d in dropped)}
    passing = [arm for arm in verdicts if verdicts[arm]["passes"]]
    chosen = min(passing, key=lambda arm: verdicts[arm]["p50_ms"]) if passing else None   # cheapest passing
    return {"current": {"p50_ms": round(cur_p50, 1), "p95_ms": round(cur_p95, 1), "max_ms": round(max(cur_t), 1)},
            "arms": verdicts, "chosen": chosen}


def markdown(label: str, scale_info: dict, profile_summary: dict | None, r: dict, v: dict) -> str:
    lines = [f"# Experiment 2C: two-stage ranking ({label})", "",
             f"- Date {date.today().isoformat()}; benchmark database: {scale_info}",
             f"- Code {r.get('code', '?')}; ranking SQL {r['meta']['rank_sql']}; stage 1 score: `{r['stage1']}` "
             "(chosen by cost in phase 0); trigram candidates always kept",
             f"- {r['frozen']} frozen queries for quality; {r['cases']} text cases for agreement and server time "
             f"(median of {TIMING_RUNS} runs, EXPLAIN ANALYZE, timing off)", "",
             "## Quality on the frozen set", "",
             "| Arm | hit@1 | hit@3 | hit@5 | hit@10 | MRR | rev exact/found |", "|---|---|---|---|---|---|---|"]
    for arm in r.get("arms", ARMS):
        o = r["quality"][arm]["overall"]
        lines.append(f"| {arm} | {o['hit@1']} | {o['hit@3']} | {o['hit@5']} | {o['hit@10']} | {o['mrr']} | "
                     f"{o['rev']['exact']}/{o['rev']['found']} |")
    lines += ["", "## Agreement and server ranking time", "",
              "| Arm | identical top 10 | mean overlap | p50 ms | p95 ms | max ms | p50 change | p95 change |",
              "|---|---|---|---|---|---|---|---|",
              f"| current | {r['cases']}/{r['cases']} | 1.0 | {v['current']['p50_ms']} | {v['current']['p95_ms']} | "
              f"{v['current']['max_ms']} | | |"]
    for arm, a in v["arms"].items():
        lines.append(f"| {arm} | {a['identical_top10']}/{r['cases']} | {a['mean_overlap']} | {a['p50_ms']} | "
                     f"{a['p95_ms']} | {a['max_ms']} | {a['p50_change']:+.0%} | {a['p95_change']:+.0%} |")
    lines += ["", "## Decision criteria (fixed before the run)", "",
              "| Arm | " + " | ".join(next(iter(v["arms"].values()))["checks"]) + " | passes |",
              "|---|" + "---|" * (len(next(iter(v["arms"].values()))["checks"]) + 1)]
    for arm, a in v["arms"].items():
        lines.append(f"| {arm} | " + " | ".join("yes" if ok else "**no**" for ok in a["checks"].values())
                     + f" | {'**yes**' if a['passes'] else 'no'} |")
    lines += ["", f"Cheapest passing arm (by p50): **{v['chosen'] or 'none'}**", "",
              "## Where the top 10s differ (reported, not a criterion)", "",
              "| Arm | changed top 10s | first differing position (min / median) | documents dropped | of which real KVL |",
              "|---|---|---|---|---|"]
    for arm, a in v["arms"].items():
        fd = a.get("first_diff_positions", [])
        lines.append(f"| {arm} | {len(fd)} | {min(fd) if fd else '-'} / {statistics.median(fd) if fd else '-'} | "
                     f"{a.get('dropped', '-')} | {a.get('dropped_real', '-')} |")
    lines += ["", "## Frozen-query rank changes", ""]
    for arm, a in v["arms"].items():
        changes = ", ".join(f"{k} {c}→{n}" for k, (c, n) in sorted(a["rank_changes"].items())) or "none"
        lines.append(f"- {arm}: {changes}")
    if profile_summary:
        lines += ["", "## Phase 0: cost profile (server ms over frozen + generic queries)", "",
                  "| Variant | p50 | p95 | mean |", "|---|---|---|---|"]
        lines += [f"| {k} | {s['p50_ms']} | {s['p95_ms']} | {s['mean_ms']} |"
                  for k, s in profile_summary.items() if k != "matches"]
        m = profile_summary["matches"]
        lines += ["", f"Matching rows per query: p50 {m['p50']}, p95 {m['p95']}, max {m['max']}; queries over "
                  f"250/500/1000/2000 matches: {m['over_250']}/{m['over_500']}/{m['over_1000']}/{m['over_2000']} "
                  f"of {m['queries']}"]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Experiment 2C: two-stage ranking (evaluation only)")
    parser.add_argument("action", choices=["profile", "check-dev", "run"])
    parser.add_argument("--load-scale", type=int, help="reload the benchmark database at this scale first")
    parser.add_argument("--stage1", default="ts_rank", help=f"comma-separated, from {sorted(STAGE1)}")
    parser.add_argument("--limits", default=",".join(map(str, LIMITS)), help="comma-separated stage-1 limits")
    parser.add_argument("--label")
    args = parser.parse_args()
    stage1s = args.stage1.split(",")
    limits = [int(n) for n in args.limits.split(",")]
    unknown = set(stage1s) - set(STAGE1)
    if unknown:
        raise SystemExit(f"unknown stage 1: {sorted(unknown)}")
    keep_awake()
    REPORTS.mkdir(parents=True, exist_ok=True)

    if args.action == "check-dev":
        session = Session(get_settings().database_url, stall_timeout=120)
        try:
            for stage1 in stage1s:
                set_arms([stage1], limits)
                different = [(c[0], arm) for c in text_cases() for arm in ARMS[1:]
                             if session.call(rank, c[1], c[2], arm) != session.call(rank, c[1], c[2], "current")]
                print(f"dev, stage 1 {stage1}: {len(text_cases())} cases x {len(ARMS) - 1} limits; "
                      f"{len(different)} differ from current {different[:5]}")
        finally:
            session.close()
        return

    session = Session(bench_database_url(), stall_timeout=600)
    try:
        if args.load_scale:
            progress(f"loading the benchmark database at scale {args.load_scale}")
            session.call(load_scale, args.load_scale, timeout=4 * 3600, retry=False)
        docs, rows = session.conn.execute("select (select count(*) from dcc.document), "
                                          "(select count(*) from dcc.search_entry)").fetchone()
        scale_info = f"{docs} documents, {rows} index rows"
        progress(scale_info)
        label = args.label or f"two-stage-{docs}"
        if args.action == "profile":
            summary = profile(session)
            (REPORTS / f"{label}.profile.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(summary, indent=2))
            return
        checkpoint = REPORTS / f"{label}.partial.json"
        r = run(session, stage1s, limits, checkpoint, scale_info)
    finally:
        session.close()
    r["code"] = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
                               capture_output=True, text=True).stdout.strip()
    v = evaluate_criteria(r)
    profile_path = REPORTS / f"{label}.profile.json"
    profile_summary = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else None
    (REPORTS / f"{label}.json").write_text(json.dumps({"scale": scale_info, "result": r, "verdicts": v},
                                                      indent=1, default=str) + "\n", encoding="utf-8")
    (REPORTS / f"{label}.md").write_text(markdown(label, scale_info, profile_summary, r, v), encoding="utf-8")
    checkpoint.unlink(missing_ok=True)
    print(markdown(label, scale_info, profile_summary, r, v))


run_eval._original_search = run_eval.search

if __name__ == "__main__":
    main()
