# Experiment 2C: two-stage ranking (two-stage-10k)

- Date 2026-10-02; benchmark database: 10000 documents, 13088 index rows
- Stage 1 score: `ts_rank` (chosen by cost in phase 0); trigram candidates always kept
- 58 frozen queries for quality; 158 text cases for agreement and server time (median of 3 runs, EXPLAIN ANALYZE, timing off)

## Quality on the frozen set

| Arm | hit@1 | hit@3 | hit@5 | hit@10 | MRR | rev exact/found |
|---|---|---|---|---|---|---|
| current | 0.707 | 0.931 | 0.931 | 0.948 | 0.816 | 10/14 |
| N=250 | 0.707 | 0.931 | 0.931 | 0.948 | 0.816 | 10/14 |
| N=500 | 0.707 | 0.931 | 0.931 | 0.948 | 0.816 | 10/14 |
| N=1000 | 0.707 | 0.931 | 0.931 | 0.948 | 0.816 | 10/14 |
| N=2000 | 0.707 | 0.931 | 0.931 | 0.948 | 0.816 | 10/14 |

## Agreement and server ranking time

| Arm | identical top 10 | mean overlap | p50 ms | p95 ms | max ms | p50 change | p95 change |
|---|---|---|---|---|---|---|---|
| current | 158/158 | 1.0 | 413.0 | 1864.8 | 2302.6 | | |
| N=250 | 135/158 | 0.964 | 76.0 | 200.0 | 847.1 | -82% | -89% |
| N=500 | 139/158 | 0.972 | 101.1 | 209.3 | 843.7 | -76% | -89% |
| N=1000 | 146/158 | 0.984 | 148.9 | 258.3 | 844.2 | -64% | -86% |
| N=2000 | 153/158 | 0.995 | 226.5 | 430.3 | 861.6 | -45% | -77% |

## Decision criteria (fixed before the run)

| Arm | Q1 no frozen query leaves the top 10 | Q2 MRR >= current - 0.01 and hit@1 down <= 1 query | Q3 >= 90% identical top 10 | S1 p95 -40% and p50 -30% | passes |
|---|---|---|---|---|---|
| N=250 | yes | yes | **no** | yes | no |
| N=500 | yes | yes | **no** | yes | no |
| N=1000 | yes | yes | yes | yes | **yes** |
| N=2000 | yes | yes | yes | yes | **yes** |

Smallest passing limit: **N=1000**

## Frozen-query rank changes

- N=250: none
- N=500: none
- N=1000: none
- N=2000: none

## Phase 0: cost profile (server ms over frozen + generic queries)

| Variant | p50 | p95 | mean |
|---|---|---|---|
| full | 887.6 | 2035.9 | 929.7 |
| no_coverage | 291.6 | 496.0 | 288.6 |
| no_fts_rank | 665.6 | 1280.9 | 656.5 |
| no_trigram | 349.4 | 1014.5 | 418.2 |
| no_collapse | 696.8 | 1645.9 | 750.1 |
| matches_only | 34.4 | 56.4 | 35.3 |
| stage1_ts_rank_1000 | 37.6 | 63.8 | 35.8 |
| stage1_term_count_1000 | 43.5 | 72.3 | 40.6 |

Matching rows per query: p50 9137, p95 12852, max 12940; queries over 250/500/1000/2000 matches: 98/98/97/89 of 98
