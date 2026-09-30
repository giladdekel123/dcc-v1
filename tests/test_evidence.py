"""Evidence builder unit tests. No database."""

from datetime import date

from app.evidence.builder import build_result, parse_highlights, revision_note, status_note
from app.evidence.facts import RevisionFacts, StatusEvent
from app.retrieval.base import HL_END, HL_START, FieldHit, Filters, RawMatch, Snippet


def facts(**overrides) -> RevisionFacts:
    base = dict(
        revision_id=11, document_id=2, doc_code="KVL-ADM-410-DR-S-0102",
        title="River Kest Bridge East Abutment General Arrangement",
        doc_type=("DR", "Drawing"), discipline=("S", "Structures"), wbs=("410", "River Kest Bridge"),
        originator=("ADM", "Arden Moss Consulting Engineers"), rev_code="C02", revision_date=date(2025, 7, 10),
        stage=("CN", "Construction"), sender=None, current_status=("FC", "For construction"),
        permitted_use=("construction", "Construction / proceed with works"), is_latest=False, revision_count=4,
        latest=("P03", date(2025, 10, 2), ("RV", "For review and comment")),
        latest_by_use={"construction": "C02", "review": "P03"},
        status_history=[StatusEvent("FC", "For construction", date(2025, 7, 10), "ADM")],
        filename="KVL-ADM-410-DR-S-0102_C02 - GA.pdf",
        original_location="KVL Project/02 Design/410 River Kest Bridge/Drawings",
        copies=["KVL Project/01 Management/Correspondence/Email Attachments/2025-07/KVL-ADM-410-DR-S-0102_C02 - GA.pdf"],
    )
    return RevisionFacts(**{**base, **overrides})


def test_highlight_markers_become_spans():
    text, spans = parse_highlights(f"very {HL_START}soft{HL_END} grey\n  {HL_START}clay{HL_END}")
    assert text == "very soft grey clay"
    assert [text[a:b] for a, b in spans] == ["soft", "clay"]


def test_revision_note_when_best_match_is_not_latest():
    note = revision_note(facts())
    assert note == ("Best match: C02 (10 Jul 2025). A later revision exists: P03 (2 Oct 2025, "
                    "For review and comment). Latest for construction: C02.")


def test_revision_note_when_best_match_is_latest_and_only():
    note = revision_note(facts(is_latest=True, revision_count=1, rev_code="P01", latest_by_use={},
                               latest=("P01", date(2025, 7, 10), None)))
    assert note == "Best match is the latest revision, P01 (10 Jul 2025); it is the only revision."


def test_status_note_describes_change_without_new_revision():
    history = [StatusEvent("AP", "For approval", date(2025, 7, 25), "CGC"),
               StatusEvent("AN", "Approved with comments", date(2025, 8, 8), "ADM")]
    assert status_note(facts(status_history=history)) == (
        "Issued as AP (For approval) on 25 Jul 2025; now AN (Approved with comments) since 8 Aug 2025, by ADM.")


def test_build_result_shape():
    match = RawMatch(11, 2,
                     field_hits=[FieldHit("title", f"River Kest Bridge {HL_START}East{HL_END} Abutment"),
                                 FieldHit("doc_type", "Drawing", via="alias 'GA'")],
                     snippets=[Snippet("page 1", f"pile {HL_START}toe{HL_END} level")],
                     scores={"score": 1.5})
    result = build_result(1, match, facts(), Filters(doc_type="DR"), debug=False)
    kinds = [e.kind for e in result.evidence]
    assert kinds == ["metadata_match", "metadata_match", "metadata_match", "content_snippet",
                     "revision_note", "status_note"]
    assert result.evidence[1].text == "Drawing (matched alias 'GA')"
    assert result.evidence[2].text == "Matches filter doc type: Drawing"
    assert result.evidence[3].locator == "page 1" and result.evidence[3].source == "extracted"
    assert result.location.open_url == "/api/revisions/11/file"
    assert result.location.other_locations == [
        r"\\kvl-fs01\Projects\KVL Project\01 Management\Correspondence\Email Attachments\2025-07"
        r"\KVL-ADM-410-DR-S-0102_C02 - GA.pdf"]
    assert "debug" not in result.model_dump()
    assert build_result(1, match, facts(), Filters(), debug=True).model_dump()["debug"] == {"score": 1.5}
