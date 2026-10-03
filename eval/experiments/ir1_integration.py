"""IR-1 integration adapter: frozen Stage-1 plan -> existing conventional ranking -> frozen Stage-2
engine -> the existing SearchResponse shape. Experiment-only; no production code is changed.

Reused unchanged: app.retrieval.baseline_fts.ranking_query (RANK_SQL), its trigram threshold
setting, the retriever's evidence queries (_evidence/_field_hits, as eval/experiments/two_stage.py
does), app.evidence.facts.load_facts and app.evidence.builder.build_result.

The pool keeps the raw SQL score (not the retriever's rounded debug score) and the revision the
ranking matched. Filters that exist only for conventional comparison (Gate A cases) are passed to
the ranking and to evidence, never into Stage 2 as M1 filters. Interpretation/audit information is
returned beside the SearchResponse, never inside it, so Gate A can compare the response as is.

This module does not read settings or .env and opens no connection: callers pass `conn`.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.evidence.builder import build_result
from app.evidence.facts import load_facts
from app.models import EvidenceItem, SearchResponse
from app.retrieval import baseline_fts
from app.retrieval.base import Filters, RawMatch
from eval.experiments import ir1_engine
from eval.experiments.ir1_engine import Document, Facts, Link, Outcome, PoolEntry, Revision, Switches
from eval.experiments.ir1_request import (ANCHOR_COUNT, POOL_SIZE, FrozenRequests, Plan, Request,
                                          load_frozen_requests, plan)

ENGINE_LABEL = "ir1-integration"          # adapter label; Gate A excludes only this and the record


# ---------------------------------------------------------------------------------------------
# Stage 1
# ---------------------------------------------------------------------------------------------

def load_request(request_id: str, frozen: FrozenRequests | None = None) -> tuple[Request, Plan]:
    """One frozen annotation and its Stage-1 plan."""
    frozen = frozen or load_frozen_requests()
    for request in frozen.requests:
        if request.id == request_id:
            return request, plan(request, frozen.unresolved)
    raise KeyError(f"no frozen request {request_id!r}")


# ---------------------------------------------------------------------------------------------
# Conventional ranking (existing ranking_query / RANK_SQL)
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class RankRow:
    """One RANK_SQL row: the document's best revision with its unrounded scores."""
    revision_id: int
    document_id: int
    score: float
    coverage: float
    fts_rank: float
    trigram: float
    tsq: str | None


Ranker = Callable[[Any, str, Filters, int], tuple[RankRow, ...]]


def rank(conn, query: str, filters: Filters, limit: int) -> tuple[RankRow, ...]:
    """The existing conventional ranking, exactly as BaselineFtsRetriever.search runs it."""
    sql, params = baseline_fts.ranking_query(query, filters, limit)
    with conn.pipeline():
        conn.execute(baseline_fts.SET_TRIGRAM_THRESHOLD_SQL, (str(baseline_fts.TRIGRAM_CANDIDATE_MIN),))
        cursor = conn.execute(sql, params)
    return tuple(RankRow(*row) for row in cursor.fetchall())


def conventional_filters(plan_: Plan, extra: Filters = Filters()) -> Filters:
    """M1 filters from the plan, plus conventional-only filters (Gate A); a key set both ways must agree."""
    merged = dict(extra.active())
    for key, code in plan_.filters().items():
        if merged.setdefault(key, code) != code:
            raise ValueError(f"filter {key!r}: plan says {code!r}, conventional filter says {merged[key]!r}")
    return Filters(**merged)


def conventional_pool(conn, plan_: Plan, switches: Switches, extra_filters: Filters = Filters(),
                      ranker: Ranker = rank) -> tuple[tuple[PoolEntry, ...], tuple[RankRow, ...]]:
    """S4 steps 1-2: the conventional ranking of lexical_query with the filters, at most POOL_SIZE
    documents, in row order, with the raw score and the matched revision."""
    rows = ranker(conn, ir1_engine.lexical_query(plan_, switches), conventional_filters(plan_, extra_filters),
                  POOL_SIZE)
    return tuple(PoolEntry(r.document_id, r.score, r.revision_id) for r in rows), rows


def anchor_ranking(conn, plan_: Plan, switches: Switches, ranker: Ranker = rank) -> tuple[int, ...]:
    """Line 116: the top ANCHOR_COUNT documents of the conventional ranking of anchor_text, no filters."""
    query = ir1_engine.anchor_query(plan_, switches)
    if query is None:
        return ()
    return tuple(r.document_id for r in ranker(conn, query, Filters(), ANCHOR_COUNT))


# ---------------------------------------------------------------------------------------------
# Stage-2 facts (read-only SQL plus pure row mapping)
# ---------------------------------------------------------------------------------------------

