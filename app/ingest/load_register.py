"""Load a corpus register (registered metadata, file provenance, links) into the dcc schema.

    python -m app.ingest.load_register [--corpus corpus] [--dry-run]

Validates everything first, then replaces all project data in one transaction. The seeded
convention vocabularies are left untouched. corpus/ground_truth is never read.
"""

import argparse
import csv
import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import psycopg

from app.config import REPO_ROOT, get_settings
from dcc_corpus import naming

REGISTER_FILES = {
    "wbs": "register/wbs.csv",
    "organisations": "register/organisations.csv",
    "people": "register/people.csv",
    "documents": "register/documents.csv",
    "revisions": "register/revisions.csv",
    "statuses": "register/revision_status.csv",
    "files": "register/revision_files.csv",
    "links": "links.csv",
}
# Every table holding project data. The convention vocabularies are not listed and never touched.
PROJECT_TABLES = [
    "information_link", "content_segment", "extraction", "revision_file", "revision_status",
    "revision", "document", "person", "organisation", "wbs_element",
]


class RegisterError(Exception):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__(f"{len(problems)} problem(s) in the register:\n" + "\n".join(f"- {p}" for p in problems))


@dataclass
class Register:
    wbs: list[dict]
    organisations: list[dict]
    people: list[dict]
    documents: list[dict]
    revisions: list[dict]
    statuses: list[dict]
    files: list[dict]
    links: list[dict]


def read_register(corpus: Path) -> Register:
    missing = [name for name in REGISTER_FILES.values() if not (corpus / name).is_file()]
    if missing:
        raise RegisterError([f"missing register file {name}" for name in missing])
    tables = {}
    for key, name in REGISTER_FILES.items():
        with open(corpus / name, encoding="utf-8", newline="") as f:
            tables[key] = list(csv.DictReader(f))
    return Register(**tables)


def read_vocab(conn: psycopg.Connection) -> dict[str, set[str]]:
    return {table: {r[0] for r in conn.execute(f"select code from dcc.{table}")}
            for table in ("discipline", "doc_type", "stage", "status")}


