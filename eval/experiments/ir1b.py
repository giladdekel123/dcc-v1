"""IR-1b: preserve the user's wording, add structured intelligence (IR1B_PREREGISTRATION.md,
IR1B_CLARIFICATIONS.md). Experiment-only; frozen IR-1 files are reused, never changed.

A condition is an IR1bConfig of five switches:
- base: the wording sent to conventional retrieval, the request's raw_text ("raw") or the frozen
  interpreted text ("text");
- delete: apply the frozen C2 phrase deletion (ir1_request.remove_context_sources) to that wording;
- boost, relationships, revisions: the frozen Stage-2 engine's Switches(m2, m3, m4).

Boosts and deletion are independent (preregistration section 5): the engine re-scores whatever pool it
is given, so "boosts" only switches m2, and "deletion" only changes the wording the pool is ranked on.
The wording sent is used for ranking and as the evidence query terms.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.models import SearchResponse
from app.retrieval.base import Filters
from eval.experiments import ir1_integration as ia
from eval.experiments.ir1_engine import Facts, Outcome, PoolEntry, Switches
from eval.experiments.ir1_request import POOL_SIZE, Plan, remove_context_sources

ENGINE_LABEL = "ir1b"
BASES = ("raw", "text")


@dataclass(frozen=True)
class IR1bConfig:
    base: str
    boost: bool
    delete: bool
    relationships: bool
    revisions: bool

    def __post_init__(self):
        if self.base not in BASES:
            raise ValueError(f"base must be one of {BASES}")

    def switches(self) -> Switches:
        return Switches(m2=self.boost, m3=self.relationships, m4=self.revisions)


# Preregistration section 4. Condition 0 is ordinary conventional search (app.search.search), not
# an IR1bConfig.
BASELINE = "0"
CONDITIONS: dict[str, IR1bConfig] = {
    "1": IR1bConfig("text", boost=True, delete=True, relationships=True, revisions=True),
    "2": IR1bConfig("raw", boost=False, delete=False, relationships=False, revisions=False),
    "3": IR1bConfig("text", boost=False, delete=False, relationships=False, revisions=False),
    "4": IR1bConfig("raw", boost=True, delete=False, relationships=False, revisions=False),
    "5": IR1bConfig("raw", boost=False, delete=True, relationships=False, revisions=False),
    "6": IR1bConfig("raw", boost=True, delete=True, relationships=False, revisions=False),
    "7": IR1bConfig("raw", boost=False, delete=False, relationships=True, revisions=False),
    "8": IR1bConfig("raw", boost=False, delete=False, relationships=False, revisions=True),
    "9": IR1bConfig("raw", boost=True, delete=False, relationships=True, revisions=True),
    "10": IR1bConfig("raw", boost=True, delete=True, relationships=True, revisions=True),
    "11": IR1bConfig("raw", boost=False, delete=False, relationships=True, revisions=True),
    "12": IR1bConfig("raw", boost=True, delete=False, relationships=False, revisions=True),
    "13": IR1bConfig("raw", boost=True, delete=False, relationships=True, revisions=False),
}
CONDITIONS["9r"] = CONDITIONS["9"]
NAMES = {
    "0": "Ordinary search baseline", "1": "Frozen IR-1 full reference", "2": "Original wording, nothing added",
    "3": "Interpreted wording, nothing added", "4": "Original + uncertain-clue boosts",
    "5": "Original minus clue phrases", "6": "Original + boosts, minus clue phrases",
    "7": "Original + relationships", "8": "Original + revision/version intelligence", "9": "Additive candidate",
    "10": "Additive candidate + phrase deletion", "11": "Additive minus boosts",
    "12": "Additive minus relationships", "13": "Additive minus revision/version intelligence",
    "9r": "Exact repeat of condition 9",
}


@dataclass(frozen=True)
class LexicalQuery:
    text: str                                  # sent to conventional retrieval and used for evidence
    base_text: str                             # the chosen wording before deletion
    removed_phrases: tuple[str, ...]
    fallback: bool                             # deletion would have emptied the wording


def lexical_query(plan: Plan, config: IR1bConfig) -> LexicalQuery:
    """Preregistration section 5: the chosen wording, then (if configured) the frozen C2 deletion of
    context-clue source phrases; no other rewriting. Overlapping sources raise the frozen PlanError."""
    base = plan.audit.raw_text if config.base == "raw" else plan.audit.text
    if not config.delete:
        return LexicalQuery(base, base, (), False)
    sources = tuple(c.source for c in plan.soft_clues if c.strength == "context")
    text, removed, fallback = remove_context_sources(base, sources)
    return LexicalQuery(text, base, removed, fallback)


@dataclass(frozen=True)
class Pipeline:
    query: LexicalQuery
    rows: tuple[ia.RankRow, ...]
    pool: tuple[PoolEntry, ...]
    anchors: tuple[int, ...]
    facts: Facts
    outcome: Outcome


def run_pipeline(conn, plan: Plan, config: IR1bConfig, ranker: ia.Ranker = ia.rank,
                 facts_loader=ia.load_stage2_facts) -> Pipeline:
    """Conventional ranking of the IR-1b wording (pool of 50, the plan's M1 filters), anchors as frozen
    (only with relationships on), Stage-2 facts, and the frozen engine with this config's switches."""
    switches = config.switches()
    query = lexical_query(plan, config)
    rows = ranker(conn, query.text, ia.conventional_filters(plan), POOL_SIZE)
    pool = tuple(PoolEntry(r.document_id, r.score, r.revision_id) for r in rows)
    anchors = ia.anchor_ranking(conn, plan, switches, ranker)
    facts = facts_loader(conn, pool, anchors)
    outcome = ia.execute_ir1(plan, pool, facts, anchors, switches)
    return Pipeline(query, tuple(rows), pool, anchors, facts, outcome)


def interpretation_record(plan: Plan, config: IR1bConfig, condition: str | None, p: Pipeline) -> dict:
    """Audit only. The frozen IR-1 record is kept under "ir1", except its lexical_query, which would
    name the IR-1 wording; the wording actually sent is under "lexical_query"."""
    ir1 = ia.interpretation_record(plan, p.outcome)
    ir1.pop("lexical_query")
    return {
        "engine": ENGINE_LABEL,
        "condition": condition,
        "condition_name": NAMES.get(condition) if condition else None,
        "config": {"base": config.base, "boost": config.boost, "delete": config.delete,
                   "relationships": config.relationships, "revisions": config.revisions},
        "original_text": plan.audit.raw_text,
        "interpreted_text": plan.audit.text,
        "lexical_query": p.query.text,
        "deleted_phrases": list(p.query.removed_phrases),
        "deletion_fallback": p.query.fallback,
        "anchors": list(p.anchors),
        "ir1": ir1,
    }


def search_ir1b(conn, plan: Plan, config: IR1bConfig, condition: str | None = None, debug: bool = False,
                ranker: ia.Ranker = ia.rank) -> ia.IR1Response:
    """One request under one IR-1b condition: the conventional SearchResponse plus the audit record."""
    p = run_pipeline(conn, plan, config, ranker)
    matches, need_trigram = ia.matches_for(p.outcome, p.rows)
    response = ia.build_search_response(conn, p.query.text, ia.conventional_filters(plan), p.rows, matches,
                                        need_trigram, [ia.related_evidence(r, p.facts) for r in p.outcome.results],
                                        debug)
    response = response.model_copy(update={"engine": ENGINE_LABEL})
    return ia.IR1Response(response, interpretation_record(plan, config, condition, p))


def baseline_response(conn, plan: Plan, debug: bool = False, search=None) -> SearchResponse:
    """Condition 0: ordinary conventional search of the original wording with the plan's filters."""
    if search is None:
        from app.search import search
    return search(conn, plan.audit.raw_text, Filters(**plan.filters()), debug=debug)


def deletion_check(plans: Sequence[Plan]) -> dict:
    """Planning only (preregistration section 13): phrase deletion on the original wording of every
    plan. Returns counts and the ids of exceptional cases; no retrieval."""
    config = IR1bConfig("raw", boost=False, delete=True, relationships=False, revisions=False)
    out = {"plans": len(plans), "with_deletion": [], "no_context_sources": [], "unchanged": [],
           "fallback": [], "errors": {}}
    for p in plans:
        if not any(c.strength == "context" for c in p.soft_clues):
            out["no_context_sources"].append(p.request_id)
            continue
        try:
            q = lexical_query(p, config)
        except ValueError as e:                                  # PlanError is a ValueError
            out["errors"][p.request_id] = str(e)
            continue
        if q.fallback:
            out["fallback"].append(p.request_id)
        elif q.text == q.base_text:
            out["unchanged"].append(p.request_id)
        else:
            out["with_deletion"].append(p.request_id)
    return out
