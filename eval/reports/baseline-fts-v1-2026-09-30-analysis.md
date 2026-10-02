# Failure analysis: baseline-fts-v1 on the frozen evaluation set

Companion to `baseline-fts-v1-2026-09-30.md` (commit `f7bab27`). This analysis describes where
the baseline fails and what that implies for the next retrieval approach. It doesn't choose a
technology, and nothing in retrieval was tuned or changed as a result of these findings.

## 1. What was measured

- **Engine:** `baseline-fts-v1`. Postgres weighted full-text search plus trigram similarity,
  collapsed to the best revision per document. Ranking code unchanged since M1.
- **Data:** the dev database rebuilt from the committed corpus: 47 documents, 62 revisions,
  64 files, 5 storylines.
- **Queries:** 58 frozen queries, 40 generated and 18 written independently by a person
  (31%). Run once.
- **Ground truth:** taken from the register, links and storyline data, never from search
  results. Twelve queries (4 generated, 8 human) accept either of two documents where the wording
  genuinely fits both.

## 2. Headline results

| | hit@1 | hit@3 | hit@10 | MRR |
|---|---|---|---|---|
| All 58 | 0.76 | 0.97 | 1.00 | 0.86 |
| Generated (40) | 0.80 | 0.97 | 1.00 | 0.88 |
| Human (18) | 0.67 | 0.94 | 1.00 | 0.80 |

- **Revision-specific queries (15):** the expected revision was the matched revision in 11,
  and visible to the user (matched, or named in the revision evidence) in 12.
- **Category spread:**
  - hit@1 = 1.00 for partial_name, date_anchored, status_anchored and old_revision;
  - lowest for cross_type (0.40), vague_topic (0.56), related_chain (0.57) and
    correct_not_latest (0.60).

**The central finding:** every expected document is in the top 10, and 97% are in the top 3.
The baseline reliably finds the right *subject*; it often orders the wrong member of that subject
first. The remaining problem is ordering and choice, not recall.

## 3. Failure patterns

14 of 58 queries didn't rank an expected document first. For all 14, the document ranked
first belongs to the **same storyline** as the answer. For 9 of 14, it's **directly linked** to
the answer in the register (`responds_to`, `supersedes`, `generated_from` or `affects`).

### F1. Right thread, wrong member of it (9 queries)

Linked documents share most of their vocabulary: an RFI and its response, a proposal and its
acceptance, a trial-hole letter and the reply to it. The baseline ranks them almost equally and
can't tell which *role* the user asked for.

| Query | Wanted | Ranked first |
|---|---|---|
| G002 "problem with the water pipe near the Mill Lane culvert" (rank 3) | RFI-0013 or trial-hole letter | Variation 07, then slab details (same thread) |
| G016 "the designer's reply to the RFI about soft clay…" | response letter | the RFI (`responds_to`) |
| G018 "Northvale Water's reply to the council's trial hole letter" | NVW reply | council letter (`responds_to`) |
| G019 "the submittal that followed the contractor's letter…" | submittal | the letter (`generated_from`) |
| G026 "Arden Moss letter accepting the alternative… surfacing" | acceptance | contractor's proposal (`responds_to`) |
| G032 "the drawing that changed after the contractor's question…" | GA / piling C02 | the RFI (`affects`) |
| H012 "What document caused us to enlarge Pond 2?" | council letter (cause) | Pond 2 GA (effect) |
| H005 "…the allowable discharge was changed from 8 to 5 l/s" | council letter | Pond 2 GA |
| H013 "…the drawing that was approved for the flow control…" | approved submittal P01 | Pond 2 GA |

The words that carry the role are "reply", "followed", "caused", "accepting", and document types
such as "drawing", "letter" and "submittal". To a word-matching engine they're ordinary, low-value
terms. This pattern explains cross_type's hit@1 of 0.40 and related_chain's 0.57.

### F2. Superseded document ranked above its replacement (3 queries)

