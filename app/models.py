"""Stable API response schema. Retrieval engines may change; this shape should not."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, model_serializer

EvidenceKind = Literal["metadata_match", "content_snippet", "revision_note", "status_note",
                       "discrepancy", "related_document"]
EvidenceSource = Literal["registered", "extracted", "derived"]


class CodeLabel(BaseModel):
    code: str
    label: str


class DocumentInfo(BaseModel):
    id: int
    doc_code: str
    title: str
    doc_type: CodeLabel
    discipline: CodeLabel
    wbs: CodeLabel
    originator: CodeLabel


class RevisionInfo(BaseModel):
    id: int
    rev_code: str
    revision_date: date
    stage: CodeLabel
    current_status: CodeLabel | None
    permitted_use: CodeLabel | None
    sender: CodeLabel | None
    is_latest: bool
    latest_rev_code: str
    latest_by_use: dict[str, str]      # permitted use code -> revision code
    revision_count: int


class Location(BaseModel):
    original_location: str            # folder, as shown on the project share
    filename: str
    open_url: str
    other_locations: list[str]        # full paths of copies


class EvidenceItem(BaseModel):
    kind: EvidenceKind
    source: EvidenceSource
    field: str | None = None
    locator: str | None = None
    link_type: str | None = None
    text: str
    highlights: list[tuple[int, int]] = []


class ResultItem(BaseModel):
    rank: int
    document: DocumentInfo
    revision: RevisionInfo
    location: Location
    evidence: list[EvidenceItem]
    debug: dict[str, float] | None = None   # only with ?debug=true; never a user-facing confidence

    @model_serializer(mode="wrap")
    def _omit_debug(self, handler) -> dict[str, Any]:
        data = handler(self)
        if self.debug is None:
            data.pop("debug", None)
        return data


class SearchResponse(BaseModel):
    query: str
    filters: dict[str, str]
    engine: str
    results: list[ResultItem]
