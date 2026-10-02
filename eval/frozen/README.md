# Frozen evaluation baseline

What the first baseline evaluation (`eval/reports/baseline-fts-v1-2026-09-30*`) was measured
against. `tests/test_frozen_corpus.py` checks it on every test run, so later corpus growth can add
documents but can never alter what the frozen queries and their ground truth were judged on.

- `corpus-v1/`: the corpus register and links as of that run: 47 documents, 62 revisions and 64
  files. Every row must still exist unchanged in `corpus/`, and every listed file must still
  have the same SHA-256. New rows are allowed.
- `queries.sha256`: fingerprints of the frozen query files. They must not change.

Don't edit these files. If a change here is ever truly needed, it's a new frozen baseline and
needs a deliberate decision, not a fix.
