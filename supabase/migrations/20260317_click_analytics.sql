-- Click analytics: time-series aggregation function for click_log
CREATE OR REPLACE FUNCTION get_click_analytics(
  p_interval text,
  p_link_id uuid DEFAULT NULL,
  p_variant_id uuid DEFAULT NULL,
  p_start_date timestamptz DEFAULT NULL,
  p_end_date timestamptz DEFAULT NULL
)
RETURNS TABLE(period timestamptz, clicks bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  RETURN QUERY
    SELECT
      date_trunc(p_interval, cl.clicked_at) AS period,
      count(*)::bigint AS clicks
    FROM click_log cl
    WHERE (p_link_id IS NULL OR cl.link_id = p_link_id)
      AND (p_variant_id IS NULL OR cl.variant_id = p_variant_id)
      AND (p_start_date IS NULL OR cl.clicked_at >= p_start_date)
      AND (p_end_date IS NULL OR cl.clicked_at < p_end_date)
    GROUP BY date_trunc(p_interval, cl.clicked_at)
    ORDER BY period;
END;
$$;
