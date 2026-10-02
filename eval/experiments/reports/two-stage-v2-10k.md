# Experiment 2C: two-stage ranking (two-stage-v2-10k)

- Date 2026-10-02; benchmark database: 10000 documents, 13088 index rows
- Code 66ba41d; ranking SQL 5a46199225a937f9; stage 1 score: `cov_ts_rank, cov_rank_cd` (chosen by cost in phase 0); trigram candidates always kept
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
| current | 158/158 | 1.0 | 246.9 | 1006.2 | 1206.2 | | |
| cov_ts_rank N=1000 | 158/158 | 1.0 | 112.8 | 212.2 | 640.5 | -54% | -79% |
| cov_ts_rank N=2000 | 158/158 | 1.0 | 161.3 | 290.8 | 639.9 | -35% | -71% |
| cov_ts_rank N=4000 | 158/158 | 1.0 | 241.9 | 468.7 | 652.4 | -2% | -53% |
| cov_rank_cd N=1000 | 158/158 | 1.0 | 149.7 | 475.7 | 785.9 | -39% | -53% |
| cov_rank_cd N=2000 | 158/158 | 1.0 | 199.4 | 562.5 | 784.5 | -19% | -44% |
| cov_rank_cd N=4000 | 158/158 | 1.0 | 273.9 | 744.2 | 915.2 | +11% | -26% |

## Decision criteria (fixed before the run)

| Arm | Q1 no frozen query leaves the top 10 | Q2 MRR >= current - 0.01 and hit@1 down <= 1 query | Q3 >= 90% identical top 10 | S1 p95 -40% and p50 -30% | passes |
|---|---|---|---|---|---|
| cov_ts_rank N=1000 | yes | yes | yes | yes | **yes** |
| cov_ts_rank N=2000 | yes | yes | yes | yes | **yes** |
| cov_ts_rank N=4000 | yes | yes | yes | **no** | no |
| cov_rank_cd N=1000 | yes | yes | yes | yes | **yes** |
| cov_rank_cd N=2000 | yes | yes | yes | **no** | no |
| cov_rank_cd N=4000 | yes | yes | yes | **no** | no |

Cheapest passing arm (by p50): **cov_ts_rank N=1000**

## Where the top 10s differ (reported, not a criterion)

| Arm | changed top 10s | first differing position (min / median) | documents dropped | of which real KVL |
|---|---|---|---|---|
| cov_ts_rank N=1000 | 0 | - / - | 0 | 0 |
| cov_ts_rank N=2000 | 0 | - / - | 0 | 0 |
| cov_ts_rank N=4000 | 0 | - / - | 0 | 0 |
| cov_rank_cd N=1000 | 0 | - / - | 0 | 0 |
| cov_rank_cd N=2000 | 0 | - / - | 0 | 0 |
| cov_rank_cd N=4000 | 0 | - / - | 0 | 0 |

## Frozen-query rank changes

- cov_ts_rank N=1000: none
- cov_ts_rank N=2000: none
- cov_ts_rank N=4000: none
- cov_rank_cd N=1000: none
- cov_rank_cd N=2000: none
- cov_rank_cd N=4000: none
