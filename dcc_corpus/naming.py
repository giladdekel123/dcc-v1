"""KVL project document coding convention.

This is our own simplified project convention, inspired by ISO 19650 concepts (originator,
volume/system, type, role, number, status, revision). It is not the ISO 19650 naming
convention and implies no compliance. This module is the only code home of the convention.

Code sets here must match the vocabularies seeded in supabase/migrations (checked by a DB test).
Project-specific values (WBS elements, organisations) live in dcc_corpus/spec/project.yaml.
"""

import re
from dataclasses import dataclass
from datetime import date

PROJECT = "KVL"

DISCIPLINES = {
    "G": "General / project management",
    "C": "Highways and civil",
    "D": "Drainage",
    "S": "Structures",
    "T": "Geotechnical",
    "U": "Utilities",
    "E": "Environmental",
    "Q": "Commercial / quantity surveying",
}

DOC_TYPES = {
    "DR": "Drawing",
    "RP": "Report",
    "RI": "Request for information",
    "LT": "Letter",
    "MM": "Meeting minutes",
    "SB": "Submittal",
    "BQ": "Bill of quantities",
    "CT": "Certificate / assurance",
    "SC": "Schedule / register",
}

# Lifecycle order matters: PD < DD < CN < HO.
STAGES = {
    "PD": "Preliminary design",
    "DD": "Detailed design",
    "CN": "Construction",
    "HO": "Handover",
}

PERMITTED_USES = ("information", "review", "approval", "construction", "as_built", "not_permitted")

# status code -> (label, permitted use)
STATUSES = {
    "FI": ("For information", "information"),
    "RV": ("For review and comment", "review"),
    "AP": ("For approval", "approval"),
    "AC": ("Accepted / approved", "construction"),
    "AN": ("Approved with comments", "construction"),
    "RJ": ("Rejected", "not_permitted"),
    "FC": ("For construction", "construction"),
    "AB": ("As-built", "as_built"),
    "OP": ("Open", "information"),
    "CL": ("Closed", "information"),
    "IS": ("Issued", "information"),
}

# Which statuses a document type may carry. Enforced by the generator/loader, not the database.
STATUS_APPLICABILITY = {
    "DR": {"FI", "RV", "AP", "FC", "AB"},
    "RP": {"FI", "RV", "AP", "AC", "AN", "RJ"},
    "RI": {"OP", "CL"},
    "LT": {"IS"},
    "MM": {"IS"},
    "SB": {"AP", "AC", "AN", "RJ"},
    "BQ": {"FI", "RV", "AP", "AC"},
    "CT": {"IS"},
    "SC": {"FI", "RV", "FC", "AB"},
}

_DOC_CODE_RE = re.compile(
    r"^(?P<project>[A-Z]{3})-(?P<originator>[A-Z]{3})-(?P<wbs>\d{3})-"
    r"(?P<doc_type>[A-Z]{2})-(?P<discipline>[A-Z])-(?P<number>\d{4})$"
)
_REV_RE = re.compile(r"^(?P<series>[PCA])(?P<number>\d{2})$")
_FILENAME_RE = re.compile(
    r"^(?P<doc_code>[A-Z]{3}-[A-Z]{3}-\d{3}-[A-Z]{2}-[A-Z]-\d{4})_(?P<rev>[PCA]\d{2}) - "
    r"(?P<title>.+)\.(?P<ext>pdf|docx|xlsx)$"
)
_WINDOWS_UNSAFE = re.compile(r'[<>:"/\\|?*]')


@dataclass(frozen=True)
class DocCode:
    originator: str
    wbs: str
    doc_type: str
    discipline: str
    number: int
    project: str = PROJECT

    def __post_init__(self):
        if self.project != PROJECT:
            raise ValueError(f"unknown project {self.project!r}")
        if not re.fullmatch(r"[A-Z]{3}", self.originator):
            raise ValueError(f"originator must be 3 capital letters: {self.originator!r}")
        if not re.fullmatch(r"\d{3}", self.wbs):
            raise ValueError(f"WBS must be 3 digits: {self.wbs!r}")
        if self.doc_type not in DOC_TYPES:
            raise ValueError(f"unknown document type {self.doc_type!r}")
        if self.discipline not in DISCIPLINES:
            raise ValueError(f"unknown discipline {self.discipline!r}")
        if not 1 <= self.number <= 9999:
            raise ValueError(f"number out of range: {self.number}")

    def __str__(self) -> str:
        return (
            f"{self.project}-{self.originator}-{self.wbs}-"
            f"{self.doc_type}-{self.discipline}-{self.number:04d}"
        )


