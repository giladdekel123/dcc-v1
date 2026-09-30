"""Load and validate the corpus spec: project.yaml plus one timeline file per storyline."""

from datetime import date
from pathlib import Path

import yaml

from dcc_corpus import naming

SPEC_DIR = Path(__file__).resolve().parent / "spec"
TIMELINE_DIR = "timeline"

TEMPLATE_FORMATS = {
    "pdf_drawing": "pdf",
    "pdf_report": "pdf",
    "pdf_certificate": "pdf",
    "docx_rfi": "docx",
    "docx_letter": "docx",
    "docx_minutes": "docx",
    "docx_submittal": "docx",
    "xlsx_schedule": "xlsx",
    "xlsx_boq": "xlsx",
    "xlsx_programme": "xlsx",
    "xlsx_table": "xlsx",     # generic schedule: columns and rows
}
# Drawing geometry kinds; a drawing without geometry.kind is a pile layout (Storyline A).
DRAWING_KINDS = {"piles", "culvert", "pond", "layout", "roundabout", "generic"}
LINK_TYPES = {"supersedes", "responds_to", "clarified_by", "generated_from", "affects", "related_to"}
PLANTED_CASES = {
    "correct_not_latest", "titleblock_discrepancy", "legacy_filename", "file_copy",
    "near_duplicate", "status_change_no_revision", "late_finding_in_appendix",
    "superseded_by_new_number",
}
# Content keys that must name a person from project.yaml.
PERSON_KEYS = {"raised_by", "addressed_to", "to", "signed_by", "checker", "designer",
               "submitted_by", "for_review_by", "chair"}
PERSON_LIST_KEYS = {"attendees", "apologies", "cc"}


