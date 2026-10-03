# IR-1b preregistration: preserve the user's wording, add structured intelligence

> **PREREGISTERED BEFORE IR-1b IMPLEMENTATION**
>
> Date: 2026-10-03. No IR-1b code exists when this document is committed. After it is committed, the
> conditions, rules, comparisons, criteria and boundary below must not change. Any substantive change
> after IR-1b results are seen is a later experiment with its own preregistration.

## 1. Purpose

IR-1b is a controlled **development** experiment following the failed IR-1 regression gate
("IR-1 failed the preregistered strict regression gate / requires reassessment"; results committed at
`7abf36cc4b97e0e122158f828e6548dfc198d7e9`, integration frozen at
`f429d1c7ade9a89676fed169cf4c388a46395c93`).

Primary question:

> Can DCC IMS preserve the user's original query wording and add structured intelligence around it,
> rather than replacing the user's wording with interpreted text?

The IR-1 failure decomposition found that 6 of the 9 baseline-#1 regressions and both requested-revision
regressions began when the raw query was replaced by the interpreted `text`; that soft-clue handling
both helped and harmed; that relationship handling helped typed relations and harmed the two `any/from`
cases; that revision handling helped with no observed harm; and that phrase deletion and boosts were
not isolated.

**These hypotheses came from the same 58 development queries. IR-1b is therefore not blind
confirmatory evidence.** The blind set S01–S12 remains untouched for later independent testing.

## 2. Frozen dataset and references

| | |
|---|---|
| Queries | G001–G040 (`eval/queries/generated.yaml`, sha256 `f41998658911512fc769afd0dd19e58399d73bae428f15faee6bcca7513f2238`) and H001–H018 (`eval/queries/human.yaml`, sha256 `5d2f35983b375f723ebe7c99070252ee14769db81a08efcfc3a01744dba92710`): 58 queries |
| Annotations | `eval/experiments/ir1_frozen58_annotations.yaml`, sha256 `5b68dab1e8eff7c2c82aa6e9e07d5686ce47ee7a06c27aae9bd3e706e577f860`, used unchanged |
| Corpus | v2, fingerprint `de124139ab678c5150004da3a268207d051dfd9e13a5618607cc4c199b30a74d` (100 documents, 120 revisions, 122 files) |
| Frozen IR-1 specification | `IR1_PREREGISTRATION.md` `3d00e06266aed0435ce4260c8d9271ccb3a60e87e0991acdb22fd53ec5c566c7`, `IR1_CLARIFICATIONS.md` `8fa0a8e531e0d9d3b1ea6927614ce70a4364b8efbef20910f3ada11ce07e6468`, `IR1_STAGE2_CLARIFICATIONS.md` `fbb5ba54e84da546c7d45c4879b734db4b58263a6658a87cdb98e0a5cd517695`, `IR1_STAGE2_ABLATION_ADDENDUM.md` `9c96c58301fb3d4976ae5bbeea17353c53c3510dd62da29101c041c3677bfe15` |
| Frozen IR-1 code | `ir1_request.py` `93c8fcac16c38d4af42cd4da3d4bc5fea080d1fa8f0c7f2fb3d3e3f5d2b2a3b7`, `ir1_engine.py` `0e7d82307e6dc5b15ee43c58e7d492e433d11bc4b79b1823464a5749633e1ded`, `ir1_integration.py` `23ca4e44af1b6b5980414b4fccffe9425e0699224453f796efd0f86d65950b3f` (all at `f429d1c`) |
| Recorded IR-1 result | `eval/experiments/reports/ir1-frozen58-2026-10-03.json`: as written sha256 `34523f852d222ca158bc3cc020473c7854fa7ec0c571d64987b062149cd8289a` (CRLF); committed blob (LF-normalised, otherwise identical) sha256 `b7fdf3085db5cb32259524fc9f9ba56f031af2e27dd257a79af66f40a1295f46` |

Frozen IR-1 code and specification files are not modified by IR-1b.

## 3. Constants that remain unchanged

- candidate pool = 50; output shortlist = 10;
- relationship anchors = 3; one relationship hop;
- likely-clue boost = +0.5; context-clue boost = +0.1 (cumulative per matching clue, S1.1);
- hard-clue behaviour (M1, with C1: WBS clues are context);
- relation annotations, relation rules (M3, S2) and revision/version logic (M4, S3, ablation addendum A1)
  exactly as frozen for IR-1.

**IR-1b is not a weight-tuning experiment.** No weight, threshold, anchor count, hop depth or other
constant is changed.

## 4. Condition matrix

