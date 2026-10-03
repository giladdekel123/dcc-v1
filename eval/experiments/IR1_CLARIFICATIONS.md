# IR-1 Pre-Result Clarifications

## Status

- This clarification was written on 2026-10-03, after the IR-1 implementation-planning review
  exposed a conflict and several ambiguities in the frozen specification.
- No IR-1 retrieval or evaluation results had been run or inspected when these decisions were
  made. No IR-1 code existed.
- The original preregistration (`eval/experiments/IR1_PREREGISTRATION.md`) and the frozen
  annotation artifact (`eval/experiments/ir1_frozen58_annotations.yaml`, sha256
  `5b68dab1e8eff7c2c82aa6e9e07d5686ce47ee7a06c27aae9bd3e706e577f860`) remain unchanged.
- This document records prospective execution rules for IR-1. It becomes part of the experiment
  specification before implementation and before any result.

Line numbers below refer to `IR1_PREREGISTRATION.md` at commit `b557c18`.

## C1 — WBS clue handling (M1/M2)

**Conflict found.**

- The source-bound annotation rule classifies a WBS area as a context clue: "Words that describe
  where a document belongs rather than what it is (for example a WBS area) are `context`"
  (rule 3, lines 220–221).
- Other preregistered passages also assume WBS is soft and contextual: the M2 rationale for
  removing a remembered WBS number from text (lines 112–113); the H006 prediction "M2 WBS as
  `context`" (line 157); the hypothesis that "strong WBS or organisation clues … should be soft
  rather than hard" (lines 193–194); and the regression watch on the 18 human queries, "a
  `context` boost must not reorder…" (lines 207–208).
- All 18 frozen human-query WBS clues were nevertheless annotated `confirmed`.
- Applying M1 (lines 105–106) mechanically to those frozen strengths would turn the WBS clues into
  hard filters, contrary to the preregistered WBS treatment.

**Decision.**

- The frozen annotation artifact is not edited.
- For IR-1 execution only, a clue whose `field` is `wbs` is treated as `context` for retrieval
  behaviour, whatever its frozen `strength` (including `confirmed`).
- WBS therefore never becomes an M1 hard filter in IR-1.
- It takes part in M2 as a context clue: it never excludes a document, and a candidate whose WBS
  element is the clue's element or one of its children receives the preregistered context boost
  (+0.1). As a context clue, its `source` is also subject to C2 (in the frozen 58 no WBS source
  phrase occurs in `text`, so removal has no effect there).
- The interpretation/audit record of each request keeps the original frozen strength next to the
  strength used, so the discrepancy remains visible.
- This is an explicit pre-result clarification, not a silent correction of the frozen
  annotations.

## C2 — Context-source lexical removal (M2)

The preregistration states that "the words of a `context` clue's `source` are removed from
`text`" (line 112) but does not specify the runtime mechanics: whether removal precedes the
pool ranking of line 109, the matching unit, case handling, or what happens if nothing remains.

**Decision.**

1. Context-source removal happens **before** the baseline lexical ranking that builds the
   candidate pool (line 109).
2. Removal is **phrase-based** and **case-insensitive**.
3. Only occurrences of the **complete** source phrase are removed, matched on whole-word
   boundaries; isolated words of the phrase are not removed on their own. For example, a context
   source `water main` removes the phrase `water main` but does not remove the word `Water` from
   an entity such as `Northvale Water`, and a source `pond` does not remove part of `ponds`.
4. Whitespace left by removal is normalised (runs collapsed to one space, ends trimmed).
5. If removal would leave no lexical text (an empty or whitespace-only string), the original
   frozen `text` value is used unchanged, rather than sending an empty query into baseline
   browse mode.
6. The frozen text is not otherwise rewritten, expanded, stemmed, inferred or semantically
   reinterpreted.

## Scope

- These clarifications apply only to IR-1.
- All other preregistered rules, constants (pool 50, boosts 0.5 and 0.1, 3 anchors), gates,
  predictions, ablations and success/failure criteria remain unchanged.
- No expected answers, baseline results, corpus-derived answer knowledge or blind S01–S12 answer
  key were used to make these clarifications.
- Any further substantive rule change after IR-1 results are observed must not be folded back
  into IR-1; it belongs in a subsequent experiment such as IR-1b.
