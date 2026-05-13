-- Precomputed daily click rollup: replaces get_click_analytics(day) CTE
-- with an indexed range scan on link_daily_clicks(link_id, date).
--
-- Feature request: ys-als-o46q

CREATE TABLE IF NOT EXISTS public.link_daily_clicks (
  link_id text NOT NULL REFERENCES public.links(id) ON DELETE CASCADE,
  date date NOT NULL,
  clicks int NOT NULL DEFAULT 0,
  by_variant jsonb NOT NULL DEFAULT '[]',
  by_source jsonb NOT NULL DEFAULT '[]',
  PRIMARY KEY (link_id, date)
);

-- Index for fast range scans
CREATE INDEX IF NOT EXISTS idx_link_daily_clicks_date
  ON public.link_daily_clicks (link_id, date DESC);

-- Enable RLS
ALTER TABLE public.link_daily_clicks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow service_role read" ON public.link_daily_clicks
  FOR SELECT TO service_role USING (true);

-- ---------------------------------------------------------------------------
-- Function: refresh_link_daily_clicks(link_id, date)
-- Rebuilds the precomputed row for a single (link_id, date) from click_log.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.refresh_link_daily_clicks(
  p_link_id text,
  p_date date
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_clicks int;
  v_by_variant jsonb;
  v_by_source jsonb;
BEGIN
  -- Aggregate today's clicks from click_log
  SELECT count(*)::int INTO v_clicks
  FROM public.click_log
  WHERE link_id = p_link_id
    AND date_trunc('day', clicked_at)::date = p_date;

  -- Build variant breakdown for the day
  SELECT coalesce(jsonb_agg(row_to_json(t) ORDER BY t.clicks DESC), '[]')
  INTO v_by_variant
  FROM (
    SELECT
      CASE
        WHEN cl.variant_id IS NULL THEN 'direct (no variant)'
        ELSE coalesce(tv.utm_source, 'unknown') || ' (ref=' || coalesce(tv.ref, 'unknown') || ')'
      END AS label,
      coalesce(tv.suffix, '') AS suffix,
      coalesce(tv.utm_source, 'direct') AS utm_source,
      coalesce(tv.ref, '') AS ref,
      count(*)::int AS clicks
    FROM public.click_log cl
    LEFT JOIN public.tracking_variants tv ON tv.id = cl.variant_id
    WHERE cl.link_id = p_link_id
      AND date_trunc('day', cl.clicked_at)::date = p_date
    GROUP BY cl.variant_id, tv.utm_source, tv.ref, tv.suffix
  ) t;

  -- Build source breakdown for the day
  SELECT coalesce(jsonb_agg(row_to_json(s) ORDER BY s.clicks DESC), '[]')
  INTO v_by_source
  FROM (
    SELECT
      coalesce(tv.utm_source, 'direct') AS source,
      count(*)::int AS clicks
    FROM public.click_log cl
    LEFT JOIN public.tracking_variants tv ON tv.id = cl.variant_id
    WHERE cl.link_id = p_link_id
      AND date_trunc('day', cl.clicked_at)::date = p_date
    GROUP BY tv.utm_source
  ) s;

  -- Upsert the daily row
  INSERT INTO public.link_daily_clicks (
    link_id, date, clicks, by_variant, by_source
  )
  VALUES (
    p_link_id, p_date, v_clicks, v_by_variant, v_by_source
  )
  ON CONFLICT (link_id, date) DO UPDATE SET
    clicks     = EXCLUDED.clicks,
    by_variant = EXCLUDED.by_variant,
    by_source  = EXCLUDED.by_source;
END;
$$;

-- ---------------------------------------------------------------------------
-- Replace the existing trigger so it refreshes BOTH link_stats (all-time)
-- and link_daily_clicks (just the affected date) in one pass.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.trigger_refresh_link_stats_and_daily()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_date date;
BEGIN
  v_date := date_trunc('day', NEW.clicked_at)::date;

  -- Refresh all-time counters
  PERFORM public.refresh_link_stats(NEW.link_id);

  -- Refresh just the affected date
  PERFORM public.refresh_link_daily_clicks(NEW.link_id, v_date);

  RETURN NEW;
END;
$$;

-- Swap the trigger
DROP TRIGGER IF EXISTS click_log_update_stats ON public.click_log;

CREATE TRIGGER click_log_update_stats
  AFTER INSERT ON public.click_log
  FOR EACH ROW
  EXECUTE FUNCTION public.trigger_refresh_link_stats_and_daily();

-- ---------------------------------------------------------------------------
-- Backfill: populate link_daily_clicks for all dates that have clicks
-- ---------------------------------------------------------------------------

DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT DISTINCT link_id, date_trunc('day', clicked_at)::date AS d
    FROM public.click_log
    ORDER BY link_id, d
  LOOP
    PERFORM public.refresh_link_daily_clicks(r.link_id, r.d);
  END LOOP;
END $$;