Common to all conditions: *original* = the frozen request's `raw_text` (identical to the query text);
*interpreted* = the frozen request's `text`; hard clues (M1) always operate; frozen annotations are used
unchanged. "Boosts" = frozen M2 soft-clue scoring; "relationships" = frozen M3; "revisions/versions" =
frozen M4 (revision_state and document_state). "Phrase deletion" = section 5.

| # | Name | Wording sent to retrieval | Boosts | Phrase deletion | Relationships | Revisions/versions | Comparison enabled |
|---|---|---|---|---|---|---|---|
| 0 | Ordinary search baseline | original | off | off | off | off | external reference (`app.search.search`) |
| 1 | Frozen IR-1 full reference | interpreted | on | on (frozen C2 on interpreted) | on | on | reproduction of the recorded IR-1 result; reference for 9 and 10 |
| 2 | Original wording, nothing added | original | off | off | off | off | pipeline control (= 0); base for A–D |
| 3 | Interpreted wording, nothing added | interpreted | off | off | off | off | A: wording replacement alone (3 vs 2) |
| 4 | Original + uncertain-clue boosts | original | on | off | off | off | B: boosts alone |
| 5 | Original minus clue phrases | original | off | on | off | off | B: deletion alone |
| 6 | Original + boosts, minus clue phrases | original | on | on | off | off | B: boosts × deletion |
| 7 | Original + relationships | original | off | off | on | off | C: relationships alone (7 vs 2) |
| 8 | Original + revision/version intelligence | original | off | off | off | on | D: revisions alone (8 vs 2) |
| 9 | **Additive candidate** | original | on | off | on | on | E: vs 0 (gate, quality) and vs 1 |
| 10 | Additive candidate + phrase deletion | original | on | on | on | on | deletion in the system (10 vs 9); wording with all on (10 vs 1) |
| 11 | Additive minus boosts | original | off | off | on | on | leave-one-out: boosts (9 vs 11) |
| 12 | Additive minus relationships | original | on | off | off | on | leave-one-out: relationships (9 vs 12) |
| 13 | Additive minus revision/version intelligence | original | on | off | on | off | leave-one-out: revisions (9 vs 13) |
| 9r | Exact repeat of condition 9 | as 9 | | | | | determinism |

14 conditions plus one repeat. Every condition is run on all 58 queries.

**Mechanism switches map onto the frozen engine** as `Switches(m2=boosts, m3=relationships,
m4=revisions/versions)`. With boosts off, every soft boost is 0, including the soft-clue key of the M3
linked-document ordering (frozen S5); relationship expansion, admission, hard-filter checks and
linked-first placement still operate. With revisions/versions off, the frozen M4-off rules apply (S5 and
addendum A1). Conditions 0–3 and the off positions add nothing beyond conventional retrieval.

## 5. New IR-1b rules (experimental separations, not changes to IR-1)

1. **Phrase deletion may be applied to the original query** (conditions 5, 6 and 10). In IR-1 it was
   applied only to the interpreted text.
2. **Uncertain-clue boosting and phrase deletion are independent switches.** In IR-1 both were "M2"
   (S5). With both on over the interpreted wording the result equals frozen IR-1 M2.

Deletion behaviour is the frozen C2 rule (`ir1_request.remove_context_sources`), unchanged:

- the phrases deleted are the `source` phrases of clues whose effective strength is `context` (C1: every
  WBS clue is context), as literal phrases;
- case-insensitive; complete phrase only, on whole-word boundaries (standard regex word characters);
- sources that normalise to the same phrase (whitespace collapsed, casefolded) are one source;
- occurrences are found in the wording given and removed together; whitespace is then collapsed and
  trimmed;
- if deletion would leave the wording empty, the undeleted wording is used (fallback);
- overlapping different source phrases raise the existing error (no precedence is invented).

No other lexical rewriting, synonym, stemming or expansion is introduced. The wording sent to
retrieval is used both for ranking and as the query terms for evidence.

## 6. Primary comparisons

- **A. Wording effect:** 3 vs 2.
- **B. Boost/deletion 2×2:** conditions 2, 4, 5, 6 (boost effect, deletion effect, interaction).
- **C. Relationships alone:** 7 vs 2.
- **D. Revisions/versions alone:** 8 vs 2, including whether the revision gains attributed to M4 in IR-1
  appear without the wording replacement.
- **E. Additive architecture:** 9 vs 0 and 9 vs 1.

## 7. Leave-one-out comparisons

- 9 vs 11: contribution of clue boosts inside the additive system (on the pool and on the order among
  linked documents together);
