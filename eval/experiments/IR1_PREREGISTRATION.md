# IR-1 preregistration: interpreted retrieval requests

> **PREREGISTERED BEFORE IR-1 IMPLEMENTATION**
>
> Date: 2026-10-03. No IR-1 code exists when this document is committed. After it is committed,
> the rules, predictions, annotation rules, criteria and procedures below must not change. Any
> change after results are seen is a new experiment (IR-1b) with its own preregistration.

## 1. Baseline

| | |
|---|---|
| Tag | `dcc-ims-v1-conventional-baseline` (annotated tag object `9acc8e41c7b40eed6f11178320ce9cee7ccc871b`) |
| Commit | `15a9efe6e9b3c3f17ff8504d4f611544ab4517a5` |
| Engine | `baseline-fts-v1`: weighted Postgres full-text search, term coverage and trigram similarity, two-stage ranking, best revision per document |
| Frozen evaluation set | 58 queries: `eval/queries/generated.yaml` (sha256 `f41998658911512fc769afd0dd19e58399d73bae428f15faee6bcca7513f2238`) and `eval/queries/human.yaml` (sha256 `5d2f35983b375f723ebe7c99070252ee14769db81a08efcfc3a01744dba92710`) |
| Corpus | v2: 100 documents, 120 revisions, 122 files; fingerprint `de124139ab678c5150004da3a268207d051dfd9e13a5618607cc4c199b30a74d` |
| Baseline report | `eval/reports/baseline-fts-v1-2026-09-30-corpus-v2.json`, reproduced exactly on 2026-10-03 |

Verified frozen-58 baseline (not to be recomputed or altered here):

| Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR | Revision-sensitive queries | Exact requested revision | Requested revision shown |
|---|---|---|---|---|---|---|---|
| 0.707 (41/58) | 0.948 | 0.966 | 1.000 | 0.827 | 15 | 11/15 | 12/15 |

Metric definitions are those of `eval/run_eval.py`: Hit@k is the share of queries whose first
expected document is in the top k; MRR is the mean of 1/rank of the first expected document (0 if
outside the top 10); revision exact means the result's matched revision is the expected one;
revision shown means the expected revision is the matched revision or is named in the revision
evidence (latest, or latest for a permitted use).

## 2. Research question

Does structured interpretation of a human retrieval request, combined with soft clues, one-hop
relationship following, and revision/state intent, measurably improve retrieval over the verified
conventional lexical/metadata baseline?

## 3. Why handwritten interpretation is allowed

IR-1 tests whether a **structured interpretation is useful to retrieval**. It does **not** test
whether a model can produce that interpretation from raw recollection. Interpreted requests are
therefore written by hand (oracle requests). They are written and frozen **before** any IR-1
result is computed for the queries they belong to, and they are never changed query by query
after retrieval outcomes are seen. Producing interpretations automatically (rules or an LLM) is a
later experiment.

## 4. Scope

**IR-1 may include:**
1. an interpreted-request representation (section 5);
2. deterministic planning from that request;
3. hard clues;
4. soft metadata clues;
5. one-hop relationship following;
6. relationship-aware candidate expansion and ranking;
7. revision and information-state intent;
8. requested historical, current and superseding information-state handling;
9. relationship evidence (the existing `related_document` evidence kind) and an explicit record
   of how each request was interpreted;
10. handwritten (oracle) interpreted requests.

**IR-1 must not include:** LLM interpretation; conversational AI; semantic or vector retrieval;
embeddings; RAG; document-grounded Q&A; Flow IN automation; AI metadata extraction; correction
learning; enterprise integrations; new information invented to reveal evaluation answers; changes
to the frozen 58 queries or their expected answers; corpus changes made to improve IR-1 scores;
approximate-amount or approximate-date reasoning (recorded in requests, but not used).

