-- DCC V1 core schema (approved sections A–I).
-- All objects live in the private "dcc" schema, which is not exposed through the Supabase Data API.
-- Deferred on purpose: search_entry + pg_trgm, revision_discrepancy view, status applicability
-- per document type, least-privilege roles, project table.

create schema if not exists dcc;
revoke all on schema dcc from public;
revoke all on schema dcc from anon, authenticated;

-- ---------------------------------------------------------------------------
-- A. Convention vocabularies (seeded by the convention_vocab migration)
-- ---------------------------------------------------------------------------

create table dcc.discipline (
  code    text primary key check (code ~ '^[A-Z]$'),
  label   text not null,
  aliases text[] not null default '{}'
);

create table dcc.doc_type (
  code    text primary key check (code ~ '^[A-Z]{2}$'),
  label   text not null,
  aliases text[] not null default '{}'
);

create table dcc.stage (
  code    text primary key check (code ~ '^[A-Z]{2}$'),
  label   text not null,
  seq     smallint not null unique,
  aliases text[] not null default '{}'
);

create table dcc.permitted_use (
  code  text primary key,
  label text not null
);

create table dcc.status (
  code               text primary key check (code ~ '^[A-Z]{2}$'),
  label              text not null,
  permitted_use_code text not null references dcc.permitted_use (code),
  aliases            text[] not null default '{}'
);
create index status_permitted_use_idx on dcc.status (permitted_use_code);

-- ---------------------------------------------------------------------------
-- B. Project reference data (loaded from the corpus spec, not seeded here)
-- ---------------------------------------------------------------------------

create table dcc.wbs_element (
  code        text primary key check (code ~ '^\d{3}$'),
  name        text not null,
  parent_code text references dcc.wbs_element (code),
  aliases     text[] not null default '{}'
);
create index wbs_element_parent_idx on dcc.wbs_element (parent_code);

create table dcc.organisation (
  code    text primary key check (code ~ '^[A-Z]{3}$'),
  name    text not null,
  role    text not null,
  aliases text[] not null default '{}'
);

create table dcc.person (
  id        bigint generated always as identity primary key,
  full_name text not null,
  org_code  text not null references dcc.organisation (code),
  job_title text,
  unique (full_name, org_code)
);
create index person_org_idx on dcc.person (org_code);

-- ---------------------------------------------------------------------------
-- C. Registered metadata: Document -> Revision
-- ---------------------------------------------------------------------------

create table dcc.document (
  id              bigint generated always as identity primary key,
  doc_code        text not null unique,
  title           text not null,
  wbs_code        text not null references dcc.wbs_element (code),
  discipline_code text not null references dcc.discipline (code),
  doc_type_code   text not null references dcc.doc_type (code),
  originator_code text not null references dcc.organisation (code),
  owner_person_id bigint references dcc.person (id)
);
create index document_wbs_idx        on dcc.document (wbs_code);
create index document_discipline_idx on dcc.document (discipline_code);
create index document_type_idx       on dcc.document (doc_type_code);
create index document_originator_idx on dcc.document (originator_code);
create index document_owner_idx      on dcc.document (owner_person_id);

create table dcc.revision (
  id            bigint generated always as identity primary key,
  document_id   bigint not null references dcc.document (id) on delete cascade,
  rev_code      text not null check (rev_code ~ '^[PCA]\d{2}$'),
  revision_date date not null,
  stage_code    text not null references dcc.stage (code),
  sender_code   text references dcc.organisation (code),  -- null: issued by the originator
  description   text,
  unique (document_id, rev_code),
  unique (id, document_id)  -- target for information_link composite foreign keys
);
create index revision_stage_idx  on dcc.revision (stage_code);
create index revision_sender_idx on dcc.revision (sender_code);
create index revision_date_idx   on dcc.revision (revision_date);

-- ---------------------------------------------------------------------------
-- D. Status / permitted-use history (separate from revision and date)
-- ---------------------------------------------------------------------------

create table dcc.revision_status (
  id               bigint generated always as identity primary key,
  revision_id      bigint not null references dcc.revision (id) on delete cascade,
  status_code      text not null references dcc.status (code),
  effective_date   date not null,
  assigned_by_code text references dcc.organisation (code),
  note             text,
  unique (revision_id, effective_date)
);
create index revision_status_status_idx      on dcc.revision_status (status_code);
create index revision_status_assigned_by_idx on dcc.revision_status (assigned_by_code);

-- ---------------------------------------------------------------------------
-- E. File provenance
-- ---------------------------------------------------------------------------

create table dcc.revision_file (
  id                bigint generated always as identity primary key,
  revision_id       bigint not null references dcc.revision (id) on delete cascade,
  copy_role         text not null default 'primary' check (copy_role in ('primary', 'copy')),
  filename          text not null,
  original_location text not null,
  storage_path      text not null unique,
  file_format       text not null check (file_format in ('pdf', 'docx', 'xlsx')),
  size_bytes        bigint not null check (size_bytes >= 0),
  sha256            text not null check (sha256 ~ '^[0-9a-f]{64}$')
);
create index revision_file_revision_idx on dcc.revision_file (revision_id);
create unique index revision_file_one_primary_idx
  on dcc.revision_file (revision_id) where copy_role = 'primary';

