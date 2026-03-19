-- Tags table: reusable labels for categorizing articles
create table if not exists public.tags (
  id text primary key default generate_prefixed_id('tag-'),
  name text not null,
  slug text not null unique,
  created_at timestamptz not null default now()
);

-- Junction table: many-to-many between links (articles) and tags
create table if not exists public.article_tags (
  id text primary key default generate_prefixed_id('at-'),
  link_id text not null references public.links(id) on delete cascade,
  tag_id text not null references public.tags(id) on delete cascade,
  created_at timestamptz not null default now(),
  unique (link_id, tag_id)
);

create index if not exists article_tags_link_id_idx on public.article_tags(link_id);
create index if not exists article_tags_tag_id_idx on public.article_tags(tag_id);

-- RLS policies for tags
alter table public.tags enable row level security;

-- Anyone with service_role can do anything
drop policy if exists service_role_all_tags on public.tags;
create policy service_role_all_tags
  on public.tags
  for all
  using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');

-- Authenticated users can read tags
drop policy if exists authenticated_read_tags on public.tags;
create policy authenticated_read_tags
  on public.tags
  for select
  using (auth.role() = 'authenticated');

-- RLS policies for article_tags
alter table public.article_tags enable row level security;

drop policy if exists service_role_all_article_tags on public.article_tags;
create policy service_role_all_article_tags
  on public.article_tags
  for all
  using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');

drop policy if exists authenticated_read_article_tags on public.article_tags;
create policy authenticated_read_article_tags
  on public.article_tags
  for select
  using (auth.role() = 'authenticated');
