"""Registered facts about matched revisions (independent of the retrieval engine)."""

from dataclasses import dataclass, field
from datetime import date

import psycopg


@dataclass
class StatusEvent:
    code: str
    label: str
    effective_date: date
    assigned_by: str | None


@dataclass
class RevisionFacts:
    revision_id: int
    document_id: int
    doc_code: str
    title: str
    doc_type: tuple[str, str]
    discipline: tuple[str, str]
    wbs: tuple[str, str]
    originator: tuple[str, str]
    rev_code: str
    revision_date: date
    stage: tuple[str, str]
    sender: tuple[str, str] | None
    current_status: tuple[str, str] | None
    permitted_use: tuple[str, str] | None
    is_latest: bool
    revision_count: int
    latest: tuple[str, date, tuple[str, str] | None] | None = None   # rev, date, status of the latest revision
    latest_by_use: dict[str, str] = field(default_factory=dict)
    status_history: list[StatusEvent] = field(default_factory=list)
    filename: str = ""
    original_location: str = ""
    copies: list[str] = field(default_factory=list)            # storage paths of copies


FACTS_SQL = """
select r.id, d.id, d.doc_code, d.title,
       dt.code, dt.label, disc.code, disc.label, w.code, w.name, orig.code, orig.name,
       r.rev_code, r.revision_date, stg.code, stg.label, snd.code, snd.name,
       rs.status_code, st.label, rs.permitted_use_code, pu.label, rs.is_latest, rs.revision_count,
       f.filename, f.original_location
from dcc.revision r
join dcc.document d            on d.id = r.document_id
join dcc.doc_type dt           on dt.code = d.doc_type_code
join dcc.discipline disc       on disc.code = d.discipline_code
join dcc.wbs_element w         on w.code = d.wbs_code
join dcc.organisation orig     on orig.code = d.originator_code
join dcc.stage stg             on stg.code = r.stage_code
left join dcc.organisation snd on snd.code = r.sender_code
join dcc.revision_summary rs   on rs.revision_id = r.id
left join dcc.status st        on st.code = rs.status_code
left join dcc.permitted_use pu on pu.code = rs.permitted_use_code
join dcc.revision_file f       on f.revision_id = r.id and f.copy_role = 'primary'
where r.id = any(%s)
"""


def load_facts(conn: psycopg.Connection, revision_ids: list[int]) -> dict[int, RevisionFacts]:
    if not revision_ids:
        return {}
    facts: dict[int, RevisionFacts] = {}
    for row in conn.execute(FACTS_SQL, (revision_ids,)):
        (rid, did, code, title, dt, dtl, dc, dcl, wc, wn, oc, on, rev, rdate, sc, sl, sdc, sdn,
         stc, stl, puc, pul, is_latest, count, filename, location) = row
        facts[rid] = RevisionFacts(
            revision_id=rid, document_id=did, doc_code=code, title=title,
            doc_type=(dt, dtl), discipline=(dc, dcl), wbs=(wc, wn), originator=(oc, on),
            rev_code=rev, revision_date=rdate, stage=(sc, sl), sender=(sdc, sdn) if sdc else None,
            current_status=(stc, stl) if stc else None, permitted_use=(puc, pul) if puc else None,
            is_latest=is_latest, revision_count=count, filename=filename, original_location=location)

    document_ids = list({f.document_id for f in facts.values()})
    latest = {did: (rev, rdate, (sc, sl) if sc else None) for did, rev, rdate, sc, sl in conn.execute("""
        select rs.document_id, rs.rev_code, rs.revision_date, rs.status_code, st.label
        from dcc.revision_summary rs left join dcc.status st on st.code = rs.status_code
        where rs.is_latest and rs.document_id = any(%s)""", (document_ids,))}
    by_use: dict[int, dict[str, str]] = {}
    for did, use, rev in conn.execute(
            "select document_id, permitted_use_code, rev_code from dcc.document_latest_by_use "
            "where document_id = any(%s)", (document_ids,)):
        by_use.setdefault(did, {})[use] = rev
    history: dict[int, list[StatusEvent]] = {}
    for rid, code, label, when, by in conn.execute("""
        select rs.revision_id, rs.status_code, st.label, rs.effective_date, rs.assigned_by_code
        from dcc.revision_status rs join dcc.status st on st.code = rs.status_code
        where rs.revision_id = any(%s) order by rs.effective_date""", (revision_ids,)):
        history.setdefault(rid, []).append(StatusEvent(code, label, when, by))
    copies: dict[int, list[str]] = {}
    for rid, path in conn.execute("""
        select revision_id, storage_path from dcc.revision_file
        where copy_role = 'copy' and revision_id = any(%s) order by id""", (revision_ids,)):
        copies.setdefault(rid, []).append(path)

    for f in facts.values():
        f.latest = latest[f.document_id]
        f.latest_by_use = by_use.get(f.document_id, {})
        f.status_history = history.get(f.revision_id, [])
        f.copies = copies.get(f.revision_id, [])
    return facts
