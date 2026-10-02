# Scalability benchmark reports

Each report is produced by `python -m eval.bench.run_bench` against the separate benchmark
database (`BENCH_DATABASE_URL`, Supabase project in eu-west-1). Synthetic records are benchmark
data only; they are not part of the DCC V1 corpus or its evaluation.

| Report | Code | Scale | Notes |
|---|---|---|---|
| `verify-200` | before change set 1 (27 round trips per search) | 200 documents | Harness verification run; 1 timed repetition. Its "Add a revision to 100 documents" line is **invalid**: those revisions had no file and were never indexed (fixed in `b3dc8d1`), so the 0.33 s index time measured an empty update. All other figures stand. |
| `baseline-fts-v1-10000` | after change set 1 (`d33e049`, 3 round trips) | 10,000 documents | 2 timed repetitions. Reconnects in the report coincide with the laptop entering Windows Modern Standby; samples spanning sleep are excluded and listed. |
| `baseline-fts-v1-10000-cs3` | after change sets 2 and 3 (`c9af46a`: scores computed once; two-stage ranking, stage 1 limited to 2,000 matches) | 10,000 documents | 2 timed repetitions; no reconnects. |

The laptop enters Modern Standby after a few idle minutes (3 on mains power), which freezes a run
and drops its connections. The benchmark, the equivalence check and the 2C experiment therefore ask
Windows to stay awake while they run (`keep_awake()` in `run_bench.py`); keep the lid open.
