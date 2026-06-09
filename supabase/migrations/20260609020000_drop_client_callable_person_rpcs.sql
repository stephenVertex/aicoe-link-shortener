-- Security advisor lints 0028/0029, step 3 (final): the admin pages now call
-- these through the admin-rpc edge function, so the old auth.uid()-based
-- signatures go away and get_click_analytics becomes service_role-only.

drop function if exists public.get_or_create_person();
drop function if exists public.create_person_source(p_label text, p_source text, p_medium text, p_content text, p_term text, p_icon text);
drop function if exists public.delete_person_source(p_source_id text);

revoke execute on function public.get_click_analytics(p_interval text, p_link_id text, p_variant_id text, p_start_date timestamp with time zone, p_end_date timestamp with time zone, p_ref text) from public, anon, authenticated;
grant execute on function public.get_click_analytics(p_interval text, p_link_id text, p_variant_id text, p_start_date timestamp with time zone, p_end_date timestamp with time zone, p_ref text) to service_role;
