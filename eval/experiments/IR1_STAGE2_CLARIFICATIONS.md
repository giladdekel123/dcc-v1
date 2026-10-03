# IR-1 Stage-2 Pre-Result Clarifications

## Status

- Written on 2026-10-03, after Stage 1 (request loading and planning, commit `51be04c`) and after
  the initial pure Stage-2 primitives exposed underspecified execution details.
- Written **before** any IR-1 retrieval or evaluation result. No IR-1 result has been run or
  inspected.
- No expected answers, frozen-58 retrieval results, baseline-result reports, corpus answer
  knowledge or blind S01–S12 answer key were used.
- `IR1_PREREGISTRATION.md`, `ir1_frozen58_annotations.yaml` and `IR1_CLARIFICATIONS.md` remain
  unchanged.
- This document resolves execution ambiguity only. Any later substantive change after results
  becomes a subsequent experiment, such as IR-1b.

Line numbers refer to `IR1_PREREGISTRATION.md` at commit `b557c18`.

## S1 — M2 soft-clue execution

**S1.1 — Multiple clues are cumulative.** Each matching soft clue contributes its own frozen boost
independently. For a candidate:

```
soft_boost = 0.5 × number_of_matching_likely_clues
           + 0.1 × number_of_matching_context_clues
```

Multiple matching clues of the same strength therefore accumulate. No cap is applied. Soft clues
never exclude a candidate.

**S1.2 — Revision-level metadata.** For revision-level metadata such as stage and sender, a
document matches the soft clue if **any** registered revision of that document matches the clue.
This follows the existing filter semantics and does not depend on the M4 representing revision.

**S1.3 — Organisation clues.** For M2 soft organisation clues, `originator` and `sender` use the
same existing organisation-filter meaning already used by M1: a document matches the organisation
clue if the existing organisation filter would match it through the relevant registered
document/revision facts. No new field-specific organisation matching semantic is introduced for
M2.

**S1.4 — WBS.** C1 remains controlling: every WBS clue is effective context, regardless of frozen
strength. A WBS context clue matches the specified WBS element itself or a **direct child** of that
element, using the existing project WBS parent-child representation. Hierarchy is not inferred from
WBS numbering.

**S1.5 — M2 ordering.** For each candidate:

```
boosted_score = unrounded_baseline_score + cumulative_soft_boost
```

Order by:

1. `boosted_score` descending;
2. the existing baseline tie-break: matched revision date descending;
3. document id ascending, as in the existing deterministic baseline ordering.

The unrounded SQL baseline score is used; the rounded/debug score is never used for ordering.
When no boosts apply, M2 preserves the conventional baseline ordering.

## S2 — M3 relationship execution

**S2.1 — Registered relationships.** For IR-1, "registered relationships" means
`information_link` records whose `provenance` is exactly `registered`. Extracted relationships do
not participate in M3. This also applies to the registered `supersedes` relationships used for
document-state handling.

**S2.2 — Hard filters remain hard.** Any document introduced through M3 relationship expansion
must satisfy the same active M1 hard filters as the original candidate pool. Relationship
expansion cannot bypass a confirmed hard constraint. If there are no M1 hard filters, this rule
has no effect.

**S2.3 — Existing frozen M3 behaviour remains.**

- Anchors are the top 3 documents of the baseline ranking of `anchor_text`, with no filters.
- One hop only.
- The requested `link_type` only, or any link type when `relation.link_type` is `any`.
- `target_side` identifies which end of the stored relationship contains the wanted document.
- Revision-level links resolve to their documents.
- Linked documents may be introduced from outside the original candidate pool.
- Repeated paths to the same document merge.
- Linked documents are ordered by the frozen M3 keys (lines 120–122).
- Non-linked documents retain their M2 order.
- Anchors are not automatically removed merely because they served as anchors.

For the final deterministic tie-break in M3, document code/id is ascending.

**S2.4 — Relationship evidence.** When several anchors and/or relationship types lead to the same
document, all registered supporting paths are retained for evidence, presented deterministically
in:

1. anchor-rank order;
2. then link type;
3. then stable identifier/order as needed.

This evidence ordering does not change ranking.

## S3 — M4 revision and document state

**S3.1 — Construction qualification.** For `latest_for_construction` and
`earliest_for_construction`, a revision qualifies when its **current** registered
status/permitted use is construction. A revision does not qualify merely because an earlier
historical status once permitted construction. This follows the existing
`revision_summary`/latest-by-use project model.

**S3.2 — Requested revision state cannot be satisfied.** If a requested `revision_state` cannot be
satisfied by a document:

- that document's baseline matched revision is retained when such a baseline matched revision
  exists;
- the interpretation/result evidence records explicitly that the requested revision state could
  not be satisfied for that document;
- no other revision is silently substituted.

If a document introduced by M3 lies outside the original baseline pool, has no baseline matched
revision, and cannot satisfy the requested `revision_state`:

- that document's S3.3 `best_match` revision is used as the fallback representing revision;
- the interpretation/result evidence records explicitly that the requested revision state could
  not be satisfied;
- the fallback revision is not claimed to satisfy the requested state.

This gives an outside-pool document the same fallback role that the baseline matched revision
provides for an in-pool document. This fallback does not change document ranking.

**S3.3 — `best_match` for an M3 document outside the baseline pool.** If a document introduced by
M3 lies outside the original baseline pool and therefore has no baseline matched revision, its
`best_match` revision is chosen as follows.

A. All registered supporting relationship paths that introduced the document are examined.

B. For revision selection only:

- if one or more supporting paths identify a specific revision on the wanted-document side, those
  revision-specific paths are considered;
- supporting paths that identify only the document do not override or conflict with a
  revision-specific path;
