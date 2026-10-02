"""Deterministic synthetic register records for the scalability benchmark. No files are created.

Records are generated one document at a time from a per-index random stream, so document i is
identical at every scale: the 10,000-document set contains the 1,000-document set, and so on.
They are written straight into the database by the benchmark harness (bulk COPY), alongside the
real 100-document KVL corpus, which is loaded the normal way.

Synthetic documents belong to fictional sister projects of about 1,600 documents each, added
in blocks as the scale grows (1 project at 1,000 documents, about 6 at 10,000, 40 at 64,000), the
way an organisation's register grows. One project cannot hold tens of thousands of documents
under the KVL convention's 4-digit numbers, and large registers span projects anyway. Synthetic
documents use only the top-level WBS elements, whose names are project-neutral.
"""

import hashlib
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from dcc_corpus import naming

# Invented place names and scheme types; 20 x 2 = 40 fictional projects, in a fixed order.
PLACES = ["Brackmoor", "Caldhollow", "Dunstrey", "Elmscar", "Fennick", "Gorsley", "Halsmere", "Invercraig",
          "Jessop Vale", "Kilbarrow", "Larkstone", "Morwenstow Cross", "Nettlebridge", "Orchley", "Pendrake",
          "Quenby", "Rookhaven", "Saltmoor", "Thurlby Fen", "Wendmere"]
SCHEMES = ["Link Road", "Bypass"]
PROJECTS = [(f"{place[:2].upper()}{'L' if scheme == 'Link Road' else 'B'}", f"{place} {scheme}")
            for scheme in SCHEMES for place in PLACES]
DOCS_PER_PROJECT = 1600
PROJECT_MONTHS = 36
LATEST_DATE = date(2026, 6, 30)    # nothing is dated after this
# Fictional organisations added for the sister projects (code, name, role).
EXTRA_ORGANISATIONS = [
    ("WSC", "West Shire Council", "client"), ("HRA", "Harbour Roads Authority", "client"),
    ("FLG", "Fellgate Design", "designer"), ("QLN", "Quillon Consulting", "designer"),
    ("BRB", "Brookbank Civils", "contractor"), ("TGW", "Thornley Groundworks", "contractor"),
]
CLIENTS, DESIGNERS, CONTRACTORS = ["NCC", "WSC", "HRA"], ["ADM", "FLG", "QLN"], ["CGC", "BRB", "TGW"]
CHECKERS, UTILITIES = ["BCS"], ["NVW", "NGE", "OLT"]
TOP_WBS = {"000": "G", "100": "G", "200": "C", "300": "D", "400": "S", "500": "C", "600": "U", "700": "E"}

# Document type mix, roughly as in a live construction register.
TYPE_WEIGHTS = {"DR": 30, "LT": 18, "RP": 14, "RI": 10, "MM": 8, "SB": 8, "SC": 4, "BQ": 4, "CT": 4}
EXT = {"DR": "pdf", "RP": "pdf", "CT": "pdf", "LT": "docx", "RI": "docx", "MM": "docx", "SB": "docx",
       "SC": "xlsx", "BQ": "xlsx"}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]

ELEMENTS = ["abutment", "pier", "wing wall", "retaining wall", "culvert", "headwall", "pond", "outfall",
            "carrier drain", "cutting", "embankment", "junction", "roundabout", "footway", "verge",
            "noise barrier", "gantry", "underpass", "parapet", "bearing"]
MATERIALS = ["capping material", "Type 1 subbase", "reinforcement", "precast units", "waterproofing membrane",
             "ductile iron pipe", "geotextile", "kerbs", "road restraint system", "lighting columns"]
SUBJECTS = ["clash between {service} and {element}", "setting out of {element} {n}",
            "reinforcement details at {element} {n}", "level discrepancy at Ch {ch}",
            "drainage connection at Ch {ch}", "temporary works for {element} {n}",
            "access to {element} {n}", "{material} substitution"]
SERVICES = ["the water main", "an 11 kV cable", "a telecom duct", "a gas main", "a foul sewer"]
SENTENCES = [
    "Work on the {element} at Ch {ch} is {pct} per cent complete and progressing to programme.",
    "Levels at Ch {ch} differ from the drawing by {mm} mm; the designer is asked to confirm the intended level.",
    "The {element} {n} design has been reviewed and the comments from the checker have been closed out.",
    "Traffic management for the {element} works will be in place from {day} for {weeks} weeks.",
    "Delivery of the {material} for the {element} was received on {day} and tested to the specification.",
    "Inspection of the {element} found minor defects, which will be corrected before the next hold point.",
    "The programme shows the {element} works finishing on {day}, {weeks} weeks later than the baseline.",
    "Quantities for the {element} have been re-measured and the {material} rate agreed at {rate} per unit.",
    "{service_cap} was located by trial hole at Ch {ch}, {mm} mm from the position shown on the records.",
    "Minutes of the discussion on the {element} are recorded under item {n} with actions for the designer.",
]