def load_yaml(name: str, spec_dir: Path = SPEC_DIR) -> dict:
    with open(spec_dir / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_spec(spec_dir: Path = SPEC_DIR) -> tuple[dict, dict]:
    """Project data, and all storyline files merged into one timeline.

    Document keys are global, so links may cross storylines. Each document records its home
    storyline; `also_in` lists other storylines it belongs to. Events are merged in date order
    (stable, so same-day events keep storyline order).
    """
    project = load_yaml("project.yaml", spec_dir)
    timeline = {"storylines": [], "documents": {}, "events": [], "links": [], "planted": [], "duplicates": []}
    for path in sorted((spec_dir / TIMELINE_DIR).glob("*.yaml")):
        story = load_yaml(f"{TIMELINE_DIR}/{path.name}", spec_dir)
        code = story["storyline"]
        timeline["storylines"].append({"code": code, "name": story["name"]})
        for key, doc in story["documents"].items():
            if key in timeline["documents"]:
                timeline["duplicates"].append(key)
            timeline["documents"][key] = {**doc, "storyline": code, "also_in": doc.get("also_in", [])}
        timeline["events"] += [{**event, "storyline": code} for event in story["events"]]
        timeline["links"] += story.get("links", [])
        timeline["planted"] += story.get("planted", [])
    timeline["events"].sort(key=lambda event: event["date"])
    return project, timeline


def split_target(target: str) -> tuple[str, str | None]:
    """'GA@C02' -> ('GA', 'C02'); 'GA' -> ('GA', None)."""
    key, _, rev = target.partition("@")
    return key, rev or None


def validate(project: dict, timeline: dict) -> list[str]:
    """Return a list of problems; empty means the spec is consistent."""
    errors: list[str] = []
    orgs = {o["code"] for o in project["organisations"]}
    wbs = {w["code"] for w in project["wbs"]}
    people = {p["name"] for p in project["people"]}
    documents = timeline["documents"]

    for w in project["wbs"]:
        if w.get("parent") and w["parent"] not in wbs:
            errors.append(f"WBS {w['code']}: unknown parent {w['parent']}")

    storylines = {s["code"] for s in timeline["storylines"]}
    errors += [f"{key}: document key defined in more than one storyline" for key in timeline.get("duplicates", [])]

    doc_types: dict[str, str] = {}
    for key, doc in documents.items():
        for other in doc.get("also_in", []):
            if other not in storylines or other == doc["storyline"]:
                errors.append(f"{key}: also_in {other} is not another known storyline")
        try:
            code = naming.parse_doc_code(doc["doc_code"])
        except ValueError as e:
            errors.append(f"{key}: {e}")
            continue
        doc_types[key] = code.doc_type
        if code.originator not in orgs:
            errors.append(f"{key}: unknown originator {code.originator}")
        if code.wbs not in wbs:
            errors.append(f"{key}: unknown WBS {code.wbs}")
        if doc["owner"] not in people:
            errors.append(f"{key}: unknown owner {doc['owner']}")
        if doc["template"] not in TEMPLATE_FORMATS:
            errors.append(f"{key}: unknown template {doc['template']}")
    if len({d["doc_code"] for d in documents.values()}) != len(documents):
        errors.append("duplicate doc_code in documents")

    issued: dict[tuple[str, str], date] = {}
    status_dates: set[tuple[str, str, date]] = set()
    for event in timeline["events"]:  # already in date order (load_spec sorts them)
        when = event["date"]
        where = f"event {when}"

        for item in event.get("issue", []):
            key, rev = item["doc"], item["rev"]
            if key not in documents:
                errors.append(f"{where}: unknown document {key}")
                continue
            try:
                naming.validate_rev(rev)
            except ValueError as e:
                errors.append(f"{where} {key}: {e}")
            if (key, rev) in issued:
                errors.append(f"{where}: {key}@{rev} issued twice")
            issued[(key, rev)] = when
            status_dates.add((key, rev, when))
            if item["stage"] not in naming.STAGES:
                errors.append(f"{where} {key}@{rev}: unknown stage {item['stage']}")
            if not naming.status_allowed(doc_types.get(key, ""), item["status"]):
                errors.append(f"{where} {key}@{rev}: status {item['status']} not allowed")
            if item.get("filed", "current") not in {"current", "superseded"}:
                errors.append(f"{where} {key}@{rev}: filed must be current or superseded")
            if "filename" in item:
                ext = TEMPLATE_FORMATS.get(documents[key]["template"])
                if not item["filename"].endswith(f".{ext}"):
                    errors.append(f"{where} {key}@{rev}: filename extension must be .{ext}")
            for copy in item.get("copies", []):
                if not copy["location"].startswith(naming.PROJECT_ROOT + "/"):
                    errors.append(f"{where} {key}@{rev}: copy outside project tree")
            content = item.get("content", {})
            if documents[key]["template"] == "pdf_drawing":
                kind = content.get("geometry", {}).get("kind", "piles")
                if kind not in DRAWING_KINDS:
                    errors.append(f"{where} {key}@{rev}: unknown drawing geometry {kind}")
            if "titleblock_doc_code" in content:
                try:
                    naming.parse_doc_code(content["titleblock_doc_code"])
                except ValueError as e:
                    errors.append(f"{where} {key}@{rev}: {e}")
            if "header_rev" in content:
                try:
                    naming.validate_rev(content["header_rev"])
                except ValueError as e:
                    errors.append(f"{where} {key}@{rev}: {e}")
            errors += _check_people(f"{where} {key}@{rev}", content, people)

        for change in event.get("status_change", []):
            key, rev = change["doc"], change["rev"]
            if (key, rev) not in issued:
                errors.append(f"{where}: status change for unissued {key}@{rev}")
                continue
            if not naming.status_allowed(doc_types[key], change["status"]):
                errors.append(f"{where} {key}@{rev}: status {change['status']} not allowed")
            if change["by"] not in orgs:
                errors.append(f"{where} {key}@{rev}: unknown organisation {change['by']}")
            if (key, rev, when) in status_dates:
                errors.append(f"{where} {key}@{rev}: two statuses on one day")
            status_dates.add((key, rev, when))

    issued_keys = {k for k, _ in issued}
    for key in documents:
        if key not in issued_keys:
            errors.append(f"{key}: never issued")

    def resolves(target: str) -> bool:
        key, rev = split_target(target)
        return key in documents and (rev is None or (key, rev) in issued)

    for link in timeline.get("links", []):
        label = f"link {link['from']} -> {link['to']}"
        if link["type"] not in LINK_TYPES:
            errors.append(f"{label}: unknown type {link['type']}")
        if not resolves(link["from"]) or not resolves(link["to"]):
            errors.append(f"{label}: unresolved target")
        elif split_target(link["from"])[0] == split_target(link["to"])[0]:
            errors.append(f"{label}: self-link")

    for case in timeline.get("planted", []):
        if case["case"] not in PLANTED_CASES:
            errors.append(f"planted {case['case']}: unknown case")
        if not resolves(case["target"]):
            errors.append(f"planted {case['case']}: unresolved target {case['target']}")

    return errors


def _check_people(where: str, content: dict, people: set[str]) -> list[str]:
    errors = []
    for k, v in content.items():
        if k in PERSON_KEYS and v not in people:
            errors.append(f"{where}: unknown person {v!r} in {k}")
        if k in PERSON_LIST_KEYS:
            errors += [f"{where}: unknown person {p!r} in {k}" for p in v if p not in people]
    for item in content.get("items", []):
        if "owner" in item and item["owner"] not in people:
            errors.append(f"{where}: unknown action owner {item['owner']!r}")
    return errors