**Implementation boundary:** IR-1 is an evaluation-layer experiment under `eval/experiments/`.
It reuses the existing retriever (`app/retrieval/baseline_fts.py`, `ranking_query`), registered
facts (`app/evidence/facts.py`) and evidence builder (`app/evidence/builder.py`) without changing
them. The production API, UI, ranking SQL and database schema are not modified. If a genuine
prerequisite for a schema or application change is found, work stops and it is brought back for
review.

## 5. Interpreted request (experiment representation)

```yaml
raw_text: "<the query exactly as written>"
text: "<subject and content words passed to the lexical retriever>"
clues:                                   # each clue is matched to an existing vocabulary code
  - field: doc_type | discipline | stage | originator | sender | wbs
    code: "<vocabulary code>"
    strength: confirmed | likely | context
    source: "<words in raw_text that support it>"
relation:                                # optional; one hop only
  link_type: responds_to | supersedes | affects | generated_from | clarified_by | related_to | any
  target_side: from | to                 # which end of the link the wanted document is on
  anchor_text: "<words describing the other (anchor) document>"
  source: "<words in raw_text that support it>"
revision_state: best_match | latest | latest_for_construction | earliest | earliest_for_construction
document_state: any | current
approx: []        # recorded only; IR-1 does not use it
verify: []        # remembered details to check against evidence; recorded only
withdrawn: []     # information the person withdrew; never used for retrieval
```

`best_match` and `any` are the defaults. A request with only `raw_text` and `text` equal to it,
and every other field at its default, is a **default request**.

## 6. Mechanisms (fixed rules)

**M0. Default equivalence.** A default request produces exactly the baseline result: the same
documents, order, revisions, scores and evidence.

**M1. Hard clues.** A `confirmed` clue becomes the existing filter of the same meaning
(`originator` and `sender` both use the existing organisation filter). Nothing else is filtered.

**M2. Soft clues.** `likely` and `context` clues never exclude a document.
- Candidate pool: the top 50 documents from the baseline ranking of `text` with M1's filters.
- A candidate matching a `likely` clue gains **+0.5** on its baseline score; one matching a
  `context` clue gains **+0.1**. A WBS clue matches the element and its children.
- The words of a `context` clue's `source` are removed from `text` (so, for example, a remembered
  WBS number is not matched as text against codes and paths).

**M3. One-hop relationships.**
- Anchors: the top 3 documents of the baseline ranking of `anchor_text`, with no filters.
- Linked set: documents connected to any anchor in the registered relationships with the
  requested `link_type` (any type if `any`), with the wanted document on `target_side`.
  Revision-level relationships count at document level.
- Ordering: linked documents come first, sorted by soft-clue boost (descending), then the
  best rank of the anchor they are linked to (ascending), then baseline score (descending, 0 if
  not in the pool), then document code. All other candidates follow in M2 order. Anchors are
  not removed.
- Each linked document carries `related_document` evidence naming the anchor and the link type.

**M4. Requested state.**
- `revision_state` selects which revision represents each candidate document, from the
  registered revisions, dates and permitted uses (`latest_for_construction` and
  `earliest_for_construction` use the permitted use "construction"). It does not change document
  order.
- `document_state: current` places any candidate superseded by another candidate (registered
  `supersedes` relationship) immediately below the document that supersedes it.

**Output:** the top 10 documents, with the existing evidence plus the interpreted request.

All constants above (pool of 50, boosts 0.5 and 0.1, 3 anchors) are fixed now and are not tuned.
These constants are experimental design choices, not validated production settings. Their purpose
is to provide a fixed, reproducible IR-1 configuration without post-result tuning.

## 7. Predictions (frozen 58)

Derived only from the committed baseline report, the failure analysis
(`eval/reports/baseline-fts-v1-2026-09-30-analysis.md`) and the corpus register. They assume the
rules above and interpreted requests written according to section 9.

### 7.1 Predicted improvements

