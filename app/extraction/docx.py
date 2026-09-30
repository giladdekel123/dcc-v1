from pathlib import Path

from docx import Document
from docx.table import Table

from app.extraction.segment import Segment


def extract_docx(path: Path) -> tuple[list[Segment], None]:
    """Paragraphs grouped under their heading; one segment per table row."""
    segments: list[Segment] = []
    section, lines = "opening", []
    table_number = 0

    def flush():
        if lines:
            segments.append(Segment(section, "\n".join(lines)))

    for block in Document(path).iter_inner_content():
        if isinstance(block, Table):
            flush()
            lines = []
            table_number += 1
            for row_number, row in enumerate(block.rows, 1):
                cells = []
                for cell in row.cells:
                    text = cell.text.strip()
                    if text and (not cells or cells[-1] != text):  # merged cells repeat their text
                        cells.append(text)
                segments.append(Segment(f"table {table_number}, row {row_number}", " | ".join(cells)))
            section = f"after table {table_number}"
            continue
        text = block.text.strip()
        if not text:
            continue
        if block.style.name.startswith(("Heading", "Title")):
            flush()
            section, lines = f'section "{text}"', [text]
        else:
            lines.append(text)
    flush()
    return segments, None
