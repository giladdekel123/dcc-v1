"""Schema tests against the hosted dev database. All writes are rolled back."""

from datetime import date

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.db

DCC_TABLES = {
    "discipline", "doc_type", "stage", "permitted_use", "status",
    "wbs_element", "organisation", "person",
    "document", "revision", "revision_status", "revision_file",
    "extraction", "content_segment", "information_link",
}


def scalar(conn, sql, params=None):
    return conn.execute(sql, params).fetchone()[0]


def add_document(conn, doc_code, doc_type="DR"):
    return scalar(
        conn,
        """insert into dcc.document (doc_code, title, wbs_code, discipline_code, doc_type_code, originator_code)
           values (%s, 'Test document', '410', 'S', %s, 'ADM') returning id""",
        (doc_code, doc_type),
    )


def add_revision(conn, document_id, rev_code, issued, stage="DD", statuses=()):
    revision_id = scalar(
        conn,
        """insert into dcc.revision (document_id, rev_code, revision_date, stage_code)
           values (%s, %s, %s, %s) returning id""",
        (document_id, rev_code, issued, stage),
    )
    for status_code, effective in statuses:
        conn.execute(
            """insert into dcc.revision_status (revision_id, status_code, effective_date)
               values (%s, %s, %s)""",
            (revision_id, status_code, effective),
        )
    return revision_id


@pytest.fixture
def project(conn):
    conn.execute("insert into dcc.wbs_element (code, name) values ('410', 'Test bridge')")
    conn.execute("insert into dcc.organisation (code, name, role) values ('ADM', 'Test designer', 'designer')")
    return conn


def summary(conn, document_id):
    rows = conn.execute(
        """select rev_code, is_latest, is_latest_for_use, permitted_use_code, status_code, revision_count
           from dcc.revision_summary where document_id = %s""",
        (document_id,),
    ).fetchall()
    return {r[0]: r[1:] for r in rows}


def latest_by_use(conn, document_id):
    rows = conn.execute(
        "select permitted_use_code, rev_code from dcc.document_latest_by_use where document_id = %s",
        (document_id,),
    ).fetchall()
    return dict(rows)


def test_all_tables_exist_with_rls(conn):
    rows = conn.execute(
        """select c.relname, c.relrowsecurity from pg_class c
           join pg_namespace n on n.oid = c.relnamespace
           where n.nspname = 'dcc' and c.relkind = 'r'"""
    ).fetchall()
    assert {name for name, _ in rows} == DCC_TABLES
    assert all(rls for _, rls in rows)


def test_public_api_roles_cannot_use_schema(conn):
    for role in ("anon", "authenticated"):
        assert scalar(conn, "select has_schema_privilege(%s, 'dcc', 'usage')", (role,)) is False


def test_convention_vocab_seeded(conn):
    assert scalar(conn, "select count(*) from dcc.discipline") == 8
    assert scalar(conn, "select count(*) from dcc.doc_type") == 9
    assert scalar(conn, "select string_agg(code, ',' order by seq) from dcc.stage") == "PD,DD,CN,HO"
    assert scalar(conn, "select count(*) from dcc.permitted_use") == 6
    assert scalar(conn, "select count(*) from dcc.status") == 11
    assert scalar(conn, "select permitted_use_code from dcc.status where code = 'FC'") == "construction"
    assert scalar(conn, "select permitted_use_code from dcc.status where code = 'RJ'") == "not_permitted"


def test_latest_is_by_issue_date_not_revision_code(project):
    conn = project
    doc = add_document(conn, "KVL-ADM-410-DR-S-0102")
    add_revision(conn, doc, "P02", date(2024, 9, 1), statuses=[("RV", date(2024, 9, 1))])
    add_revision(conn, doc, "C01", date(2025, 2, 1), stage="CN", statuses=[("FC", date(2025, 2, 1))])
    add_revision(conn, doc, "C02", date(2025, 6, 1), stage="CN", statuses=[("FC", date(2025, 6, 1))])
    # P03 issued for comment after C02 for construction
    add_revision(conn, doc, "P03", date(2025, 9, 1), stage="CN", statuses=[("RV", date(2025, 9, 1))])

    s = summary(conn, doc)
    assert [rev for rev, row in s.items() if row[0]] == ["P03"]
    assert s["P03"][4] == 4
    assert latest_by_use(conn, doc) == {"review": "P03", "construction": "C02"}
    # C01 keeps its FC status; being older is not a status
    assert s["C01"][3] == "FC"


