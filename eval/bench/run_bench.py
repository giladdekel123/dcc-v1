"""Scalability benchmark: load a scale into the separate benchmark database, then measure.

    python -m eval.bench.run_bench --scale 200 [--label NAME] [--reps 2]

Uses BENCH_DATABASE_URL only, and refuses to run if it points at the dev database. Each run
replaces the benchmark database's project data with the real 100-document KVL corpus plus
(scale - 100) synthetic documents, measures, and then applies a small incremental change.
The search system is called exactly as the API calls it; nothing in retrieval is modified.
"""

import argparse
import json
import os
import re
import statistics
import threading
import time
from datetime import date
from pathlib import Path

import psycopg
import yaml
from dotenv import load_dotenv

from app.config import REPO_ROOT, get_settings
from app.ingest.build_index import build_index
from app.ingest.extract_content import extract_all
from app.ingest.load_register import load
from app.retrieval import baseline_fts
from app.retrieval.base import Filters
from app.search import RETRIEVER, search
from dcc_corpus import naming
from eval.bench.synthetic import EXTRA_ORGANISATIONS, SyntheticDocument, generate
from eval.run_eval import evaluate, load_queries, summarise

BENCH_DIR = REPO_ROOT / "eval" / "bench"
REPORTS_DIR = BENCH_DIR / "reports"
CORPUS = REPO_ROOT / "corpus"
REAL_DOCUMENTS = 100
EXPLAIN_SAMPLE = 12         # ranking queries explained on the server
LOAD_TIMEOUT = 2 * 3600     # seconds allowed for loading and indexing a scale (not retried)
INCREMENTAL_TIMEOUT = 1800  # seconds allowed for the incremental change (not retried)


def bench_database_url() -> str:
    """The benchmark database; never the dev database."""
    load_dotenv(REPO_ROOT / ".env")
    bench = os.getenv("BENCH_DATABASE_URL")
    if not bench:
        raise SystemExit("BENCH_DATABASE_URL is not set (add it to .env)")
    if same_database(bench, get_settings().database_url):
        raise SystemExit("BENCH_DATABASE_URL points at the dev database; refusing to run")
    return bench


def same_database(a: str | None, b: str | None) -> bool:
    """Same user, host and database name. On Supabase the user carries the project ref."""
    def identity(url):
        m = re.match(r"^postgres(?:ql)?://([^:@]+)(?::[^@]*)?@([^/]+)/([^?]*)", url or "")
        return m.groups() if m else None
    return identity(a) is not None and identity(a) == identity(b)


KEEPALIVES = {"keepalives": 1, "keepalives_idle": 10, "keepalives_interval": 5, "keepalives_count": 3}