DOCUMENTS_SQL = """
select d.id, d.doc_code, d.doc_type_code, d.discipline_code, d.wbs_code, d.originator_code
from dcc.document d where d.id = any(%s) order by d.id
"""
# Current permitted use: dcc.revision_summary (the existing latest-by-use model, S3.1).
REVISIONS_SQL = """
select r.id, r.document_id, r.rev_code, r.revision_date, r.stage_code, r.sender_code, rs.permitted_use_code
from dcc.revision r join dcc.revision_summary rs on rs.revision_id = r.id
where r.document_id = any(%s) order by r.document_id, r.id
"""
LINKS_SQL = """
select l.id, l.from_document_id, l.from_revision_id, l.to_document_id, l.to_revision_id, l.link_type, l.provenance
from dcc.information_link l
where l.from_document_id = any(%(ids)s) or l.to_document_id = any(%(ids)s) order by l.id
"""
WBS_SQL = "select w.code, w.parent_code from dcc.wbs_element w order by w.code"


def link_from_row(row: Sequence) -> Link:
    link_id, from_doc, from_rev, to_doc, to_rev, link_type, provenance = row
    return Link(from_document_id=from_doc, to_document_id=to_doc, link_type=link_type, provenance=provenance,
                from_revision_id=from_rev, to_revision_id=to_rev, id=link_id)


def revision_from_row(row: Sequence) -> Revision:
    rev_id, doc_id, rev_code, revision_date, stage, sender, permitted_use = row
    if not isinstance(revision_date, date):
        raise ValueError(f"revision {rev_id}: revision_date must be a date")
    return Revision(rev_id, doc_id, rev_code, revision_date, stage, sender, permitted_use)


def facts_from_rows(document_rows: Sequence[Sequence], revision_rows: Sequence[Sequence],
                    link_rows: Sequence[Sequence], wbs_rows: Sequence[Sequence]) -> Facts:
    """Faithful mapping of registered rows into Stage-2 facts; nothing is derived or inferred."""
    revisions: dict[int, list[Revision]] = {}
    for row in revision_rows:
        r = revision_from_row(row)
        revisions.setdefault(r.document_id, []).append(r)
    documents = {}
    for doc_id, doc_code, doc_type, discipline, wbs, originator in document_rows:
        documents[doc_id] = Document(doc_id, doc_code, doc_type, discipline, wbs, originator,
                                     tuple(revisions.get(doc_id, ())))
    return Facts(documents=documents, wbs_parent={code: parent for code, parent in wbs_rows},
                 links=tuple(link_from_row(row) for row in link_rows))


def load_stage2_facts(conn, pool: Sequence[PoolEntry], anchors: Sequence[int]) -> Facts:
    """Facts for the pool, the anchors and every document one link away from them, with all their
    revisions; links touching any of those documents (covers M3 and supersession among candidates);
    the WBS hierarchy. Read-only."""
    seed = sorted({e.document_id for e in pool} | set(anchors))
    first = conn.execute(LINKS_SQL, {"ids": seed}).fetchall()
    ids = sorted(set(seed) | {row[1] for row in first} | {row[3] for row in first})
    links = conn.execute(LINKS_SQL, {"ids": ids}).fetchall()
    return facts_from_rows(conn.execute(DOCUMENTS_SQL, (ids,)).fetchall(),
                           conn.execute(REVISIONS_SQL, (ids,)).fetchall(),
                           links, conn.execute(WBS_SQL).fetchall())


# ---------------------------------------------------------------------------------------------
# Stage 2
# ---------------------------------------------------------------------------------------------

def execute_ir1(plan_: Plan, pool: Sequence[PoolEntry], facts: Facts, anchors: Sequence[int],
                switches: Switches) -> Outcome:
    """The frozen engine, unchanged."""
    return ir1_engine.run(plan_, pool, facts, anchors, switches)


# ---------------------------------------------------------------------------------------------
# Response conversion
# ---------------------------------------------------------------------------------------------

TRIGRAM_SQL = """
select e.revision_id, case when %(q)s = '' then 0 else extensions.word_similarity(%(q)s, e.trgm_text) end
from dcc.search_entry e where e.revision_id = any(%(ids)s)
"""


@dataclass(frozen=True)
class IR1Response:
    response: SearchResponse                  # the conventional response shape; Gate A compares this
    interpretation: dict                      # adapter-only record, kept outside the response


def _rounded(row: RankRow) -> dict[str, float]:
    """The retriever's debug scores (BaselineFtsRetriever.search), for identical debug output."""
    return {"score": round(row.score, 4), "coverage": round(row.coverage, 4),
            "fts_rank": round(row.fts_rank, 4), "trigram": round(row.trigram, 4)}


def matches_for(outcome: Outcome, rows: Sequence[RankRow]) -> tuple[list[RawMatch], list[int]]:
    """RawMatch per result for its representing revision. A pool document shown with the revision
    the ranking matched keeps that row's scores; any other revision (M4 choice, outside the pool)
    gets no ranking scores and needs a trigram value for its evidence."""
    row_by_doc = {r.document_id: r for r in rows}
    matches, need_trigram = [], []
    for result in outcome.results:
        revision_id = result.revision.revision.id
        row = row_by_doc.get(result.document_id)
        if row is not None and row.revision_id == revision_id:
            matches.append(RawMatch(revision_id, result.document_id, scores=_rounded(row)))
        else:
            matches.append(RawMatch(revision_id, result.document_id, scores={}))
            need_trigram.append(revision_id)
    return matches, need_trigram


