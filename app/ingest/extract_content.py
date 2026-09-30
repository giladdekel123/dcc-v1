"""Extract text segments and self-declared fields from every registered file.

    python -m app.ingest.extract_content [--corpus corpus]

Writes only dcc.extraction and dcc.content_segment; registered metadata is never modified.
Run after load_register (reloading the register clears extraction).
"""

import argparse
import hashlib
from collections import Counter
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.extraction import EXTRACTOR_VERSION, Extracted, extract


def extract_file(corpus: Path, storage_path: str, file_format: str, sha256: str) -> Extracted:
    root = corpus.resolve()
    path = (corpus / storage_path).resolve()
    if not path.is_relative_to(root):
        return Extracted("failed", error="path outside the corpus folder")
    if not path.is_file():
        return Extracted("failed", error="file not found")
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
        return Extracted("failed", error="file changed since registration (SHA-256 mismatch)")
    return extract(path, file_format)


def extract_all(conn: psycopg.Connection, corpus: Path) -> dict[str, Extracted]:
    """Re-extract every registered file. Does not commit; the caller owns the transaction."""
    files = conn.execute(
        "select id, storage_path, file_format, sha256 from dcc.revision_file order by id").fetchall()
    results = {}
    with conn.transaction():
        for file_id, storage_path, file_format, sha256 in files:
            result = extract_file(corpus, storage_path, file_format, sha256)
            conn.execute("delete from dcc.extraction where revision_file_id = %s", (file_id,))
            conn.execute(
                """insert into dcc.extraction (revision_file_id, extractor_version, outcome, error,
                                               unit_count, extracted_fields)
                   values (%s, %s, %s, %s, %s, %s)""",
                (file_id, EXTRACTOR_VERSION, result.outcome, result.error, result.unit_count, Jsonb(result.fields)))
            conn.cursor().executemany(
                "insert into dcc.content_segment (revision_file_id, seq, locator, body) values (%s, %s, %s, %s)",
                [(file_id, seq, s.locator, s.body) for seq, s in enumerate(result.segments, 1)])
            results[storage_path] = result
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract text from every registered corpus file.")
    parser.add_argument("--corpus", type=Path, default=get_settings().corpus_root)
    args = parser.parse_args()

    database_url = get_settings().database_url
    if not database_url:
        raise SystemExit("DATABASE_URL is not set")
    with psycopg.connect(database_url, prepare_threshold=None) as conn:
        results = extract_all(conn, args.corpus)
        conn.commit()
    outcomes = Counter(r.outcome for r in results.values())
    segments = sum(len(r.segments) for r in results.values())
    print(f"{EXTRACTOR_VERSION}: {len(results)} files, {segments} segments, "
          + ", ".join(f"{n} {o}" for o, n in sorted(outcomes.items())))
    for path, r in results.items():
        if r.outcome != "ok":
            print(f"  {r.outcome}: {path} ({r.error or 'no text'})")


if __name__ == "__main__":
    main()
