"""What every retrieval engine returns. Evidence is built from this, so engines are swappable."""

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

import psycopg

# Highlight markers inside matched text; the evidence builder turns them into character spans.
HL_START, HL_END = "\x02", "\x03"


@dataclass(frozen=True)
class Filters:
    discipline: str | None = None
    doc_type: str | None = None
    stage: str | None = None
    org: str | None = None           # originator or sender
    wbs: str | None = None           # includes child WBS elements
    date_from: date | None = None
    date_to: date | None = None

    def active(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class FieldHit:
    field: str                       # e.g. "title", "doc_type"
    text: str                        # value with highlight markers
    via: str | None = None           # "alias 'RFI'", "similar spelling"


@dataclass
class Snippet:
    locator: str
    text: str                        # passage with highlight markers


@dataclass
class RawMatch:
    revision_id: int
    document_id: int
    field_hits: list[FieldHit] = field(default_factory=list)
    snippets: list[Snippet] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)   # debug only; never shown as confidence


class Retriever(Protocol):
    name: str

    def search(self, conn: psycopg.Connection, query: str, filters: Filters, limit: int) -> list[RawMatch]: ...
