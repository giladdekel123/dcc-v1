from pathlib import Path

from pypdf import PdfReader

from app.extraction.segment import Segment


def extract_pdf(path: Path) -> tuple[list[Segment], int]:
    """One segment per page."""
    reader = PdfReader(path)
    segments = []
    for number, page in enumerate(reader.pages, 1):
        lines = [line.strip() for line in (page.extract_text() or "").splitlines()]
        segments.append(Segment(f"page {number}", "\n".join(line for line in lines if line)))
    return segments, len(reader.pages)
