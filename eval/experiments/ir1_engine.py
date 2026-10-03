"""IR-1 stage 2: pure mechanisms over supplied candidate facts. No database, no retrieval.

Specification: IR1_PREREGISTRATION.md section 6, IR1_CLARIFICATIONS.md (C1, C2) and
IR1_STAGE2_CLARIFICATIONS.md (S1-S6). The caller supplies the conventional candidate pool (with
unrounded baseline scores and matched revisions), the anchor ranking, and the registered facts
(documents, revisions, links, WBS parents). This module never retrieves anything.

Each mechanism is a separate function; `run` applies them in the S4 order, and `Switches` turns
M2, M3 and M4 off independently for the preregistered ablations (S5 and
IR1_STAGE2_ABLATION_ADDENDUM.md A1). Where the specification says to stop and report,
UndefinedRuleError is raised.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final

from eval.experiments.ir1_request import (ANCHOR_COUNT, CONTEXT_BOOST, LIKELY_BOOST, LINK_TYPES, POOL_SIZE,
                                          REVISION_STATES, Plan, Relation, SoftClue)

OUTPUT_SIZE: Final = 10                                                   # preregistration line 134
REGISTERED: Final = "registered"                                          # S2.1
CONSTRUCTION: Final = "construction"                                      # S3.1
REGISTERED_LINK_TYPES: Final = tuple(t for t in LINK_TYPES if t != "any")  # dcc.information_link check
FILTER_KEYS: Final = ("doc_type", "discipline", "stage", "org")           # keys a Plan can produce


class UndefinedRuleError(ValueError):
    """Execution reached a case the frozen specification says to stop and report."""


# ---------------------------------------------------------------------------------------------
# Supplied facts
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Revision:
    id: int
    document_id: int
    rev_code: str
    revision_date: date
    stage: str
    sender: str | None = None
    permitted_use: str | None = None                  # of the CURRENT status (revision_summary)
    past_permitted_uses: tuple[str, ...] = ()         # earlier statuses; never qualify (S3.1)


@dataclass(frozen=True)
class Document:
    id: int
    doc_code: str
    doc_type: str
    discipline: str
    wbs: str
    originator: str
    revisions: tuple[Revision, ...]

    def __post_init__(self):
        if not self.revisions:
            raise ValueError(f"document {self.id} has no revisions")
        if any(r.document_id != self.id for r in self.revisions):
            raise ValueError(f"document {self.id} lists another document's revision")
        if len({r.id for r in self.revisions}) != len(self.revisions):
            raise ValueError(f"document {self.id} lists a revision twice")

    def revision(self, revision_id: int) -> Revision:
        for r in self.revisions:
            if r.id == revision_id:
                return r
        raise ValueError(f"revision {revision_id} is not a revision of document {self.id}")


@dataclass(frozen=True)
class Link:
    """One information_link row: `from_document_id <link_type> to_document_id`."""
    from_document_id: int
    to_document_id: int
    link_type: str
    provenance: str = REGISTERED
    from_revision_id: int | None = None
    to_revision_id: int | None = None
    id: int | None = None                             # stable identifier, for evidence order only

    def __post_init__(self):
        if self.link_type not in REGISTERED_LINK_TYPES:
            raise ValueError(f"unknown link type {self.link_type!r}")
        if self.from_document_id == self.to_document_id:
            raise ValueError("a link joins two different documents")


@dataclass(frozen=True)
class Facts:
    documents: Mapping[int, Document]                 # every pool and linked document
    wbs_parent: Mapping[str, str | None]              # WBS element -> parent (existing hierarchy)
    links: tuple[Link, ...] = ()

    def document(self, document_id: int) -> Document:
        if document_id not in self.documents:
            raise ValueError(f"no facts supplied for document {document_id}")
        return self.documents[document_id]


@dataclass(frozen=True)
class PoolEntry:
    """One conventional candidate, in baseline order."""
    document_id: int
    baseline_score: float                             # unrounded SQL score (S1.5, S6)
    matched_revision_id: int


@dataclass(frozen=True)
class Switches:
    m2: bool = True
    m3: bool = True
    m4: bool = True                                   # M1 is never ablated (S5)


# ---------------------------------------------------------------------------------------------
# M1: hard-filter eligibility (existing filter semantics, S2.2, S3.5)
# ---------------------------------------------------------------------------------------------

def eligible_revisions(doc: Document, filters: Mapping[str, str]) -> tuple[Revision, ...]:
    """The revisions satisfying every active hard filter, as the existing filters do row by row:
    doc_type and discipline are document facts; stage is a revision fact; the organisation filter
    matches the document's originator OR the revision's sender, so originator-only matching leaves
    every revision eligible (S3.5 item 9). Empty means the document is not eligible."""
    unknown = set(filters) - set(FILTER_KEYS)
    if unknown:
        raise ValueError(f"unknown hard filters {sorted(unknown)}")
    if "doc_type" in filters and doc.doc_type != filters["doc_type"]:
        return ()
    if "discipline" in filters and doc.discipline != filters["discipline"]:
        return ()
    stage, org = filters.get("stage"), filters.get("org")
    return tuple(r for r in doc.revisions
                 if (stage is None or r.stage == stage)
                 and (org is None or doc.originator == org or r.sender == org))


# ---------------------------------------------------------------------------------------------
# M2: soft clues (S1)
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ClueMatch:
    field: str
    code: str
    strength: str                                     # effective strength (C1)
    boost: float
    source: str


@dataclass(frozen=True)
class M2Score:
    document_id: int
    baseline_score: float
    matches: tuple[ClueMatch, ...]
    soft_boost: float
    boosted_score: float


def organisation_matches(doc: Document, code: str) -> bool:
    """S1.3: the existing organisation filter - document originator or any revision's sender."""
    return doc.originator == code or any(r.sender == code for r in doc.revisions)