def validate(reg: Register, corpus: Path, vocab: dict[str, set[str]]) -> list[str]:
    problems: list[str] = []
    wbs = {w["code"] for w in reg.wbs}
    orgs = {o["code"] for o in reg.organisations}
    people = {p["name"] for p in reg.people}

    problems += [f"WBS {w['code']}: unknown parent {w['parent_code']}"
                 for w in reg.wbs if w["parent_code"] and w["parent_code"] not in wbs]
    problems += [f"person {p['name']}: unknown organisation {p['org_code']}" for p in reg.people if p["org_code"] not in orgs]

    doc_types: dict[str, str] = {}
    for d in reg.documents:
        code = d["doc_code"]
        try:
            parsed = naming.parse_doc_code(code)
        except ValueError as e:
            problems.append(f"document {code}: {e}")
            continue
        doc_types[code] = d["doc_type_code"]
        if (parsed.wbs, parsed.discipline, parsed.doc_type, parsed.originator) != (
                d["wbs_code"], d["discipline_code"], d["doc_type_code"], d["originator_code"]):
            problems.append(f"document {code}: code does not match its registered columns")
        if d["wbs_code"] not in wbs:
            problems.append(f"document {code}: unknown WBS {d['wbs_code']}")
        if d["originator_code"] not in orgs:
            problems.append(f"document {code}: unknown originator {d['originator_code']}")
        if d["discipline_code"] not in vocab["discipline"] or d["doc_type_code"] not in vocab["doc_type"]:
            problems.append(f"document {code}: discipline or document type not in the vocabulary")
        if d["owner_name"] and d["owner_name"] not in people:
            problems.append(f"document {code}: unknown owner {d['owner_name']}")
    problems += [f"document {c}: listed {n} times"
                 for c, n in Counter(d["doc_code"] for d in reg.documents).items() if n > 1]

    revision_dates: dict[tuple[str, str], date] = {}
    for r in reg.revisions:
        key = (r["doc_code"], r["rev_code"])
        label = f"revision {key[0]} {key[1]}"
        if key[0] not in doc_types:
            problems.append(f"{label}: unknown document")
        try:
            naming.validate_rev(key[1])
            revision_dates[key] = date.fromisoformat(r["revision_date"])
        except ValueError as e:
            problems.append(f"{label}: {e}")
        if r["stage_code"] not in vocab["stage"]:
            problems.append(f"{label}: unknown stage {r['stage_code']}")
        if r["sender_code"] and r["sender_code"] not in orgs:
            problems.append(f"{label}: unknown sender {r['sender_code']}")
    problems += [f"revision {k[0]} {k[1]}: listed {n} times"
                 for k, n in Counter((r["doc_code"], r["rev_code"]) for r in reg.revisions).items() if n > 1]

    status_keys = Counter()
    for s in reg.statuses:
        key = (s["doc_code"], s["rev_code"])
        label = f"status {s['status_code']} on {key[0]} {key[1]}"
        if key not in revision_dates:
            problems.append(f"{label}: unknown revision")
            continue
        if s["status_code"] not in vocab["status"]:
            problems.append(f"{label}: unknown status")
        elif not naming.status_allowed(doc_types.get(key[0], ""), s["status_code"]):
            problems.append(f"{label}: not allowed for document type {doc_types.get(key[0])}")
        if date.fromisoformat(s["effective_date"]) < revision_dates[key]:
            problems.append(f"{label}: dated before the revision was issued")
        if s["assigned_by_code"] and s["assigned_by_code"] not in orgs:
            problems.append(f"{label}: unknown organisation {s['assigned_by_code']}")
        status_keys[(key, s["effective_date"])] += 1
    problems += [f"revision {k[0][0]} {k[0][1]}: two statuses on {k[1]}" for k, n in status_keys.items() if n > 1]
    problems += [f"revision {k[0]} {k[1]}: no status" for k in revision_dates
                 if not any(sk[0] == k for sk in status_keys)]

    root = corpus.resolve()
    primaries = Counter()
    for f in reg.files:
        key = (f["doc_code"], f["rev_code"])
        label = f"file {f['storage_path']}"
        if key not in revision_dates:
            problems.append(f"{label}: unknown revision")
        if f["copy_role"] == "primary":
            primaries[key] += 1
        if f["storage_path"] != f"{f['original_location']}/{f['filename']}":
            problems.append(f"{label}: storage path does not match location and filename")
        if not f["filename"].endswith(f".{f['file_format']}"):
            problems.append(f"{label}: extension does not match format {f['file_format']}")
        parsed = naming.parse_filename(f["filename"])  # None = legacy filename, which is allowed
        if parsed and (str(parsed.doc_code), parsed.rev) != key:
            problems.append(f"{label}: filename names {parsed.doc_code} {parsed.rev}")
        path = (corpus / f["storage_path"]).resolve()
        if not path.is_relative_to(root):
            problems.append(f"{label}: outside the corpus folder")
        elif not path.is_file():
            problems.append(f"{label}: file not found")
        else:
            data = path.read_bytes()
            if len(data) != int(f["size_bytes"]) or hashlib.sha256(data).hexdigest() != f["sha256"]:
                problems.append(f"{label}: size or SHA-256 does not match the register")
    problems += [f"revision {k[0]} {k[1]}: {primaries[k]} primary files" for k in revision_dates if primaries[k] != 1]
    if len({f["storage_path"] for f in reg.files}) != len(reg.files):
        problems.append("duplicate storage paths")

    for link in reg.links:
        label = f"link {link['from_doc_code']} {link['link_type']} {link['to_doc_code']}"
        for doc, rev in ((link["from_doc_code"], link["from_rev_code"]), (link["to_doc_code"], link["to_rev_code"])):
            if doc not in doc_types or (rev and (doc, rev) not in revision_dates):
                problems.append(f"{label}: unresolved {doc} {rev}".rstrip())
    return problems


