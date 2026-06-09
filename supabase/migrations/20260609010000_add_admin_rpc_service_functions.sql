-- Security advisor lints 0028/0029: stop exposing person/analytics RPCs to
-- anon/authenticated via PostgREST. These new variants take an explicit
-- p_email (verified by the admin-rpc edge function from the caller's Supabase
-- Auth JWT) instead of reading auth.uid(), and are executable only by
-- service_role. The old auth.uid()-based signatures coexist until the admin
-- pages switch to admin-rpc, then get dropped in a follow-up migration.

create or replace function public.get_or_create_person(p_email text, p_name text default null)
returns json
language plpgsql
security definer
set search_path = public
as $$
declare
  user_email text := trim(coalesce(p_email, ''));
  user_name text;
  user_slug text;
  person_record json;
begin
  if user_email = '' then
    raise exception 'Email is required';
  end if;

  user_name := coalesce(nullif(trim(coalesce(p_name, '')), ''), split_part(user_email, '@', 1));

  -- Try to find existing person by email
  select row_to_json(p) into person_record
  from public.people p
  where p.email = user_email;

  if person_record is not null then
    return person_record;
  end if;

  -- Try to find existing person by slug (pre-seeded without email)
  user_slug := lower(replace(split_part(user_email, '@', 1), '.', '-'));

  select row_to_json(p) into person_record
  from public.people p
  where p.slug = user_slug;

  if person_record is not null then
    update public.people set email = user_email where slug = user_slug;
    select row_to_json(p) into person_record
    from public.people p
    where p.slug = user_slug;
    return person_record;
  end if;

  -- Auto-create new person
  insert into public.people (name, slug, email)
  values (user_name, user_slug, user_email)
  returning row_to_json(people) into person_record;

  return person_record;
end;
$$;

create or replace function public.create_person_source(p_email text, p_label text, p_source text, p_medium text default 'social', p_content text default null, p_term text default null, p_icon text default null)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  person_json jsonb;
  v_person_id text;
  v_person_slug text;
  source_norm text;
  medium_norm text;
  content_norm text;
  term_norm text;
  label_norm text;
  icon_norm text;
  source_row person_sources%rowtype;
  link_row links%rowtype;
  generated_count integer := 0;
begin
  person_json := public.get_or_create_person(p_email);
  v_person_id := (person_json ->> 'id');
  v_person_slug := lower(trim(person_json ->> 'slug'));

  source_norm := lower(trim(coalesce(p_source, '')));
  source_norm := regexp_replace(source_norm, '[^a-z0-9_-]+', '-', 'g');
  source_norm := regexp_replace(source_norm, '(^-+|-+$)', '', 'g');
  if source_norm = '' then
    raise exception 'Source is required';
  end if;

  medium_norm := lower(trim(coalesce(nullif(p_medium, ''), 'social')));
  medium_norm := regexp_replace(medium_norm, '[^a-z0-9_-]+', '-', 'g');
  medium_norm := regexp_replace(medium_norm, '(^-+|-+$)', '', 'g');
  if medium_norm = '' then medium_norm := 'social'; end if;

  content_norm := nullif(lower(trim(coalesce(p_content, ''))), '');
  if content_norm is not null then
    content_norm := regexp_replace(content_norm, '[^a-z0-9_-]+', '-', 'g');
    content_norm := regexp_replace(content_norm, '(^-+|-+$)', '', 'g');
    content_norm := nullif(content_norm, '');
  end if;

  term_norm := nullif(lower(trim(coalesce(p_term, ''))), '');
  if term_norm is not null then
    term_norm := regexp_replace(term_norm, '[^a-z0-9_-]+', '-', 'g');
    term_norm := regexp_replace(term_norm, '(^-+|-+$)', '', 'g');
    term_norm := nullif(term_norm, '');
  end if;

  label_norm := trim(coalesce(p_label, ''));
  if label_norm = '' then
    label_norm := initcap(source_norm);
    if content_norm is not null then
      label_norm := label_norm || ' - ' || replace(content_norm, '-', ' ');
    end if;
  end if;

  icon_norm := nullif(trim(coalesce(p_icon, '')), '');
  if icon_norm is null then
    icon_norm := case
      when source_norm = 'linkedin' then '💼'
      when source_norm in ('x', 'twitter') then '⚡'
      when source_norm = 'youtube' then '▶️'
      when source_norm = 'discord' then '🎮'
      when source_norm = 'whatsapp' then '💬'
      when source_norm = 'slack' then '⚙️'
      when source_norm = 'email' then '✉️'
      else '🔗'
    end;
  end if;

  select * into source_row
  from public.person_sources ps
  where ps.person_id = v_person_id
    and ps.utm_source = source_norm
    and ps.utm_medium = medium_norm
    and coalesce(ps.utm_content, '') = coalesce(content_norm, '')
    and coalesce(ps.utm_term, '') = coalesce(term_norm, '')
  limit 1;

  if not found then
    insert into public.person_sources (person_id, label, icon, utm_source, utm_medium, utm_content, utm_term)
    values (v_person_id, label_norm, icon_norm, source_norm, medium_norm, content_norm, term_norm)
    returning * into source_row;
  else
    update public.person_sources
    set label = label_norm,
        icon = icon_norm
    where id = source_row.id
    returning * into source_row;
  end if;

  for link_row in select * from public.links loop
    perform public.ensure_tracking_variant(link_row.id, v_person_slug, source_row.utm_source, source_row.utm_medium, source_row.utm_content, source_row.utm_term);
    generated_count := generated_count + 1;
  end loop;

  return to_jsonb(source_row) || jsonb_build_object('generated_links', generated_count);
end;
$$;

create or replace function public.delete_person_source(p_email text, p_source_id text)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  person_json jsonb;
  v_person_id text;
begin
  person_json := public.get_or_create_person(p_email);
  v_person_id := (person_json ->> 'id');

  delete from public.person_sources ps
  where ps.id = p_source_id
    and ps.person_id = v_person_id;

  return found;
end;
$$;

-- service_role only: these carry caller identity as a parameter, so they must
-- never be reachable with client keys.
revoke execute on function public.get_or_create_person(p_email text, p_name text) from public, anon, authenticated;
revoke execute on function public.create_person_source(p_email text, p_label text, p_source text, p_medium text, p_content text, p_term text, p_icon text) from public, anon, authenticated;
revoke execute on function public.delete_person_source(p_email text, p_source_id text) from public, anon, authenticated;
grant execute on function public.get_or_create_person(p_email text, p_name text) to service_role;
grant execute on function public.create_person_source(p_email text, p_label text, p_source text, p_medium text, p_content text, p_term text, p_icon text) to service_role;
grant execute on function public.delete_person_source(p_email text, p_source_id text) to service_role;
