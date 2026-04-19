# Link Shortener with UTM Campaign Attribution

> **⚠️ Historical document.** This was the original planning document for the project. It is preserved for reference but is no longer authoritative — the current architecture is documented in `README.md` and `AGENTS.md`. Some items described here (CLI commands, function names, deployment steps) have been superseded.

## Architecture

**Supabase project:** `dumhbtxskncofwwzrmfx`  
**Domain:** `aicoe.fit`

## Database Schema

### `links` table — one row per short link
- `id` (uuid, PK)
- `slug` (text, unique, indexed) — e.g. `cursor-mar26`
- `destination_url` (text) — e.g. `https://trilogyai.substack.com/p/workshop-cursor-practical`
- `created_at` (timestamptz)

### `tracking_variants` table — UTM parameter sets, tied to a link
- `id` (uuid, PK)
- `link_id` (uuid, FK → links)
- `suffix` (text, unique, indexed) — e.g. `h43` (hash of UTM params)
- `utm_source` (text) — e.g. `linkedin`
- `utm_medium` (text) — e.g. `social`
- `utm_campaign` (text) — e.g. `cursor-mar26`
- `utm_content` (text, nullable)
- `utm_term` (text, nullable)
- `ref` (text, nullable) — e.g. `stephen`
- `created_at` (timestamptz)

### `click_log` table — analytics
- `id` (uuid, PK)
- `link_id` (uuid, FK → links)
- `variant_id` (uuid, FK → tracking_variants, nullable)
- `clicked_at` (timestamptz)
- `ip_hash` (text) — hashed for privacy
- `user_agent` (text)
- `referer` (text)

## Redirect Logic (Supabase Edge Function)

Request comes in → parse path:

1. Try exact match on `links.slug` → 302 redirect to `destination_url`
2. If no match, split on last `-` → try `slug` + `suffix` lookup via join → 302 redirect to `destination_url` + UTM query params appended
3. If still no match → 404

## Suffix Encoding

Hash the sorted UTM param values (source+medium+campaign+content+term+ref) with a short base36 hash. Deterministic — same params always produce the same suffix.

## Admin CLI (Python + uv)

Scripts for:
- `create_link` — create a new short link
- `create_variant` — add a tracking variant to an existing link
- `list_links` — show all links and their variants
- `click_stats` — basic analytics

## Web Admin Panel

Simple HTML/JS page (can be served from Supabase or static hosting) that calls the Supabase API with auth to CRUD links and variants.

## Example Flow

```bash
create_link --slug cursor-mar26 --url https://trilogyai.substack.com/p/workshop-cursor-practical

create_variant --slug cursor-mar26 --ref stephen --utm_source linkedin --utm_medium social
# → suffix: h43
# → full short URL: aicoe.fit/cursor-mar26-h43
# → redirects to: https://trilogyai.substack.com/p/workshop-cursor-practical?ref=stephen&utm_source=linkedin&utm_medium=social
```

## TODO

- [ ] Create/configure Supabase project (reauth needed)
- [ ] Design and apply database schema
- [ ] Build Supabase Edge Function for redirect logic
- [ ] Build CLI admin scripts (Python/uv)
- [ ] Build simple web admin panel
- [ ] Initialize git repo and push
