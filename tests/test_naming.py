from datetime import date

import pytest

from dcc_corpus import naming


def test_doc_code_round_trip():
    code = naming.parse_doc_code("KVL-ADM-410-DR-S-0102")
    assert (code.originator, code.wbs, code.doc_type, code.discipline, code.number) == ("ADM", "410", "DR", "S", 102)
    assert str(code) == "KVL-ADM-410-DR-S-0102"


@pytest.mark.parametrize("bad", [
    "KVL-ADM-410-DR-S-102",    # number too short
    "XYZ-ADM-410-DR-S-0102",   # wrong project
    "KVL-ADM-410-XX-S-0102",   # unknown doc type
    "KVL-ADM-410-DR-Z-0102",   # unknown discipline
    "KVL-ADM-41-DR-S-0102",    # WBS too short
    "KVL-ADM-410-DR-S-0000",   # number out of range
])
def test_invalid_doc_codes_rejected(bad):
    with pytest.raises(ValueError):
        naming.parse_doc_code(bad)


def test_revision_ordering_p_before_c_before_a():
    revs = ["A01", "C02", "P03", "C01", "P01"]
    assert sorted(revs, key=naming.rev_rank) == ["P01", "P03", "C01", "C02", "A01"]
    for bad in ["P00", "B01", "C1", "c01"]:
        with pytest.raises(ValueError):
            naming.validate_rev(bad)


def test_filename_round_trip():
    name = naming.build_filename("KVL-ADM-410-DR-S-0102", "C02", "East Abutment GA: Rev/Draft", "pdf")
    assert name == "KVL-ADM-410-DR-S-0102_C02 - East Abutment GA- Rev-Draft.pdf"
    parsed = naming.parse_filename(name)
    assert str(parsed.doc_code) == "KVL-ADM-410-DR-S-0102"
    assert (parsed.rev, parsed.ext) == ("C02", "pdf")


@pytest.mark.parametrize("legacy", [
    "Response to RFI 12 - piles.docx",
    "Copy of BoQ rev2 FINAL.xlsx",
    "KVL-ADM-410-DR-S-0102 - no revision.pdf",
])
def test_legacy_filenames_parse_to_none(legacy):
    assert naming.parse_filename(legacy) is None


def test_status_applicability():
    assert naming.status_allowed("RI", "CL")
    assert not naming.status_allowed("RI", "FC")
    assert naming.status_allowed("SB", "RJ")
    assert all(s in naming.STATUSES for allowed in naming.STATUS_APPLICABILITY.values() for s in allowed)


def test_locations():
    issued = date(2025, 7, 10)
    loc = naming.standard_location("DR", "410 River Kest Bridge", "ADM", issued)
    assert loc == "KVL Project/02 Design/410 River Kest Bridge/Drawings"
    assert naming.superseded_location(loc) == "KVL Project/99 Superseded/02 Design/410 River Kest Bridge/Drawings"
    assert naming.standard_location("LT", "", "ADM", issued) == "KVL Project/01 Management/Correspondence/Incoming/ADM"
    assert naming.standard_location("LT", "", "NCC", issued) == "KVL Project/01 Management/Correspondence/Outgoing"
    assert naming.standard_location("MM", "", "CGC", issued) == "KVL Project/01 Management/Meetings/2025"
    assert naming.standard_location("SC", "100 Project management", "CGC", issued) == "KVL Project/01 Management/Programme"
    assert naming.standard_location("RP", "100 Project management", "CGC", issued) == \
        "KVL Project/01 Management/Progress Reports"
    assert naming.standard_location("RP", "300 Drainage", "ADM", issued) == "KVL Project/02 Design/300 Drainage/Reports"
    assert naming.standard_location("SC", "410 River Kest Bridge", "ADM", issued) == \
        "KVL Project/02 Design/410 River Kest Bridge/Schedules"
    assert naming.display_path(loc, "x.pdf") == r"\\kvl-fs01\Projects\KVL Project\02 Design\410 River Kest Bridge\Drawings\x.pdf"


@pytest.mark.db
def test_code_sets_match_database_seed(conn):
    def table(sql):
        return dict(conn.execute(sql).fetchall())

    assert table("select code, label from dcc.discipline") == naming.DISCIPLINES
    assert table("select code, label from dcc.doc_type") == naming.DOC_TYPES
    assert [r[0] for r in conn.execute("select code from dcc.stage order by seq")] == list(naming.STAGES)
    assert {r[0] for r in conn.execute("select code from dcc.permitted_use")} == set(naming.PERMITTED_USES)
    statuses = {code: (label, use) for code, label, use in
                conn.execute("select code, label, permitted_use_code from dcc.status")}
    assert statuses == naming.STATUSES
