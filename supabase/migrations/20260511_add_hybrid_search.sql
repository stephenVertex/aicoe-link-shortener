-- Add body_text and full-text search to links for hybrid keyword + semantic search

-- 1. Add body_text column to store stripped article body
ALTER TABLE public.links
ADD COLUMN IF NOT EXISTS body_text text;

-- 2. Add search_vector tsvector column for PostgreSQL FTS
ALTER TABLE public.links
ADD COLUMN IF NOT EXISTS search_vector tsvector;

-- 3. Create GIN index for fast keyword search
CREATE INDEX IF NOT EXISTS idx_links_search_vector
ON public.links USING GIN (search_vector);

-- 4. Create function to update search_vector from multiple text columns
CREATE OR REPLACE FUNCTION public.update_links_search_vector()
RETURNS trigger AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(NEW.author, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(NEW.description, '')), 'C') ||
    setweight(to_tsvector('english', coalesce(NEW.body_text, '')), 'C') ||
    setweight(to_tsvector('english', coalesce(NEW.transcript, '')), 'D');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 5. Create trigger to auto-update search_vector on insert/update
DROP TRIGGER IF EXISTS links_search_vector_update ON public.links;
CREATE TRIGGER links_search_vector_update
  BEFORE INSERT OR UPDATE ON public.links
  FOR EACH ROW
  EXECUTE FUNCTION public.update_links_search_vector();

-- 6. Backfill search_vector for existing rows
UPDATE public.links
SET search_vector =
  setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
  setweight(to_tsvector('english', coalesce(author, '')), 'B') ||
  setweight(to_tsvector('english', coalesce(description, '')), 'C') ||
  setweight(to_tsvector('english', coalesce(body_text, '')), 'C') ||
  setweight(to_tsvector('english', coalesce(transcript, '')), 'D')
WHERE search_vector IS NULL;

-- 7. Hybrid search function: combines vector similarity + full-text search rank
-- Returns results ordered by a blended score of semantic similarity and keyword relevance
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