G031 ("the current drainage strategy"), H017 ("what replaced the earlier drainage strategy
report?") and H002 all rank the superseded Drainage Strategy Report first, with the replacement
second.
- The old report's title is closer to the words people use, and it has two revisions of text.
- The register's `supersedes` link and words like "current" and "replaced" play no part in
  ranking.

### F3. Vocabulary mismatch (the worst query, plus H012)

**G003** ("pond needs to hold more water because the council cut the discharge rate") ranked the
correct report **7th**.
- "Hold more water" and "cut" appear nowhere in the candidate documents, whose source text says
  "storage increases" and "reduce".
- The superseded report shares more of the query's literal words ("water" from "surface water",
  and "rate").

**H012** (also listed under F1) has the same issue in a milder form: "caused us to enlarge" isn't how the council letter
is written.

Exact-word matching can't connect a paraphrase to the document's own wording. That's the
classic limit of lexical retrieval.

### F4. Earlier revisions aren't selected (3 of 5 old-revision queries)

G012, G015 and H008 ask for an earlier revision ("first construction issue", "original invert",
"before the construction revision").
- The document ranks first every time, so old_revision hit@1 is 1.00.
- But the shown revision is the later C02, and the wanted revision isn't named anywhere in the
  evidence.

The baseline picks the best-matching revision by text. Later revisions likely carry more of the
matching text (for example, notes that mention the earlier state), and the engine has no concept
of "earlier" or "original".