def progress(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


class Stalled(psycopg.OperationalError):
    """A call that produced no result within its time limit and was abandoned."""


class Session:
    """An autocommit connection to the benchmark database that survives stalls and network drops.

    Every call runs in a worker thread with a time limit. A call still running at the limit is
    abandoned together with its connection: nothing waits for the network to report the failure,
    which on this machine took between 12 and 80 minutes. The connection is replaced, retrying
    with increasing waits for up to `reconnect_for` seconds (DNS and network drops), and the call is
    repeated, up to `attempts` times in all. Every stall, failure and reconnect is logged and kept in
    `events`. Autocommit keeps each query in its own short transaction.
    """

    def __init__(self, url: str, stall_timeout: float = 60.0, reconnect_for: float = 300.0, attempts: int = 3):
        self.url, self.stall_timeout, self.reconnect_for, self.attempts = url, stall_timeout, reconnect_for, attempts
        self.reconnects, self.stalls, self.events = 0, 0, []
        self.conn = self._connect_with_retry()

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.url, prepare_threshold=None, connect_timeout=20, autocommit=True, **KEEPALIVES)

    def _event(self, kind: str, call: str, detail: str) -> None:
        self.events.append({"time": time.strftime("%H:%M:%S"), "kind": kind, "call": call, "detail": detail})
        progress(f"connection {kind} during {call}: {detail}")

    def _connect_with_retry(self) -> psycopg.Connection:
        waited, delay = 0.0, 5.0                         # waits between attempts: 5, 10, 20, 40, 60, 60 ... s
        while True:
            try:
                return self._connect()
            except psycopg.OperationalError as exc:
                if waited + delay > self.reconnect_for:
                    self._event("connect-failed", "connect", f"{_first_line(exc)}; giving up")
                    raise
                self._event("connect-failed", "connect", f"{_first_line(exc)}; retrying in {delay:.0f} s")
                time.sleep(delay)
                waited, delay = waited + delay, min(delay * 2, 60.0)

    def _run(self, fn, args, kwargs, timeout: float):
        conn, box = self.conn, {}

        def target():
            try:
                box["value"] = fn(conn, *args, **kwargs)
            except BaseException as exc:                 # handed back to the calling thread
                box["error"] = exc

        worker = threading.Thread(target=target, name=f"bench-{fn.__name__}", daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():                            # abandoned; the thread keeps the old connection
            self.stalls += 1
            raise Stalled(f"no result within {timeout:g} s")
        if "error" in box:
            raise box["error"]
        return box["value"]

    def call(self, fn, *args, timeout: float | None = None, retry: bool = True, **kwargs):
        """fn(conn, *args, **kwargs) with a time limit (default stall_timeout). With retry=False (writes),
        a failed call is not repeated: the connection is still replaced, and the error is raised."""
        timeout = timeout or self.stall_timeout
        for attempt in range(1, self.attempts + 1):
            try:
                return self._run(fn, args, kwargs, timeout)
            except psycopg.OperationalError as exc:
                stalled = isinstance(exc, Stalled)
                self._event("stall" if stalled else "error", fn.__name__,
                            f"{_first_line(exc)} (attempt {attempt} of {self.attempts if retry else 1}); reconnecting")
                if not stalled:                          # a stalled connection is still in use by its thread
                    try:
                        self.conn.close()
                    except psycopg.Error:
                        pass
                self.conn = self._connect_with_retry()
                self.reconnects += 1
                if not retry or attempt == self.attempts:
                    raise

    def close(self):
        self.conn.close()


def _first_line(exc: BaseException) -> str:
    return (str(exc).strip().splitlines() or [type(exc).__name__])[0]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def insert_synthetic(conn: psycopg.Connection, documents: list[SyntheticDocument]) -> list[int]:
    """Bulk-insert synthetic records (register, files, extraction, segments, links). Returns revision ids."""
    if not documents:
        return []
    with conn.transaction():
        conn.cursor().executemany(
            "insert into dcc.organisation (code, name, role) values (%s, %s, %s) on conflict (code) do nothing",
            EXTRA_ORGANISATIONS)
        cur = conn.cursor()
        with cur.copy("copy dcc.document (doc_code, title, wbs_code, discipline_code, doc_type_code, "
                      "originator_code) from stdin") as copy:
            for d in documents:
                copy.write_row((d.doc_code, d.title, d.wbs_code, d.discipline_code, d.doc_type_code, d.originator_code))
        doc_ids = dict(conn.execute("select doc_code, id from dcc.document where doc_code = any(%s)",
                                    ([d.doc_code for d in documents],)))
        with cur.copy("copy dcc.revision (document_id, rev_code, revision_date, stage_code) from stdin") as copy:
            for d in documents:
                for r in d.revisions:
                    copy.write_row((doc_ids[d.doc_code], r["rev_code"], r["revision_date"], r["stage_code"]))
        rev_ids = {(doc_id, rev): rid for rid, doc_id, rev in conn.execute(
            "select id, document_id, rev_code from dcc.revision where document_id = any(%s)", (list(doc_ids.values()),))}
        pairs = [(d, r, rev_ids[(doc_ids[d.doc_code], r["rev_code"])]) for d in documents for r in d.revisions]
        with cur.copy("copy dcc.revision_status (revision_id, status_code, effective_date) from stdin") as copy:
            for _, r, rid in pairs:
                for status, when in r["statuses"]:
                    copy.write_row((rid, status, when))
        with cur.copy("copy dcc.revision_file (revision_id, copy_role, filename, original_location, storage_path, "
                      "file_format, size_bytes, sha256) from stdin") as copy:
            for _, r, rid in pairs:
                f = r["file"]
                copy.write_row((rid, "primary", f["filename"], f["location"], f["storage_path"], f["format"],
                                f["size_bytes"], f["sha256"]))
        file_ids = dict(conn.execute("select revision_id, id from dcc.revision_file where revision_id = any(%s)",
                                     ([rid for *_, rid in pairs],)))
        with cur.copy("copy dcc.extraction (revision_file_id, extractor_version, outcome, unit_count, "
                      "extracted_fields) from stdin") as copy:
            for d, r, rid in pairs:
                fields = {"doc_code": d.doc_code, "rev_code": r["rev_code"], "status_code": r["statuses"][0][0],
                          "date": r["revision_date"].isoformat()}
                copy.write_row((file_ids[rid], "synthetic", "ok", len(r["segments"]), json.dumps(fields)))
        with cur.copy("copy dcc.content_segment (revision_file_id, seq, locator, body) from stdin") as copy:
            for _, r, rid in pairs:
                for seq, body in enumerate(r["segments"], 1):
                    copy.write_row((file_ids[rid], seq, f"page {seq}", body))
        all_ids = dict(conn.execute("select doc_code, id from dcc.document where doc_code = any(%s)",
                                    ([link["to_doc_code"] for d in documents for link in d.links] or [""],)))
        all_ids.update(doc_ids)
        cur.executemany(
            "insert into dcc.information_link (from_document_id, to_document_id, link_type, provenance) "
            "values (%s, %s, %s, 'registered')",
            [(doc_ids[d.doc_code], all_ids[link["to_doc_code"]], link["link_type"]) for d in documents for link in d.links])
    return [rid for *_, rid in pairs]


def load_scale(conn: psycopg.Connection, scale: int) -> dict:
    """Replace project data with the real corpus plus (scale - 100) synthetic documents, then index."""
    timings = {}
    t = time.perf_counter()
    load(conn, CORPUS)
    extract_all(conn, CORPUS)
    conn.commit()
    timings["load_real_corpus_s"] = time.perf_counter() - t

    t = time.perf_counter()
    documents = generate(max(scale - REAL_DOCUMENTS, 0))
    timings["generate_s"] = time.perf_counter() - t
    t = time.perf_counter()
    insert_synthetic(conn, documents)
    conn.commit()
    timings["insert_synthetic_s"] = time.perf_counter() - t

    t = time.perf_counter()
    indexed = build_index(conn)
    conn.commit()
    timings["full_index_build_s"] = time.perf_counter() - t
    timings["index_rows"] = indexed
    conn.execute("analyze")
    return timings


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------

def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(p / 100 * len(ordered)) - 1))]


