-- Enable pgvector extension
create extension if not exists vector with schema extensions;

-- Add embedding column to links table (1536 dimensions for text-embedding-3-small)
alter table public.links add column if not exists embedding extensions.vector(1536);

-- Create HNSW index for fast similarity search
create index if not exists links_embedding_hnsw_idx
  on public.links
  using hnsw (embedding extensions.vector_cosine_ops)
  with (m = 16, ef_construction = 64);

-- Create similarity search function
create or replace function public.match_articles(
  query_embedding extensions.vector(1536),
  match_threshold float default 0.3,
  match_count int default 20
)
returns table (
  id uuid,
  slug text,
  title text,
  author text,
  destination_url text,
  published_at timestamptz,
  created_at timestamptz,
  similarity float
)
language plpgsql
security definer
set search_path = 'public', 'extensions'
as $$
begin
  return query
  select
    l.id,
    l.slug,
    l.title,
    l.author,
    l.destination_url,
    l.published_at,
    l.created_at,
    1 - (l.embedding <=> query_embedding) as similarity
  from public.links l
  where l.embedding is not null
    and 1 - (l.embedding <=> query_embedding) > match_threshold
  order by l.embedding <=> query_embedding
  limit match_count;
end;
$$;

-- Grant execute to authenticated users
grant execute on function public.match_articles(extensions.vector, float, int) to authenticated;
grant execute on function public.match_articles(extensions.vector, float, int) to service_role;