def parse_doc_code(text: str) -> DocCode:
    m = _DOC_CODE_RE.match(text)
    if not m:
        raise ValueError(f"not a KVL document code: {text!r}")
    return DocCode(
        project=m["project"],
        originator=m["originator"],
        wbs=m["wbs"],
        doc_type=m["doc_type"],
        discipline=m["discipline"],
        number=int(m["number"]),
    )


def validate_rev(rev: str) -> str:
    m = _REV_RE.match(rev)
    if not m or m["number"] == "00":
        raise ValueError(f"not a KVL revision code: {rev!r}")
    return rev


def rev_rank(rev: str) -> int:
    """P < C < A, then numeric. Mirrors dcc.rev_code_rank; used only to break same-day ties."""
    validate_rev(rev)
    return "PCA".index(rev[0]) * 1000 + 1000 + int(rev[1:])


def safe_title(title: str) -> str:
    return re.sub(r"\s+", " ", _WINDOWS_UNSAFE.sub("-", title)).strip()


def build_filename(doc_code: DocCode | str, rev: str, title: str, ext: str) -> str:
    validate_rev(rev)
    return f"{doc_code}_{rev} - {safe_title(title)}.{ext}"


@dataclass(frozen=True)
class ParsedFilename:
    doc_code: DocCode
    rev: str
    title: str
    ext: str


def parse_filename(filename: str) -> ParsedFilename | None:
    """Parse a convention filename. Returns None for legacy names that do not follow it."""
    m = _FILENAME_RE.match(filename)
    if not m:
        return None
    try:
        return ParsedFilename(parse_doc_code(m["doc_code"]), validate_rev(m["rev"]), m["title"], m["ext"])
    except ValueError:
        return None


def status_allowed(doc_type: str, status: str) -> bool:
    return status in STATUS_APPLICABILITY.get(doc_type, set())


# ---------------------------------------------------------------------------
# Simulated project folder tree (original file location, shown as provenance)
# ---------------------------------------------------------------------------

PROJECT_ROOT = "KVL Project"
DISPLAY_ROOT = r"\\kvl-fs01\Projects"
SHARE_OWNER = "NCC"  # the project share is the client's; others' correspondence is "Incoming"
SUPERSEDED = "99 Superseded"
MANAGEMENT_WBS = "100"  # project-management schedules (programmes) and reports (progress) sit with management records
PROJECT_WIDE_WBS = "000"  # project-wide reports are management plans (health and safety, quality, environment)


def standard_location(doc_type: str, wbs_folder: str, originator: str, issued: date) -> str:
    """Folder (relative, '/'-separated) where a current file of this kind is filed."""
    match doc_type:
        case "MM":
            parts = ["01 Management", "Meetings", str(issued.year)]
        case "LT" if originator == SHARE_OWNER:
            parts = ["01 Management", "Correspondence", "Outgoing"]
        case "LT":
            parts = ["01 Management", "Correspondence", "Incoming", originator]
        case "DR":
            parts = ["02 Design", wbs_folder, "Drawings"]
        case "RP" if wbs_folder.startswith(f"{MANAGEMENT_WBS} "):
            parts = ["01 Management", "Progress Reports"]
        case "RP" if wbs_folder.startswith(f"{PROJECT_WIDE_WBS} "):
            parts = ["01 Management", "Plans"]
        case "RP":
            parts = ["02 Design", wbs_folder, "Reports"]
        case "SC" if wbs_folder.startswith(f"{MANAGEMENT_WBS} "):
            parts = ["01 Management", "Programme"]
        case "SC":
            parts = ["02 Design", wbs_folder, "Schedules"]
        case "RI":
            parts = ["03 Construction", "RFIs"]
        case "SB":
            parts = ["03 Construction", "Submittals", wbs_folder]
        case "BQ":
            parts = ["04 Commercial", "BoQ"]
        case "CT":
            parts = ["05 Assurance", "Certificates"]
        case _:
            raise ValueError(f"no filing rule for document type {doc_type!r}")
    return "/".join([PROJECT_ROOT, *parts])


def superseded_location(location: str) -> str:
    """Mirror of a location under 99 Superseded."""
    prefix = PROJECT_ROOT + "/"
    if not location.startswith(prefix):
        raise ValueError(f"location outside the project tree: {location!r}")
    return f"{PROJECT_ROOT}/{SUPERSEDED}/{location[len(prefix):]}"


def display_path(location: str, filename: str | None = None) -> str:
    """Windows-style path as the user would have seen it on the project share."""
    path = "\\".join([DISPLAY_ROOT, *location.split("/")])
    return f"{path}\\{filename}" if filename else path
