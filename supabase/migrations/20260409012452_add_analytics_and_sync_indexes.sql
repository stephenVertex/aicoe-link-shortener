-- Performance indexes for analytics and sync operations
-- Based on query patterns across edge functions, RPC functions, and CLI code

-- click_log: composite index for per-link click analytics with time ordering
CREATE INDEX IF NOT EXISTS idx_click_log_link_id_clicked_at
  ON public.click_log (link_id, clicked_at DESC);

-- click_log: partial index for variant lookups (variant_id is nullable)
CREATE INDEX IF NOT EXISTS idx_click_log_variant_id
  ON public.click_log (variant_id)
  WHERE variant_id IS NOT NULL;

-- tracking_variants: FK lookup from links
CREATE INDEX IF NOT EXISTS idx_tracking_variants_link_id
  ON public.tracking_variants (link_id);

-- tracking_variants: partial index for context lookups (context_id is nullable)
CREATE INDEX IF NOT EXISTS idx_tracking_variants_context_id
  ON public.tracking_variants (context_id)
  WHERE context_id IS NOT NULL;

-- links: destination URL lookups (dedup checks, reverse lookups)
CREATE INDEX IF NOT EXISTS idx_links_destination_url
  ON public.links (destination_url);

-- links: published articles listing sorted by date
CREATE INDEX IF NOT EXISTS idx_links_published_at
  ON public.links (published_at DESC NULLS LAST);

-- sync_operations: latest sync per source
CREATE INDEX IF NOT EXISTS idx_sync_operations_source_started_at
  ON public.sync_operations (source, started_at DESC);

-- sync_operations: status filtering (running/error/success)
CREATE INDEX IF NOT EXISTS idx_sync_operations_status
  ON public.sync_operations (status);
