"""Facets and filter behaviour against the dev data (read-only)."""

import pytest
from fastapi.testclient import TestClient

from app import db
from app.facets import load_facets
from app.main import app

pytestmark = pytest.mark.db


def all_values(facets):
    return facets.doc_types + facets.disciplines + facets.stages + facets.organisations + facets.wbs


def test_facet_counts_agree_with_the_register(conn):
    facets = load_facets(conn)
    documents = conn.execute("select count(*) from dcc.document").fetchone()[0]
    assert sum(v.count for v in facets.doc_types) == documents
    assert sum(v.count for v in facets.disciplines) == documents
    assert sum(w.count for w in facets.wbs) == documents        # top-level counts include children
    assert all(v.count > 0 for v in all_values(facets))
    assert all(k.count > 0 for w in facets.wbs for k in w.children)


def test_facet_shape(conn):
    facets = load_facets(conn)
    order = [c for c, in conn.execute("select code from dcc.stage order by seq")]
    codes = [s.code for s in facets.stages]
    assert codes == [c for c in order if c in codes]           # lifecycle order
    structures = next(w for w in facets.wbs if w.code == "400")
    assert [k.code for k in structures.children] == ["410"]
    low, high = conn.execute("select min(revision_date), max(revision_date) from dcc.revision").fetchone()
    assert (facets.date_range.min, facets.date_range.max) == (low, high)


def test_api_facets_and_filters(conn):
    db.close_pool()
    client = TestClient(app)
    body = client.get("/api/facets").json()
    assert {"doc_types", "disciplines", "stages", "organisations", "wbs", "date_range"} <= set(body)

    minutes = client.get("/api/search", params={"doc_type": "MM"}).json()["results"]
    minutes_in_register = conn.execute("select count(*) from dcc.document where doc_type_code = 'MM'").fetchone()[0]
    assert len(minutes) == min(minutes_in_register, 10)
    assert {r["document"]["doc_type"]["code"] for r in minutes} == {"MM"}

    structures = client.get("/api/search", params={"wbs": "400"}).json()["results"]
    assert structures and {r["document"]["wbs"]["code"] for r in structures} <= {"400", "410"}

    reversed_dates = client.get("/api/search", params={"date_from": "2025-09-01", "date_to": "2025-01-01"})
    assert reversed_dates.status_code == 422
