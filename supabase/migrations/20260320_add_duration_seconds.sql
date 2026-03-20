-- Add duration_seconds to links and backfill from SRT transcript timestamps.
-- Also updates match_articles to include duration_seconds in the return type.
ALTER TABLE public.links ADD COLUMN IF NOT EXISTS duration_seconds integer;

-- Backfill: extract last SRT end-timestamp → video duration in seconds
-- SRT format: HH:MM:SS,mmm --> HH:MM:SS,mmm
UPDATE public.links l
SET duration_seconds = sub.dur
FROM (
  SELECT
    id,
    MAX((m[1])::int * 3600 + (m[2])::int * 60 + (m[3])::int) AS dur
  FROM (
    SELECT id,
           regexp_matches(transcript,
             '\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*(\d{2}):(\d{2}):(\d{2})',
             'g') AS m
    FROM public.links
    WHERE content_type = 'video' AND transcript IS NOT NULL
  ) t
  GROUP BY id
) sub
WHERE l.id = sub.id;

-- Update match_articles to return duration_seconds
DROP FUNCTION IF EXISTS public.match_articles(extensions.vector, float, int, text);

CREATE OR REPLACE FUNCTION public.match_articles(
  query_embedding extensions.vector(1536),
  match_threshold float DEFAULT 0.3,
  match_count int DEFAULT 20,
  content_type_filter text DEFAULT NULL
)
RETURNS TABLE (
  id text,
  slug text,
  title text,
  author text,
  destination_url text,
  published_at timestamptz,
  created_at timestamptz,
  content_type text,
  duration_seconds integer,
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
    l.content_type::text,
    l.duration_seconds,
    (1 - (l.embedding <=> query_embedding))::float AS similarity
  FROM public.links l
  WHERE l.embedding IS NOT NULL
    AND 1 - (l.embedding <=> query_embedding) > match_threshold
    AND (content_type_filter IS NULL OR l.content_type = content_type_filter)
  ORDER BY l.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

GRANT EXECUTE ON FUNCTION public.match_articles(extensions.vector, float, int, text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.match_articles(extensions.vector, float, int, text) TO service_role;
SELECT pg_notify('pgrst', 'reload schema');
