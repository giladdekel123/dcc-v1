# Scalability benchmark: verify-200

- Engine: baseline-fts-v1; date 2026-10-01; database: separate benchmark project
- Corpus: 200 documents, 247 revisions, 249 files (100 real KVL + 100 synthetic)
- Database region: eu-west-1; network round trip (select 1): 80.8 ms; reconnects during the run: 1
- Workload: 98 text, 30 text + filters, 20 filters only; 1 timed repetition(s) after a warm-up

## Latency (end to end, per query median of repetitions)

| Workload | queries | p50 ms | p95 ms | max ms |
|---|---|---|---|---|
| text_only | 98 | 2138.2 | 2328.2 | 3332.1 |
| text_plus_filters | 30 | 2094.0 | 2146.5 | 2159.1 |
| filters_only | 20 | 468.0 | 513.2 | 575.0 |

**Ranking query on the server** (14 sampled): p50 25.2 ms, p95 32.8 ms. Access to `search_entry`: Seq Scan x12, Index Scan (search_entry_document_idx) x2

## Load and index

- Real corpus load and extraction: 34.0 s
- Synthetic insert: 1.8 s (generation 0.0 s)
- Full index build: 0.5 s for 247 revisions

## Storage

- Database: 15.6 MB; `dcc` schema 4.1 MB, of which indexes 2.3 MB
- Largest tables (MB): search_entry 1.5, content_segment 1.31, revision_file 0.24, document 0.17, revision 0.16, revision_status 0.12

## Incremental change

- Add 100 documents: insert 1.73 s, index 0.42 s
- Add a revision to 100 documents: insert 15.35 s, index 0.33 s

## Known-item sanity check (58 frozen queries; not a quality figure)

hit@1 0.707, hit@10 0.966
