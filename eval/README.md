# DCC evaluation set

The evaluation set measures how well a retrieval engine finds the document a person has in
mind from partial memory. The same set compares the baseline (`baseline-fts-v1`) with any
later engine.

## Files

- `briefing.md`: a plain-language project history. It's the only material query writers should
  read; it has no document codes, filenames or folders.
- `queries/generated.yaml`: 40 queries written from the ground truth before any run.
- `queries/human.yaml`: queries written independently by a person (target: at least 18).
- `run_eval.py`: runs every query through the same search path the API uses and writes a report.
- `reports/`: committed evaluation reports.

## Writing human queries

1. Read `briefing.md`. Don't open the corpus files, browse folders or run searches first.
2. Write the query as you'd type it if you half-remembered the document: vague, misspelt,
   the wrong word, a sender, a rough date. Short or long is fine.
3. Only then look up the document you meant in `corpus/register/documents.csv` and put its
   `doc_code` in `expected`. List more than one code only if either would genuinely satisfy you.
4. If you want a particular revision (for example "the one to build from" or "the original
   version"), add `expected_rev`.
5. Pick the closest category. Spread queries across categories; the tricky ones
   (`correct_not_latest`, `related_chain`, `status_anchored`) matter most.

## Query format

```yaml
- id: H001                  # unique; G### for generated, H### for human
  author: human             # generated | human
  category: vague_topic     # see below
  query: what you remember about the document
  filters: {}               # optional: discipline, doc_type, stage, org, wbs, date_from, date_to
  expected: [KVL-ADM-410-LT-S-0031]   # one or more acceptable doc codes
  expected_rev: C02         # optional
  notes: optional
```

**Categories:**

| Category | Meaning |
|---|---|
| `vague_topic` | you remember roughly what it was about |
| `partial_name` | you remember part of its title or name |
| `old_revision` | you want an earlier revision, not the latest |
| `cross_type` | you remember a related document of another type |
| `date_anchored` | you remember roughly when |
| `sender_anchored` | you remember who sent or wrote it |
| `correct_not_latest` | you want the revision that's valid for use, which isn't the newest |
| `related_chain` | you remember what it led to or came from |
| `status_anchored` | you remember its status (rejected, closed, approved with comments…) |

## Running

```bash
python -m app.ingest.rebuild          # make sure the database matches the corpus
python -m eval.run_eval               # writes eval/reports/<engine>-<date>.json and .md
python -m eval.run_eval --compare eval/reports/a.json eval/reports/b.json
```

## Metrics

- **hit@k** (k = 1, 3, 5, 10): share of queries where an expected document is in the top k.
- **MRR**: mean of 1 / rank of the first expected document (0 if not in the top 10).
- **Revision** (only for queries with `expected_rev`, and only when the document was found):
  - *exact*: the result's matched revision is the expected one;
  - *named*: the result shows the expected revision, either as its matched revision or in its
    revision evidence (latest, or latest for a permitted use such as construction).

Results are broken down by author (generated vs human) and by category. There are no scores
in the report, because ranking scores aren't comparable between engines.

## Scalability evidence

The evaluation set measures quality on the 100-document corpus. How search time grows with
corpus size, and the changes made for it, are summarised in [bench/SCALABILITY.md](bench/SCALABILITY.md).
