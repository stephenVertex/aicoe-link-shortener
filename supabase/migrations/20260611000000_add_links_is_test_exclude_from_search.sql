-- Add is_test flag to links table and exclude test links from production search

-- 1. Add is_test column to links table
ALTER TABLE public.links
ADD COLUMN IF NOT EXISTS is_test boolean NOT NULL DEFAULT false;

-- 2. Create partial index for fast lookup of test links (admin/debug use)
CREATE INDEX IF NOT EXISTS idx_links_is_test
ON public.links (id)
WHERE is_test = true;

-- 3. Flag known test/dev links from the bug report (do not delete rows)
UPDATE public.links
SET is_test = true
WHERE slug IN (
  'mytestslug123',
  'bz11id',
  '8hr',
  'fi2',
  '0hsnqq',
  'xa0thn',
  'cra'
);

-- 4. Update hybrid_match_articles to exclude test links
CREATE OR REPLACE FUNCTION public.hybrid_match_articles(
  query_embedding extensions.vector(1536),
  query_text text,
  match_threshold float DEFAULT 0.3,
  match_count int DEFAULT 20,
  content_type_filter text DEFAULT NULL,
  author_filter text DEFAULT NULL,
  vector_weight float DEFAULT 0.7,
  keyword_weight float DEFAULT 0.3
)
RETURNS TABLE (
  id text,
  slug text,
  title text,
  author text,
  destination_url text,
  published_at timestamptz,
  created_at timestamptz,
  similarity float,
  keyword_rank float,
  hybrid_score float
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = 'public', 'extensions'
AS $$
BEGIN
  RETURN QUERY
  WITH vector_scores AS (
    SELECT
      l.id::text as vid,
      l.slug::text as vslug,
      l.title::text as vtitle,
      l.author::text as vauthor,
      l.destination_url::text as vdest,
      l.published_at::timestamptz as vpub,
      l.created_at::timestamptz as vcreated,
      (1 - (l.embedding <=> query_embedding))::float as vsim
    FROM public.links l
    WHERE l.embedding IS NOT NULL
      AND l.is_test = false
      AND 1 - (l.embedding <=> query_embedding) > match_threshold
      AND (content_type_filter IS NULL OR l.content_type = content_type_filter)
      AND (author_filter IS NULL OR l.author ILIKE '%' || author_filter || '%')
  ),
  keyword_scores AS (
    SELECT
      l.id::text as kid,
      ts_rank_cd(l.search_vector, plainto_tsquery('english', query_text), 32)::float as krank
    FROM public.links l
    WHERE l.search_vector @@ plainto_tsquery('english', query_text)
      AND l.is_test = false
      AND (content_type_filter IS NULL OR l.content_type = content_type_filter)
      AND (author_filter IS NULL OR l.author ILIKE '%' || author_filter || '%')
  ),
  combined AS (
    -- All vector results, with keyword rank if available
    SELECT
      v.vid as cid,
      v.vslug as cslug,
      v.vtitle as ctitle,
      v.vauthor as cauthor,
      v.vdest as cdest,
      v.vpub as cpub,
      v.vcreated as ccreated,
      v.vsim as csim,
      COALESCE(k.krank, 0.0) as ckrank,
      (vector_weight * v.vsim + keyword_weight * COALESCE(k.krank, 0.0)) as chybrid
    FROM vector_scores v
    LEFT JOIN keyword_scores k ON v.vid = k.kid

    UNION

    -- Keyword-only results not in vector results (with similarity = 0)
    SELECT
      k.kid as cid,
      l.slug::text as cslug,
      l.title::text as ctitle,
      l.author::text as cauthor,
      l.destination_url::text as cdest,
      l.published_at::timestamptz as cpub,
      l.created_at::timestamptz as ccreated,
      0.0 as csim,
      k.krank as ckrank,
      (vector_weight * 0.0 + keyword_weight * k.krank) as chybrid
    FROM keyword_scores k
    JOIN public.links l ON l.id = k.kid
    LEFT JOIN vector_scores v ON v.vid = k.kid
    WHERE v.vid IS NULL
  )
  SELECT
    combined.cid,
    combined.cslug,
    combined.ctitle,
    combined.cauthor,
    combined.cdest,
    combined.cpub,
    combined.ccreated,
    combined.csim,
    combined.ckrank,
    combined.chybrid
  FROM combined
  ORDER BY combined.chybrid DESC
  LIMIT match_count;
END;
$$;

GRANT EXECUTE ON FUNCTION public.hybrid_match_articles(
  extensions.vector, text, float, int, text, text, float, float
) TO authenticated;

GRANT EXECUTE ON FUNCTION public.hybrid_match_articles(
  extensions.vector, text, float, int, text, text, float, float
) TO service_role;

-- 5. Update search_video_chunks to exclude test links
CREATE OR REPLACE FUNCTION public.search_video_chunks(
  query_embedding extensions.vector(1536),
  match_threshold float DEFAULT 0.3,
  match_count int DEFAULT 20,
  dedupe_videos boolean DEFAULT true
)
RETURNS TABLE (
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
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = 'public', 'extensions'
AS $$
BEGIN
  IF dedupe_videos THEN
    RETURN QUERY
    WITH ranked_chunks AS (
      SELECT
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
        row_number() OVER (PARTITION BY c.link_id ORDER BY c.embedding <=> query_embedding) as rn
      FROM public.video_chunks c
      JOIN public.links l ON c.link_id = l.id
      WHERE c.embedding IS NOT NULL
        AND l.is_test = false
        AND 1 - (c.embedding <=> query_embedding) > match_threshold
    )
    SELECT
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
    FROM ranked_chunks
    WHERE rn = 1
    ORDER BY similarity DESC
    LIMIT match_count;
  ELSE
    RETURN QUERY
    SELECT
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
    FROM public.video_chunks c
    JOIN public.links l ON c.link_id = l.id
    WHERE c.embedding IS NOT NULL
      AND l.is_test = false
      AND 1 - (c.embedding <=> query_embedding) > match_threshold
    ORDER BY c.embedding <=> query_embedding
    LIMIT match_count;
  END IF;
END;
$$;

GRANT EXECUTE ON FUNCTION public.search_video_chunks(extensions.vector, float, int, boolean) TO authenticated;
GRANT EXECUTE ON FUNCTION public.search_video_chunks(extensions.vector, float, int, boolean) TO service_role;

-- 6. Update match_articles to exclude test links
CREATE OR REPLACE FUNCTION public.match_articles(
  query_embedding extensions.vector(1536),
  match_threshold float DEFAULT 0.3,
  match_count int DEFAULT 20,
  content_type_filter text DEFAULT NULL,
  author_filter text DEFAULT NULL
)
RETURNS TABLE (
  id text,
  slug text,
  title text,
  author text,
  destination_url text,
  published_at timestamptz,
  created_at timestamptz,
  similarity float
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = 'public', 'extensions'
AS $$
BEGIN
  RETURN QUERY
  SELECT
    l.id::text,
    l.slug::text,
    l.title::text,
    l.author::text,
    l.destination_url::text,
    l.published_at::timestamptz,
    l.created_at::timestamptz,
    (1 - (l.embedding <=> query_embedding))::float AS similarity
  FROM public.links l
  WHERE l.embedding IS NOT NULL
    AND l.is_test = false
    AND 1 - (l.embedding <=> query_embedding) > match_threshold
    AND (content_type_filter IS NULL OR l.content_type = content_type_filter)
    AND (author_filter IS NULL OR l.author ILIKE '%' || author_filter || '%')
  ORDER BY l.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

GRANT EXECUTE ON FUNCTION public.match_articles(extensions.vector, float, int, text, text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.match_articles(extensions.vector, float, int, text, text) TO service_role;
