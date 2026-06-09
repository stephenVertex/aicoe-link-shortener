-- Security advisor: anon/authenticated_security_definer_function_executable
-- (lints 0028/0029)
-- These SECURITY DEFINER functions are only called server-side (edge
-- functions / CLI with the service role key) or are unused, yet were
-- executable by anon and authenticated via /rest/v1/rpc/*. Most notably
-- validate_api_key was an unauthenticated API-key oracle.
--
-- Intentionally still anon-executable (called from admin-site browser code
-- with the anon key): create_person_source, delete_person_source,
-- get_click_analytics, get_or_create_person.

REVOKE EXECUTE ON FUNCTION public.create_custom_variant(p_link_id text, p_source text, p_medium text, p_content text, p_term text) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.ensure_tracking_variant(p_link_id text, p_ref text, p_source text, p_medium text, p_content text, p_term text) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.hybrid_match_articles(query_embedding extensions.vector, query_text text, match_threshold double precision, match_count integer, content_type_filter text, author_filter text, vector_weight double precision, keyword_weight double precision) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.match_articles(query_embedding extensions.vector, match_threshold double precision, match_count integer, content_type_filter text, author_filter text) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.log_error(p_function_name text, p_error_message text, p_context jsonb) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.refresh_link_daily_clicks(p_link_id text, p_date date) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.refresh_link_stats(p_link_id text) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.trigger_refresh_link_stats() FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.trigger_refresh_link_stats_and_daily() FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.validate_api_key(p_api_key text) FROM PUBLIC, anon, authenticated;

-- Ensure server-side callers keep access after the PUBLIC revoke.
GRANT EXECUTE ON FUNCTION public.create_custom_variant(p_link_id text, p_source text, p_medium text, p_content text, p_term text) TO service_role;
GRANT EXECUTE ON FUNCTION public.ensure_tracking_variant(p_link_id text, p_ref text, p_source text, p_medium text, p_content text, p_term text) TO service_role;
GRANT EXECUTE ON FUNCTION public.hybrid_match_articles(query_embedding extensions.vector, query_text text, match_threshold double precision, match_count integer, content_type_filter text, author_filter text, vector_weight double precision, keyword_weight double precision) TO service_role;
GRANT EXECUTE ON FUNCTION public.match_articles(query_embedding extensions.vector, match_threshold double precision, match_count integer, content_type_filter text, author_filter text) TO service_role;
GRANT EXECUTE ON FUNCTION public.log_error(p_function_name text, p_error_message text, p_context jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.refresh_link_daily_clicks(p_link_id text, p_date date) TO service_role;
GRANT EXECUTE ON FUNCTION public.refresh_link_stats(p_link_id text) TO service_role;
GRANT EXECUTE ON FUNCTION public.trigger_refresh_link_stats() TO service_role;
GRANT EXECUTE ON FUNCTION public.trigger_refresh_link_stats_and_daily() TO service_role;
GRANT EXECUTE ON FUNCTION public.validate_api_key(p_api_key text) TO service_role;