def load(conn: psycopg.Connection, corpus: Path) -> dict[str, int]:
    """Validate and replace all project data. Does not commit; the caller owns the transaction."""
    reg = read_register(corpus)
    problems = validate(reg, corpus, read_vocab(conn))
    if problems:
        raise RegisterError(problems)

    with conn.transaction():
        conn.execute("truncate " + ", ".join(f"dcc.{t}" for t in PROJECT_TABLES) + " restart identity")
        cur = conn.cursor()

        pending = list(reg.wbs)
        while pending:  # parents before children
            inserted = {r[0] for r in conn.execute("select code from dcc.wbs_element")}
            ready = [w for w in pending if not w["parent_code"] or w["parent_code"] in inserted]
            cur.executemany(
                "insert into dcc.wbs_element (code, name, parent_code, aliases) values (%s, %s, %s, %s)",
                [(w["code"], w["name"], w["parent_code"] or None, _aliases(w)) for w in ready])
            pending = [w for w in pending if w not in ready]

        cur.executemany("insert into dcc.organisation (code, name, role, aliases) values (%s, %s, %s, %s)",
                        [(o["code"], o["name"], o["role"], _aliases(o)) for o in reg.organisations])
        cur.executemany("insert into dcc.person (full_name, org_code, job_title) values (%s, %s, %s)",
                        [(p["name"], p["org_code"], p["title"]) for p in reg.people])
        person_ids = dict(conn.execute("select full_name, id from dcc.person").fetchall())

        cur.executemany(
            """insert into dcc.document (doc_code, title, wbs_code, discipline_code, doc_type_code,
                                         originator_code, owner_person_id)
               values (%s, %s, %s, %s, %s, %s, %s)""",
            [(d["doc_code"], d["title"], d["wbs_code"], d["discipline_code"], d["doc_type_code"],
              d["originator_code"], person_ids.get(d["owner_name"])) for d in reg.documents])
        doc_ids = dict(conn.execute("select doc_code, id from dcc.document").fetchall())

        cur.executemany(
            """insert into dcc.revision (document_id, rev_code, revision_date, stage_code, sender_code, description)
               values (%s, %s, %s, %s, %s, %s)""",
            [(doc_ids[r["doc_code"]], r["rev_code"], r["revision_date"], r["stage_code"],
              r["sender_code"] or None, r["description"] or None) for r in reg.revisions])
        rev_ids = {(code, rev): rid for code, rev, rid in conn.execute(
            "select d.doc_code, r.rev_code, r.id from dcc.revision r join dcc.document d on d.id = r.document_id")}

        cur.executemany(
            """insert into dcc.revision_status (revision_id, status_code, effective_date, assigned_by_code, note)
               values (%s, %s, %s, %s, %s)""",
            [(rev_ids[(s["doc_code"], s["rev_code"])], s["status_code"], s["effective_date"],
              s["assigned_by_code"] or None, s["note"] or None) for s in reg.statuses])

        cur.executemany(
            """insert into dcc.revision_file (revision_id, copy_role, filename, original_location, storage_path,
                                              file_format, size_bytes, sha256)
               values (%s, %s, %s, %s, %s, %s, %s, %s)""",
            [(rev_ids[(f["doc_code"], f["rev_code"])], f["copy_role"], f["filename"], f["original_location"],
              f["storage_path"], f["file_format"], int(f["size_bytes"]), f["sha256"]) for f in reg.files])

        cur.executemany(
            """insert into dcc.information_link (from_document_id, from_revision_id, to_document_id, to_revision_id,
                                                 link_type, provenance, note)
               values (%s, %s, %s, %s, %s, %s, %s)""",
            [(doc_ids[l["from_doc_code"]], rev_ids.get((l["from_doc_code"], l["from_rev_code"])),
              doc_ids[l["to_doc_code"]], rev_ids.get((l["to_doc_code"], l["to_rev_code"])),
              l["link_type"], l["provenance"], l["note"] or None) for l in reg.links])

    return {name: len(getattr(reg, name)) for name in REGISTER_FILES}


def _aliases(row: dict) -> list[str]:
    return [a for a in row["aliases"].split("|") if a]


def main() -> None:
    parser = argparse.ArgumentParser(description="Load the corpus register into the dcc schema.")
    parser.add_argument("--corpus", type=Path, default=REPO_ROOT / "corpus")
    parser.add_argument("--dry-run", action="store_true", help="validate and load, then roll back")
    args = parser.parse_args()

    database_url = get_settings().database_url
    if not database_url:
        raise SystemExit("DATABASE_URL is not set")
    with psycopg.connect(database_url, prepare_threshold=None) as conn:
        try:
            counts = load(conn, args.corpus)
        except RegisterError as e:
            raise SystemExit(str(e)) from None
        print("Loaded: " + ", ".join(f"{n} {k}" for k, n in counts.items()))
        rows = conn.execute(
            """select d.doc_code,
                      max(s.rev_code) filter (where s.is_latest),
                      max(s.rev_code) filter (where s.is_latest_for_use and s.permitted_use_code = 'construction')
               from dcc.document d join dcc.revision_summary s on s.document_id = d.id
               group by d.doc_code order by d.doc_code""").fetchall()
        for doc_code, latest, construction in rows:
            print(f"  {doc_code}: latest {latest}"
                  + (f", latest for construction {construction}" if construction else ""))
        if args.dry_run:
            conn.rollback()
            print("Dry run: rolled back, nothing changed.")
        else:
            conn.commit()


if __name__ == "__main__":
    main()