| Query | Baseline problem | Mechanism | Register data used | Expected |
|---|---|---|---|---|
| G016 | rank 2; the RFI it answers is #1 | M3 `responds_to` (target = from), M2 likely originator (designer) | one response letter linked to the RFI ranked #1 | #1 (high confidence) |
| G018 | rank 2; the letter it replies to is #1 | M3 `responds_to`, M2 likely originator (water company) | one reply linked to the letter ranked #1 | #1 (high) |
| G019 | rank 2; the letter it followed is #1 | M3 `generated_from`, M2 likely doc type (submittal) | one submittal generated from the letter ranked #1 | #1 |
| G026 | rank 2; the proposal it accepts is #1 | M3 `responds_to` and/or M2 likely originator (designer) | one response linked to the proposal ranked #1 | #1 (high) |
| G032 | rank 5; the RFI is #1 | M3 `affects` (target = to), M2 likely doc type (drawing) | the RFI affects two drawings (both accepted answers) and a schedule | #1 |
| H017 | rank 2; the superseded report is #1 | M3 `supersedes` (target = from) | one document supersedes the report ranked #1 | #1 (high) |
| G031 | rank 2; the superseded report is #1 | M4 `document_state: current` | registered `supersedes` between the two reports | #1 |
| H006 | rank 7; six documents of the remembered WBS rank above | M2 WBS as `context`, M2 likely originator (water company) | both accepted letters are from the water company and filed under a different WBS | #1 (medium; depends on boost sizes) |