- if all revision-specific supporting paths identify the same revision, that revision is the
  `best_match`;
- if revision-specific supporting paths identify different revisions, execution stops and the case
  is reported as ambiguous;
- if no supporting path identifies a specific revision, the document's latest registered revision
  is the `best_match`.

C. Document-only supporting paths remain valid relationship evidence. They are ignored only for
choosing the `best_match` revision when a revision-specific path is available.

D. No additional lexical retrieval is performed to resolve the revision.

**S3.4 — Ambiguous supersession structures.** For `document_state: current`, the frozen rule
continues: a superseded candidate is placed immediately below the candidate that supersedes it.
If the supplied registered supersession graph contains a structure for which that rule does not
yield one unique deterministic order, including:

- one candidate superseded by multiple candidate superseders;
- one candidate superseding multiple candidate documents where "immediately below" is not uniquely
  satisfiable;
- a supersession cycle;

that request/run stops and is reported as an undefined execution case. No graph-resolution
precedence is invented inside IR-1.

**S3.5 — Revision-level hard filters remain hard.** M1 hard filters constrain not only document
membership but, where the filter depends on revision-level facts, the revision that may represent
that document.

- **Document-level** hard-filter facts constrain document membership.
- **Revision-level** hard-filter facts additionally constrain representing-revision selection.

For IR-1:

- a hard stage clue is revision-level;
- the sender component of a hard organisation clue is revision-level;
- the originator component of the existing organisation filter is document-level.

Therefore:

1. When M4 selects a representing revision, any active revision-level hard filter must still be
   satisfied by the selected revision.
2. When S3.3 chooses `best_match` for an M3-introduced document outside the original pool, a
   revision-specific relationship path may supply the representing revision only if that revision
   satisfies every active revision-level hard filter.
3. If a revision identified by an S3.3 relationship path does not satisfy the active revision-level
   hard filters, it is not eligible as the representing revision.
4. When no revision satisfies both the requested `revision_state` and the active revision-level
   hard filters, the requested `revision_state` is treated as unsatisfied.
5. The fallback representing revision must itself satisfy the active revision-level hard filters.
6. For an in-pool document, the conventional baseline matched revision is used as fallback when it
   satisfies those filters.
7. For an outside-pool M3 document, the S3.3 `best_match` procedure is applied only across
   revisions eligible under the active revision-level hard filters. Specifically:
   - revision-specific supporting paths whose wanted-side revision fails an active revision-level
     hard filter are ineligible for representing-revision selection;
   - those paths remain relationship evidence;
   - if the remaining eligible revision-specific paths all identify the same revision, that
     revision is used;
   - if they identify different eligible revisions, execution stops and the ambiguity is reported,
     as already specified by S3.3;
   - if no eligible revision-specific path remains, the latest registered revision that satisfies
     the active revision-level hard filters is used.
8. If the document has no registered revision satisfying the active revision-level hard filters,
   the document is not eligible for the IR-1 result set. A revision that violates a confirmed hard
   constraint is never displayed merely to retain the document.
9. Originator-only matching does not constrain revision selection, because originator is a
   document-level fact.
10. These rules introduce no additional lexical retrieval and do not alter the meaning of the hard
    filters.

The governing principle: a relationship or revision-state operation may change which revision
represents a qualifying document, but it may not cause the displayed result to violate a
confirmed M1 hard constraint.

## S4 — Operation order and scope

IR-1 executes in this order:

1. M1 hard filters define the conventional candidate-pool constraints.
2. Build the conventional candidate pool of 50 using the Stage-1 `pool_text` and the M1 filters.
3. **M2:** calculate cumulative soft boosts and establish the M2 order.
4. **M3:** if relation intent exists, perform the frozen one-hop relationship mechanism and
   establish the M3 order. M3-introduced documents must satisfy the M1 hard filters.
5. **document_state:** apply `document_state: current` supersession ordering to the **full**
   M3-ordered candidate list, including eligible documents introduced through M3.
6. Cut the resulting document list to the top 10.
7. **M4 revision_state:** choose the representing revision for each displayed document.

Revision-state selection does not change document ranking. Evidence is generated/rebuilt for the
representing revision after M4.

## S5 — Ablations

The preregistered M2, M3 and M4 ablations (line 263) mean:

**M2 disabled:**
- no soft-clue boosts;
- no C2 context-source lexical removal;
- WBS context clues have no M2 effect;
- the conventional lexical query uses the original frozen `text` rather than the C2-derived
  `pool_text`;
- M3, if enabled, receives soft boost = 0 for every document.

**M3 disabled:**
- no anchor search;
- no relationship expansion;
- no M3 relationship reordering.

**M4 disabled:**
- no `revision_state` selection beyond the conventional baseline representing revision;
- no `document_state` supersession reordering.

M1 is not ablated. Each mechanism remains independently switchable.

## S6 — Ordinary deterministic execution details

- Ranking calculations use unrounded baseline SQL scores.
- Debug/display rounding never determines order.
- The deterministic document-code/id tie-break is ascending wherever the frozen rule reaches that
  final tie-break.
- When M4 changes the representing revision, the existing evidence is rebuilt for that selected
  revision using the same query terms.
- Evidence formatting/order does not alter ranking.

## S7 — Scope

- Constants remain unchanged: candidate pool 50; likely +0.5; context +0.1; relation anchors 3.
- The original preregistration remains authoritative except where this prospective clarification
  resolves an execution ambiguity.
- `IR1_CLARIFICATIONS.md` remains authoritative for C1 and C2.
- The frozen annotations remain unchanged.
- No result-informed modification has occurred.
- Any later substantive execution-rule change after IR-1 results are inspected must be treated as a
  subsequent experiment, such as IR-1b.
