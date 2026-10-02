"""Rebuild dcc.search_entry: one weighted full-text row per revision, from its primary file.

    python -m app.ingest.build_index

Run after load_register and extract_content.
"""

import psycopg

from app.config import get_settings

BUILD_SQL = """
insert into dcc.search_entry (revision_id, document_id, tsv, trgm_text)
select
  r.id,
  d.id,
  setweight(to_tsvector('english', concat_ws(' ', d.title, d.doc_code, f.filename)), 'A')
  || setweight(to_tsvector('english', concat_ws(' ',
       disc.label, array_to_string(disc.aliases, ' '),
       dt.label, array_to_string(dt.aliases, ' '),
       w.name, array_to_string(w.aliases, ' '), pw.name, array_to_string(pw.aliases, ' '),
       orig.name, array_to_string(orig.aliases, ' '),
       snd.name, array_to_string(snd.aliases, ' '),
       stg.label, array_to_string(stg.aliases, ' '),
       st.label, array_to_string(st.aliases, ' '), pu.label,
       p.full_name)), 'B')
  || setweight(to_tsvector('english', concat_ws(' ',
       r.description,
       (select string_agg(value, ' ') from jsonb_each_text(e.extracted_fields - 'found_in')))), 'C')
  || setweight(coalesce(
       (select to_tsvector('english', string_agg(s.body, ' ' order by s.seq))
        from dcc.content_segment s where s.revision_file_id = f.id), ''::tsvector), 'D'),
  concat_ws(' ', d.title, d.doc_code, f.filename)
from dcc.revision r
join dcc.document d            on d.id = r.document_id
join dcc.revision_file f       on f.revision_id = r.id and f.copy_role = 'primary'
left join dcc.extraction e     on e.revision_file_id = f.id
join dcc.discipline disc       on disc.code = d.discipline_code
join dcc.doc_type dt           on dt.code = d.doc_type_code
join dcc.wbs_element w         on w.code = d.wbs_code
left join dcc.wbs_element pw   on pw.code = w.parent_code
join dcc.organisation orig     on orig.code = d.originator_code
left join dcc.organisation snd on snd.code = r.sender_code
join dcc.stage stg             on stg.code = r.stage_code
left join dcc.revision_current_status cs on cs.revision_id = r.id
left join dcc.status st        on st.code = cs.status_code
left join dcc.permitted_use pu on pu.code = cs.permitted_use_code
left join dcc.person p         on p.id = d.owner_person_id
"""


def build_index(conn: psycopg.Connection, revision_ids: list[int] | None = None) -> int:
    """Rebuild the search index. Does not commit; the caller owns the transaction.

    With `revision_ids`, only those revisions' entries are replaced (incremental update after new or
    changed documents); every other entry is left untouched. Without it, the whole index is rebuilt.
    """
    with conn.transaction():
        if revision_ids is None:
            conn.execute("delete from dcc.search_entry")
            return conn.execute(BUILD_SQL).rowcount
        conn.execute("delete from dcc.search_entry where revision_id = any(%s)", (revision_ids,))
        return conn.execute(BUILD_SQL + "where r.id = any(%s)", (revision_ids,)).rowcount


def main() -> None:
    database_url = get_settings().database_url
    if not database_url:
        raise SystemExit("DATABASE_URL is not set")
    with psycopg.connect(database_url, prepare_threshold=None) as conn:
        rows = build_index(conn)
        conn.commit()
    print(f"Search index rebuilt: {rows} revisions")


if __name__ == "__main__":
    main()
