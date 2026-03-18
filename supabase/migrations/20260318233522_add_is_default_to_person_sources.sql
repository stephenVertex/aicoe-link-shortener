-- Add is_default flag to person_sources to mark system/default channels
-- Default channels (Discord, LinkedIn, X, YouTube) are protected from deletion
ALTER TABLE public.person_sources
  ADD COLUMN IF NOT EXISTS is_default boolean NOT NULL DEFAULT false;

-- Mark the standard channels as default (simple sources with no content/term targeting)
UPDATE public.person_sources
SET is_default = true
WHERE utm_source IN ('discord', 'linkedin', 'x', 'youtube')
  AND utm_content IS NULL
  AND utm_term IS NULL;
