-- Add author_filter parameter to match_articles so Postgres applies the filter
-- inside the vector search instead of post-filtering in the edge function.
-- This prevents the top-N cutoff from hiding relevant results by a given author.

DROP FUNCTION IF EXISTS public.match_articles(extensions.vector, float, int, text);

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
    AND 1 - (l.embedding <=> query_embedding) > match_threshold
    AND (content_type_filter IS NULL OR l.content_type = content_type_filter)
    AND (author_filter IS NULL OR l.author ILIKE '%' || author_filter || '%')
  ORDER BY l.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

GRANT EXECUTE ON FUNCTION public.match_articles(extensions.vector, float, int, text, text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.match_articles(extensions.vector, float, int, text, text) TO service_role;
