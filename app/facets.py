"""Filter values present in the corpus, with document counts (whole corpus, not per search)."""

import psycopg

from app.models import DateRange, FacetsResponse, FacetValue, WbsFacet

DOC_TYPES_SQL = """
select dt.code, dt.label, count(*) from dcc.document d join dcc.doc_type dt on dt.code = d.doc_type_code
group by dt.code, dt.label order by dt.label
"""
DISCIPLINES_SQL = """
select x.code, x.label, count(*) from dcc.document d join dcc.discipline x on x.code = d.discipline_code
group by x.code, x.label order by x.label
"""
# A document matches a stage filter if any of its revisions is in that stage.
STAGES_SQL = """
select s.code, s.label, count(distinct r.document_id) from dcc.revision r join dcc.stage s on s.code = r.stage_code
group by s.code, s.label, s.seq order by s.seq
"""
# Same semantics as the search org filter: originator, or sender of any revision.
ORGANISATIONS_SQL = """
select o.code, o.name, count(distinct d.id)
from dcc.organisation o
join dcc.document d on d.originator_code = o.code
   or exists (select 1 from dcc.revision r where r.document_id = d.id and r.sender_code = o.code)
group by o.code, o.name order by o.name
"""
WBS_SQL = """
select w.code, w.name, w.parent_code, count(d.id)
from dcc.wbs_element w left join dcc.document d on d.wbs_code = w.code
group by w.code, w.name, w.parent_code order by w.code
"""


def _values(conn: psycopg.Connection, sql: str) -> list[FacetValue]:
    return [FacetValue(code=code, label=label, count=count) for code, label, count in conn.execute(sql)]


def load_facets(conn: psycopg.Connection) -> FacetsResponse:
    rows = conn.execute(WBS_SQL).fetchall()
    children: dict[str, list] = {}
    for code, name, parent, count in rows:
        if parent:
            children.setdefault(parent, []).append(WbsFacet(code=code, label=name, count=count))
    wbs = []
    for code, name, parent, count in rows:
        if parent:
            continue
        kids = [k for k in children.get(code, []) if k.count]
        total = count + sum(k.count for k in kids)  # the WBS filter covers the element and its children
        if total:
            wbs.append(WbsFacet(code=code, label=name, count=total, children=kids))

    low, high = conn.execute("select min(revision_date), max(revision_date) from dcc.revision").fetchone()
    return FacetsResponse(
        doc_types=_values(conn, DOC_TYPES_SQL),
        disciplines=_values(conn, DISCIPLINES_SQL),
        stages=_values(conn, STAGES_SQL),
        organisations=_values(conn, ORGANISATIONS_SQL),
        wbs=wbs,
        date_range=DateRange(min=low, max=high),
    )
