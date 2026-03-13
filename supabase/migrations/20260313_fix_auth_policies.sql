drop policy if exists authenticated_read_own_person_sources on public.person_sources;
create policy authenticated_read_own_person_sources
  on public.person_sources
  for select
  using (
    auth.role() = 'authenticated'
    and exists (
      select 1
      from public.people p
      where p.id = person_sources.person_id
        and p.email = coalesce(auth.jwt() ->> 'email', '')
    )
  );

drop policy if exists authenticated_update_own_people on public.people;
create policy authenticated_update_own_people
  on public.people
  for update
  using (
    auth.role() = 'authenticated'
    and email = coalesce(auth.jwt() ->> 'email', '')
  );
