-- Baseline search index: weighted full-text per revision, trigram text for typos and code fragments,
-- and a per-segment tsvector for picking and highlighting passages. Rebuilt by app.ingest.build_index.

create extension if not exists pg_trgm with schema extensions;

alter table dcc.content_segment
  add column body_tsv tsvector generated always as (to_tsvector('english', body)) stored;
create index content_segment_body_tsv_idx on dcc.content_segment using gin (body_tsv);

create table dcc.search_entry (
  revision_id bigint primary key references dcc.revision (id) on delete cascade,
  document_id bigint not null references dcc.document (id) on delete cascade,
  tsv         tsvector not null,     -- A: title, code, filename; B: vocabulary labels; C: description, declared fields; D: body
  trgm_text   text not null,         -- title, code, filename
  built_at    timestamptz not null default now()
);
create index search_entry_document_idx on dcc.search_entry (document_id);
create index search_entry_tsv_idx on dcc.search_entry using gin (tsv);
create index search_entry_trgm_idx on dcc.search_entry using gin (trgm_text extensions.gin_trgm_ops);

alter table dcc.search_entry enable row level security;