Revision-state predictions (document already ranked #1; the revision changes):

| Query | Baseline | Mechanism | Expected |
|---|---|---|---|
| G012 | later construction revision matched; the first construction issue wanted | M4 `earliest_for_construction` | exact |
| G015 | later construction revision matched; the original construction issue wanted | M4 `earliest_for_construction` | exact |
| H008 | construction revision matched; the earlier pre-construction revision wanted | M4 `earliest` | exact |
| G029 | a later for-comment revision matched; the latest for construction wanted (shown only in evidence) | M4 `latest_for_construction` | exact |

Predicted totals if every prediction above holds: Hit@1 49/58; human Hit@1 14/18; exact
requested revision 15/15; Hit@10 unchanged at 58/58. These totals describe the
predictions; they are not success thresholds (section 12).

### 7.2 Predicted non-improvements

| Query | Rank | Class | Why IR-1 should not fix it |
|---|---|---|---|
| H012 | 3 | two-hop relationship | the remembered effect is two links away from the answer; one hop reaches the wrong document. Watch for harm. |
| H005 | 2 | paraphrase / wording | a remembered detail in different words and units; no relationship or state cue |
| G002 | 3 | paraphrase | different words for the remembered object; no explicit cue |
| H002 | 2 | implicit currency | the wording does not ask for the current document, so M4 does not trigger |
| G040 | 3 | approximate amount | approximate amounts are excluded from IR-1 |
| G021 | 2 | approximate date | approximate dates are excluded from IR-1 |
| G011 | 2 | abbreviation | an abbreviation not represented in the vocabularies |
| H013 | 2 | incorrect remembered document type | the person names a drawing; the answer is a submittal. A document-type clue would push the wrong way. Watch for harm. |
| G003 | 8 | paraphrase (exploratory) | no improvement is preregistered; see below |

**G003 is exploratory.** No improvement is preregistered for G003. If applying the source-bound
annotation rules (section 9) independently produces a relationship interpretation for it, its
result is reported as exploratory and does not count as fulfilment of a predicted improvement.

### 7.3 Improvement classes (hypothesis)

IR-1 is expected to improve failures involving: relationship-chain memory; document
succession/supersession; requested historical revision or state; strong WBS or organisation clues
that should be soft rather than hard; sender or origin clues; and target-versus-anchor confusion
(the remembered document relates to the target rather than being it).

IR-1 is **not** expected to solve failures dominated by: paraphrase or semantic mismatch; wording
with little lexical overlap; approximate amounts; approximate dates; unrepresented abbreviations;
two-hop or longer relationship chains; an incorrectly remembered document type; or missing
information that needs semantic understanding. These negative predictions are part of the
experiment. IR-1 is not to be broadened because these cases remain difficult.

## 8. Regression watch list

- **H012 and H013:** predicted risks of harm (section 7.2).
- **G013:** asks for the older, superseded report; it must not receive `document_state: current`.
- **All 18 human queries:** each begins with a WBS reference; a `context` boost must not reorder
  queries that are correct today.
- **Every query ranked #1 today (41):** any downward move is a regression.

## 9. Annotation rules (interpreted requests)

1. **Source-bound.** Every clue, relationship and state value cites the words in `raw_text` that
   support it (`source`). An element without a supporting phrase is not allowed.
2. **No answer knowledge.** Requests must not contain document codes, titles, dates, people or
   other facts that are not in `raw_text`. Annotators must not consult expected answers, search
   results or the corpus while writing a request.
3. **Hard vs soft.** `confirmed` only when the person states the fact without hedging and it
   names a vocabulary value directly. Hedged statements ("I think", "maybe") are `likely`.
   Words that describe where a document belongs rather than what it is (for example a WBS area)
   are `context`. Document-type words are never `confirmed`.
4. **Target vs anchor.** If the person describes the wanted document through another document
   ("the reply to…", "what replaced…", "the drawing that changed after…"), the other document is
   the anchor (`anchor_text`) and the link type and side are recorded. If no relationship is
   described, `relation` is omitted.
5. **State.** `revision_state` and `document_state` are set only from explicit words ("first
   construction issue", "earlier", "before", "current", "build from", "replaced"). Otherwise
   they stay at the defaults.
6. **Uncertainty and withdrawals.** Uncertain recollections stay soft. Anything the person
   withdraws goes in `withdrawn` and is never used.
7. **Approximate facts and verifiable details** go in `approx` and `verify` (recorded, unused).
8. **Freezing.** All requests for a set are written, reviewed, committed and fingerprinted
   (sha256) before any IR-1 result is computed for that set. They are not edited afterwards.
9. **Who writes them.**
   - **Frozen 58 (development set):** the Claude session that analysed the failures and wrote
     these predictions must not draft these requests. Instead:
     - they are produced in a separate annotation pass;
     - the annotator receives only the raw query text, the interpreted-request schema (section 5)
       and these frozen annotation rules;
     - the annotator must not consult expected answers, baseline results, prediction tables, the
       failure analysis, corpus contents or search output;
     - preferably the annotator is a fresh Claude session supplied only with those permitted
       materials;
     - Gilad reviews the annotations only for compliance with the source-bound annotation rules,
       not for whether they retrieve the expected answer;
     - all 58 requests are then frozen, fingerprinted and committed before any IR-1 result is run.

     The frozen 58 and their answers are public within the project, so this set measures
     mechanism behaviour, not independence.
   - **Blind set:** written by Gilad, who has not seen the blind answers.
10. **Audit.** Before freezing, a mechanical check confirms that every `source` occurs in
    `raw_text` and that no document code appears in any request.

## 10. Evaluation procedure (frozen 58)

1. Implement IR-1 under `eval/experiments/` on a branch from the baseline tag. No production
   change.
2. **Gate A, default equivalence:** default requests give 0 differences against the baseline on
   all 58 frozen queries and all 189 cases of `eval/check_equivalence.py` on the dev corpus.
3. **Gate B, annotations frozen:** the frozen-58 requests are committed and fingerprinted, and the
   audit (section 9, rule 10) passes.
4. **Runs:** baseline; IR-1 with all mechanisms; IR-1 run a second time (determinism); and one
   ablation per mechanism (M2, M3, M4 each disabled) for attribution.
5. **Report:** Hit@1/3/5/10, MRR, exact requested revision and requested revision shown; per-query
   rank movement; lists of improved, worsened and unchanged queries; results by failure class
   (sections 7.1 and 7.2); and, for each prediction, predicted vs actual.
6. Results are reported whatever they are. Nothing in sections 5–9 is changed in response.

## 11. Regression rule

A higher aggregate metric does not cancel a regression. No query ranked #1 at baseline may move
down, and no requested-revision correctness may regress (a requested revision that is exact or
shown at baseline must remain so); either breaks the strict gate in section 12 and cannot be
accepted as a trade-off. All other regressions must be reported and explained. For every query
that becomes worse (lower document rank, or a requested revision no longer exact or shown), the
report gives the old rank, the new rank, the cause if it can be determined, and the IR-1
mechanism involved (from the ablation runs). Regressions are never accepted silently.

## 12. Success, partial success and failure

**Success** requires all of:
1. Gate A passes (0 differences).
2. Two full IR-1 runs are identical (deterministic and reproducible).
3. Measurable improvement in the targeted classes: in each of relationship-chain, supersession,
   requested-revision and soft-clue classes, the queries predicted to improve mostly do improve
   (document rank, or revision exactness for the revision class).
4. Strict regression gate: No query ranked #1 at baseline may move down. No requested-revision
   correctness may regress. All other regressions must be reported and explained.
5. Attribution: each improvement disappears when its mechanism is disabled (ablation).
6. The annotation audit passes (gains do not come from answer-aware requests).

**Partial success:** criteria 1, 2, 4 and 6 hold, but criterion 3 holds only for some classes.
The result justifies a narrowly defined follow-up on the classes that worked.

**Failure / reassessment** if any of:
- default behaviour does not reproduce the baseline (Gate A);
- results are not reproducible;
- any query ranked #1 at baseline moves down, or any requested-revision correctness regresses
  (the strict gate, criterion 4);
- other regressions are not reported and explained;
- gains depend on answer-aware annotations;
- frozen-set gains in a targeted class do not appear for the same class in the blind evaluation;
- the experiment needs a schema change or changes to the baseline ranking to work, or its
  complexity is out of proportion to the measured benefit.

No overall Hit@1 target is set.

## 13. Blind evaluation

| | |
|---|---|
| Identifier | Blind set 2: scenarios S01–S12 |
| Answer-key fingerprint (sha256) | `1c5c67240d03f9b0fb91fae43de54d285c551d335734902aff5d8d2ac00867d3` |
| Size | 12 scenarios |
| Key location | held outside the repository, in Gilad's own storage; verified against the fingerprint on 2026-10-03 |

**Exposure record:**
- **Claude authored the S01–S12 answer key and is EXPOSED.** Earlier working copies of the key and
  of the scenario-design notes also remain in Claude's local session storage.
- **Gilad has not seen the blind answers and is CLEAN.**
- This preregistration was written without accessing the sealed key. Its mechanisms,
  predictions, classes, annotation rules and criteria come from the frozen-58 evidence and the
  DCC IMS characterization only.
- The blind evaluation therefore tests the frozen IR-1 rules on Gilad's queries and Gilad's
  interpreted requests. It does not test the independence of the IR-1 author.

**Open prerequisites (must be resolved before the blind evaluation, preferably before IR-1
implementation):**
- Gilad's blind queries for the scenarios are not yet frozen or fingerprinted.
- S13 is not yet located, frozen or fingerprinted; whether it joins the blind set is undecided.
- Gilad's interpreted requests for the blind queries do not yet exist.

**Protocol.** The blind evaluation runs only after (1) IR-1 implementation is complete, (2) the
frozen-58 analysis is complete and reported, and (3) no further tuning is permitted. Then:
1. Gilad's blind queries and interpreted requests are frozen and fingerprinted.
2. One run of the baseline (raw queries) and one run of IR-1 (interpreted requests).
3. The key is verified against the fingerprint above, then revealed and used for scoring.
4. Results are reported by failure class with the same metrics and regression rules. Nothing is
   changed afterwards.

## 14. Stop conditions

Stop and report, without working around the problem, if:
- Gate A fails;
- a schema change, a production code change or a change to the baseline ranking appears
  necessary;
- any frozen query, expected answer or corpus file would need to change;
- an interpreted request would need a fact that is not in its query text;
- the sealed key would need to be accessed before the protocol in section 13 allows it;
- results are not reproducible across runs.