The opposite case works through the evidence rather than the ranking. G029 ("the GA … we should
build from") matched P03, but the result shows "Latest for construction: C02", so the user can
still see the right revision.

### F5. Structured cues treated as ordinary words (1 query ranked 7th, plus a risk)

**H006** ("WBS 330 Mill Lane Culvert. Document from Northvale Water about protecting the existing
water main") ranked the correct letter **7th**. All **six** WBS 330 documents came first.
- The Northvale Water letters are filed under WBS 610, not 330. The query's WBS number was
  treated as ordinary text, and "330" in the query matched the document codes, titles and paths
  of every 330 document.
- The sender cue, "from Northvale Water", counts only as a name match. It isn't understood as
  "originator is Northvale Water".

All 18 human queries begin with a WBS reference, and two point to a WBS other than the answer's.
That's a realistic memory slip, and the one that isn't also anchored by a date (H006) failed
badly. A search that treats "WBS 330" as a hint rather than a hard word match would be more
forgiving.

### What the baseline does well

- Exact and partial names, including legacy filenames and the trap in G007: 7 of 7 ranked first.
- Date-anchored queries (7 of 7), helped by distinct wording in minutes, reports and letters.
- Status-anchored queries (7 of 7), because statuses and their aliases are in the index.
- Revision *evidence*: when the ranking picks a newer revision, the "latest for construction"
  line still gives the user the correct revision in 12 of 15 revision queries.
- Typos (smoke tests) and every document within the top 10.

## 4. Limits of this measurement

- **The corpus is small.** With 47 documents, the top 10 is 21% of the corpus, so hit@10 = 1.00
  flatters the baseline. hit@1 and MRR are the more informative figures here, and a larger
  corpus would make hit@3 and hit@10 meaningful. The corpus (64 files, but only 47 logical
  documents) is below the intended 60–100 logical documents; an expansion to about 100 documents
  is planned as a separate step, with the 58 queries and their ground truth kept frozen and this
  47-document report kept as the historical record.
- **Few human queries.** Each of the 18 is worth 5.6 percentage points of human hit@1, so the
  gap between human and generated results is directional, not precise.
- **Author bias.** The generated queries were written by the same author as the corpus, which
  probably makes them easier. The human set's lower hit@1 (0.67 against 0.80) is consistent with
  that.
- **Lenient scoring.** Twelve queries accept either of two documents, which lifts hit@1 somewhat.
  Every case is justified in `human.yaml` and `generated.yaml`.
- **One project, English only.** Nothing here tests cross-project or multilingual retrieval.
- **Scale.** The 47-document corpus is suitable for testing retrieval *quality*, but it cannot
  validate retrieval at production scale. Query latency, index build time, index size and
  ranking behaviour with thousands of near-similar documents are all untested. See section 6.

## 5. What this implies for the next retrieval approach (options, not a decision)

The failures fall into two groups.

- **Understanding what the user asked for:**
  - F1: which role in a thread;
  - F3: paraphrase;
  - F4: which revision;
  - F5: which cues are filters rather than words.
- **Using what the register already knows:** F2 and F1 both involve links (`supersedes`,
  `responds_to`) that exist but aren't used.

Candidate directions, with the patterns each would plausibly address:

| Option | What it is | F1 role | F2 superseded | F3 paraphrase | F4 revision | F5 structured cues | Notes |
|---|---|---|---|---|---|---|---|
| A. Rule-based query parsing plus link-aware ranking (no AI) | detect cues such as "reply", "replaced", "current", "earlier", "from <org>", "WBS nnn"; boost or demote by links and revision order | partly | **yes** | no | **yes** | **yes** | Planned M3 tuning territory. Cheap and fully explainable, but brittle for wording nobody anticipated. |
| B. Semantic (embedding) retrieval | match meaning, not words | weak | no | **yes** | no | no | Addresses the worst vocabulary case (G003). Alone, it probably doesn't separate linked documents with similar meaning. |
| C. Hybrid lexical plus semantic | combine the baseline and option B | weak | no | **yes** | no | partly | Keeps what the baseline already does well (names, codes, typos). |
| D. Reranking the top 10 | a second stage (for example a cross-encoder or an LLM) orders the candidates with the full query and each candidate's evidence | **yes** | **yes**, if links and status are given to it | **yes** | **yes**, if revisions are given to it | **yes** | Well suited because hit@10 is already 1.00: the answer is in the candidate set, only the order is wrong. Evidence can still come from the existing builder. |
| E. LLM query understanding into structured search | turn the query into filters and intents (document type, originator, WBS as a hint, date range, revision intent, relation) before searching | **yes** | **yes** | partly | **yes** | **yes** | Must still show the user how the query was interpreted, to keep the evidence principle. |

These aren't mutually exclusive. The results suggest that the biggest gains come from **ordering
within an already-correct candidate set (D, E)** and from **using the register's links and
revision order (A)**, more than from finding documents the baseline misses (B, C). The single
worst query (G003) is the exception: it's a pure paraphrase case.

**Criteria for comparing options** (applied with `eval/run_eval.py --compare` against this report):
1. Improve hit@1 and MRR overall **and on the human queries**, without lowering hit@3.
2. Improve revision exact from 11/15 without losing the "shown" figure.
3. Keep every result's evidence explainable: no unexplained confidence scores, and the user can
   see why each result is there.
4. Be practical: cost, latency, where data is processed, and how much the approach depends on
   tuning to this particular corpus.

## 6. Scalability: requirements and a future benchmark

### Requirements for production search

- **Search reads a pre-built index.** It must never rescan or re-extract source files per query.
  DCC V1 already works this way: `/api/search` reads only `search_entry`, `content_segment` and
  the register tables. Source files are read only during ingestion and when a user opens one.
- **Ingestion must become incremental.** New or changed documents should be registered,
  extracted and indexed on their own, detected by `sha256` and revision. Today
  `app.ingest.rebuild` reloads, re-extracts and re-indexes everything. That's acceptable for a
  64-file test corpus, but not for production.
- **Whichever intelligent retrieval architecture is chosen must keep both properties.** For
  example, embeddings or other derived data are computed at ingestion and stored, not at query
  time. Any per-query model call must work only on a small candidate set, as a reranker (option D)
  would.

### Benchmark plan (not implemented yet)

To run **before** the intelligent retrieval architecture is chosen, as a test separate from the
quality evaluation:

- **Scales:** about **1,000**, **10,000** and **64,000** documents, with revisions in a realistic
  ratio (about 1.3 per document, as in the corpus).
- **Lightweight synthetic records, no physical files.** Documents, revisions, statuses, links,
  content segments and index rows are generated directly in the database from templates and
  vocabulary like the KVL corpus. Near-duplicates are deliberate, for example many progress
  reports, drawing series and RFIs on similar subjects. No 64,000 PDF, DOCX or XLSX files are
  created.
- **Isolation:** run in a separate schema or database, never mixed into the dev corpus or the
  quality evaluation data.
- **What to measure at each scale:**
  - query latency (p50 and p95) for text only, text plus filters, and filters only;
  - index build time and index size;
  - time to add or change a small batch of documents incrementally;
  - whether a few planted known items are still found in the top 10.

  This last check is a sanity check, not a replacement for the quality evaluation.
- **Engines covered:** the current baseline first. Later, each candidate architecture (A–E), so
  its cost in latency, storage and ingestion time can be weighed alongside its quality results.
- **Output:** a committed benchmark report next to this one, with the same "measure first, then
  decide" rule.

## 7. Suggested next steps (for decision)

1. **Decide the direction** (A–E, or a combination), using this analysis and the criteria above.
2. **Plan and run the scalability benchmark (section 6)** before settling the intelligent
   retrieval architecture, so the decision weighs cost at scale as well as quality.
3. **Make the measurement harder before comparing engines:** a larger corpus so the top 10 is a
   smaller share, and more human-written queries, especially the cross_type, related_chain and
   paraphrase cases where the baseline is weakest.
4. **Keep this baseline report frozen as the reference.** Any M3 tuning or new engine is
   measured against it with the same frozen query set.

## 8. Addendum: the same evaluation on the 100-document corpus

After the corpus expansion (M2.5), the same frozen 58 queries were run once more, with ranking
unchanged, on the 100-document corpus (report `baseline-fts-v1-2026-09-30-corpus-v2`).
- The original 47 documents and their files are byte-identical in both corpora; the
  frozen-corpus guard checks this.
- The 53 new documents each passed an answer-safety review, so none of them is a valid answer
  to any of the 58 queries, and the ground truth is unchanged.

| | 47 documents (register 3717ff517034) | 100 documents (register de124139ab67) |
|---|---|---|
| hit@1 overall | 0.76 | **0.71** |
| hit@3 overall | 0.97 | 0.95 |
| hit@10 overall | 1.00 | 1.00 |
| MRR overall | 0.86 | **0.83** |
| hit@1 generated (40) | 0.80 | **0.72** |
| hit@1 human (18) | 0.67 | 0.67 (unchanged) |
| Revision: exact / shown (of 15) | 11 / 12 | 11 / 12 |

**Five generated queries moved down. In each case, only new distractor documents were ranked
above the answer:**

| Query | Rank | Ranked above the answer |
|---|---|---|
| G011 "Pond 1 GA" | 1 → 2 | Pond 1 West Outfall Headwall Details |
| G021 "the monthly progress report issued at the start of September" | 1 → 2 | Monthly Progress Report – September 2025 (issued 3 October) |
| G040 "the variation the council accepted for about 48 thousand pounds" | 1 → 3 | Variations 05 and 03 |
| G032 "the drawing that changed after the contractor's question about soft clay" | 3 → 5 | RFI-0017 and RFI-0016 |
| G003 "pond needs to hold more water…" | 7 → 8 | Pond 1 West Outfall Headwall Details |

**What this adds to the analysis:**
1. **Some of the 47-document figures were a small-corpus effect,** as section 4 expected. The
   categories that looked perfect (partial_name, date_anchored, status_anchored) each lost one
   query once realistic near-duplicates existed.
2. **The human queries didn't change at all.** Their failures were already caused by the patterns
   in section 3, not by corpus size, so the human figures are the more stable reference.
3. **New evidence for F5 (structured cues as words):**
   - G040's "about 48 thousand pounds" can't be matched to £48,650, so other variations outrank it.
   - G021's "issued at the start of September" is matched on the month in a title, not on the
     issue date.
4. **Several strong distractors had no effect:**
   - the Northgrid cable-protection letter (against H006);
   - the Pond 1 flow control submittal (against G030, H009 and H013);
   - the deck plan P01 (against H008);
   - the road safety audit response (against H011 and H018).

   Those queries either already separated correctly, or already failed for another reason (H006
   is still at rank 7 because of its WBS 330 cue).
5. **The conclusions in sections 5–7 are unchanged.** Every answer is still in the top 10.
   Ordering and revision choice, not recall, remain the problem. The options analysis still
   applies, and the scalability benchmark is still needed.

From this point, the 100-document report is the reference for comparing future engines. The
47-document report stays as the historical first baseline.

**Measurement tooling:** every report now records the corpus it was measured against (document,
revision and file counts, plus a fingerprint of the register), and `--compare` names both reports
and their corpora. The corpus information in the two reports above was added after their runs,
without changing any result. A confirmation re-run on the 100-document corpus produced identical
results and the same fingerprint.
