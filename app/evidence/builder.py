"""Turn a retriever's RawMatch plus registered facts into a ResultItem with structured evidence.

Engine-independent: any retriever returning RawMatch gets the same evidence and the same UI.
Evidence states facts; it never declares a document correct and carries no confidence score.
"""

import re
from datetime import date

from app.evidence.facts import RevisionFacts
from app.models import CodeLabel, DocumentInfo, EvidenceItem, Location, ResultItem, RevisionInfo
from app.retrieval.base import HL_END, HL_START, Filters, RawMatch
from dcc_corpus import naming


def parse_highlights(marked: str) -> tuple[str, list[tuple[int, int]]]:
    """Collapse whitespace and turn highlight markers into (start, end) character spans."""
    text = re.sub(r"\s+", " ", marked).strip()
    out: list[str] = []
    spans: list[tuple[int, int]] = []
    start = None
    for ch in text:
        if ch == HL_START:
            start = len(out)
        elif ch == HL_END:
            if start is not None and len(out) > start:
                spans.append((start, len(out)))
            start = None
        else:
            out.append(ch)
    return "".join(out), spans


def label(pair: tuple[str, str] | None) -> CodeLabel | None:
    return CodeLabel(code=pair[0], label=pair[1]) if pair else None


def fmt(d: date) -> str:
    return f"{d.day} {d.strftime('%b %Y')}"


def revision_note(f: RevisionFacts) -> str:
    latest_rev, latest_date, latest_status = f.latest
    if f.is_latest:
        text = f"Best match is the latest revision, {f.rev_code} ({fmt(f.revision_date)})"
        text += f", of {f.revision_count} revisions." if f.revision_count > 1 else "; it is the only revision."
    else:
        status = f", {latest_status[1]}" if latest_status else ""
        text = (f"Best match: {f.rev_code} ({fmt(f.revision_date)}). "
                f"A later revision exists: {latest_rev} ({fmt(latest_date)}{status}).")
    construction = f.latest_by_use.get("construction")
    if construction and f.revision_count > 1:
        text += f" Latest for construction: {construction}."
    return text


def status_note(f: RevisionFacts) -> str | None:
    events = f.status_history
    if not events:
        return None
    if len(events) == 1:
        e = events[0]
        return f"Status {e.code} ({e.label}) since {fmt(e.effective_date)}."
    first, *middle, last = events
    parts = [f"Issued as {first.code} ({first.label}) on {fmt(first.effective_date)}"]
    parts += [f"then {e.code} ({e.label}) on {fmt(e.effective_date)}" for e in middle]
    now = f"now {last.code} ({last.label}) since {fmt(last.effective_date)}"
    parts.append(now + (f", by {last.assigned_by}" if last.assigned_by else ""))
    return "; ".join(parts) + "."


def filter_evidence(f: RevisionFacts, filters: Filters) -> list[EvidenceItem]:
    values = {
        "discipline": f.discipline, "doc_type": f.doc_type, "stage": f.stage, "wbs": f.wbs,
        "org": f.originator if filters.org == f.originator[0] else f.sender,
    }
    items = []
    for key, value in filters.active().items():
        if key in values and values[key]:
            text = f"Matches filter {key.replace('_', ' ')}: {values[key][1]}"
        elif key in ("date_from", "date_to"):
            text = f"Issued {fmt(f.revision_date)}, within the date filter"
        else:
            continue
        items.append(EvidenceItem(kind="metadata_match", source="registered", field=key, text=text))
    return items


def build_result(rank: int, match: RawMatch, f: RevisionFacts, filters: Filters, debug: bool) -> ResultItem:
    evidence: list[EvidenceItem] = []
    for hit in match.field_hits:
        text, spans = parse_highlights(hit.text)
        if hit.via:
            text = f"{text} (matched {hit.via})"
        evidence.append(EvidenceItem(kind="metadata_match", source="registered", field=hit.field,
                                     text=text, highlights=spans))
    evidence += filter_evidence(f, filters)
    for snippet in match.snippets:
        text, spans = parse_highlights(snippet.text)
        evidence.append(EvidenceItem(kind="content_snippet", source="extracted", locator=snippet.locator,
                                     text=text, highlights=spans))
    evidence.append(EvidenceItem(kind="revision_note", source="derived", text=revision_note(f)))
    if note := status_note(f):
        evidence.append(EvidenceItem(kind="status_note", source="registered", text=note))

    return ResultItem(
        rank=rank,
        document=DocumentInfo(id=f.document_id, doc_code=f.doc_code, title=f.title, doc_type=label(f.doc_type),
                              discipline=label(f.discipline), wbs=label(f.wbs), originator=label(f.originator)),
        revision=RevisionInfo(
            id=f.revision_id, rev_code=f.rev_code, revision_date=f.revision_date, stage=label(f.stage),
            current_status=label(f.current_status), permitted_use=label(f.permitted_use), sender=label(f.sender),
            is_latest=f.is_latest, latest_rev_code=f.latest[0], latest_by_use=f.latest_by_use,
            revision_count=f.revision_count),
        location=Location(
            original_location=naming.display_path(f.original_location), filename=f.filename,
            open_url=f"/api/revisions/{f.revision_id}/file",
            other_locations=[naming.display_path(*path.rsplit("/", 1)) for path in f.copies]),
        evidence=evidence,
        debug=match.scores if debug else None,
    )
