-- Create precomputed link_stats table
-- This eliminates N+1 analytics queries by maintaining counters
-- updated by a trigger on click_log insert.
--
-- Feature request: ys-als-1tti

CREATE TABLE IF NOT EXISTS public.link_stats (
  link_id text PRIMARY KEY REFERENCES public.links(id) ON DELETE CASCADE,
  total_clicks int NOT NULL DEFAULT 0,
  by_variant jsonb NOT NULL DEFAULT '[]',
  by_source jsonb NOT NULL DEFAULT '[]',
  by_referrer jsonb NOT NULL DEFAULT '[]',
  by_country jsonb NOT NULL DEFAULT '[]',
  by_person jsonb NOT NULL DEFAULT '[]',
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Enable RLS (analytics reads this; write via trigger only)
ALTER TABLE public.link_stats ENABLE ROW LEVEL SECURITY;

-- Allow service_role to read (edge functions use service_role)
CREATE POLICY "Allow service_role read" ON public.link_stats
  FOR SELECT TO service_role USING (true);

-- ---------------------------------------------------------------------------
-- Function: refresh_link_stats(link_id)
-- Rebuilds all precomputed counters for a single link from click_log.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.refresh_link_stats(p_link_id text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_total int;
  v_by_variant jsonb;
  v_by_source jsonb;
  v_by_referrer jsonb;
  v_by_country jsonb;
  v_by_person jsonb;
BEGIN
  -- total clicks
  SELECT count(*)::int INTO v_total
  FROM public.click_log
  WHERE link_id = p_link_id;

  -- by_variant: label, suffix, utm_source, ref, clicks
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
    GROUP BY cl.variant_id, tv.utm_source, tv.ref, tv.suffix
  ) t;

  -- by_source: source, clicks
  SELECT coalesce(jsonb_agg(row_to_json(t) ORDER BY t.clicks DESC), '[]')
  INTO v_by_source
  FROM (
    SELECT
      coalesce(tv.utm_source, 'direct') AS source,
      count(*)::int AS clicks
    FROM public.click_log cl
    LEFT JOIN public.tracking_variants tv ON tv.id = cl.variant_id
    WHERE cl.link_id = p_link_id
    GROUP BY tv.utm_source
  ) t;

  -- by_referrer: referrer, clicks
  SELECT coalesce(jsonb_agg(row_to_json(t) ORDER BY t.clicks DESC), '[]')
  INTO v_by_referrer
  FROM (
    SELECT
      CASE
        WHEN nullif(trim(referer), '') IS NULL THEN 'direct'
        ELSE split_part(
          replace(replace(trim(referer), 'https://', ''), 'http://', ''),
          '/',
          1
        )
      END AS referrer,
      count(*)::int AS clicks
    FROM public.click_log
    WHERE link_id = p_link_id
    GROUP BY 1
  ) t;

  -- by_country: country, clicks
  SELECT coalesce(jsonb_agg(row_to_json(t) ORDER BY t.clicks DESC), '[]')
  INTO v_by_country
  FROM (
    SELECT
      coalesce(nullif(trim(country_code), ''), 'unknown') AS country,
      count(*)::int AS clicks
    FROM public.click_log
    WHERE link_id = p_link_id
    GROUP BY 1
  ) t;

  -- by_person: ref, name, clicks
  SELECT coalesce(jsonb_agg(row_to_json(t) ORDER BY t.clicks DESC), '[]')
  INTO v_by_person
  FROM (
    SELECT
      coalesce(tv.ref, '') AS ref,
      coalesce(p.name, tv.ref) AS name,
      count(*)::int AS clicks
    FROM public.click_log cl
    LEFT JOIN public.tracking_variants tv ON tv.id = cl.variant_id
    LEFT JOIN public.people p ON p.slug = tv.ref
    WHERE cl.link_id = p_link_id
    GROUP BY tv.ref, p.name
  ) t;

  -- Upsert
  INSERT INTO public.link_stats (
    link_id, total_clicks, by_variant, by_source,
    by_referrer, by_country, by_person, updated_at
  )
  VALUES (
    p_link_id, v_total, v_by_variant, v_by_source,
    v_by_referrer, v_by_country, v_by_person, now()
  )
  ON CONFLICT (link_id) DO UPDATE SET
    total_clicks = EXCLUDED.total_clicks,
    by_variant   = EXCLUDED.by_variant,
    by_source    = EXCLUDED.by_source,
    by_referrer  = EXCLUDED.by_referrer,
    by_country   = EXCLUDED.by_country,
    by_person    = EXCLUDED.by_person,
    updated_at   = EXCLUDED.updated_at;
END;
$$;

-- ---------------------------------------------------------------------------
-- Trigger: rebuild stats on every click_log insert
-- Click volume is low (~3,600 total), so per-insert rebuild is fine.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.trigger_refresh_link_stats()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  PERFORM public.refresh_link_stats(NEW.link_id);
  RETURN NEW;
END;
$$;

-- Drop existing trigger if present (idempotent)
DROP TRIGGER IF EXISTS click_log_update_stats ON public.click_log;

CREATE TRIGGER click_log_update_stats
  AFTER INSERT ON public.click_log
  FOR EACH ROW
  EXECUTE FUNCTION public.trigger_refresh_link_stats();

-- ---------------------------------------------------------------------------
-- Backfill: populate link_stats for every link that has clicks
-- ---------------------------------------------------------------------------

DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN SELECT id FROM public.links LOOP
    PERFORM public.refresh_link_stats(r.id);
  END LOOP;
END $$;