def clue_matches(clue: SoftClue, doc: Document, wbs_parent: Mapping[str, str | None]) -> bool:
    """Exact code equality on registered facts. stage and sender match any revision (S1.2); wbs
    matches the element or a direct child by the supplied parent links (S1.4)."""
    if clue.field == "doc_type":
        return doc.doc_type == clue.code
    if clue.field == "discipline":
        return doc.discipline == clue.code
    if clue.field == "wbs":
        return doc.wbs == clue.code or wbs_parent.get(doc.wbs) == clue.code
    if clue.field == "stage":
        return any(r.stage == clue.code for r in doc.revisions)
    if clue.field in ("originator", "sender"):
        return organisation_matches(doc, clue.code)
    raise ValueError(f"unknown clue field {clue.field!r}")


def m2_score(soft_clues: Sequence[SoftClue], doc: Document, wbs_parent: Mapping[str, str | None],
             baseline_score: float) -> M2Score:
    """S1.1: every matching clue counts; soft_boost = 0.5 x likely matches + 0.1 x context matches."""
    matches = tuple(ClueMatch(c.field, c.code, c.strength, c.boost, c.source)
                    for c in soft_clues if clue_matches(c, doc, wbs_parent))
    likely = sum(1 for m in matches if m.strength == "likely")
    context = sum(1 for m in matches if m.strength == "context")
    if likely + context != len(matches):
        raise ValueError("a soft clue must be likely or context")
    boost = LIKELY_BOOST * likely + CONTEXT_BOOST * context
    return M2Score(doc.id, baseline_score, matches, boost, baseline_score + boost)


def m2_order(pool: Sequence[PoolEntry], scores: Mapping[int, M2Score], facts: Facts) -> tuple[int, ...]:
    """S1.5: boosted score desc, matched revision date desc, document id asc."""
    def key(entry: PoolEntry):
        matched = facts.document(entry.document_id).revision(entry.matched_revision_id)
        return (-scores[entry.document_id].boosted_score, -matched.revision_date.toordinal(), entry.document_id)
    return tuple(e.document_id for e in sorted(pool, key=key))


