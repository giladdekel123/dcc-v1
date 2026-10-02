"""Baseline retriever: Postgres weighted full-text search plus trigram similarity. No AI.

score = term coverage + weighted full-text rank + 0.5 x trigram similarity

- term coverage: share of the query's terms found anywhere in the revision (0..1), so documents
  matching more of what the user remembered beat documents repeating one word
- full-text rank: ts_rank_cd with weights A=1.0 B=0.4 C=0.2 D=0.1, normalised to 0..1
- trigram similarity: word_similarity(query, title + code + filename), for typos and fragments

Revisions are ranked, then collapsed to their best revision per document (ties: newer revision).

Two stages: the score above is computed only for candidates - the STAGE1_LIMIT best full-text
matches by coverage then ts_rank, plus every trigram (spelling) candidate, or every filtered row
when browsing. A query matching STAGE1_LIMIT rows or fewer is ranked exactly as by scoring every
match. Chosen by experiment 2C-v2 (eval/experiments/reports/two-stage-v2-*.md).

Round trips: one for ranking (the trigram threshold is set in the same pipeline), one for the
evidence of all results together.
"""

import psycopg

from app.retrieval.base import HL_END, HL_START, FieldHit, Filters, RawMatch, Snippet

NAME = "baseline-fts-v1"
TRIGRAM_MIN = 0.3
# Stage 1 keeps this many full-text matches (best coverage, then ts_rank). Experiment 2C-v2 arm A:
# frozen-set quality unchanged at 10,000 and 40,000 documents; 158/158 and 156/158 top 10s identical.
STAGE1_LIMIT = 2000
# The trigram index finds candidates with word_similarity at or above this (set per session as
# pg_trgm.word_similarity_threshold); TRIGRAM_MIN is then applied exactly. Kept just below
# TRIGRAM_MIN so the index can never miss a row the exact condition would keep.
TRIGRAM_CANDIDATE_MIN = 0.29
SET_TRIGRAM_THRESHOLD_SQL = "select set_config('pg_trgm.word_similarity_threshold', %s, false)"
_HIGHLIGHT = f"StartSel={HL_START}, StopSel={HL_END}"
_FIELD_HEADLINE = f"HighlightAll=true, {_HIGHLIGHT}"
_SNIPPET_HEADLINE = f'MaxFragments=2, MaxWords=30, MinWords=12, FragmentDelimiter=" ... ", {_HIGHLIGHT}'