@dataclass
class SyntheticDocument:
    doc_code: str
    title: str
    project: str
    wbs_code: str
    discipline_code: str
    doc_type_code: str
    originator_code: str
    revisions: list[dict] = field(default_factory=list)   # rev_code, revision_date, stage_code, statuses, file, segments
    links: list[dict] = field(default_factory=list)       # to_doc_code, link_type


def _fill(rng: random.Random, template: str, near: date) -> str:
    service = rng.choice(SERVICES)
    return template.format(
        element=rng.choice(ELEMENTS), material=rng.choice(MATERIALS), n=rng.randint(1, 12),
        ch=f"{rng.randint(0, 6)}+{rng.randint(0, 999):03d}", pct=rng.choice([15, 30, 45, 60, 75, 90]),
        mm=rng.choice([35, 60, 120, 250, 450]), weeks=rng.randint(1, 8), rate=f"{rng.uniform(8, 300):.2f}",
        day=(near + timedelta(days=rng.randint(-45, 45))).strftime("%d %B %Y").lstrip("0"),
        service=service, service_cap=service[0].upper() + service[1:])


def _title(rng: random.Random, doc_type: str, number: int, month: date, progress: bool) -> str:
    element, n = rng.choice(ELEMENTS).title(), rng.randint(1, 12)
    match doc_type:
        case "DR":
            view = rng.choice(["General Arrangement", "Reinforcement Details", "Sections", "Setting Out",
                               "Elevation", f"Layout Sheet {rng.randint(1, 3)} of 3"])
            return f"{element} {n} {view}"
        case "RP":
            if progress:
                return f"Monthly Progress Report - {MONTHS[month.month - 1]} {month.year}"
            return f"{element} {rng.choice(['Design Report', 'Inspection Report', 'Test Report', 'Survey Report'])}"
        case "RI":
            subject = _fill(rng, rng.choice(SUBJECTS), month)
            return f"RFI-{number:04d} {subject[0].upper()}{subject[1:]}"
        case "LT":
            return f"{element} {n} - {rng.choice(['Response to Query', 'Notice of Delay', 'Request for Access', 'Proposal', 'Acceptance'])}"
        case "MM":
            return f"Progress Meeting No. {number} Minutes"
        case "SB":
            return f"{rng.choice(MATERIALS).title()} - {rng.choice(['Source Approval', 'Product Data', 'Method Statement'])}"
        case "SC":
            return rng.choice(["Construction Programme", f"{element} Schedule", "Drawing Register"])
        case "BQ":
            return f"Variation {number:02d} - {element} {rng.choice(['Additional Works', 'Remeasurement', 'Omission'])}"
        case _:  # CT
            return f"{element} {n} Check Certificate"


def _originator(rng: random.Random, doc_type: str, client: str, designer: str, contractor: str) -> str:
    """Each project has one client, designer and contractor; checkers and utilities are shared."""
    pools = {"DR": [designer], "RI": [contractor], "MM": [contractor], "SB": [contractor], "SC": [contractor],
             "CT": CHECKERS, "BQ": [contractor, designer], "RP": [designer, contractor],
             "LT": [client, designer, contractor, *UTILITIES]}
    return rng.choice(pools[doc_type])


def _statuses(rng: random.Random, doc_type: str, rev: str, issued: date) -> list[tuple[str, date]]:
    later = issued + timedelta(days=rng.randint(5, 30))
    match doc_type:
        case "DR":
            return [("FC" if rev.startswith("C") else "RV", issued)]
        case "RI":
            return [("OP", issued)] + ([("CL", later)] if rng.random() < 0.8 else [])
        case "SB":
            return [("AP", issued), (rng.choice(["AN", "AC", "AC", "RJ"]), later)]
        case "BQ":
            return [("AP", issued), ("AC", later)] if rng.random() < 0.7 else [("FI", issued)]
        case "RP":
            return [("AP", issued), ("AC", later)] if rng.random() < 0.2 else [("FI", issued)]
        case "SC":
            return [("FI", issued)]
        case _:  # LT, MM, CT
            return [("IS", issued)]


def _stage(day: date, start: date) -> str:
    months = (day.year - start.year) * 12 + day.month - start.month
    return "PD" if months < 6 else "DD" if months < 15 else "CN"


