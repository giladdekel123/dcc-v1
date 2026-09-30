"""Search orchestration: retriever -> registered facts -> evidence."""

import psycopg

from app.evidence.builder import build_result
from app.evidence.facts import load_facts
from app.models import SearchResponse
from app.retrieval.base import Filters, Retriever
from app.retrieval.baseline_fts import BaselineFtsRetriever

MAX_RESULTS = 10
RETRIEVER: Retriever = BaselineFtsRetriever()


def search(conn: psycopg.Connection, query: str, filters: Filters,
           limit: int = MAX_RESULTS, debug: bool = False) -> SearchResponse:
    matches = RETRIEVER.search(conn, query, filters, min(limit, MAX_RESULTS))
    facts = load_facts(conn, [m.revision_id for m in matches])
    return SearchResponse(
        query=query,
        filters={k: str(v) for k, v in filters.active().items()},
        engine=RETRIEVER.name,
        results=[build_result(rank, m, facts[m.revision_id], filters, debug) for rank, m in enumerate(matches, 1)],
    )
