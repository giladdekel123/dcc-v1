# IR-1b pre-implementation clarification: targeted-class criterion

## Status

- Applies to `eval/experiments/IR1B_PREREGISTRATION.md` (commit `cd6c657ae5c23bf15cbb0beb3377335b0b556926`,
  sha256 `9432b13cc014127c3078b230b40287f70dd4f52a5c8804053143f118e63d5eb4`), which is not edited.
- Written on 2026-10-03, after preregistration and **before any IR-1b implementation or result**.
- It resolves one ambiguity: how full-success criterion 8 ("at least one targeted retrieval class
  improves over condition 0") is judged. It replaces the class-improvement sentence in section 11 of
  the preregistration ("more of its queries improve than worsen").
- It does not change any condition, retrieval mechanism, weight, constant, query, annotation, or any
  success or regression criterion other than making criterion 8 precise.

## Targeted classes (unchanged)

The classes are exactly those defined before IR-1b (IR-1 preregistration sections 7.1 and 7.3):

| Class | Queries |
|---|---|
| Relationship chain | G016, G018, G019, G026, G032 |
| Supersession | G031, H017 |
| Requested revision | G012, G015, G029, H008 |
| Soft clue | H006 |

## Query-level movement (relative to condition 0)

**Relationship-chain, supersession and soft-clue classes** (document rank of the correct target):

- *improves*: the target's rank is better than at baseline;
- *worsens*: the target's rank is worse than at baseline, including leaving the top 10;
- *unchanged*: the rank is identical to baseline.

**Requested-revision class** (requested-revision exactness):

- *improves*: the requested revision was not exact at baseline and becomes exact;
- *worsens*: it was exact at baseline and becomes non-exact;
- *unchanged*: otherwise, for this class-level criterion.

## Class-level rule for criterion 8

A targeted class counts as **improved** only when **at least one query in the class improves and no
query in the class worsens**. No net-count rule ("more improvements than regressions") is used for full
success.

All individual movements of every query, in every class and condition, are still reported regardless
of this class-level definition.
