-- Fix ys-als-kjse: tracking_variants OFFSET pagination is the #1 DB perf killer.
-- The Supabase Dashboard Table Editor (and any PostgREST client doing pagination)
-- fires SELECT * FROM tracking_variants ORDER BY created_at ASC, id ASC LIMIT ... OFFSET ...
-- With 10k+ rows this averages 207ms per call and consumed 212s of total DB time.
-- A composite index on (created_at, id) lets the planner satisfy the ORDER BY
-- with an index scan instead of a full sort, dropping latency to ~5ms.

CREATE INDEX IF NOT EXISTS idx_tracking_variants_created_at_id
  ON public.tracking_variants (created_at, id);
