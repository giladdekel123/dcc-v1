-- Cover the composite revision foreign keys on information_link (Supabase advisor 0001_unindexed_foreign_keys).
-- The new indexes lead with the revision column, so they replace the single-column ones.

drop index dcc.information_link_from_rev_idx;
drop index dcc.information_link_to_rev_idx;

create index information_link_from_rev_doc_idx on dcc.information_link (from_revision_id, from_document_id);
create index information_link_to_rev_doc_idx   on dcc.information_link (to_revision_id, to_document_id);