def _add_months(day: date, months: int) -> date:
    total = day.month - 1 + months
    return date(day.year + total // 12, total % 12 + 1, min(day.day, 28))


def _revision_count(rng: random.Random, doc_type: str, progress: bool) -> int:
    """Drawings are revised most; letters, RFIs, minutes, certificates and progress reports never."""
    if doc_type == "DR":
        return rng.choices([1, 2, 3], weights=[35, 45, 20])[0]
    if doc_type in ("RP", "SC", "SB", "BQ") and not progress:
        return rng.choices([1, 2], weights=[75, 25])[0]
    return 1


def generate(count: int, seed: int = 1905) -> list[SyntheticDocument]:
    """The first `count` synthetic documents. Prefix-stable: generate(n)[:m] == generate(m) for m <= n."""
    numbers: dict[tuple, int] = {}
    recent: dict[tuple, list[tuple[str, date]]] = {}   # (project, doc_type) -> (doc code, first issue date)
    documents = []
    for i in range(count):
        rng = random.Random(f"{seed}:{i}")
        project_index = i // DOCS_PER_PROJECT
        project, project_name = PROJECTS[project_index % len(PROJECTS)]
        start = _add_months(date(2016, 1, 1), 2 * project_index)   # the 40th project starts mid-2022
        client, designer, contractor = (pool[project_index % 3] for pool in (CLIENTS, DESIGNERS, CONTRACTORS))
        doc_type = rng.choices(list(TYPE_WEIGHTS), weights=list(TYPE_WEIGHTS.values()))[0]
        progress = doc_type == "RP" and rng.random() < 0.15
        originator = contractor if progress else _originator(rng, doc_type, client, designer, contractor)
        wbs = "100" if doc_type in ("MM", "SC") or progress else rng.choice(list(TOP_WBS))
        discipline = "Q" if doc_type == "BQ" else TOP_WBS[wbs]
        key = (project, originator, doc_type)
        numbers[key] = numbers.get(key, 0) + 1
        doc_code = f"{project}-{originator}-{wbs}-{doc_type}-{discipline}-{numbers[key]:04d}"
        if doc_type == "MM":        # weekly meetings, numbered in date order
            issued = start + timedelta(days=7 * (numbers[key] - 1))
        elif progress:              # one report per month, issued early the following month
            sequence = numbers[(project, "progress")] = numbers.get((project, "progress"), 0) + 1
            issued = _add_months(start, sequence) + timedelta(days=rng.randint(2, 6))
        else:
            issued = start + timedelta(days=rng.randint(0, 30 * PROJECT_MONTHS))
        issued = min(issued, LATEST_DATE)
        first_issued = issued
        report_month = _add_months(issued, -1)
        title = _title(rng, doc_type, numbers[key], report_month, progress)
        doc = SyntheticDocument(doc_code, title, project, wbs, discipline, doc_type, originator)

        revision_count = _revision_count(rng, doc_type, progress)
        for r in range(revision_count):
            if r and issued > LATEST_DATE:
                break
            if doc_type == "DR":
                rev = f"P{r + 1:02d}" if r == 0 and revision_count > 1 else f"C{r:02d}" if revision_count > 1 else "C01"
            else:
                rev = f"P{r + 1:02d}"
            segments = [" ".join(_fill(rng, rng.choice(SENTENCES), issued) for _ in range(3))
                        for _ in range(rng.randint(2, 4))]
            filename = naming.build_filename(doc_code, rev, title, EXT[doc_type])
            body = "\n".join(segments).encode()
            doc.revisions.append({
                "rev_code": rev, "revision_date": issued, "stage_code": _stage(issued, start),
                "statuses": _statuses(rng, doc_type, rev, issued),
                "file": {"filename": filename, "location": f"SYNTH/{project}/{doc_type}",
                         "storage_path": f"SYNTH/{project}/{doc_type}/{filename}", "format": EXT[doc_type],
                         "size_bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()},
                "segments": segments,
            })
            issued += timedelta(days=rng.randint(20, 120))

        def earlier(doc_types, window):
            """Documents of these types in this project, issued before this one, most recent last."""
            found = [code for t in doc_types for code, when in recent.get((project, t), [])[-window:]
                     if when < first_issued]
            return found

        if doc_type == "LT" and rng.random() < 0.4 and (rfis := earlier(["RI"], 50)):
            doc.links.append({"to_doc_code": rng.choice(rfis), "link_type": "responds_to"})
        if doc_type == "MM" and (anything := earlier(TYPE_WEIGHTS, 5)):
            doc.links.append({"to_doc_code": rng.choice(anything), "link_type": "related_to"})
        if doc_type == "RP" and not progress and rng.random() < 0.03 and (reports := earlier(["RP"], 20)):
            doc.links.append({"to_doc_code": rng.choice(reports), "link_type": "supersedes"})
        recent.setdefault((project, doc_type), []).append((doc_code, first_issued))
        documents.append(doc)
    return documents
