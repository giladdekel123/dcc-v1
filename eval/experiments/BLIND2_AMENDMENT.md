# Blind set 2 amendment: blind query source, WBS clues and the nature of the test

## Status

- Amends `eval/experiments/BLIND2_PREREGISTRATION.md` (commit
  `e8eb6f121300cf100d59d49e07f17d196d28fc53`, sha256
  `22829248820b8791492b7aed22edd68df578a8bcd1e464ba61b6b07d68538fbe`), which is not edited or
  superseded.
- Written on 2026-10-03, **before** any S01–S12 query file, annotation file, blind runner or blind
  retrieval output exists, and without any access to the sealed answer key.
- It replaces the query-authorship rule (preregistration section 5) and the purpose statement
  (section 1) as set out below. It does not change the set, the candidate, the conditions, the
  metrics, the safety gate, the non-regression criteria, the verdicts, the key protection or the
  one-shot order.

## M1 — Nature of the test (replaces the purpose statement)

The S01–S12 scenario texts were written by Claude while Claude was also writing the answer key, so their
wording was chosen with knowledge of the target documents. This is therefore **not an independent
human-recollection wording test**. It is:

> a one-shot held-out retrieval test on 12 previously unused scenarios, with target-informed scenario
> wording.

The questions it answers are unchanged otherwise: whether the development-selected condition-8 candidate
holds up without harming conventional retrieval on scenarios not used to select or tune it, and whether
its revision/version benefit appears outside the 58 development queries. Results are reported with this
limitation stated.

## M2 — Query body (replaces the authorship rule)

- The query body for each of S01–S12 is the **original scenario text as first delivered on 2026-10-02 at
  14:25:04 UTC** (session `237dab39-a955-4952-8afa-37c8b312c3aa`; repeated unchanged at 14:40 UTC), with
  no rewriting, summarising, enrichment, cleanup or interpretation.
- **Formatting (the only change to the delivered text):** remove the leading label with its bold markers
  and the single space after it (`**S01.** ` … `**S12.** `), and remove every remaining `**` marker.
  Every other character, word, punctuation mark and space is kept byte-for-byte. The scenario id is
  stored separately.
- Later expanded or elaborated versions of the scenarios are excluded. Their details were
  discussion-generated, may be imaginary or incorrect, and are not used in any form.
- Nothing is added to or suggested for any query apart from a user-supplied WBS (M3): no contractor
  names, contract or agreement numbers, document references, formal document titles, technical
  methods, company names, extra dates, materials, species or engineering terms, inferred metadata, or
  any detail from later discussion.
