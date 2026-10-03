# Blind set 2 preregistration: one-shot confirmation of IR-1b condition 8

> **PREREGISTERED BEFORE ANY BLIND QUERY, ANNOTATION, RETRIEVAL OUTPUT OR ANSWER IS SEEN BY CLAUDE**
>
> Date: 2026-10-03. When this document is committed, no S01–S12 query file, annotation file, blind
> runner or blind output exists in the repository, and the sealed answer key has not been opened in
> this work. After commit, the set, candidate, conditions, rules, metrics, criteria and order below
> must not change.

## 1. Purpose

> Test once, on 12 previously unused human-recollection queries, whether the development-selected
> condition-8 candidate generalizes without harming conventional retrieval and whether its
> revision/version benefit appears outside the 58-query development set.

- **Condition 8 was selected after seeing the 58 development queries** (`IR1B_RESULT.md`, commit
  `c19302e3c6147561516a4e82fced27f9d6d0bef2`); its development figures are not confirmation.
- **S01–S12 have not been used to select or tune it.**
- **The blind test is one-shot.**
- **The candidate cannot change after the blind queries are frozen.**

## 2. Blind set

The confirmation set is **S01–S12 only** (Blind set 2). S13 is not part of this experiment. The sample
size is fixed at **12** before any blind query or result is observed.

## 3. Fixed candidate

The candidate is exactly frozen IR-1b **condition 8**, implementation frozen at
`865c0a4a143ad6c1b448701d62afd2c7e35c045c` (`eval/experiments/ir1b.py` sha256
`d881413e5caf39bf1a53651d374fdff7a515f0d59afb370abfe9ab706781862e`, `ir1b.CONDITIONS["8"]`):

- original (raw) user wording preserved, sent unchanged to conventional retrieval;
- uncertain-clue boosts **off**; phrase deletion **off**; relationships **off**;
- revision/version intelligence (frozen M4: `revision_state`, `document_state`, S3, addendum A1)
  **on**;
- all other frozen behaviour as implemented, including M1: a `confirmed` non-WBS clue in a blind
  interpreted request becomes the existing hard filter (C1 makes every WBS clue context). Any such
  clue is recorded before the run and is not modified.

No modified variant ("condition 8b") is created. Constants are unchanged (pool 50, output 10).

## 4. Compared conditions

| Condition | Definition | Equivalent IR-1b condition |
|---|---|---|
| **B0** baseline | ordinary conventional search (`app.search.search`) on the original query wording | 0 |
| **B2** pipeline control | original wording through the IR-1b pipeline with nothing added (`ir1b.search_ir1b`, config 2) | 2 |
| **B8** fixed candidate | original wording + revision/version intelligence only (`ir1b.search_ir1b`, config 8) | 8 |
| **B8r** determinism repeat | identical to B8 | 8 |

No other condition (IR-1b conditions 1, 3–7, 9–13) is run. This is not a model-selection experiment.

**B2 must reproduce B0** (every outcome field per query, and the full response apart from the engine
label) before B8 is interpreted. **B8r must equal B8** (outcomes and full response hashes).

## 5. Blind query authorship

- The user alone supplies the natural-language S01–S12 queries.
- Claude Code (which authored the answer key and is exposed to it) must not propose, rewrite, clean up,
  interpret or improve their wording.
- The queries preserve the user's actual recollection wording exactly.
- Once supplied, the query file's byte content is hashed (sha256) and committed before any retrieval.
- The query file contains only query ids and query text: no expected document, revision, ranking
  target or any answer-derived field.

## 6. Blind interpreted annotations

- Claude Code must not author, edit or suggest the interpreted requests.
- They are produced independently of the answer key, without key access, using the frozen
  interpretation schema and annotation rules (IR-1 preregistration sections 5 and 9, with
  `IR1_CLARIFICATIONS.md` C1 and C2), and validated by the frozen Stage-1 request parser.
- The annotation file contains no expected document id, correct revision, ranking target or
  answer-derived field.
- The annotation file is frozen, hashed and committed before any retrieval.
- B8 uses from each request only what condition 8 uses: the original wording (`raw_text`, which must
  equal the frozen query text), `revision_state`, `document_state`, and any M1 hard filter from
  `confirmed` non-WBS clues. Other fields are recorded but have no effect in B8.

**Revision-sensitive before scoring.** A blind query is *revision-sensitive* when its independently
frozen interpreted request has a non-default `revision_state` (not `best_match`) and/or a non-default
`document_state` (not `any`). The list is computed and committed before retrieval and may not be
changed after the answer key is revealed.

## 7. Key protection

Sealed answer-key fingerprint (from the IR-1 preregistration, section 13):

`sha256 1c5c67240d03f9b0fb91fae43de54d285c551d335734902aff5d8d2ac00867d3`

The key is held outside the repository in the user's storage. It must not be opened, decoded, printed,
searched or used until all of the following have happened, in order:

1. the queries are frozen and committed;
2. the annotations are frozen and committed;
3. the blind runner is frozen and committed;
4. B0, B2, B8 and B8r retrieval has completed;
5. the raw blind retrieval output has been written once, hashed and committed.

Only then may a scorer verify the key's sha256 against the fingerprint above and use it mechanically.
A key whose hash does not match is not used.

## 8. Metrics

After the key is revealed, for B0 and B8 side by side (and B2, B8r as controls), with the scoring
semantics of `eval/run_eval.py`:

- Hit@1, Hit@3, Hit@5, Hit@10 (first expected document within the top k);
- MRR (1/rank of the first expected document, 0 outside the top 10);
- per-query rank of the correct document;
- exact requested revision (matched revision equals the key's expected revision), where the key
  defines an expected revision;
- requested revision shown (expected revision is the matched, latest or latest-for-use revision),
  where defined.

Because n = 12, no statistical-significance threshold and no percentage improvement target is used.

## 9. Strict blind safety gate

B8 fails the safety gate if, relative to B0, any of the following occurs (each case listed
individually):

- a query whose correct result is #1 in B0 is below #1 in B8;
- a requested revision that is exact in B0 is not exact in B8;
- a correct answer in B0's top 10 is not in B8's top 10.

## 10. Aggregate non-regression

For confirmation, B8 must not be below B0 on any of Hit@1, Hit@3, Hit@5, Hit@10 or MRR, and the
counts of exact requested revisions and of requested revisions shown must not be lower in B8 than in
B0.

## 11. Blind verdicts

Exactly one outcome is reported. **C takes precedence** whenever any of its conditions holds.

**C. Blind confirmation failed** if any of:

- B2 does not reproduce B0;
- B8r does not reproduce B8;
- the strict safety gate fails;
- any of Hit@1, Hit@3, Hit@5, Hit@10 or MRR is below B0;
- exact requested revisions decrease;
- requested revisions shown decrease.

**A. Blind benefit confirmed** requires all of:

- B2 reproduces B0, and B8r reproduces B8;
- the strict safety gate passes;
- no aggregate retrieval metric is below B0;
- exact and shown revision counts are not below B0;
- at least one preregistered revision-sensitive blind query improves from non-exact (B0) to exact
  (B8), with no exact-to-non-exact regression.

**B. Blind safety confirmed, benefit not demonstrated** when every control, safety and
non-regression criterion passes but no revision-sensitive query shows a new exact-revision
improvement. This includes the case where B0 is already exact for every revision-sensitive query. It
is not evidence of revision improvement.

If there are **zero** preregistered revision-sensitive blind queries, the test can assess retrieval
safety (outcome B or C) but cannot confirm the hypothesized revision benefit.

## 12. One-shot order

1. Commit this blind preregistration.
2. The user supplies the S01–S12 raw query text.
3. Annotations are created independently, without key access.
4. Queries and annotations are hashed and committed (with the revision-sensitive list and any M1
   hard-filter clues recorded).
5. The blind runner is built and tested on synthetic data only.
6. The runner is frozen and committed.
7. B0, B2, B8 and B8r are run once.
8. Raw outputs are written once (byte-exact, LF only).
9. Raw outputs are hashed and committed.
10. Only then is the sealed key accessed.
11. The key's sha256 is verified against section 7.
12. The committed outputs are scored mechanically.
13. The blind result is written.
14. Nothing is tuned or rerun based on the outcome.

## 13. Failure handling

If a technical failure occurs **before** a valid raw blind output is produced: stop; document the
failure; do not inspect the key; repair only the technical issue, tested on synthetic data; and
preregister any substantive change before trying again.

If a valid raw blind output **has** been produced, there is no second attempt.

## 14. Provenance

| | |
|---|---|
| Frozen evaluation implementation | `865c0a4a143ad6c1b448701d62afd2c7e35c045c` |
| IR-1b preregistration / clarification | `cd6c657…` (`9432b13c…`) / `0d7469f…` (`b1718292…`) |
| IR-1b raw result | commit `ed182c158e18919a0a70593cd2f94e06f48087e7`, sha256 `752b3885fee388ca42703cc2ec8b53f06c5a86720d06209b11269321bcbf9b4c` |
| IR-1b result note | commit `c19302e3c6147561516a4e82fced27f9d6d0bef2`, sha256 `999b0167354987de740b9565ed4963d52c84bec71cce00ee91fb2cb6f429338d` |
| Corpus | v2, fingerprint `de124139ab678c5150004da3a268207d051dfd9e13a5618607cc4c199b30a74d` |
| Answer key | sealed, outside the repository, sha256 `1c5c67240d03f9b0fb91fae43de54d285c551d335734902aff5d8d2ac00867d3` |
| Exposure | Claude authored the key and is exposed; the user has not seen the answers |