# ---------------------------------------------------------------------------------------------
# M3: one-hop relationships (S2)
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Path:
    """One registered link from an anchor to a wanted document."""
    anchor_document_id: int
    anchor_rank: int
    link_type: str
    wanted_revision_id: int | None                    # the link's revision on the wanted side, if any
    anchor_revision_id: int | None
    link_id: int | None

    def sort_key(self):                               # S2.4: anchor rank, link type, then stable ids
        ids = (self.link_id, self.wanted_revision_id, self.anchor_revision_id)
        return (self.anchor_rank, self.link_type, *((v is None, v or 0) for v in ids))


@dataclass(frozen=True)
class LinkedDocument:
    document_id: int
    anchor_rank: int                                  # best (lowest) rank of an anchor it is linked to
    paths: tuple[Path, ...]                           # every supporting path, in S2.4 order


def select_anchors(anchor_ranking: Sequence[int]) -> tuple[int, ...]:
    """Line 116: the top 3 documents of the supplied baseline ranking of anchor_text."""
    return tuple(dict.fromkeys(anchor_ranking))[:ANCHOR_COUNT]


def linked_documents(anchors: Sequence[int], links: Sequence[Link], relation: Relation) -> tuple[LinkedDocument, ...]:
    """Lines 117-119 and S2.1/S2.3: documents one registered link away from an anchor, with the
    requested type (every type for `any`) and the wanted document on target_side. Identical paths
    merge. Sorted by document id. No hard filter here (see run); reached documents are not expanded."""
    rank = {doc: i for i, doc in enumerate(anchors, 1)}
    found: dict[int, set[Path]] = {}
    for link in links:
        if link.provenance != REGISTERED:
            continue
        if relation.link_type != "any" and link.link_type != relation.link_type:
            continue
        if relation.target_side == "from":                 # wanted <link_type> anchor
            wanted, anchor = link.from_document_id, link.to_document_id
            wanted_rev, anchor_rev = link.from_revision_id, link.to_revision_id
        else:                                               # anchor <link_type> wanted
            wanted, anchor = link.to_document_id, link.from_document_id
            wanted_rev, anchor_rev = link.to_revision_id, link.from_revision_id
        if anchor in rank:
            found.setdefault(wanted, set()).add(
                Path(anchor, rank[anchor], link.link_type, wanted_rev, anchor_rev, link.id))
    return tuple(LinkedDocument(doc, min(p.anchor_rank for p in paths),
                                tuple(sorted(paths, key=Path.sort_key)))
                 for doc, paths in sorted(found.items()))


def m3_order(m2_order: Sequence[int], linked: Sequence[LinkedDocument], boost: Mapping[int, float],
             baseline_score: Mapping[int, float], doc_code: Mapping[int, str]) -> tuple[int, ...]:
    """Lines 120-123: linked documents first, by soft-clue boost desc, best anchor rank asc,
    baseline score desc (0 if not in the pool), document code asc (then id, S2.3); then every
    other candidate in M2 order. Anchors are not removed."""
    pool = set(m2_order)
    if len(pool) != len(m2_order):
        raise ValueError("m2_order lists a document twice")
    missing = [d.document_id for d in linked if d.document_id not in boost or d.document_id not in doc_code]
    missing += [d for d in m2_order if d not in baseline_score]
    if missing:
        raise ValueError(f"boost, document code or baseline score missing for documents {sorted(set(missing))}")

    def key(d: LinkedDocument):
        score = baseline_score[d.document_id] if d.document_id in pool else 0.0
        return (-boost[d.document_id], d.anchor_rank, -score, doc_code[d.document_id], d.document_id)

    first = tuple(d.document_id for d in sorted(linked, key=key))
    placed = set(first)
    return first + tuple(d for d in m2_order if d not in placed)


