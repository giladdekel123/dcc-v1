"""Baseline retriever: Postgres weighted full-text search plus trigram similarity. No AI.

score = term coverage + weighted full-text rank + 0.5 x trigram similarity

- term coverage: share of the query's terms found anywhere in the revision (0..1), so documents
  matching more of what the user remembered beat documents repeating one word
- full-text rank: ts_rank_cd with weights A=1.0 B=0.4 C=0.2 D=0.1, normalised to 0..1
- trigram similarity: word_similarity(query, title + code + filename), for typos and fragments

Revisions are ranked, then collapsed to their best revision per document (ties: newer revision).
"""

import psycopg

from app.retrieval.base import HL_END, HL_START, FieldHit, Filters, RawMatch, Snippet

NAME = "baseline-fts-v1"
TRIGRAM_MIN = 0.3
_HIGHLIGHT = f"StartSel={HL_START}, StopSel={HL_END}"
_FIELD_HEADLINE = f"HighlightAll=true, {_HIGHLIGHT}"
_SNIPPET_HEADLINE = f'MaxFragments=2, MaxWords=30, MinWords=12, FragmentDelimiter=" ... ", {_HIGHLIGHT}'

RANK_SQL = """
with scored as (
  select e.revision_id, e.document_id, r.revision_date, r.rev_code,
         coalesce((select count(*) from unnest(%(terms)s::text[]) t where e.tsv @@ t::tsquery)::float
                  / nullif(cardinality(%(terms)s::text[]), 0), 0) as coverage,
         coalesce(ts_rank_cd('{{0.1, 0.2, 0.4, 1.0}}', e.tsv, %(tsq)s::tsquery, 32), 0) as fts_rank,
         case when %(q)s = '' then 0 else extensions.word_similarity(%(q)s, e.trgm_text) end as trigram
  from dcc.search_entry e
  join dcc.revision r on r.id = e.revision_id
  join dcc.document d on d.id = e.document_id
  where {filters}
),
ranked as (
  select *, coverage + fts_rank + 0.5 * trigram as score,
         row_number() over (partition by document_id
                            order by coverage + fts_rank + 0.5 * trigram desc,
                                     revision_date desc, dcc.rev_code_rank(rev_code) desc) as pos_in_document
  from scored
  where %(browse)s or coverage > 0 or trigram >= %(trigram_min)s
)
select revision_id, document_id, score, coverage, fts_rank, trigram
from ranked
where pos_in_document = 1
order by score desc, revision_date desc, document_id
limit %(limit)s
"""

FIELDS_SQL = """
select v.field, v.value,
       case when to_tsvector('english', v.value) @@ %(tsq)s::tsquery
            then ts_headline('english', v.value, %(tsq)s::tsquery, %(opts)s) end as hit,
       (select a from unnest(v.aliases) a where to_tsvector('english', a) @@ %(tsq)s::tsquery limit 1) as alias
from dcc.revision r
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
where r.id = %(revision_id)s and v.value is not null
order by v.ord
"""

SNIPPETS_SQL = """
select s.locator, ts_headline('english', s.body, %(tsq)s::tsquery, %(opts)s)
from dcc.revision_file f
join dcc.content_segment s on s.revision_file_id = f.id
where f.revision_id = %(revision_id)s and f.copy_role = 'primary' and s.body_tsv @@ %(tsq)s::tsquery
order by ts_rank(s.body_tsv, %(tsq)s::tsquery) desc, s.seq
limit 2
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


def _quote(lexeme: str) -> str:
    """A lexeme as a tsquery literal."""
    return "'" + lexeme.replace("\\", "\\\\").replace("'", "''") + "'"


class BaselineFtsRetriever:
    name = NAME

    def search(self, conn: psycopg.Connection, query: str, filters: Filters, limit: int) -> list[RawMatch]:
        query = query.strip()
        lexemes = conn.execute("select tsvector_to_array(to_tsvector('english', %s))", (query,)).fetchone()[0] \
            if query else []
        terms = [_quote(lexeme) for lexeme in lexemes]
        tsq = " | ".join(terms) or None
        active = filters.active()
        where = " and ".join(FILTER_SQL[k] for k in active) or "true"
        rows = conn.execute(RANK_SQL.format(filters=where), {
            **active, "terms": terms, "tsq": tsq, "q": query, "browse": not query,
            "trigram_min": TRIGRAM_MIN, "limit": limit,
        }).fetchall()

        matches = []
        for revision_id, document_id, score, coverage, fts_rank, trigram in rows:
            match = RawMatch(revision_id, document_id, scores={
                "score": round(score, 4), "coverage": round(coverage, 4),
                "fts_rank": round(fts_rank, 4), "trigram": round(trigram, 4)})
            if query:
                match.field_hits = self._field_hits(conn, revision_id, tsq, trigram)
                match.snippets = self._snippets(conn, revision_id, tsq)
            matches.append(match)
        return matches

    def _field_hits(self, conn, revision_id: int, tsq: str | None, trigram: float) -> list[FieldHit]:
        hits = []
        title = None
        for field, value, hit, alias in conn.execute(
                FIELDS_SQL, {"revision_id": revision_id, "tsq": tsq, "opts": _FIELD_HEADLINE}):
            if field == "title":
                title = value
            if hit:
                hits.append(FieldHit(field, hit))
            elif alias:
                hits.append(FieldHit(field, value, via=f"alias '{alias}'"))
        if trigram >= TRIGRAM_MIN and not any(h.field in ("title", "doc_code", "filename") for h in hits):
            hits.insert(0, FieldHit("title", title, via="similar spelling"))
        return hits

    def _snippets(self, conn, revision_id: int, tsq: str | None) -> list[Snippet]:
        if not tsq:
            return []
        return [Snippet(locator, text) for locator, text in conn.execute(
            SNIPPETS_SQL, {"revision_id": revision_id, "tsq": tsq, "opts": _SNIPPET_HEADLINE})]
