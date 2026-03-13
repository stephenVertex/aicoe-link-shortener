-- Tracks reusable source profiles per person and supports retroactive generation
create table if not exists public.person_sources (
  id uuid primary key default gen_random_uuid(),
  person_id uuid not null references public.people(id) on delete cascade,
  label text not null,
  icon text,
  utm_source text not null,
  utm_medium text not null default 'social',
  utm_content text,
  utm_term text,
  created_at timestamptz not null default now()
);

create unique index if not exists person_sources_unique_profile_idx
  on public.person_sources (
    person_id,
    utm_source,
    utm_medium,
    coalesce(utm_content, ''),
    coalesce(utm_term, '')
  );

alter table public.person_sources enable row level security;

drop policy if exists authenticated_read_own_person_sources on public.person_sources;
create policy authenticated_read_own_person_sources
  on public.person_sources
  for select
  using (
    auth.role() = 'authenticated'
    and exists (
      select 1
      from public.people p
      join auth.users u on u.id = auth.uid()
      where p.id = person_sources.person_id
        and p.email = u.email
    )
  );

drop policy if exists service_role_all_person_sources on public.person_sources;
create policy service_role_all_person_sources
  on public.person_sources
  for all
  using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');

create or replace function public.ensure_tracking_variant(
  p_link_id uuid,
  p_ref text,
  p_source text,
  p_medium text default 'social',
  p_content text default null,
  p_term text default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  campaign text;
  source_norm text;
  medium_norm text;
  content_norm text;
  term_norm text;
  ref_norm text;
  combined text;
  hash_hex text;
  suffix_candidate text;
  suffix_len integer := 6;
  existing_row tracking_variants%rowtype;
  inserted_row tracking_variants%rowtype;
begin
  select slug into campaign from public.links where id = p_link_id;
  if campaign is null then
    raise exception 'Link not found';
  end if;

  ref_norm := lower(trim(coalesce(p_ref, '')));
  if ref_norm = '' then
    raise exception 'Ref is required';
  end if;

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

  select * into existing_row
  from public.tracking_variants
  where link_id = p_link_id
    and ref = ref_norm
    and utm_source = source_norm
    and utm_medium = medium_norm
    and coalesce(utm_content, '') = coalesce(content_norm, '')
    and coalesce(utm_term, '') = coalesce(term_norm, '')
  limit 1;

  if found then
    return to_jsonb(existing_row);
  end if;

  combined := concat_ws('|', source_norm, medium_norm, campaign, coalesce(content_norm, ''), coalesce(term_norm, ''), ref_norm);
  hash_hex := md5(combined);

  loop
    suffix_candidate := substr(hash_hex, 1, suffix_len);
    select * into existing_row from public.tracking_variants where suffix = suffix_candidate limit 1;
    exit when not found;

    if existing_row.link_id = p_link_id
      and existing_row.ref = ref_norm
      and existing_row.utm_source = source_norm
      and existing_row.utm_medium = medium_norm
      and coalesce(existing_row.utm_content, '') = coalesce(content_norm, '')
      and coalesce(existing_row.utm_term, '') = coalesce(term_norm, '') then
      return to_jsonb(existing_row);
    end if;

    suffix_len := suffix_len + 1;
    if suffix_len > 12 then
      raise exception 'Unable to generate unique suffix';
    end if;
  end loop;

  insert into public.tracking_variants (link_id, suffix, utm_source, utm_medium, utm_campaign, utm_content, utm_term, ref)
  values (p_link_id, suffix_candidate, source_norm, medium_norm, campaign, content_norm, term_norm, ref_norm)
  returning * into inserted_row;

  return to_jsonb(inserted_row);
end;
$$;

create or replace function public.create_custom_variant(
  p_link_id uuid,
  p_source text,
  p_medium text default 'social',
  p_content text default null,
  p_term text default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  person_slug text;
begin
  if auth.uid() is null then
    raise exception 'Not authenticated';
  end if;

  person_slug := (public.get_or_create_person() ->> 'slug');
  return public.ensure_tracking_variant(p_link_id, person_slug, p_source, p_medium, p_content, p_term);
end;
$$;

create or replace function public.create_person_source(
  p_label text,
  p_source text,
  p_medium text default 'social',
  p_content text default null,
  p_term text default null,
  p_icon text default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  person_json jsonb;
  v_person_id uuid;
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
  person_json := public.get_or_create_person();
  v_person_id := (person_json ->> 'id')::uuid;
  v_person_slug := lower(trim(person_json ->> 'slug'));

  source_norm := regexp_replace(regexp_replace(lower(trim(coalesce(p_source, ''))), '[^a-z0-9_-]+', '-', 'g'), '(^-+|-+$)', '', 'g');
  medium_norm := regexp_replace(regexp_replace(lower(trim(coalesce(nullif(p_medium, ''), 'social'))), '[^a-z0-9_-]+', '-', 'g'), '(^-+|-+$)', '', 'g');
  content_norm := nullif(regexp_replace(regexp_replace(lower(trim(coalesce(p_content, ''))), '[^a-z0-9_-]+', '-', 'g'), '(^-+|-+$)', '', 'g'), '');
  term_norm := nullif(regexp_replace(regexp_replace(lower(trim(coalesce(p_term, ''))), '[^a-z0-9_-]+', '-', 'g'), '(^-+|-+$)', '', 'g'), '');

  label_norm := trim(coalesce(p_label, ''));
  if label_norm = '' then
    label_norm := case source_norm
      when 'linkedin' then 'LinkedIn'
      when 'x' then 'X'
      when 'youtube' then 'YouTube'
      when 'discord' then 'Discord'
      else initcap(source_norm)
    end;
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

create or replace function public.delete_person_source(p_source_id uuid)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  person_json jsonb;
  v_person_id uuid;
begin
  person_json := public.get_or_create_person();
  v_person_id := (person_json ->> 'id')::uuid;

  delete from public.person_sources
  where id = p_source_id
    and person_id = v_person_id;

  return found;
end;
$$;

insert into public.person_sources (person_id, label, icon, utm_source, utm_medium)
select p.id, v.label, v.icon, v.utm_source, v.utm_medium
from public.people p
cross join (values
  ('LinkedIn', '💼', 'linkedin', 'social'),
  ('X', '⚡', 'x', 'social'),
  ('YouTube', '▶️', 'youtube', 'social'),
  ('Discord', '🎮', 'discord', 'social')
) as v(label, icon, utm_source, utm_medium)
where not exists (
  select 1 from public.person_sources ps
  where ps.person_id = p.id
    and ps.utm_source = v.utm_source
    and ps.utm_medium = v.utm_medium
    and coalesce(ps.utm_content, '') = ''
    and coalesce(ps.utm_term, '') = ''
);

-- Retroactively backfill variants for all existing links and source profiles
DO $$
declare
  link_row public.links%rowtype;
  source_row public.person_sources%rowtype;
  person_slug text;
begin
  for source_row in select * from public.person_sources loop
    select slug into person_slug from public.people where id = source_row.person_id;
    if person_slug is null then continue; end if;
    for link_row in select * from public.links loop
      perform public.ensure_tracking_variant(link_row.id, person_slug, source_row.utm_source, source_row.utm_medium, source_row.utm_content, source_row.utm_term);
    end loop;
  end loop;
end $$;
