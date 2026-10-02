# Scalability benchmark: baseline-fts-v1-10000

- Engine: baseline-fts-v1; date 2026-10-01; database: separate benchmark project
- Corpus: 10000 documents, 13088 revisions, 13090 files (100 real KVL + 9900 synthetic)
- Database region: eu-west-1; network round trip (select 1): 79.6 ms; reconnects during the run: 4 (stalled statements aborted after 60.0 s: 0)
- Workload: 98 text, 30 text + filters, 20 filters only; 2 timed repetition(s) after a warm-up

## Latency (end to end, per query median of repetitions)

| Workload | queries | p50 ms | p95 ms | max ms |
|---|---|---|---|---|
| text_only | 98 | 1449.8 | 2615.9 | 3455.3 |
| text_plus_filters | 30 | 632.0 | 973.3 | 1072.6 |
| filters_only | 20 | 400.7 | 462.8 | 486.4 |

Timed samples excluded because they included a stalled connection and reconnect: 3
- text_only: "minutes of the meeting where the east abutment piling problem was first raised"  (780455.1 ms)
- text_only: "WBS 330 Mill Lane Culvert. Something from around the time of the trial hole about the water main being deeper than expected."  (40296.8 ms)
- text_plus_filters: "inspection report defects gantry" {'wbs': '400'} (12445819.6 ms)

**Ranking query on the server** (14 sampled): p50 889.3 ms, p95 1427.9 ms. Access to `search_entry`: Bitmap Heap Scan x13, Bitmap Index Scan (search_entry_tsv_idx) x13, Bitmap Index Scan (search_entry_trgm_idx) x13, Index Scan (search_entry_document_idx) x1

## Load and index

- Real corpus load and extraction: 35.1 s
- Synthetic insert: 33.4 s (generation 3.4 s)
- Full index build: 13.4 s for 13088 revisions

## Storage

- Database: 108.0 MB; `dcc` schema 96.2 MB, of which indexes 32.8 MB
- Largest tables (MB): content_segment 41.35, search_entry 36.96, revision_file 6.77, extraction 2.73, revision 2.55, revision_status 2.52

## Incremental change

- Add 100 documents: insert 1.87 s, index 0.49 s (135 revisions indexed)
- Re-issue 100 documents as a new revision (file, extraction and text copied from the previous revision): insert 0.64 s, index 0.43 s (100 revisions indexed)

## Known-item sanity check (58 frozen queries; not a quality figure)

hit@1 0.707, hit@10 0.948

## Connection events

- 19:35:42 error during search: consuming input failed: server closed the connection unexpectedly (attempt 1 of 3); reconnecting
- 19:39:34 error during search: consuming input failed: server closed the connection unexpectedly (attempt 1 of 3); reconnecting
- 19:48:42 error during search: consuming input failed: server closed the connection unexpectedly (attempt 1 of 3); reconnecting
- 19:48:42 connect-failed during connect: failed to resolve host 'aws-1-eu-west-1.pooler.supabase.com': [Errno 11001] getaddrinfo failed; retrying in 5 s
- 21:38:15 connect-failed during connect: failed to resolve host 'aws-1-eu-west-1.pooler.supabase.com': [Errno 11001] getaddrinfo failed; retrying in 10 s
- 22:30:51 connect-failed during connect: failed to resolve host 'aws-1-eu-west-1.pooler.supabase.com': [Errno 11001] getaddrinfo failed; retrying in 20 s
- 01:58:45 error during search: consuming input failed: server closed the connection unexpectedly (attempt 1 of 3); reconnecting