-- ---------------------------------------------------------------------------
-- F. Extracted content (never written into registered metadata)
-- ---------------------------------------------------------------------------

create table dcc.extraction (
  revision_file_id  bigint primary key references dcc.revision_file (id) on delete cascade,
  extractor_version text not null,
  extracted_at      timestamptz not null default now(),
  outcome           text not null check (outcome in ('ok', 'empty', 'failed')),
  error             text,
  unit_count        integer check (unit_count >= 0),
  extracted_fields  jsonb not null default '{}'
);

create table dcc.content_segment (
  id               bigint generated always as identity primary key,
  revision_file_id bigint not null references dcc.extraction (revision_file_id) on delete cascade,
  seq              integer not null,
  locator          text not null,
  body             text not null,
  unique (revision_file_id, seq)
);

-- ---------------------------------------------------------------------------
-- H. Lightweight information relationships ("from <link_type> to")
-- ---------------------------------------------------------------------------

create table dcc.information_link (
  id               bigint generated always as identity primary key,
  from_document_id bigint not null references dcc.document (id) on delete cascade,
  from_revision_id bigint,
  to_document_id   bigint not null references dcc.document (id) on delete cascade,
  to_revision_id   bigint,
  link_type        text not null check (link_type in
                     ('supersedes', 'responds_to', 'clarified_by', 'generated_from', 'affects', 'related_to')),
  provenance       text not null default 'registered' check (provenance in ('registered', 'extracted')),
  note             text,
  foreign key (from_revision_id, from_document_id)
    references dcc.revision (id, document_id) on delete cascade,
  foreign key (to_revision_id, to_document_id)
    references dcc.revision (id, document_id) on delete cascade,
  check (from_document_id <> to_document_id),
  unique nulls not distinct (from_document_id, from_revision_id, to_document_id, to_revision_id, link_type)
);
create index information_link_to_doc_idx   on dcc.information_link (to_document_id);
create index information_link_from_rev_idx on dcc.information_link (from_revision_id);
create index information_link_to_rev_idx   on dcc.information_link (to_revision_id);

-- ---------------------------------------------------------------------------
-- G. Derived "latest" and "latest for a permitted use" (nothing stored)
-- ---------------------------------------------------------------------------

-- Tie-breaker only: orders revision codes P < C < A, then numerically.
create function dcc.rev_code_rank(rev_code text) returns integer
language sql immutable strict
set search_path = ''
as $$
  select (case left(rev_code, 1) when 'P' then 1 when 'C' then 2 when 'A' then 3 end) * 1000
         + substring(rev_code from 2)::integer
$$;

create view dcc.revision_current_status with (security_invoker = true) as
select distinct on (rs.revision_id)
       rs.revision_id,
       rs.status_code,
       s.permitted_use_code,
       rs.effective_date as status_date
from dcc.revision_status rs
join dcc.status s on s.code = rs.status_code
order by rs.revision_id, rs.effective_date desc;

-- "Latest" = most recently issued (revision_date); rev_code_rank breaks same-day ties.
create view dcc.revision_summary with (security_invoker = true) as
with ordered as (
  select r.id,
         r.document_id,
         r.rev_code,
         r.revision_date,
         r.stage_code,
         row_number() over (partition by r.document_id
                            order by r.revision_date desc, dcc.rev_code_rank(r.rev_code) desc) as recency,
         count(*) over (partition by r.document_id) as revision_count
  from dcc.revision r
)
select o.id as revision_id,
       o.document_id,
       o.rev_code,
       o.revision_date,
       o.stage_code,
       o.recency,
       (o.recency = 1) as is_latest,
       o.revision_count,
       cs.status_code,
       cs.permitted_use_code,
       cs.status_date,
       case when cs.permitted_use_code is null then false
            else row_number() over (partition by o.document_id, cs.permitted_use_code
                                    order by o.recency) = 1
       end as is_latest_for_use
from ordered o
left join dcc.revision_current_status cs on cs.revision_id = o.id;

create view dcc.document_latest_by_use with (security_invoker = true) as
select document_id, permitted_use_code, revision_id, rev_code, revision_date
from dcc.revision_summary
where is_latest_for_use;

-- ---------------------------------------------------------------------------
-- I. Defense in depth: RLS on every table, no policies (owner role bypasses RLS)
-- ---------------------------------------------------------------------------

alter table dcc.discipline       enable row level security;
alter table dcc.doc_type         enable row level security;
alter table dcc.stage            enable row level security;
alter table dcc.permitted_use    enable row level security;
alter table dcc.status           enable row level security;
alter table dcc.wbs_element      enable row level security;
alter table dcc.organisation     enable row level security;
alter table dcc.person           enable row level security;
alter table dcc.document         enable row level security;
alter table dcc.revision         enable row level security;
alter table dcc.revision_status  enable row level security;
alter table dcc.revision_file    enable row level security;
alter table dcc.extraction       enable row level security;
alter table dcc.content_segment  enable row level security;
alter table dcc.information_link enable row level security;