# ---------------------------------------------------------------------------------------------
# M4: requested state (S3)
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class RevisionChoice:
    revision: Revision
    requested_state: str                              # the plan's revision_state
    satisfied: bool | None                            # False: S3.2 fallback; None: M4 off, not evaluated
    note: str | None = None
    basis: str = "m4"                                 # m4 | conventional_baseline | m4_off_default


def rev_code_rank(rev_code: str) -> int:
    """dcc.rev_code_rank: P < C < A, then numerically (same-day tie-breaker only)."""
    if len(rev_code) != 3 or rev_code[0] not in "PCA" or not rev_code[1:].isdigit():
        raise ValueError(f"invalid revision code {rev_code!r}")
    return "PCA".index(rev_code[0]) * 1000 + 1000 + int(rev_code[1:])


def recency_order(revisions: Sequence[Revision]) -> tuple[Revision, ...]:
    """dcc.revision_summary: newest first by revision_date, then rev_code_rank. One document only."""
    if len({r.document_id for r in revisions}) > 1:
        raise ValueError("revisions of more than one document")
    if len({r.rev_code for r in revisions}) != len(revisions):
        raise ValueError("a revision code appears twice")
    return tuple(sorted(revisions, key=lambda r: (r.revision_date, rev_code_rank(r.rev_code)), reverse=True))


def best_match_revision(doc: Document, eligible: Sequence[Revision], baseline_revision_id: int | None,
                        paths: Sequence[Path] = ()) -> Revision:
    """In-pool: the baseline matched revision (S3.5 item 6). Outside the pool (S3.3 with S3.5 item 7):
    the one eligible revision named by revision-specific paths; several -> stop; none -> the latest
    eligible revision. Ineligible paths stay evidence but cannot supply the revision."""
    eligible_ids = {r.id for r in eligible}
    if baseline_revision_id is not None:
        if baseline_revision_id not in eligible_ids:
            raise ValueError(f"baseline revision {baseline_revision_id} of document {doc.id} fails a hard filter")
        return doc.revision(baseline_revision_id)
    named = {p.wanted_revision_id for p in paths if p.wanted_revision_id is not None}
    for revision_id in named:
        doc.revision(revision_id)                           # a path must name this document's revision
    named &= eligible_ids
    if len(named) > 1:
        raise UndefinedRuleError(f"document {doc.id}: supporting paths name different eligible revisions "
                                 f"{sorted(named)} (S3.3)")
    if named:
        return doc.revision(named.pop())
    return recency_order(eligible)[0]


def representing_revision(revision_state: str, doc: Document, filters: Mapping[str, str],
                          baseline_revision_id: int | None, paths: Sequence[Path] = ()) -> RevisionChoice:
    """Lines 127-130 with S3.1-S3.3 and S3.5: the revision that represents the document."""
    if revision_state not in REVISION_STATES:
        raise ValueError(f"unknown revision_state {revision_state!r}")
    eligible = eligible_revisions(doc, filters)
    if not eligible:
        raise ValueError(f"document {doc.id} has no revision satisfying the hard filters (S3.5 item 8)")
    if revision_state == "best_match":
        return RevisionChoice(best_match_revision(doc, eligible, baseline_revision_id, paths), revision_state, True)
    ordered = recency_order(eligible)
    if revision_state.endswith("_for_construction"):
        ordered = tuple(r for r in ordered if r.permitted_use == CONSTRUCTION)       # current use only
    if not ordered:                                                                   # S3.2
        fallback = best_match_revision(doc, eligible, baseline_revision_id, paths)
        return RevisionChoice(fallback, revision_state, False,
                              f"requested revision state {revision_state} could not be satisfied; "
                              f"showing the best match {fallback.rev_code}")
    return RevisionChoice(ordered[0] if revision_state.startswith("latest") else ordered[-1], revision_state, True)