- Wording that is part of the original scenario text stays, including its instructions to the reader
  (for example "not the contractor's question") and its cross-references (S02 begins "Same situation as
  S01."). These are searched as written.

## M3 — User-supplied WBS

- The user may supply a WBS code for a scenario only where the user genuinely knows it independently.
- If the user supplies one, the query text is the formatted body, then one space, then the literal clue
  `WBS <code>` exactly as supplied (for example `WBS 320`). B0, B2 and B8 therefore all receive the
  identical query text, including the clue.
- If the user supplies none for a scenario, nothing is appended.
- Claude Code does not suggest, infer, check, verify or retrieve any WBS, and never against the answer
  key.
- The per-scenario WBS choices (a code, or none) are frozen and committed before any retrieval.
- A WBS that already appears in the original scenario text (S11 contains "(WBS 300)") is part of the
  query body under M2, not a user-supplied clue.

## M4 — Query file

- The query file contains only, per scenario: the id (S01–S12), the user-supplied WBS or none, and the
  query text (M2 body plus any M3 clue). It contains no expected document, revision, ranking target or
  answer-derived field.
- It is hashed (sha256) and committed before any retrieval, separately from the source pins below.
- Each query body in it must reproduce the formatted-body hash recorded below; each query text must equal
  that body, plus the M3 clue where one was supplied.

## M5 — Annotations (unchanged in substance)

- The user writes the interpreted requests independently, without access to the answer key, under the
  frozen interpretation schema and annotation rules (preregistration section 6). Each request's
  `raw_text` equals that scenario's frozen query text (M4).
- Claude Code does not author, suggest, review or improve any annotation content. Its only role is
  mechanical: checking that the file parses with the frozen Stage-1 request parser and contains no
  answer-derived field, and reporting format errors without proposing content.
- The revision-sensitive list is computed mechanically from the user's frozen annotations and committed
  before retrieval.

## M6 — Source pins

Computed mechanically on 2026-10-03 from the 12 scenario lines of the 14:25:04 UTC message (identical in
the 14:40 UTC repeat). The extraction printed only these hashes, after confirming each line carries its
own label in order and contains no document code, revision code, hash or answer wording. The answer key
was not accessed. Hashes are sha256 of the UTF-8 text; set hashes are over the 12 items in order, each
followed by one LF.

| | sha256 |
|---|---|
| Source set (12 delivered lines, as delivered) | `16e951e1a99a6ffc288806c6f1966daec883342346857bd9b52ae22512d1e49a` |
| Body set (12 formatted bodies, M2) | `7ca87f7e0c9ee80b6a04bec531c9a7f65de17bf1a85d886a2f9932b0b45106a9` |

| Id | Delivered line | Formatted body |
|---|---|---|
| S01 | `6a45e568eb4857da721a121fe57ef5e718cdfe05d99b465bf2925d0cad5e8ee7` | `5ac81fce71396aba2555c5277730613b0a0d43e7c7da676befd7a73eb30fc90b` |
| S02 | `49f440760616b6a000b7f60388034831c1cd47ad5fbaf6766988226ea2a2d74a` | `53c71b53b1c22b7f389c2a1963846f8257d41e9edc95a0883bfffd1bfb1fe93e` |
| S03 | `42ca724b81e226a185316703379af5f877f4fe385b87d307cee6b1294eced425` | `bccfe2da2bd27a610c3334c7abbefeb0ad61efc227f8e2c18454d8d93787a2f4` |
| S04 | `6de1b75660f34533309851a9aaa1d32ff9a8ba0c4ca416f527bff20c9b39beb6` | `557b9dfa2e472a7ad5a31ed3a4e4887faa18dd420890509164260f80f8a71d04` |
| S05 | `0cac89a621c89d9adf4dab53bd832166c0640ef2c0e3d1004d53cb1841fdbaf3` | `3b8b16265f9a077c6a3af6cdf8fbe50e2a8f433e2d5d56a832218fd529c1d23b` |
| S06 | `f9ee8a34891fd810bbec2a343018f12a22f10d04c8516f0313ce572d40c88102` | `6dc8dcde9dfbed4939efc80a0eadd2086ce25a70aa76fbcea607bf8cba8af244` |
| S07 | `a00cf5c12e01b41426438bf34eb109dd41d50fe432f89bdb61f0fe55f58b8713` | `0ea8bfcbc3de8e236184feb76cf420b94ddcb292f6b3db265704eb335974be74` |
| S08 | `6c86e4bd35fe87245b937a596a3b7f2f258a417959d62ed9588873346691a035` | `bc3ed8858da6a53cb4dacde8657f9b7346a1dfd5b64c7fc7bdb3916cc66eb185` |
| S09 | `2253340359f646439162c372ab801cdc88496a1cb2dfcdb0c167e48158958060` | `1a95ac69cea487dd51154f0a671ce00b220d410972292e79accb7f0dab8acf91` |
| S10 | `20183d796f5be44510e304810dae72a26787a7bbee3f013b5275966e4411e8f4` | `105ca06908c052d638058f45767b15ee8de5f61044358c781756d61e93f551a5` |
| S11 | `e6846dce301a52a2a18956e66455d4cbee5c82234b816bb3258f2c8eb49e3d52` | `0a31bad002fdc4aacfc83360238ee91d35ef1febecd0dfeb4d43ebe201cdafee` |
| S12 | `8015f3fec46f7826e42b6e34a04c6eeb8f082569eb80cb63c147a5d422588f94` | `131ccd5bb2cedfd4ca3149f4694e2495220687d2d2d8a48b8262020309f70f5e` |

## M7 — Unchanged

Everything else in the preregistration stands: S01–S12 only (no S13), n = 12; the fixed candidate
(IR-1b condition 8 at `865c0a4a143ad6c1b448701d62afd2c7e35c045c`); conditions B0, B2, B8 and B8r; the
metrics; the strict safety gate; the aggregate non-regression rule; verdicts A, B and C; the key
fingerprint `1c5c67240d03f9b0fb91fae43de54d285c551d335734902aff5d8d2ac00867d3` and its protection; the
one-shot order; and failure handling.
