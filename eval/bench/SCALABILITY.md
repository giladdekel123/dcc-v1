# Scalability summary (DCC V1)

**Question.** Does the baseline retriever (`baseline-fts-v1`) stay usable well beyond the
100-document KVL corpus? **Decision (2026-10-02):** the 10,000- and 40,000-document results
below are sufficient scalability evidence for V1. A 64,000-document run was not made: at about
8.5 MB per 1,000 documents it would exceed the 500 MB free-plan database limit.

**Setup.** A separate Supabase project (eu-west-1, free plan; about 75-80 ms per round trip from
the development machine) holding the real 100 KVL documents plus synthetic register records for
40 fictional projects. The synthetic records are benchmark data only, not V1 scope. Workload: the
58 frozen evaluation queries, 40 generic queries and 20 filter combinations
([workload.yaml](workload.yaml)). Harness: [run_bench.py](run_bench.py); reports in [reports/](reports/).

## Results

| Code | Scale | Search, end to end (median / p95) | Ranking on the server (median / p95) | Source |
|---|---|---|---|---|
| Original (27 round trips per search) | 200 docs | 2.14 s / 2.33 s | 25 / 33 ms | [verify-200](reports/verify-200.md) |
| Change set 1 | 10,000 docs | 1.45 s / 2.62 s | 889 / 1,428 ms | [baseline-fts-v1-10000](reports/baseline-fts-v1-10000.md) |
| Change sets 1-3 | 10,000 docs | **0.69 s / 0.83 s** | **198 / 235 ms** | [baseline-fts-v1-10000-cs3](reports/baseline-fts-v1-10000-cs3.md) |
| Change sets 1-2 | 40,000 docs | - | 906 / 4,170 ms | [two-stage-v2-40k](../experiments/reports/two-stage-v2-40k.md) ("current") |
| Change sets 1-3 | 40,000 docs | - | **374 / 700 ms** | check C7 in commit `c9af46a` |

Server-side figures come from EXPLAIN ANALYZE (14 sampled queries in the benchmark reports, 158
text cases at 40,000). The known-item check (58 frozen queries among the synthetic documents) is
unchanged by every change: hit@1 0.707, hit@10 0.948 at 10,000 documents.

## Changes made, and how each was verified

| Change set | What | Effect on results | Verification |
|---|---|---|---|
| 1 (`d33e049`) | 27 database round trips per search reduced to 3 (batched evidence and facts); index-usable candidate selection | None | Full responses for 189 cases compared with the previous code on dev and 2,000 documents: 0 differences in 3,450 results |
| 2 (`b7a0878`) | Each candidate's scores computed once (materialized `scored`) | None | 0 differences on dev and 40,000 documents; test compares materialized and inline forms |
| 3 (`c9af46a`) | Two-stage ranking: the exact score only for the 2,000 best full-text matches by coverage then `ts_rank`, plus every spelling (trigram) candidate | Identical whenever a query matches 2,000 rows or fewer, which covers every query on the V1 corpus. At 40,000 documents, 2 of 189 cases changed (a synthetic distractor swapped at position 6 or 10) | Checks C1-C7 fixed in advance: 0 differences on dev and 10,000; only the 2 predicted cases at 40,000; frozen evaluation identical to the committed baseline |

Change set 3 was chosen by experiment, with criteria fixed before each run
([experiments/two_stage.py](../experiments/two_stage.py)):
- **2C** ([10k](../experiments/reports/two-stage-10k.md), [40k](../experiments/reports/two-stage-40k.md)): `ts_rank` alone as stage 1 failed the agreement criterion at 40,000 (real KVL documents were dropped).
- **2C-v2** ([10k](../experiments/reports/two-stage-v2-10k.md), [40k](../experiments/reports/two-stage-v2-40k.md)): coverage first passed all criteria at both scales. N=2000 was chosen over the cheaper N=1000 for fewer top-10 changes.
- **RUM indexes (2D):** available on our Supabase projects but not needed. Stage 1 with the existing GIN indexes takes tens of milliseconds.

## Other findings

- **Storage:** `dcc` schema 96 MB at 10,000 documents; the database is 339 MB at 40,000.
- **Incremental updates:** at 10,000 documents, adding 100 documents takes about 1.8 s to insert and 0.4 s to re-index.
- **Laptop sleep, not the network:** every "network" stall during benchmarking coincided with the laptop entering Windows Modern Standby. Long runs now ask Windows to stay awake (`keep_awake()`).

## Known limits (deferred beyond V1)

- **Code-like queries:** queries such as document codes still take about 2 s on the server at 40,000 documents, because all their spelling candidates are kept. Capping them would change typo behaviour.
- **Network share of the timings:** the latencies include about 75 ms per round trip from the development machine. Production latency depends on where the app is hosted relative to the database.
- **Dev-database tests:** they have no stall protection. If the laptop sleeps during a run, they can stall and fail with connection errors (one run had 30 such errors), so keep it awake while testing.