def m4_off_default_revision(doc: Document, filters: Mapping[str, str]) -> Revision:
    """Ablation addendum A1: with M4 disabled, an outside-pool M3 document is represented by its
    latest registered revision that satisfies every active revision-level hard filter. No
    revision_state, link revision, S3.3, construction or supersession logic is used."""
    eligible = eligible_revisions(doc, filters)
    if not eligible:
        raise ValueError(f"document {doc.id} has no revision satisfying the hard filters "
                         "(addendum A1 item 9: wiring/invariant error)")
    return recency_order(eligible)[0]


def m4_off_choice(plan: Plan, doc: Document, filters: Mapping[str, str],
                  baseline_revision_id: int | None) -> RevisionChoice:
    """S5 and addendum A1: M4 disabled. In-pool documents keep the conventional baseline revision;
    outside-pool documents get the A1 default. The requested state is recorded, not evaluated."""
    if baseline_revision_id is not None:
        return RevisionChoice(doc.revision(baseline_revision_id), plan.revision_state, None,
                              "M4 disabled: conventional baseline revision; requested revision state not evaluated",
                              "conventional_baseline")
    revision = m4_off_default_revision(doc, filters)
    return RevisionChoice(revision, plan.revision_state, None,
                          f"M4 disabled: latest eligible revision {revision.rev_code} shown as a neutral "
                          "representation default; requested revision state not evaluated",
                          "m4_off_default")


def current_order(order: Sequence[int], links: Sequence[Link]) -> tuple[int, ...]:
    """Lines 131-132 with S2.1 and S3.4: each candidate superseded by another candidate (registered
    `supersedes`, document level) is placed immediately below the candidate that supersedes it.
    Other candidates keep their order. Two superseders, one document superseding two, or a cycle
    stop with UndefinedRuleError."""
    candidates = set(order)
    if len(candidates) != len(order):
        raise ValueError("order lists a document twice")
    superseder: dict[int, int] = {}
    superseded: dict[int, int] = {}
    for new, old in sorted({(l.from_document_id, l.to_document_id) for l in links
                            if l.provenance == REGISTERED and l.link_type == "supersedes"}):
        if new not in candidates or old not in candidates:
            continue
        if superseder.setdefault(old, new) != new:
            raise UndefinedRuleError(f"document {old} is superseded by two candidates ({superseder[old]}, {new})")
        if superseded.setdefault(new, old) != old:
            raise UndefinedRuleError(f"document {new} supersedes two candidates ({superseded[new]}, {old})")
    for start in superseder:                                   # cycles have no top document
        seen, doc = set(), start
        while doc in superseder:
            if doc in seen:
                raise UndefinedRuleError(f"supersedes cycle through document {doc}")
            seen.add(doc)
            doc = superseder[doc]
    out: list[int] = []
    for doc in order:
        if doc in superseder:
            continue                                           # placed under its superseder
        while doc is not None:
            out.append(doc)
            doc = superseded.get(doc)
    return tuple(out)


# ---------------------------------------------------------------------------------------------
# Orchestration (S4) and ablations (S5)
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ResultEntry:
    rank: int
    document_id: int
    in_pool: bool
    revision: RevisionChoice
    paths: tuple[Path, ...] = ()                      # related_document evidence, S2.4 order


@dataclass(frozen=True)
class Outcome:
    switches: Switches
    lexical_query: str                                # the query the retrieval layer ranks for the pool
    anchor_query: str | None                          # the query for the anchor ranking, if M3 runs
    filters: Mapping[str, str]
    m2_scores: tuple[M2Score, ...]                    # pool, in pool order
    linked: tuple[LinkedDocument, ...]                # eligible linked documents
    linked_scores: tuple[M2Score, ...]                # soft boosts of eligible linked documents
    rejected_linked: tuple[int, ...]                  # linked documents failing the hard filters (S2.2)
    order: tuple[int, ...]                            # full ordered list before the cut
    results: tuple[ResultEntry, ...]                  # the top OUTPUT_SIZE, with representing revisions


def lexical_query(plan: Plan, switches: Switches) -> str:
    """S5: with M2 disabled the retrieval layer ranks the frozen text, not the C2 pool text."""
    return plan.pool_text if switches.m2 else plan.audit.text


