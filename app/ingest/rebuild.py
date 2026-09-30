"""Load the register, extract content and rebuild the search index, in one transaction.

    python -m app.ingest.rebuild [--corpus corpus]
"""

import argparse
from collections import Counter
from pathlib import Path

import psycopg

from app.config import get_settings
from app.ingest.build_index import build_index
from app.ingest.extract_content import extract_all
from app.ingest.load_register import RegisterError, load


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=get_settings().corpus_root)
    args = parser.parse_args()

    database_url = get_settings().database_url
    if not database_url:
        raise SystemExit("DATABASE_URL is not set")
    with psycopg.connect(database_url, prepare_threshold=None) as conn:
        try:
            counts = load(conn, args.corpus)
        except RegisterError as e:
            raise SystemExit(str(e)) from None
        outcomes = Counter(r.outcome for r in extract_all(conn, args.corpus).values())
        indexed = build_index(conn)
        conn.commit()
    print(f"Loaded {counts['documents']} documents, {counts['revisions']} revisions, {counts['files']} files; "
          f"extracted {dict(outcomes)}; indexed {indexed} revisions")


if __name__ == "__main__":
    main()