def related_evidence(result, facts: Facts) -> list[EvidenceItem]:
    """M3 line 124 / S2.4: one related_document item per supporting path, in path order."""
    return [EvidenceItem(kind="related_document", source="registered", link_type=p.link_type,
                         text=f"Linked to {facts.document(p.anchor_document_id).doc_code} ({p.link_type})")
            for p in result.paths]


def interpretation_record(plan_: Plan, outcome: Outcome) -> dict:
    a = plan_.audit
    return {
        "engine": ENGINE_LABEL,
        "request_id": plan_.request_id,
        "switches": {"m2": outcome.switches.m2, "m3": outcome.switches.m3, "m4": outcome.switches.m4},
        "is_default": plan_.is_default,
        "lexical_query": outcome.lexical_query,
        "anchor_query": outcome.anchor_query,
        "hard_filters": dict(outcome.filters),
        "soft_clues": [{"field": c.field, "code": c.code, "strength": c.strength,
                        "frozen_strength": c.frozen_strength, "boost": c.boost, "source": c.source}
                       for c in plan_.soft_clues],
        "relation": None if plan_.relation is None else vars(plan_.relation).copy(),
        "revision_state": plan_.revision_state,
        "document_state": plan_.document_state,
        "audit": {"raw_text": a.raw_text, "text": a.text, "approx": list(a.approx), "verify": list(a.verify),
                  "withdrawn": list(a.withdrawn), "removed_phrases": list(a.removed_phrases),
                  "pool_text_fallback": a.pool_text_fallback},
        "rejected_linked": list(outcome.rejected_linked),
        "revisions": [{"rank": r.rank, "document_id": r.document_id, "in_pool": r.in_pool,
                       "revision_id": r.revision.revision.id, "basis": r.revision.basis,
                       "requested_state": r.revision.requested_state, "satisfied": r.revision.satisfied,
                       "note": r.revision.note} for r in outcome.results],
    }


def to_response(conn, plan_: Plan, outcome: Outcome, rows: Sequence[RankRow], facts: Facts,
                extra_filters: Filters = Filters(), debug: bool = False) -> IR1Response:
    """Build the conventional SearchResponse for the IR-1 results with the existing evidence
    and fact builders, as app.search.search does, plus related_document evidence for M3 paths."""
    query = outcome.lexical_query
    filters = conventional_filters(plan_, extra_filters)
    matches, need_trigram = matches_for(outcome, rows)
    retriever = baseline_fts.BaselineFtsRetriever()
    stripped = query.strip()
    if stripped and rows:                                       # as BaselineFtsRetriever.search
        tsq = rows[0].tsq
        trigram = {r.revision_id: r.trigram for r in rows}
        if need_trigram:
            trigram.update(dict(conn.execute(TRIGRAM_SQL, {"q": stripped, "ids": need_trigram}).fetchall()))
        fields, passages = retriever._evidence(conn, [m.revision_id for m in matches], tsq)
        for match in matches:
            match.field_hits = retriever._field_hits(fields.get(match.revision_id, []),
                                                     trigram=trigram.get(match.revision_id, 0.0))
            match.snippets = passages.get(match.revision_id, []) if tsq else []
    revision_facts = load_facts(conn, [m.revision_id for m in matches])
    results = []
    for rank_, (match, result) in enumerate(zip(matches, outcome.results), 1):
        item = build_result(rank_, match, revision_facts[match.revision_id], filters, debug)
        if result.paths:
            item = item.model_copy(update={"evidence": item.evidence + related_evidence(result, facts)})
        results.append(item)
    response = SearchResponse(query=query, filters={k: str(v) for k, v in filters.active().items()},
                              engine=ENGINE_LABEL, results=results)
    return IR1Response(response, interpretation_record(plan_, outcome))


def gate_a_view(response: SearchResponse) -> dict:
    """Decision 1: the response compared in Gate A, minus only the adapter's engine label."""
    data = response.model_dump(mode="json")
    data.pop("engine")
    return data


# ---------------------------------------------------------------------------------------------
# One request end to end (not executed in this stage)
# ---------------------------------------------------------------------------------------------

def search_ir1(conn, plan_: Plan, switches: Switches = Switches(), extra_filters: Filters = Filters(),
               debug: bool = False, ranker: Ranker = rank) -> IR1Response:
    pool, rows = conventional_pool(conn, plan_, switches, extra_filters, ranker)
    anchors = anchor_ranking(conn, plan_, switches, ranker)
    facts = load_stage2_facts(conn, pool, anchors)
    outcome = execute_ir1(plan_, pool, facts, anchors, switches)
    return to_response(conn, plan_, outcome, rows, facts, extra_filters, debug)