def latency_summary(samples: dict[str, list[float]]) -> dict:
    """Per-query median over repetitions, then p50/p95/max across queries (milliseconds)."""
    per_query = [statistics.median(v) * 1000 for v in samples.values()]
    return {"queries": len(per_query), "p50_ms": round(percentile(per_query, 50), 1),
            "p95_ms": round(percentile(per_query, 95), 1), "max_ms": round(max(per_query), 1)}


def spread(items: list, n: int) -> list:
    """n items evenly spread across the list (all of them if n is larger)."""
    if n >= len(items):
        return list(items)
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


def run_workload(session: Session, reps: int, n_text: int, n_filtered: int, n_filters_only: int,
                 results: dict | None = None, checkpoint=lambda: None) -> dict:
    """Time the workload into `results`, calling checkpoint() every 10 queries and after each set, so a
    crash loses at most the last 10 queries. A set still in progress is marked complete: false."""
    workload = yaml.safe_load((BENCH_DIR / "workload.yaml").read_text(encoding="utf-8"))
    frozen, _ = load_queries()
    generic = workload["generic_queries"]
    n_frozen = round(n_text * len(frozen) / (len(frozen) + len(generic)))
    texts = spread([q.query for q in frozen], n_frozen) + spread(generic, n_text - n_frozen)
    filters = [Filters(**{k: (date.fromisoformat(v) if k.startswith("date") else v) for k, v in f.items()})
               for f in workload["filters"]]
    jobs = {
        "text_only": [(t, Filters()) for t in texts],
        "text_plus_filters": [(t, filters[i % len(filters)]) for i, t in enumerate(spread(texts, n_filtered))],
        "filters_only": [("", f) for f in spread(filters, n_filters_only)],
    }
    results = {} if results is None else results
    excluded = results.setdefault("excluded_samples", [])
    for name, calls in jobs.items():
        samples: dict[str, list[float]] = {}
        for i, (text, f) in enumerate(calls):
            session.call(search, text, f)                          # warm-up
            for _ in range(reps):
                before = session.reconnects
                t = time.perf_counter()
                session.call(search, text, f)
                elapsed = time.perf_counter() - t
                if session.reconnects > before:                    # timed sample includes a stall and reconnect
                    excluded.append({"workload": name, "query": text, "filters": f.active(),
                                     "ms": round(elapsed * 1000, 1)})
                    progress(f"{name}: query {i + 1} hit a reconnect ({elapsed:.1f} s); sample excluded")
                    continue
                samples.setdefault(f"{i}", []).append(elapsed)
            done = i + 1 == len(calls)
            if (i + 1) % 10 == 0 or done:
                progress(f"{name}: {i + 1}/{len(calls)} queries")
                if samples:
                    results[name] = {**latency_summary(samples), "complete": done}
                checkpoint()
    return results


