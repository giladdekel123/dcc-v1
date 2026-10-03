# IR-1 Stage-2 Ablation Addendum

## Status

- The Stage-2 clarification `IR1_STAGE2_CLARIFICATIONS.md` (sha256
  `fbb5ba54e84da546c7d45c4879b734db4b58263a6658a87cdb98e0a5cd517695`) was already frozen at commit
  `0936e7d2baaf3e2a7a68049c770f74abcebdd2ac`.
- During pre-result code review, one M4-off ablation ambiguity was found: when M4 is disabled, an
  M3-introduced document from outside the conventional pool has no conventional baseline
  representing revision, and the frozen rules did not say which revision represents it.
- No IR-1 retrieval or evaluation result had been observed when this addendum was written.
- This addendum resolves only that ambiguity.
- All previous frozen rules (`IR1_PREREGISTRATION.md`, `ir1_frozen58_annotations.yaml`,
  `IR1_CLARIFICATIONS.md`, `IR1_STAGE2_CLARIFICATIONS.md`) remain authoritative except where this
  addendum explicitly defines this previously unspecified case.

## A1 — M4-off outside-pool representation

When M4 is disabled:

1. In-pool documents retain their conventional baseline representing revision.
2. M3-introduced outside-pool documents remain eligible for the result set, subject to M1 hard
   constraints.
3. Because an outside-pool document has no conventional baseline matched revision, its
   representation default is **the latest registered revision that satisfies all active
   revision-level M1 hard filters**.
4. M1 is never ablated.
5. Therefore:
   - a hard stage clue remains a revision-level constraint;
   - where an organisation hard filter qualifies through sender, the representing revision must
     satisfy that sender condition;
   - an originator-only organisation match is document-level and does not further constrain
     revision selection.
6. This is a representation default only. It does not use:
   - requested `revision_state` intent;
   - S3.3 relationship-specific revision selection;
   - construction-state selection;
   - `document_state` supersession logic.
7. The chosen revision is not interpreted as satisfying the requested `revision_state`.
8. The representation default does not change document ranking.
9. Because S2.2/M1 eligibility is applied before the document enters the M3 result set, an admitted
   outside-pool document has at least one registered revision satisfying the active revision-level
   hard filters. If execution nevertheless reaches an outside-pool document for which no registered
   revision satisfies those filters, execution stops and a wiring/invariant error is reported. An
   ineligible revision is never displayed.
10. This rule applies only when M4 is disabled, M3 is enabled, and the document was introduced from
    outside the conventional pool.

All other M4-off behaviour remains unchanged.

## A2 — Experimental interpretation

M4-off removes the revision/document-state behaviour being ablated. It does not remove M1
eligibility constraints.

Selecting the latest M1-eligible registered revision for an outside-pool document is therefore a
neutral representation requirement, not an M4 revision-state decision.

The M4-off ablation does not use relationship-specific revision information merely to decide which
revision to display.

## A3 — Scope

This addendum:

- does not change full IR-1 behaviour;
- does not change M2-off behaviour when M4 remains enabled;
- does not change M3-off behaviour;
- affects only M4-off execution where M3 introduces a document from outside the conventional pool;
- resolves the interaction between that representation default and revision-level M1 hard filters
  (S3.5 of `IR1_STAGE2_CLARIFICATIONS.md`).

Any later substantive change after IR-1 results are observed requires IR-1b.