def test_rejected_latest_submittal_keeps_earlier_approval_visible(project):
    conn = project
    doc = add_document(conn, "KVL-ADM-410-SB-S-0001", doc_type="SB")
    add_revision(conn, doc, "P01", date(2025, 3, 1),
                 statuses=[("AP", date(2025, 3, 1)), ("AN", date(2025, 3, 20))])
    add_revision(conn, doc, "P02", date(2025, 5, 1),
                 statuses=[("AP", date(2025, 5, 1)), ("RJ", date(2025, 5, 15))])

    s = summary(conn, doc)
    assert s["P02"][:4] == (True, True, "not_permitted", "RJ")
    assert s["P01"][:4] == (False, True, "construction", "AN")
    assert latest_by_use(conn, doc) == {"not_permitted": "P02", "construction": "P01"}


def test_same_day_revisions_tie_break_on_revision_code(project):
    conn = project
    doc = add_document(conn, "KVL-ADM-410-DR-S-0103")
    add_revision(conn, doc, "C01", date(2025, 4, 1))
    add_revision(conn, doc, "P04", date(2025, 4, 1))
    s = summary(conn, doc)
    assert s["C01"][0] is True and s["P04"][0] is False
    # revisions without any status are never "latest for use"
    assert latest_by_use(conn, doc) == {}


def test_information_link_constraints(project):
    conn = project
    rfi = add_document(conn, "KVL-ADM-410-RI-S-0012", doc_type="RI")
    dwg = add_document(conn, "KVL-ADM-410-DR-S-0104")
    dwg_c01 = add_revision(conn, dwg, "C01", date(2025, 2, 1))

    conn.execute(
        """insert into dcc.information_link (from_document_id, to_document_id, to_revision_id, link_type)
           values (%s, %s, %s, 'affects')""",
        (rfi, dwg, dwg_c01),
    )

    def rejected(sql, params):
        with pytest.raises(psycopg.errors.IntegrityError):
            with conn.transaction():
                conn.execute(sql, params)

    link_sql = """insert into dcc.information_link
                    (from_document_id, from_revision_id, to_document_id, to_revision_id, link_type)
                  values (%s, %s, %s, %s, %s)"""
    rejected(link_sql, (rfi, None, dwg, dwg_c01, "affects"))       # duplicate (nulls not distinct)
    rejected(link_sql, (rfi, dwg_c01, dwg, None, "related_to"))    # revision belongs to another document
    rejected(link_sql, (dwg, None, dwg, None, "related_to"))       # self-link
    rejected(link_sql, (rfi, None, dwg, None, "mentions"))         # unknown link type


def test_revision_file_has_one_primary(project):
    conn = project
    doc = add_document(conn, "KVL-ADM-410-DR-S-0105")
    rev = add_revision(conn, doc, "C01", date(2025, 2, 1))
    file_sql = """insert into dcc.revision_file
                    (revision_id, copy_role, filename, original_location, storage_path, file_format, size_bytes, sha256)
                  values (%s, %s, 'f.pdf', 'KVL Project/02 Design', %s, 'pdf', 1, %s)"""
    sha = "0" * 64
    conn.execute(file_sql, (rev, "primary", "a/f.pdf", sha))
    conn.execute(file_sql, (rev, "copy", "b/f.pdf", sha))
    with pytest.raises(psycopg.errors.UniqueViolation):
        with conn.transaction():
            conn.execute(file_sql, (rev, "primary", "c/f.pdf", sha))


def test_health_reports_database_ok(conn):
    response = TestClient(app).get("/api/health")
    assert response.json()["database"] == "ok"