def corpus_counts(conn: psycopg.Connection) -> dict:
    documents, revisions, files = conn.execute("""
        select (select count(*) from dcc.document), (select count(*) from dcc.revision),
               (select count(*) from dcc.revision_file)""").fetchone()
    return {"documents": documents, "revisions": revisions, "files": files}


def round_trip_ms(conn: psycopg.Connection, n: int = 20) -> float:
    times = []
    for _ in range(n):
        t = time.perf_counter()
        conn.execute("select 1").fetchone()
        times.append(time.perf_counter() - t)
    return round(statistics.median(times) * 1000, 1)


def explain_sample() -> list[tuple[str, Filters]]:
    frozen, _ = load_queries()
    sample = [(q.query, Filters()) for q in frozen[::max(1, len(frozen) // EXPLAIN_SAMPLE)][:EXPLAIN_SAMPLE]]
    return sample + [("piles", Filters(doc_type="DR")), ("", Filters(wbs="400"))]


def explain_one(conn: psycopg.Connection, text: str, f: Filters) -> tuple[float, list[str]]:
    """Server-side execution time and search_entry access nodes of the ranking query for one query.
    Builds the same SQL and parameters as the baseline retriever (read-only reuse of its constants)."""
    lexemes = conn.execute("select tsvector_to_array(to_tsvector('english', %s))", (text,)).fetchone()[0] if text else []
    terms = [baseline_fts._quote(x) for x in lexemes]
    active = f.active()
    sql = baseline_fts.RANK_SQL.format(filters=" and ".join(baseline_fts.FILTER_SQL[k] for k in active) or "true")
    plan = conn.execute("explain (analyze, format json) " + sql, {
        **active, "terms": terms, "tsq": " | ".join(terms) or None, "q": text, "browse": not text,
        "trigram_min": baseline_fts.TRIGRAM_MIN, "limit": 10}).fetchone()[0][0]
    scans = []

    def walk(node):
        if node.get("Relation Name") == "search_entry" or node.get("Index Name", "").startswith("search_entry"):
            scans.append(f"{node['Node Type']}" + (f" ({node['Index Name']})" if node.get("Index Name") else ""))
        for child in node.get("Plans", []):
            walk(child)
    walk(plan["Plan"])
    return plan["Execution Time"], scans


def explain_ranking(session: Session) -> dict:
    times, scans = [], {}
    sample = explain_sample()
    for text, f in sample:
        ms, nodes = session.call(explain_one, text, f)
        times.append(ms)
        for label in nodes:
            scans[label] = scans.get(label, 0) + 1
    return {"queries": len(sample), "p50_ms": round(percentile(times, 50), 1),
            "p95_ms": round(percentile(times, 95), 1), "search_entry_access": scans}


def known_items(session: Session) -> dict:
    """The 58 frozen queries, one call each (each with its own time limit)."""
    frozen, _ = load_queries()
    outcomes = []
    for q in frozen:
        outcomes += session.call(evaluate, [q])
    overall = summarise(outcomes)["overall"]
    return {"hit@1": overall["hit@1"], "hit@10": overall["hit@10"]}


def storage(conn: psycopg.Connection) -> dict:
    rows = conn.execute("""
        select c.relname, pg_total_relation_size(c.oid), pg_indexes_size(c.oid)
        from pg_class c join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'dcc' and c.relkind = 'r' order by 2 desc""").fetchall()
    return {"database_mb": round(conn.execute("select pg_database_size(current_database())").fetchone()[0] / 1e6, 1),
            "dcc_total_mb": round(sum(r[1] for r in rows) / 1e6, 1),
            "tables_mb": {name: round(total / 1e6, 2) for name, total, _ in rows[:6]},
            "indexes_mb": round(sum(r[2] for r in rows) / 1e6, 1)}


# A new revision is indexed from its primary file, so each re-issued P09 revision gets one: a copy of
# the previous revision's file record, extraction and text segments (one statement for the batch).
REISSUE_FILES_SQL = """
with prev as (
  select distinct on (r.document_id) r.document_id, f.*
  from dcc.revision r
  join dcc.revision_file f on f.revision_id = r.id and f.copy_role = 'primary'
  where r.document_id = any(%(docs)s) and r.rev_code <> 'P09'
  order by r.document_id, r.revision_date desc, r.id desc
),
new_files as (
  insert into dcc.revision_file (revision_id, copy_role, filename, original_location, storage_path,
                                 file_format, size_bytes, sha256)
  select n.id, 'primary', regexp_replace(p.filename, '_[PCA][0-9]{2}', '_P09'), p.original_location,
         'bench-reissue/P09/' || p.storage_path, p.file_format, p.size_bytes, p.sha256
  from dcc.revision n join prev p on p.document_id = n.document_id
  where n.id = any(%(new)s)
  returning id, revision_id
),
pairs as (
  select nf.id as new_file_id, p.id as prev_file_id
  from new_files nf join dcc.revision n on n.id = nf.revision_id join prev p on p.document_id = n.document_id
),
new_extraction as (
  insert into dcc.extraction (revision_file_id, extractor_version, outcome, unit_count, extracted_fields)
  select pr.new_file_id, e.extractor_version, e.outcome, e.unit_count,
         jsonb_set(e.extracted_fields, '{rev_code}', '"P09"')
  from pairs pr join dcc.extraction e on e.revision_file_id = pr.prev_file_id
  returning revision_file_id
)
insert into dcc.content_segment (revision_file_id, seq, locator, body)
select pr.new_file_id, s.seq, s.locator, s.body
from pairs pr join dcc.content_segment s on s.revision_file_id = pr.prev_file_id
where pr.new_file_id in (select revision_file_id from new_extraction)
"""


def incremental(conn: psycopg.Connection, scale: int, batch: int = 100) -> dict:
    """Time adding `batch` new documents, and adding a revision to `batch` existing ones."""
    start = max(scale - REAL_DOCUMENTS, 0)
    new_documents = generate(start + batch)[start:]
    t = time.perf_counter()
    new_revisions = insert_synthetic(conn, new_documents)
    conn.commit()
    insert_s = time.perf_counter() - t
    t = time.perf_counter()
    add_indexed = build_index(conn, revision_ids=new_revisions)
    conn.commit()
    add_index_s = time.perf_counter() - t

    targets = conn.execute("""select d.id, d.doc_type_code from dcc.document d
                              where d.doc_code not like 'KVL-%%' order by d.id limit %s""", (batch,)).fetchall()
    doc_ids = [doc_id for doc_id, _ in targets]
    statuses = [sorted(naming.STATUS_APPLICABILITY[doc_type])[0] for _, doc_type in targets]
    t = time.perf_counter()
    with conn.transaction():                                       # one statement per table, not per row
        changed = [rid for (rid,) in conn.execute("""
            insert into dcc.revision (document_id, rev_code, revision_date, stage_code)
            select doc_id, 'P09', %s, 'CN' from unnest(%s::bigint[]) with ordinality as t(doc_id, n) order by n
            returning id""", (date(2026, 6, 30), doc_ids)).fetchall()]
        conn.execute("""
            insert into dcc.revision_status (revision_id, status_code, effective_date)
            select r.id, s.status, %s
            from unnest(%s::bigint[], %s::text[]) as s(doc_id, status)
            join dcc.revision r on r.document_id = s.doc_id and r.rev_code = 'P09'""",
                     (date(2026, 6, 30), doc_ids, statuses))
        conn.execute(REISSUE_FILES_SQL, {"docs": doc_ids, "new": changed})
    change_insert_s = time.perf_counter() - t
    t = time.perf_counter()
    change_indexed = build_index(conn, revision_ids=changed)
    conn.commit()
    change_index_s = time.perf_counter() - t
    return {"batch": batch, "add_documents_insert_s": round(insert_s, 2), "add_documents_index_s": round(add_index_s, 2),
            "add_documents_indexed": add_indexed,
            "add_revisions_insert_s": round(change_insert_s, 2), "add_revisions_index_s": round(change_index_s, 2),
            "add_revisions_indexed": change_indexed}


def markdown(report: dict) -> str:
    c, t, s = report["corpus"], report["load"], report["storage"]
    lines = [f"# Scalability benchmark: {report['label']}", "",
             f"- Engine: {report['engine']}; date {report['created']}; database: separate benchmark project",
             f"- Corpus: {c['documents']} documents, {c['revisions']} revisions, {c['files']} files "
             f"(100 real KVL + {c['documents'] - REAL_DOCUMENTS} synthetic)",
             f"- Database region: {report.get('database_region', 'unknown')}; network round trip (select 1): "
             f"{report['round_trip_ms']} ms; reconnects during the run: {report.get('reconnects', 0)} "
             f"(stalled statements aborted after {report.get('stall_timeout_s', '-')} s: {report.get('stalls', 0)})",
             f"- Workload: {report['workload']['text']} text, {report['workload']['text_plus_filters']} text + filters, "
             f"{report['workload']['filters_only']} filters only; {report['workload']['reps']} timed repetition(s) "
             "after a warm-up", "",
             "## Latency (end to end, per query median of repetitions)", "",
             "| Workload | queries | p50 ms | p95 ms | max ms |", "|---|---|---|---|---|"]
    lines += [f"| {k}{'' if v.get('complete', True) else ' (incomplete)'} | {v['queries']} | {v['p50_ms']} | "
              f"{v['p95_ms']} | {v['max_ms']} |" for k, v in report["latency"].items() if k != "excluded_samples"]
    excluded = report["latency"].get("excluded_samples", [])
    lines += ["", f"Timed samples excluded because they included a stalled connection and reconnect: {len(excluded)}"]
    lines += [f"- {x['workload']}: \"{x['query']}\" {x['filters'] or ''} ({x['ms']} ms)" for x in excluded]
    e = report["ranking_explain"]
    lines += ["", f"**Ranking query on the server** ({e['queries']} sampled): p50 {e['p50_ms']} ms, "
              f"p95 {e['p95_ms']} ms. Access to `search_entry`: "
              + ", ".join(f"{k} x{n}" for k, n in e["search_entry_access"].items()), "",
              "## Load and index", "",
              f"- Real corpus load and extraction: {t['load_real_corpus_s']:.1f} s",
              f"- Synthetic insert: {t['insert_synthetic_s']:.1f} s (generation {t['generate_s']:.1f} s)",
              f"- Full index build: {t['full_index_build_s']:.1f} s for {t['index_rows']} revisions", "",
              "## Storage", "",
              f"- Database: {s['database_mb']} MB; `dcc` schema {s['dcc_total_mb']} MB, of which indexes {s['indexes_mb']} MB",
              "- Largest tables (MB): " + ", ".join(f"{k} {v}" for k, v in s["tables_mb"].items()), "",
              "## Incremental change", ""]
    i = report["incremental"]
    lines += [f"- Add {i['batch']} documents: insert {i['add_documents_insert_s']} s, index {i['add_documents_index_s']} s "
              f"({i.get('add_documents_indexed', '?')} revisions indexed)",
              f"- Re-issue {i['batch']} documents as a new revision (file, extraction and text copied from the previous "
              f"revision): insert {i['add_revisions_insert_s']} s, index {i['add_revisions_index_s']} s "
              f"({i.get('add_revisions_indexed', '?')} revisions indexed)", "",
              "## Known-item sanity check (58 frozen queries; not a quality figure)", "",
              f"hit@1 {report['known_items']['hit@1']}, hit@10 {report['known_items']['hit@10']}", "",
              "## Connection events", ""]
    events = report.get("connection_events", [])
    lines += [f"- {e['time']} {e['kind']} during {e['call']}: {e['detail']}" for e in events] or ["- none"]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the scalability benchmark at one scale.")
    parser.add_argument("--scale", type=int, required=True, help="total documents, including the 100 real ones")
    parser.add_argument("--label")
    parser.add_argument("--reps", type=int, default=2)
    parser.add_argument("--text-queries", type=int, default=98, help="text-only queries (frozen + generic)")
    parser.add_argument("--filtered-queries", type=int, default=30, help="text queries also run with a filter")
    parser.add_argument("--filter-only-queries", type=int, default=20)
    parser.add_argument("--region", default="unknown", help="benchmark database region, recorded in the report")
    parser.add_argument("--stall-timeout", type=float, default=60.0,
                        help="seconds before a database call (one search) is abandoned as stalled and retried")
    args = parser.parse_args()

    label = args.label or f"{RETRIEVER.name}-{args.scale}"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    partial = REPORTS_DIR / f"{label}.partial.json"

    report: dict = {"label": label, "engine": RETRIEVER.name, "created": date.today().isoformat(),
                    "scale": args.scale, "database_region": args.region, "stall_timeout_s": args.stall_timeout}
    session = Session(bench_database_url(), args.stall_timeout)

    def save():
        report["reconnects"], report["stalls"], report["connection_events"] = (
            session.reconnects, session.stalls, session.events)
        partial.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")

    try:
        progress(f"loading scale {args.scale}")
        load_timings = session.call(load_scale, args.scale, timeout=LOAD_TIMEOUT, retry=False)
        report.update({
            "corpus": session.call(corpus_counts),
            "round_trip_ms": session.call(round_trip_ms),
            "load": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in load_timings.items()},
            "storage": session.call(storage),
            "workload": {"reps": args.reps, "text": args.text_queries, "text_plus_filters": args.filtered_queries,
                         "filters_only": args.filter_only_queries},
            "latency": {},
        })
        save()
        progress(f"loaded {report['corpus']}; measuring latency")
        run_workload(session, args.reps, args.text_queries, args.filtered_queries, args.filter_only_queries,
                     results=report["latency"], checkpoint=save)
        progress("explaining the ranking query")
        report["ranking_explain"] = explain_ranking(session)
        save()
        progress("known-item check")
        report["known_items"] = known_items(session)
        save()
        progress("incremental change")
        report["incremental"] = session.call(incremental, args.scale, timeout=INCREMENTAL_TIMEOUT, retry=False)
        save()
    except BaseException as exc:
        report["aborted"] = {"time": time.strftime("%H:%M:%S"), "error": f"{type(exc).__name__}: {_first_line(exc)}"}
        save()
        progress(f"aborted; results so far are in {partial.name}")
        raise
    finally:
        session.close()

    (REPORTS_DIR / f"{label}.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    (REPORTS_DIR / f"{label}.md").write_text(markdown(report), encoding="utf-8")
    partial.unlink(missing_ok=True)
    print(markdown(report))


if __name__ == "__main__":
    main()
