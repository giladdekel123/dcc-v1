"""Extract located text segments and self-declared fields from corpus files. No database access.

Extracted content is evidence about what a file says. It never overwrites registered metadata.
"""

from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path

from app.extraction.docx import extract_docx
from app.extraction.fields import find_fields
from app.extraction.pdf import extract_pdf
from app.extraction.segment import Segment
from app.extraction.xlsx import extract_xlsx

EXTRACTOR_VERSION = (
    f"dcc-extract-1 (pypdf {version('pypdf')}, python-docx {version('python-docx')}, "
    f"openpyxl {version('openpyxl')})"
)
EXTRACTORS = {"pdf": extract_pdf, "docx": extract_docx, "xlsx": extract_xlsx}


@dataclass
class Extracted:
    outcome: str                     # ok | empty | failed
    segments: list[Segment] = field(default_factory=list)
    fields: dict = field(default_factory=dict)
    unit_count: int | None = None    # pages (PDF) or sheets (XLSX)
    error: str | None = None


def extract(path: Path, file_format: str) -> Extracted:
    try:
        segments, unit_count = EXTRACTORS[file_format](path)
    except Exception as e:  # one unreadable file must not stop the run; record why
        return Extracted("failed", error=f"{type(e).__name__}: {e}")
    segments = [s for s in segments if s.body.strip()]
    if not segments:
        return Extracted("empty", unit_count=unit_count)
    return Extracted("ok", segments, find_fields(segments), unit_count)
