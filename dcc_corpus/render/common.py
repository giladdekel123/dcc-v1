"""Helpers shared by the renderers: reproducible output and project context."""

import io
import random
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import reportlab.rl_config

from dcc_corpus import naming

# Fixed PDF creation date and document ID, so identical input gives identical bytes.
reportlab.rl_config.invariant = 1

_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
_CORE_DATES = re.compile(rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:(?:created|modified)>)")


@dataclass
class RenderContext:
    """Everything a renderer needs for one file."""
    project: dict
    doc: dict                 # timeline document entry + doc_code
    rev: str
    issued: date
    status: str               # registered status at issue
    stage: str
    description: str
    content: dict
    history: list = field(default_factory=list)   # [(rev, date, description)] up to and including this one
    seed: int = 0

    @property
    def code(self) -> naming.DocCode:
        return naming.parse_doc_code(self.doc["doc_code"])

    def org_name(self, code: str) -> str:
        return next(o["name"] for o in self.project["organisations"] if o["code"] == code)

    def person(self, name: str) -> dict:
        return next(p for p in self.project["people"] if p["name"] == name)

    def person_line(self, name: str) -> str:
        p = self.person(name)
        return f"{name}, {p['title']}, {self.org_name(p['org'])}"

    def status_text(self, code: str | None = None) -> str:
        code = code or self.status
        return f"{code} - {naming.STATUSES[code][0]}"


def fmt_date(d: date) -> str:
    return d.strftime("%d %B %Y").lstrip("0")


def fixed_datetime(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 9, 0, 0)


def pile_layout(seed: int, piles: int) -> list[dict]:
    """Pile positions and ground levels. Seeded per structure, so every revision agrees."""
    rng = random.Random(f"{seed}:east-abutment-piles")
    per_row = (piles + 1) // 2
    layout = []
    for i in range(piles):
        row, col = divmod(i, per_row)
        layout.append({
            "ref": f"E{i + 1}",
            "x": col * 2.7,
            "y": row * 2.7,
            "easting": round(452310.0 + col * 2.7 + rng.uniform(-0.01, 0.01), 3),
            "northing": round(318420.0 + row * 2.7 + rng.uniform(-0.01, 0.01), 3),
            "ground_level": round(14.1 + rng.uniform(0.0, 0.3), 2),
        })
    return layout


def normalise_ooxml(path: Path, when: date) -> None:
    """Rewrite a DOCX/XLSX zip with fixed entry timestamps, fixed order and fixed core dates."""
    stamp = fixed_datetime(when).strftime("%Y-%m-%dT%H:%M:%SZ").encode()
    with zipfile.ZipFile(path) as src:
        entries = [(info.filename, src.read(info)) for info in src.infolist()]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for name, data in entries:
            if name == "docProps/core.xml":
                data = _CORE_DATES.sub(rb"\g<1>" + stamp + rb"\g<2>", data)
            info = zipfile.ZipInfo(name, date_time=_ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            dst.writestr(info, data)
    path.write_bytes(buf.getvalue())
