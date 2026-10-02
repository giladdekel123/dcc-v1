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


# One statement: the matched revisions with their latest revision, latest revision per permitted
# use, status history and copies (each aggregated per revision or document).
FACTS_SQL = """
select r.id, d.id, d.doc_code, d.title,
       dt.code, dt.label, disc.code, disc.label, w.code, w.name, orig.code, orig.name,
       r.rev_code, r.revision_date, stg.code, stg.label, snd.code, snd.name,
       rs.status_code, st.label, rs.permitted_use_code, pu.label, rs.is_latest, rs.revision_count,
       f.filename, f.original_location,
       lt.rev_code, lt.revision_date, lt.status_code, lt.status_label,
       coalesce(bu.uses, '{}'), coalesce(bu.revs, '{}'),
       coalesce(h.codes, '{}'), coalesce(h.labels, '{}'), coalesce(h.dates, '{}'), coalesce(h.assigned_by, '{}'),
       coalesce(c.paths, '{}')
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
join lateral (
  select l.rev_code, l.revision_date, l.status_code, ls.label as status_label
  from dcc.revision_summary l left join dcc.status ls on ls.code = l.status_code
  where l.is_latest and l.document_id = d.id
) lt on true
left join lateral (
  select array_agg(u.permitted_use_code order by u.permitted_use_code) as uses,
         array_agg(u.rev_code order by u.permitted_use_code) as revs
  from dcc.document_latest_by_use u where u.document_id = d.id
) bu on true
left join lateral (
  select array_agg(e.status_code order by e.effective_date, e.id) as codes,
         array_agg(es.label order by e.effective_date, e.id) as labels,
         array_agg(e.effective_date order by e.effective_date, e.id) as dates,
         array_agg(e.assigned_by_code order by e.effective_date, e.id) as assigned_by
  from dcc.revision_status e join dcc.status es on es.code = e.status_code
  where e.revision_id = r.id
) h on true
left join lateral (
  select array_agg(cp.storage_path order by cp.id) as paths
  from dcc.revision_file cp where cp.copy_role = 'copy' and cp.revision_id = r.id
) c on true
where r.id = any(%s)
"""


def load_facts(conn: psycopg.Connection, revision_ids: list[int]) -> dict[int, RevisionFacts]:
    if not revision_ids:
        return {}
    facts: dict[int, RevisionFacts] = {}
    for row in conn.execute(FACTS_SQL, (revision_ids,)):
        (rid, did, code, title, dt, dtl, dc, dcl, wc, wn, oc, on, rev, rdate, sc, sl, sdc, sdn,
         stc, stl, puc, pul, is_latest, count, filename, location,
         lrev, ldate, lsc, lsl, uses, use_revs, h_codes, h_labels, h_dates, h_by, copies) = row
        facts[rid] = RevisionFacts(
            revision_id=rid, document_id=did, doc_code=code, title=title,
            doc_type=(dt, dtl), discipline=(dc, dcl), wbs=(wc, wn), originator=(oc, on),
            rev_code=rev, revision_date=rdate, stage=(sc, sl), sender=(sdc, sdn) if sdc else None,
            current_status=(stc, stl) if stc else None, permitted_use=(puc, pul) if puc else None,
            is_latest=is_latest, revision_count=count, filename=filename, original_location=location,
            latest=(lrev, ldate, (lsc, lsl) if lsc else None),
            latest_by_use=dict(zip(uses, use_revs)),
            status_history=[StatusEvent(*event) for event in zip(h_codes, h_labels, h_dates, h_by)],
            copies=list(copies))
    return facts
