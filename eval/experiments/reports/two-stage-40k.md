# Experiment 2C: two-stage ranking (two-stage-40k)

- Date 2026-10-02; benchmark database: 40000 documents, 52869 index rows
- Code 4c6e207; ranking SQL 5a46199225a937f9; stage 1 score: `ts_rank` (chosen by cost in phase 0); trigram candidates always kept
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
| current | 158/158 | 1.0 | 919.1 | 4150.4 | 11464.0 | | |
| N=250 | 125/158 | 0.923 | 219.5 | 597.1 | 1992.1 | -76% | -86% |
| N=500 | 130/158 | 0.937 | 227.1 | 598.4 | 2000.0 | -75% | -86% |
| N=1000 | 136/158 | 0.968 | 263.3 | 615.3 | 2002.3 | -71% | -85% |
| N=2000 | 139/158 | 0.977 | 324.3 | 611.3 | 1996.8 | -65% | -85% |

## Decision criteria (fixed before the run)

| Arm | Q1 no frozen query leaves the top 10 | Q2 MRR >= current - 0.01 and hit@1 down <= 1 query | Q3 >= 90% identical top 10 | S1 p95 -40% and p50 -30% | passes |
|---|---|---|---|---|---|
| N=250 | yes | yes | **no** | yes | no |
| N=500 | yes | yes | **no** | yes | no |
| N=1000 | yes | yes | **no** | yes | no |
| N=2000 | yes | yes | **no** | yes | no |

Smallest passing limit: **none**

## Frozen-query rank changes

- N=250: none
- N=500: none
- N=1000: none
- N=2000: none
