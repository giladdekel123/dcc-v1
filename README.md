# DCC V1

DCC helps a project participant find the right project document when they remember only part of it.
They don't need to know the exact filename, document code or filing location.
DCC returns a short ranked list with structured evidence: matched metadata, content snippets,
revision and status information, and the original file location. **DCC provides the evidence;
the user makes the judgment.**

V1 works on a synthetic corpus of 60–100 files for one fictional infrastructure project,
Kestrel Valley Link Road (KVL). The first goal is to build and measure a basic retrieval baseline.
The AI/semantic retrieval approach has not been chosen yet.

## ISO 19650 position

DCC V1 is **ISO 19650-aware, not ISO 19650-compliant**. It borrows concepts such as information
containers, originator, status as a statement of permitted use, revision, relationships between
information and provenance. The document coding scheme is the **KVL project convention**,
inspired by those concepts. It is not the ISO 19650 naming convention, and DCC makes no claim
of compliance.

## Stack

Python 3.13 · FastAPI · HTML/CSS/JavaScript · Supabase/PostgreSQL (planned) · Railway (later)

## Run locally

```bash
pip install -r requirements-dev.txt
cp .env.example .env            # optional for now; DATABASE_URL is not used yet
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 (the page) or http://127.0.0.1:8000/api/health.
Interactive API docs are at http://127.0.0.1:8000/docs.

## Test

```bash
pytest
```

## Synthetic corpus

```bash
python -m dcc_corpus.generate   # regenerates corpus/ deterministically (seed 1905)
```

The corpus is committed as the stable V1 test set; tests check it matches a fresh generation.

## Layout

```
app/          FastAPI backend (config, API routes, database)
web/          static frontend served at /
dcc_corpus/   KVL naming convention, corpus spec and deterministic generator
corpus/       generated synthetic project files, register CSVs, links, ground truth
supabase/     database migrations
tests/        pytest suite (database tests skip without DATABASE_URL)
```