# q: the query's stemmed terms, each quoted as a tsquery literal, in tsvector order; computed once.
# first_stage: the STAGE1_LIMIT best full-text matches by coverage, then ts_rank (cheap; coverage
# dominates the final score). candidates: those, every trigram candidate and, when browsing, every
# filtered row. The exact conditions in `ranked` decide. stage1_limit NULL scores every match.
# `scored` is materialized so each candidate's coverage, rank and trigram are computed once; inlined,
# Postgres re-evaluated them for every reference in `ranked` (score, window order, filter).
RANK_SQL = """
with q as materialized (
  select terms, terms::tsquery[] as term_queries,
         nullif(array_to_string(terms, ' | '), '') as tsq_text,
         nullif(array_to_string(terms, ' | '), '')::tsquery as tsq
  from (select array(select '''' || replace(replace(lexeme, '\\', '\\\\'), '''', '''''') || ''''
                     from unnest(tsvector_to_array(to_tsvector('english', %(q)s))) with ordinality as t(lexeme, n)
                     order by n) as terms) quoted
),
first_stage as (
  select e.revision_id
  from dcc.search_entry e
  join dcc.revision r on r.id = e.revision_id
  join dcc.document d on d.id = e.document_id
  where {filters} and e.tsv @@ (select tsq from q)
  order by coalesce((select count(*) from unnest((select term_queries from q)) t where e.tsv @@ t)::float
                    / nullif(cardinality((select terms from q)), 0), 0) desc,
           ts_rank('{{0.1, 0.2, 0.4, 1.0}}', e.tsv, (select tsq from q)) desc, e.revision_id
  limit %(stage1_limit)s
),
candidates as (
  select revision_id from first_stage
  union
  select e.revision_id
  from dcc.search_entry e
  join dcc.revision r on r.id = e.revision_id
  join dcc.document d on d.id = e.document_id
  where {filters} and %(q)s operator(extensions.<%%) e.trgm_text
  union
  select e.revision_id
  from dcc.search_entry e
  join dcc.revision r on r.id = e.revision_id
  join dcc.document d on d.id = e.document_id
  where %(browse)s and {filters}
),
scored as materialized (
  select e.revision_id, e.document_id, r.revision_date, r.rev_code,
         coalesce((select count(*) from unnest((select term_queries from q)) t where e.tsv @@ t)::float
                  / nullif(cardinality((select terms from q)), 0), 0) as coverage,
         coalesce(ts_rank_cd('{{0.1, 0.2, 0.4, 1.0}}', e.tsv, (select tsq from q), 32), 0) as fts_rank,
         case when %(q)s = '' then 0 else extensions.word_similarity(%(q)s, e.trgm_text) end as trigram
  from candidates c
  join dcc.search_entry e on e.revision_id = c.revision_id
  join dcc.revision r on r.id = e.revision_id
  join dcc.document d on d.id = e.document_id
),
ranked as (
  select *, coverage + fts_rank + 0.5 * trigram as score,
         row_number() over (partition by document_id
                            order by coverage + fts_rank + 0.5 * trigram desc,
                                     revision_date desc, dcc.rev_code_rank(rev_code) desc) as pos_in_document
  from scored
  where %(browse)s or coverage > 0 or trigram >= %(trigram_min)s
)
select revision_id, document_id, score, coverage, fts_rank, trigram, (select tsq_text from q) as tsq
from ranked
where pos_in_document = 1
order by score desc, revision_date desc, document_id
limit %(limit)s
"""

# Matched fields and the best two passages for all results in one statement.
EVIDENCE_SQL = """
with q as (select %(tsq)s::tsquery as tsq),
fields as (
  select r.id as revision_id, v.ord, v.field, v.value,
         case when to_tsvector('english', v.value) @@ q.tsq
              then ts_headline('english', v.value, q.tsq, %(field_opts)s) end as hit,
         (select a from unnest(v.aliases) a where to_tsvector('english', a) @@ q.tsq limit 1) as alias
  from dcc.revision r
  cross join q
  join dcc.document d            on d.id = r.document_id
  join dcc.revision_file f       on f.revision_id = r.id and f.copy_role = 'primary'
  join dcc.doc_type dt           on dt.code = d.doc_type_code
  join dcc.discipline disc       on disc.code = d.discipline_code
  join dcc.wbs_element w         on w.code = d.wbs_code
  join dcc.organisation orig     on orig.code = d.originator_code
  left join dcc.organisation snd on snd.code = r.sender_code
  join dcc.stage stg             on stg.code = r.stage_code
  left join dcc.revision_current_status cs on cs.revision_id = r.id
  left join dcc.status st        on st.code = cs.status_code
  left join dcc.person p         on p.id = d.owner_person_id
  cross join lateral (values
    (1, 'title', d.title, null::text[]),
    (2, 'doc_code', d.doc_code, null),
    (3, 'filename', f.filename, null),
    (4, 'doc_type', dt.label, dt.aliases),
    (5, 'discipline', disc.label, disc.aliases),
    (6, 'wbs', w.name, w.aliases),
    (7, 'originator', orig.name, orig.aliases),
    (8, 'sender', snd.name, snd.aliases),
    (9, 'stage', stg.label, stg.aliases),
    (10, 'status', st.label, st.aliases),
    (11, 'owner', p.full_name, null)
  ) as v(ord, field, value, aliases)
  where r.id = any(%(revision_ids)s) and v.value is not null
),
passages as (
  select f.revision_id, s.locator, s.body,
         row_number() over (partition by f.revision_id
                            order by ts_rank(s.body_tsv, q.tsq) desc, s.seq) as n
  from dcc.revision_file f
  cross join q
  join dcc.content_segment s on s.revision_file_id = f.id
  where f.revision_id = any(%(revision_ids)s) and f.copy_role = 'primary' and s.body_tsv @@ q.tsq
)
select revision_id, 'field' as kind, ord, field, value, hit, alias from fields
union all
select p.revision_id, 'passage', p.n, p.locator, ts_headline('english', p.body, q.tsq, %(snippet_opts)s), null, null
from passages p cross join q
where p.n <= 2
order by 1, 2, 3
"""

