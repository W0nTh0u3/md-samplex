begin;
create table public.attempts (
  id uuid primary key,
  owner_id uuid not null references auth.users(id) on delete cascade,
  bank_version text not null,
  revision integer not null default 0 check (revision >= 0),
  editor_id uuid not null,
  payload jsonb not null,
  updated_at timestamptz not null default now(),
  constraint payload_owner_matches check (payload->>'ownerId' = owner_id::text),
  constraint payload_id_matches check (payload->>'id' = id::text),
  constraint payload_bank_matches check (payload->>'bankVersion' = bank_version),
  constraint payload_revision_matches check ((payload->>'revision')::integer = revision),
  constraint payload_editor_matches check (payload->>'editorId' = editor_id::text)
);
create index attempts_owner_updated_idx on public.attempts (owner_id, updated_at desc);
alter table public.attempts enable row level security;
create policy "Students read their own attempts" on public.attempts for select to authenticated
  using ((select auth.uid()) = owner_id);
revoke all on public.attempts from anon, authenticated;
grant select on public.attempts to authenticated;
grant all on public.attempts to service_role;
-- Client writes are deliberately unavailable. Server endpoints validate answers,
-- practice locks, bank version, owner, revision and editor before CAS updates.
-- Correct answers are kept in the server-side versioned bank, never this table.
commit;
