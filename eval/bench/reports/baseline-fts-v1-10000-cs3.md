# Scalability benchmark: baseline-fts-v1-10000-cs3

- Engine: baseline-fts-v1; date 2026-10-02; database: separate benchmark project
- Corpus: 10000 documents, 13088 revisions, 13090 files (100 real KVL + 9900 synthetic)
- Database region: eu-west-1; network round trip (select 1): 74.6 ms; reconnects during the run: 0 (stalled statements aborted after 60.0 s: 0)
- Workload: 98 text, 30 text + filters, 20 filters only; 2 timed repetition(s) after a warm-up

## Latency (end to end, per query median of repetitions)

| Workload | queries | p50 ms | p95 ms | max ms |
|---|---|---|---|---|
| text_only | 98 | 686.9 | 827.7 | 1095.1 |
| text_plus_filters | 30 | 576.7 | 683.3 | 696.4 |
| filters_only | 20 | 417.6 | 667.4 | 669.5 |

Timed samples excluded because they included a stalled connection and reconnect: 0

**Ranking query on the server** (14 sampled): p50 198.0 ms, p95 234.5 ms. Access to `search_entry`: Bitmap Heap Scan x27, Bitmap Index Scan (search_entry_tsv_idx) x14, Bitmap Index Scan (search_entry_trgm_idx) x13, Index Scan (search_entry_pkey) x14, Index Scan (search_entry_document_idx) x2

## Load and index

- Real corpus load and extraction: 32.8 s
- Synthetic insert: 13.3 s (generation 4.3 s)
- Full index build: 11.5 s for 13088 revisions

## Storage

- Database: 107.9 MB; `dcc` schema 96.0 MB, of which indexes 32.8 MB
- Largest tables (MB): content_segment 41.35, search_entry 36.96, revision_file 6.77, extraction 2.73, revision_status 2.52, document 2.44

## Incremental change

- Add 100 documents: insert 1.82 s, index 0.42 s (135 revisions indexed)
- Re-issue 100 documents as a new revision (file, extraction and text copied from the previous revision): insert 0.55 s, index 0.38 s (100 revisions indexed)

## Known-item sanity check (58 frozen queries; not a quality figure)

hit@1 0.707, hit@10 0.948

## Connection events

- none
