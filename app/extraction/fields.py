"""Find what a file declares about itself: document code, revision, status and date.

A label must be followed by a colon, a line break (PDF tables) or " | " (DOCX/XLSX rows), so prose
such as "Revision C02 remains the construction issue" is not mistaken for a declared field.
The first match in document order wins, and its segment locator is recorded.
"""

import re
from datetime import datetime

from app.extraction.segment import Segment

_SEP = r"[ \t]*[:|\n][ \t]*"
PATTERNS = {
    "doc_code": re.compile(r"\b(?:Drawing number|Document|Our ref)" + _SEP + r"([A-Z]{3}-[A-Z]{3}-\d{3}-[A-Z]{2}-[A-Z]-\d{4})\b"),
    "rev_code": re.compile(r"\bRevision" + _SEP + r"([PCA]\d{2})\b"),
    "status_code": re.compile(r"\bStatus" + _SEP + r"([A-Z]{2}) - "),
    "date": re.compile(r"\bDate" + _SEP + r"(\d{1,2} [A-Z][a-z]+ \d{4})\b"),
}


def find_fields(segments: list[Segment]) -> dict:
    fields: dict = {}
    found_in: dict[str, str] = {}
    for segment in segments:
        for name, pattern in PATTERNS.items():
            if name in fields:
                continue
            m = pattern.search(segment.body)
            if not m:
                continue
            value = m.group(1)
            if name == "date":
                try:
                    value = datetime.strptime(value, "%d %B %Y").date().isoformat()
                except ValueError:
                    continue
            fields[name] = value
            found_in[name] = segment.locator
    if fields:
        fields["found_in"] = found_in
    return fields
