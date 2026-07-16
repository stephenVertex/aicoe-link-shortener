-- Junction table: many-to-many between aifs_submissions and tags
-- Reuses the existing public.tags table (id, name, slug, created_at) so a
-- single tag vocabulary serves both articles and aifs submissions.

create table if not exists public.aifs_submission_tags (
  id text primary key default generate_prefixed_id('ast-'),
  submission_id uuid not null references public.aifs_submissions(id) on delete cascade,
  tag_id text not null references public.tags(id) on delete cascade,
  created_at timestamptz not null default now(),
  unique (submission_id, tag_id)
);

create index if not exists aifs_submission_tags_submission_id_idx
  on public.aifs_submission_tags(submission_id);
create index if not exists aifs_submission_tags_tag_id_idx
  on public.aifs_submission_tags(tag_id);

-- RLS policies for aifs_submission_tags
alter table public.aifs_submission_tags enable row level security;

drop policy if exists service_role_all_aifs_submission_tags on public.aifs_submission_tags;
create policy service_role_all_aifs_submission_tags
  on public.aifs_submission_tags
  for all
  using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');

drop policy if exists authenticated_read_aifs_submission_tags on public.aifs_submission_tags;
create policy authenticated_read_aifs_submission_tags
  on public.aifs_submission_tags
  for select
  using (auth.role() = 'authenticated');
