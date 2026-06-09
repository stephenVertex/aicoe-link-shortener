-- Security advisor: function_search_path_mutable (lint 0011)
-- Pin search_path on functions that previously resolved objects via the
-- caller's search_path. search_video_chunks needs `extensions` for the
-- vector type/operators (same pattern as hybrid_match_articles).

ALTER FUNCTION public.generate_aifs_short_id(p_url text) SET search_path = public;
ALTER FUNCTION public.generate_aifs_short_id_on_insert() SET search_path = public;
ALTER FUNCTION public.log_error(p_function_name text, p_error_message text, p_context jsonb) SET search_path = public;
ALTER FUNCTION public.slice_srt_transcript(p_srt text, p_start_sec double precision, p_end_sec double precision) SET search_path = public;
ALTER FUNCTION public.update_links_search_vector() SET search_path = public;
ALTER FUNCTION public.search_video_chunks(query_embedding extensions.vector, match_threshold double precision, match_count integer, dedupe_videos boolean) SET search_path = public, extensions;
