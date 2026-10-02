# Experiment 2C: two-stage ranking (two-stage-v2-40k)

- Date 2026-10-02; benchmark database: 40000 documents, 52869 index rows
- Code 115e9ba; ranking SQL 5a46199225a937f9; stage 1 score: `cov_ts_rank, cov_rank_cd` (chosen by cost in phase 0); trigram candidates always kept
- 58 frozen queries for quality; 158 text cases for agreement and server time (median of 3 runs, EXPLAIN ANALYZE, timing off)

## Quality on the frozen set

| Arm | hit@1 | hit@3 | hit@5 | hit@10 | MRR | rev exact/found |
|---|---|---|---|---|---|---|
| current | 0.707 | 0.931 | 0.931 | 0.948 | 0.816 | 10/14 |
| cov_ts_rank N=1000 | 0.707 | 0.931 | 0.931 | 0.948 | 0.816 | 10/14 |
| cov_ts_rank N=2000 | 0.707 | 0.931 | 0.931 | 0.948 | 0.816 | 10/14 |
| cov_ts_rank N=4000 | 0.707 | 0.931 | 0.931 | 0.948 | 0.816 | 10/14 |
| cov_rank_cd N=1000 | 0.707 | 0.931 | 0.931 | 0.948 | 0.816 | 10/14 |
| cov_rank_cd N=2000 | 0.707 | 0.931 | 0.931 | 0.948 | 0.816 | 10/14 |
| cov_rank_cd N=4000 | 0.707 | 0.931 | 0.931 | 0.948 | 0.816 | 10/14 |

## Agreement and server ranking time

| Arm | identical top 10 | mean overlap | p50 ms | p95 ms | max ms | p50 change | p95 change |
|---|---|---|---|---|---|---|---|
| current | 158/158 | 1.0 | 906.1 | 4170.0 | 8254.5 | | |
| cov_ts_rank N=1000 | 154/158 | 0.992 | 313.4 | 689.1 | 2058.9 | -65% | -84% |
| cov_ts_rank N=2000 | 156/158 | 0.999 | 366.6 | 703.2 | 2059.4 | -60% | -83% |
| cov_ts_rank N=4000 | 158/158 | 1.0 | 461.0 | 862.1 | 2068.8 | -49% | -79% |
| cov_rank_cd N=1000 | 154/158 | 0.992 | 439.9 | 1524.2 | 2544.1 | -51% | -63% |
| cov_rank_cd N=2000 | 156/158 | 0.999 | 494.6 | 1602.7 | 2561.7 | -45% | -62% |
| cov_rank_cd N=4000 | 158/158 | 1.0 | 592.3 | 1887.2 | 3648.7 | -35% | -55% |

## Decision criteria (fixed before the run)

| Arm | Q1 no frozen query leaves the top 10 | Q2 MRR >= current - 0.01 and hit@1 down <= 1 query | Q3 >= 90% identical top 10 | S1 p95 -40% and p50 -30% | passes |
|---|---|---|---|---|---|
| cov_ts_rank N=1000 | yes | yes | yes | yes | **yes** |
| cov_ts_rank N=2000 | yes | yes | yes | yes | **yes** |
| cov_ts_rank N=4000 | yes | yes | yes | yes | **yes** |
| cov_rank_cd N=1000 | yes | yes | yes | yes | **yes** |
| cov_rank_cd N=2000 | yes | yes | yes | yes | **yes** |
| cov_rank_cd N=4000 | yes | yes | yes | yes | **yes** |

Cheapest passing arm (by p50): **cov_ts_rank N=1000**

## Where the top 10s differ (reported, not a criterion)

| Arm | changed top 10s | first differing position (min / median) | documents dropped | of which real KVL |
|---|---|---|---|---|
| cov_ts_rank N=1000 | 4 | 2 / 4.5 | 13 | 0 |
| cov_ts_rank N=2000 | 2 | 6 / 8.0 | 2 | 0 |
| cov_ts_rank N=4000 | 0 | - / - | 0 | 0 |
| cov_rank_cd N=1000 | 4 | 2 / 4.5 | 13 | 0 |
| cov_rank_cd N=2000 | 2 | 6 / 8.0 | 2 | 0 |
| cov_rank_cd N=4000 | 0 | - / - | 0 | 0 |

## Frozen-query rank changes

- cov_ts_rank N=1000: none
- cov_ts_rank N=2000: none
- cov_ts_rank N=4000: none
- cov_rank_cd N=1000: none
- cov_rank_cd N=2000: none
- cov_rank_cd N=4000: none
