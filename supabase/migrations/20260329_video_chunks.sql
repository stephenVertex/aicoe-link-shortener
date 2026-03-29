-- Video chunks table for timestamped semantic search
-- Each video is split into overlapping chunks with their own embeddings

create table if not exists public.video_chunks (
  id text primary key default generate_prefixed_id('chk-'),
  link_id text not null references public.links(id) on delete cascade,
  chunk_index int not null,
  start_time int not null,
  end_time int not null,
  text text not null,
  embedding extensions.vector(1536),
  created_at timestamptz default now(),
  unique(link_id, chunk_index)
);

-- Index for fast chunk lookup by video
create index if not exists video_chunks_link_id_idx on public.video_chunks(link_id);

-- HNSW index for semantic search
create index if not exists video_chunks_embedding_hnsw_idx
  on public.video_chunks
  using hnsw (embedding extensions.vector_cosine_ops)
  with (m = 16, ef_construction = 64);

-- Function to search video chunks with timestamps
create or replace function public.search_video_chunks(
  query_embedding extensions.vector(1536),
  match_threshold float default 0.3,
  match_count int default 20,
  dedupe_videos boolean default true
)
returns table (
  chunk_id text,
  link_id text,
  chunk_index int,
  start_time int,
  end_time int,
  text text,
  video_slug text,
  video_title text,
  video_url text,
  similarity float
)
language plpgsql
security definer
set search_path = 'public', 'extensions'
as $$
begin
  if dedupe_videos then
    return query
    with ranked_chunks as (
      select
        c.id as chunk_id,
        c.link_id,
        c.chunk_index,
        c.start_time,
        c.end_time,
        c.text,
        l.slug as video_slug,
        l.title as video_title,
        l.destination_url as video_url,
        (1 - (c.embedding <=> query_embedding))::float as similarity,
        row_number() over (partition by c.link_id order by c.embedding <=> query_embedding) as rn
      from public.video_chunks c
      join public.links l on c.link_id = l.id
      where c.embedding is not null
        and 1 - (c.embedding <=> query_embedding) > match_threshold
    )
    select 
      ranked_chunks.chunk_id::text,
      ranked_chunks.link_id::text,
      ranked_chunks.chunk_index,
      ranked_chunks.start_time,
      ranked_chunks.end_time,
      ranked_chunks.text::text,
      ranked_chunks.video_slug::text,
      ranked_chunks.video_title::text,
      ranked_chunks.video_url::text,
      ranked_chunks.similarity::float
    from ranked_chunks
    where rn = 1
    order by similarity desc
    limit match_count;
  else
    return query
    select
      c.id::text as chunk_id,
      c.link_id::text,
      c.chunk_index,
      c.start_time,
      c.end_time,
      c.text::text,
      l.slug::text as video_slug,
      l.title::text as video_title,
      l.destination_url::text as video_url,
      (1 - (c.embedding <=> query_embedding))::float as similarity
    from public.video_chunks c
    join public.links l on c.link_id = l.id
    where c.embedding is not null
      and 1 - (c.embedding <=> query_embedding) > match_threshold
    order by c.embedding <=> query_embedding
    limit match_count;
  end if;
end;
$$;

grant execute on function public.search_video_chunks(extensions.vector, float, int, boolean) to authenticated;
grant execute on function public.search_video_chunks(extensions.vector, float, int, boolean) to service_role;

-- RLS policies
alter table public.video_chunks enable row level security;

create policy "Allow public read access to video chunks"
  on public.video_chunks for select
  using (true);

create policy "Allow service role full access to video chunks"
  on public.video_chunks for all
  using (auth.role() = 'service_role');

-- Notify PostgREST to reload schema
select pg_notify('pgrst', 'reload schema');
