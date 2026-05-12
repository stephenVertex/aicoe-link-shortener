-- Fix ys-als-8f45: last-articles edge function does a full-table scan with
-- ORDER BY published_at DESC NULLS LAST LIMIT ... OFFSET ... on the links table.
-- With only 309 rows it still averages 193ms per call (22,619ms total over 117 calls).
--
-- There is already an index on published_at DESC NULLS LAST, but the query
-- orders by (published_at, id) and uses OFFSET. A composite index on
-- (published_at DESC NULLS LAST, id) lets the planner satisfy the ORDER BY
-- and LIMIT/OFFSET with an index scan instead of a full sort + scan.

CREATE INDEX IF NOT EXISTS idx_links_published_at_id
  ON public.links (published_at DESC NULLS LAST, id);
