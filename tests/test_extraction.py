"""Extraction from real corpus files. No database."""

from pathlib import Path

from app.extraction import extract

KVL = Path(__file__).resolve().parent.parent / "corpus" / "KVL Project"
DRAWINGS = KVL / "02 Design/410 River Kest Bridge/Drawings"


def text(result):
    return "\n".join(s.body for s in result.segments)


def test_drawing_title_block_fields_include_planted_status():
    result = extract(DRAWINGS / "KVL-ADM-410-DR-S-0102_P03 - River Kest Bridge East Abutment General Arrangement.pdf", "pdf")
    assert result.outcome == "ok" and result.unit_count == 1
    assert {k: result.fields[k] for k in ("doc_code", "rev_code", "status_code", "date")} == {
        "doc_code": "KVL-ADM-410-DR-S-0102", "rev_code": "P03", "status_code": "FC", "date": "2025-10-02"}
    assert result.fields["found_in"]["status_code"] == "page 1"
    assert "weep holes" in text(result)


def test_prose_mentioning_a_revision_is_not_a_declared_field():
    # The P03 notes say "Revision C02 remains the construction issue"; the title block says P03.
    result = extract(DRAWINGS / "KVL-ADM-410-DR-S-0102_P03 - River Kest Bridge East Abutment General Arrangement.pdf", "pdf")
    assert "Revision C02 remains" in text(result)
    assert result.fields["rev_code"] == "P03"


def test_report_appendix_is_located_by_page():
    result = extract(KVL / "02 Design/410 River Kest Bridge/Reports/"
                           "KVL-SGI-410-RP-T-0001_P01 - River Kest Bridge Ground Investigation Report.pdf", "pdf")
    appendix = [s for s in result.segments if "Appendix C - BH-E3" in s.body]
    assert appendix and appendix[0].locator.startswith("page ")
    assert "-9.8 mAOD" in appendix[0].body


def test_minutes_item_is_its_own_table_row():
    result = extract(KVL / "01 Management/Meetings/2025/KVL-CGC-100-MM-G-0007_P01 - Progress Meeting No. 7 Minutes.docx", "docx")
    rows = [s for s in result.segments if s.body.startswith("7.3 |")]
    assert len(rows) == 1
    assert rows[0].locator.startswith("table ") and "soft grey clay" in rows[0].body
    assert result.fields["doc_code"] == "KVL-CGC-100-MM-G-0007"


def test_legacy_named_letter_declares_its_code():
    result = extract(KVL / "01 Management/Correspondence/Incoming/ADM/Response to RFI 12 - piles.docx", "docx")
    assert result.fields["doc_code"] == "KVL-ADM-410-LT-S-0031"
    assert result.fields["date"] == "2025-06-30"
    assert "rev_code" not in result.fields  # letters carry no revision
    assert "24.0 m" in text(result)


def test_pile_schedule_sheet():
    result = extract(KVL / "02 Design/410 River Kest Bridge/Schedules/"
                           "KVL-ADM-410-SC-S-0003_C02 - River Kest Bridge East Abutment Pile Schedule.xlsx", "xlsx")
    assert result.unit_count == 2
    assert result.fields["rev_code"] == "C02"
    schedule = next(s for s in result.segments if s.locator.startswith('sheet "Pile Schedule"'))
    assert "-11.15" in schedule.body


def test_corrupt_file_fails_without_raising(tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 this is not really a pdf")
    result = extract(broken, "pdf")
    assert result.outcome == "failed" and result.error and result.segments == []
