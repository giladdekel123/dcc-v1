# IR-1b result

Post-result documentation (not a preregistration). Written on 2026-10-03 after the frozen IR-1b run.

## Official verdict: FAILURE

The preregistered principal candidate, **condition 9** (original wording + uncertain-clue boosts +
relationships + revision/version intelligence, no phrase deletion):

- moved **H010 from baseline rank 1 to rank 5**, so it failed the strict no-baseline-#1-regression gate
  (full-success criterion 4);
- also fell **below baseline on Hit@3** (0.914 vs 0.948) **and Hit@5** (0.931 vs 0.966) (criterion 7).

All reproduction controls and the determinism check passed with zero differences: condition 0
reproduced the frozen baseline, condition 1 reproduced the recorded frozen IR-1 result (outcomes and
response hashes), condition 2 reproduced condition 0, and condition 9r reproduced condition 9. This is
therefore an experimental result, not a pipeline failure.

For reference, condition 9 had Hit@1 0.776 (45/58) vs 0.707 (41/58), MRR 0.849 vs 0.827, Hit@10
1.000 (unchanged), and 15/15 exact and shown requested revisions vs 11/15 and 12/15. These do not
change the verdict.

## Main findings

1. **Replacing the user's original wording with interpreted wording was strongly harmful.**
   Interpreted wording alone (condition 3 vs 2): Hit@1 0.707 → 0.569, 11 baseline-#1 regressions,
   3 exact-revision regressions.
2. **Phrase deletion was harmful overall.** Deletion alone (5 vs 2) caused 5 baseline-#1 regressions
   and one correct answer leaving the top 10; inside the full system (10 vs 9) it added regressions.
3. **Soft-clue boosts were mixed / roughly neutral**, with at least one clear harm case: boosts alone
   (4 vs 2) gained one Hit@1 with no #1 regression, but moved H013 from rank 2 to 7 (its `likely`
   document-type clue points to the wrong type, a preregistered harm risk).
4. **Relationship intelligence produced meaningful gains but caused the remaining serious
   regressions.** Relationships alone (7 vs 2) gave the largest single-mechanism Hit@1 gain (41 → 44:
   G016, G018, G019, H017), but both vague `any`/`from` relations were harmed: H010 (1 → 5) and G032
   (5 → out of the top 10 alone; 5 → 8 in condition 9).
5. **Revision/version intelligence produced clean gains with no observed regression.** Revisions alone
   (8 vs 2): 15/15 exact and shown requested revisions, G031 2 → 1, and no regression of any kind.

The typed-versus-`any` relationship observation is descriptive only (6 relations), as preregistered.

## Development candidate selected after IR-1b: condition 8

Condition 8 is selected as the candidate for possible independent blind confirmation:

> Preserve the user's original query wording and add only the frozen revision/version intelligence.

(No uncertain-clue boosts, no phrase deletion, no relationship intelligence.)

**This candidate was selected after observing the 58-query development results. Its performance on
those 58 queries is therefore development evidence, not independent confirmation.**

Condition 8 development results (frozen 58, relative to the ordinary-search baseline, condition 0):

| | Condition 8 | Baseline |
|---|---|---|
| Hit@1 | 42/58 (0.724) | 41/58 (0.707) |
| Hit@3 | 0.948 | 0.948 (unchanged) |
| Hit@5 | 0.966 | 0.966 (unchanged) |
| Hit@10 | 58/58 (1.000) | 58/58 (unchanged) |
| MRR | 0.836 | 0.827 |
| Exact requested revisions | 15/15 | 11/15 |
| Requested revisions shown | 15/15 | 12/15 |
| Baseline-#1 regressions | 0 | – |
| Exact-revision regressions | 0 | – |
| Correct answers leaving the top 10 | 0 | – |

**Condition 8 is not declared a successful experiment by itself.** It is a candidate chosen from
development data for a separate blind confirmation test.

## Provenance

| | |
|---|---|
| IR-1b preregistration | commit `cd6c657ae5c23bf15cbb0beb3377335b0b556926`, `IR1B_PREREGISTRATION.md` sha256 `9432b13cc014127c3078b230b40287f70dd4f52a5c8804053143f118e63d5eb4` |
| IR-1b clarification | commit `0d7469f88a2be0197fbb51d7e2c7b2a6ddf2cab9`, `IR1B_CLARIFICATIONS.md` sha256 `b171829258443238290ccb7413a2af2bb767187d9c4f607cce109f5a339eb39e` |
| Frozen evaluation implementation | commit `865c0a4a143ad6c1b448701d62afd2c7e35c045c` (`ir1b.py` sha256 `d881413e5caf39bf1a53651d374fdff7a515f0d59afb370abfe9ab706781862e`, `ir1b_run.py` sha256 `751ed2ef561f393366767be0d50750590aaa0af138d0145fefc465fced12b825`) |
| Controls result | commit `18e516861017089269866e808ef4c01ed5b4ee0e`, `ir1b-controls-2026-10-03.json` sha256 `3dc34a3b2de80758498f85413a5e45eb1308374cad1c974a60abf56e41c46408` |
| Raw result | commit `ed182c158e18919a0a70593cd2f94e06f48087e7`, `eval/experiments/reports/ir1b-frozen58-2026-10-03.json` sha256 `752b3885fee388ca42703cc2ec8b53f06c5a86720d06209b11269321bcbf9b4c` (LF only, byte-exact) |
| Corpus | v2, fingerprint `de124139ab678c5150004da3a268207d051dfd9e13a5618607cc4c199b30a74d` |

No frozen file was altered. S01–S12 were not accessed during IR-1b.