FILTER_SQL = {
    "discipline": "d.discipline_code = %(discipline)s",
    "doc_type": "d.doc_type_code = %(doc_type)s",
    "stage": "r.stage_code = %(stage)s",
    "org": "(d.originator_code = %(org)s or r.sender_code = %(org)s)",
    "wbs": "d.wbs_code in (select code from dcc.wbs_element where code = %(wbs)s or parent_code = %(wbs)s)",
    "date_from": "r.revision_date >= %(date_from)s",
    "date_to": "r.revision_date <= %(date_to)s",
}


def ranking_query(query: str, filters: Filters, limit: int,
                  stage1_limit: int | None = STAGE1_LIMIT) -> tuple[str, dict]:
    """The ranking SQL and its parameters (also used by the benchmark to explain the same query).
    stage1_limit=None scores every match (LIMIT NULL), the exhaustive ranking tests compare against."""
    query = query.strip()
    active = filters.active()
    where = " and ".join(FILTER_SQL[k] for k in active) or "true"
    return RANK_SQL.format(filters=where), {
        **active, "q": query, "browse": not query, "trigram_min": TRIGRAM_MIN, "limit": limit,
        "stage1_limit": stage1_limit}


class BaselineFtsRetriever:
    name = NAME

    def search(self, conn: psycopg.Connection, query: str, filters: Filters, limit: int) -> list[RawMatch]:
        query = query.strip()
        sql, params = ranking_query(query, filters, limit)
        with conn.pipeline():                            # one round trip for both statements
            conn.execute(SET_TRIGRAM_THRESHOLD_SQL, (str(TRIGRAM_CANDIDATE_MIN),))
            ranking = conn.execute(sql, params)
        rows = ranking.fetchall()

        matches = [RawMatch(revision_id, document_id, scores={
            "score": round(score, 4), "coverage": round(coverage, 4),
            "fts_rank": round(fts_rank, 4), "trigram": round(trigram, 4)})
            for revision_id, document_id, score, coverage, fts_rank, trigram, _ in rows]
        if query and rows:
            tsq = rows[0][6]
            fields, passages = self._evidence(conn, [m.revision_id for m in matches], tsq)
            for match, row in zip(matches, rows):
                match.field_hits = self._field_hits(fields.get(match.revision_id, []), trigram=row[5])
                match.snippets = passages.get(match.revision_id, []) if tsq else []
        return matches

    def _evidence(self, conn, revision_ids: list[int], tsq: str | None):
        fields: dict[int, list[tuple]] = {}
        passages: dict[int, list[Snippet]] = {}
        for revision_id, kind, _, field, value, hit, alias in conn.execute(EVIDENCE_SQL, {
                "revision_ids": revision_ids, "tsq": tsq,
                "field_opts": _FIELD_HEADLINE, "snippet_opts": _SNIPPET_HEADLINE}):
            if kind == "field":
                fields.setdefault(revision_id, []).append((field, value, hit, alias))
            else:
                passages.setdefault(revision_id, []).append(Snippet(field, value))
        return fields, passages

    def _field_hits(self, rows: list[tuple], trigram: float) -> list[FieldHit]:
        hits = []
        title = None
        for field, value, hit, alias in rows:
            if field == "title":
                title = value
            if hit:
                hits.append(FieldHit(field, hit))
            elif alias:
                hits.append(FieldHit(field, value, via=f"alias '{alias}'"))
        if trigram >= TRIGRAM_MIN and not any(h.field in ("title", "doc_code", "filename") for h in hits):
            hits.insert(0, FieldHit("title", title, via="similar spelling"))
        return hits
