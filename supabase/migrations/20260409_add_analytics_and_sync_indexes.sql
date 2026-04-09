-- Indexes for analytics queries (click_log)
-- link_id is used in 7+ analytics queries; composite with clicked_at covers both
-- link_id-only lookups and link_id + time-range filters
CREATE INDEX idx_click_log_link_id_clicked_at ON public.click_log (link_id, clicked_at DESC);

-- variant_id used in manage-contexts click counting and RPC analytics
CREATE INDEX idx_click_log_variant_id ON public.click_log (variant_id) WHERE variant_id IS NOT NULL;

-- Indexes for analytics queries (tracking_variants)
-- link_id used in 6+ queries for counting/fetching variants per link and batch resolution
CREATE INDEX idx_tracking_variants_link_id ON public.tracking_variants (link_id);

-- context_id used in manage-contexts for fetching variants by context
CREATE INDEX idx_tracking_variants_context_id ON public.tracking_variants (context_id) WHERE context_id IS NOT NULL;

-- Indexes for links table analytics and sync queries
-- destination_url used in 6+ URL lookup queries (currently seq scans)
CREATE INDEX idx_links_destination_url ON public.links (destination_url);

-- published_at DESC NULLS LAST used for article ordering in last-articles, embed, chunk
CREATE INDEX idx_links_published_at ON public.links (published_at DESC NULLS LAST);

-- Indexes for sync_operations table
-- Composite source + started_at for "most recent sync by source" pattern and source-only filtering
CREATE INDEX idx_sync_operations_source_started_at ON public.sync_operations (source, started_at DESC);

-- status filtering for finding running/failed syncs
CREATE INDEX idx_sync_operations_status ON public.sync_operations (status);