- 9 vs 12: contribution of relationships inside the additive system;
- 9 vs 13: contribution of revision/version handling inside the additive system.

A difference between a mechanism's single-mechanism effect (4, 7 or 8 vs 2) and its leave-one-out
effect indicates an interaction; it is not by itself evidence of a causal explanation.

## 8. Secondary comparisons

- 10 vs 9: phrase deletion inside the full additive system;
- 10 vs 1: original versus interpreted wording with all mechanisms and phrase deletion operating;
- 2 vs 0: pipeline reproduction control;
- 1 vs the recorded frozen IR-1 result: historical reproduction control (ranks, matched revisions, top
  10 and revision flags per query);
- 9 vs 9r: determinism.

Typed versus vague (`any`) relationship categories may be reported descriptively only; the sample (6
relations) is too small for a separate criterion.

## 9. Metrics

For every condition, as computed by `eval/run_eval.py` (`evaluate`, `summarise`) unchanged: Hit@1,
Hit@3, Hit@5, Hit@10, MRR, exact requested revision, requested revision shown; overall and by author
(generated/human) and by category. Per-query rank, matched revision, revision flags and top 10 are
preserved for every condition, together with each query's IR-1b configuration and wording sent.

## 10. Regression reporting

For condition 9, relative to condition 0, report explicitly (never only inside aggregates):

- every baseline #1 query that moves down (old rank, new rank);
- every requested revision that is exact at baseline and becomes non-exact;
- every correct result that leaves the top 10.

The same lists are reported for every other condition, descriptively.

## 11. Success criteria

**Targeted retrieval classes** are those preregistered for IR-1 (IR-1 preregistration sections 7.1 and
7.3): relationship chain (G016, G018, G019, G026, G032), supersession (G031, H017), requested revision
(G012, G015, G029, H008; measured by revision exactness), and soft clue (H006). A class **improves** when
more of its queries improve than worsen relative to condition 0 (document rank, or revision exactness for
the requested-revision class).

**Full success** requires all of:

1. condition 2 exactly reproduces condition 0;
2. condition 1 exactly reproduces the recorded frozen IR-1 result;
3. condition 9 exactly reproduces in 9r;
4. condition 9 causes no baseline #1 regression;
5. condition 9 causes no exact requested-revision regression;
6. condition 9 causes no correct answer to leave the top 10;
7. condition 9 is not below condition 0 on Hit@1, Hit@3, Hit@5, Hit@10 or MRR;
8. at least one targeted retrieval class improves over condition 0;
9. that improvement can be interpreted using the single-mechanism and/or leave-one-out conditions.

**Partial success / reassessment:** criteria 1–6 hold, but one or more of 7, 8 or 9 do not.

**Failure:** a control fails (1 or 2), determinism fails (3), or the strict regression gate fails (4, 5
or 6).

No numerical improvement target is set; none may be derived from the already-observed 58 results.

## 12. Known limitations (unresolved interactions)

- wording × individual mechanisms (wording is isolated only with nothing added, 3 vs 2, and with
  everything added, 10 vs 1);
- where boosts act inside relationship ordering (9 vs 11 combines pool boosts and linked-document
  ordering);
- relationship × revision/version interaction (the `current` reordering can move documents introduced by
  relationships);
- interactions of three or more mechanisms;
- phrase deletion × relationship/revision effects (visible only as 10 vs 9);
- annotation quality versus mechanism quality (relation types, anchor wording and clues come from the
  frozen annotations);
- the 58 queries are not blind and generated the hypotheses.

## 13. Experimental boundary

**The first execution of any non-control IR-1b condition (3–13 and 9r) against the real development
corpus is the start of IR-1b result observation.**

Before that boundary the following may occur: implementation; synthetic and unit tests; plumbing and
equivalence tests on synthetic data; planning-only checks of phrase deletion on the original wording of
the 58 (no retrieval); and preparation of the reproduction controls (conditions 0, 1 and 2). If a
planning check raises the overlap error for any query, work stops and is reported before the boundary.

No IR-1b outcome may be inspected while the implementation or rules are being changed. Raw results are
written once, with byte-exact preservation, before any analysis. Any substantive change after results
are seen is a later experiment, not a modification of IR-1b.

Implementation constraint: frozen IR-1 files (`ir1_request.py`, `ir1_engine.py`, `ir1_integration.py`,
the IR-1 specification files and annotations) are not modified; IR-1b adds its own module, tests and
runner, reusing the frozen functions.

## 14. Blind set protection

S01–S12 must not be accessed, run, decoded or inspected during IR-1b design, implementation, debugging
or evaluation.