def anchor_query(plan: Plan, switches: Switches) -> str | None:
    return plan.relation.anchor_text if switches.m3 and plan.relation is not None else None


def run(plan: Plan, pool: Sequence[PoolEntry], facts: Facts, anchor_ranking: Sequence[int] = (),
        switches: Switches = Switches()) -> Outcome:
    """S4: M1 (supplied pool) -> M2 -> M3 -> document_state -> top 10 -> M4 revision choice.

    `pool` is the conventional ranking of lexical_query(plan, switches) with plan.filters(), at most
    POOL_SIZE documents, in baseline order; `anchor_ranking` is the conventional ranking of
    anchor_query(plan, switches) with no filters, given only when M3 runs."""
    filters = plan.filters()                                                    # 1. M1
    if len(pool) > POOL_SIZE:                                                   # 2. pool
        raise ValueError(f"the pool holds at most {POOL_SIZE} documents")
    if len({e.document_id for e in pool}) != len(pool):
        raise ValueError("the pool lists a document twice")
    for entry in pool:
        doc = facts.document(entry.document_id)
        doc.revision(entry.matched_revision_id)
        if entry.matched_revision_id not in {r.id for r in eligible_revisions(doc, filters)}:
            raise ValueError(f"pool document {doc.id}: matched revision fails the hard filters")
    a_query = anchor_query(plan, switches)
    if a_query is None and anchor_ranking:
        raise ValueError("an anchor ranking was supplied but M3 does not run for this plan")

    clues = plan.soft_clues if switches.m2 else ()                              # 3. M2
    scores = {e.document_id: m2_score(clues, facts.document(e.document_id), facts.wbs_parent, e.baseline_score)
              for e in pool}
    order = m2_order(pool, scores, facts) if switches.m2 else tuple(e.document_id for e in pool)

    linked: tuple[LinkedDocument, ...] = ()                                     # 4. M3
    linked_scores: tuple[M2Score, ...] = ()
    rejected: tuple[int, ...] = ()
    if a_query is not None:
        found = linked_documents(select_anchors(anchor_ranking), facts.links, plan.relation)
        linked = tuple(d for d in found if eligible_revisions(facts.document(d.document_id), filters))
        rejected = tuple(d.document_id for d in found if d not in linked)
        baseline = {e.document_id: e.baseline_score for e in pool}                # 0 outside the pool
        linked_scores = tuple(m2_score(clues, facts.document(d.document_id), facts.wbs_parent,
                                       baseline.get(d.document_id, 0.0)) for d in linked)
        boost = {s.document_id: s.soft_boost for s in linked_scores}
        order = m3_order(order, linked, boost, baseline,
                         {d.document_id: facts.document(d.document_id).doc_code for d in linked})

    if switches.m4 and plan.document_state == "current":                       # 5. document_state
        order = current_order(order, facts.links)

    top = order[:OUTPUT_SIZE]                                                   # 6. cut

    matched = {e.document_id: e.matched_revision_id for e in pool}              # 7. M4
    paths = {d.document_id: d.paths for d in linked}

    def choose(doc_id: int) -> RevisionChoice:
        doc = facts.document(doc_id)
        if switches.m4:
            return representing_revision(plan.revision_state, doc, filters, matched.get(doc_id),
                                         paths.get(doc_id, ()))
        return m4_off_choice(plan, doc, filters, matched.get(doc_id))         # S5, addendum A1

    results = tuple(ResultEntry(rank, doc_id, doc_id in matched, choose(doc_id), paths.get(doc_id, ()))
                    for rank, doc_id in enumerate(top, 1))
    return Outcome(switches=switches, lexical_query=lexical_query(plan, switches), anchor_query=a_query,
                   filters=filters, m2_scores=tuple(scores[e.document_id] for e in pool), linked=linked,
                   linked_scores=linked_scores, rejected_linked=rejected, order=order, results=results)
