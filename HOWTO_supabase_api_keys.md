# HOWTO: als API Key Authentication System

This document explains how the `als` API key authentication system works end-to-end.
It is written for coding agents so they can understand the pattern and replicate it
in new edge functions.

---

## Overview

The `als` (aicoe.fit link shortener) system uses a simple, custom API key scheme:

1. Each person in the `people` table has an `api_key` column (format: `als_<48-hex-chars>`).
2. Edge functions accept the key via the `x-api-key` HTTP header (or fallback `api_key` query/body param).
3. The key is validated by calling the `validate_api_key` Postgres RPC, which returns the
   person's identity or `null` on failure.
4. The CLI stores the key in `~/.als.credentials` (INI format, mode `0600`) and attaches it
   to every request.

This is **not** Supabase Auth (JWTs). It is a separate bespoke layer that allows programmatic
access without an OAuth session.

---

## 1. How API Keys Are Generated and Stored

### Database Column

The `api_key` column lives on the `people` table:

```sql
-- Migration: 20260317_api_keys.sql
ALTER TABLE people ADD COLUMN api_key text UNIQUE;
CREATE INDEX idx_people_api_key ON people (api_key) WHERE api_key IS NOT NULL;
```

The column has a `DEFAULT` that auto-generates a key for new rows:

```sql
-- Migration: 20260317_populate_api_keys.sql
ALTER TABLE public.people
  ALTER COLUMN api_key SET DEFAULT 'als_' || encode(gen_random_bytes(24), 'hex');
```

Existing rows were back-filled at migration time:

```sql
UPDATE public.people
SET api_key = 'als_' || encode(gen_random_bytes(24), 'hex')
WHERE api_key IS NULL;
```

**Key format:** `als_` prefix + 48 lowercase hex characters (= 24 random bytes).
Example: `als_a1b2c3d4e5f6...` (52 chars total).

### Viewing Your Key

The admin dashboard (`admin-site/index.html`) has a "My API Key" page (`#/api-key`).
It fetches the key directly from Supabase using the user's authenticated session:

```js
// admin-site/index.html (renderApiKeyPage)
const { data } = await sb.from('people').select('api_key').eq('id', currentPerson.id).single();
const apiKey = data?.api_key || '';
```

RLS is irrelevant here because the admin site uses the anon key + a real Google OAuth
session. The `api_key` column is readable by authenticated users for their own row
(standard Supabase RLS behaviour with `auth.uid()` matching).

---

## 2. How Edge Functions Validate the Key

### The `validate_api_key` Postgres RPC

All protected edge functions call this stored procedure:

```sql
-- From information_schema.routines (public.validate_api_key)
DECLARE
  person_row people%ROWTYPE;
BEGIN
  IF p_api_key IS NULL OR p_api_key = '' THEN
    RETURN NULL;
  END IF;

  SELECT * INTO person_row
  FROM public.people
  WHERE api_key = p_api_key;

  IF NOT FOUND THEN
    RETURN NULL;
  END IF;

  RETURN jsonb_build_object(
    'id', person_row.id,
    'name', person_row.name,
    'slug', person_row.slug,
    'email', person_row.email
  );
END;
```

On success it returns a JSONB object with `id`, `name`, `slug`, `email`.
On failure (empty key or no match) it returns `NULL`.

The fast lookup is backed by `idx_people_api_key` (partial index on non-null values).

### TypeScript Helper Pattern

Both `get-link` and `shorten-url` use the same helper:

```typescript
// supabase/functions/get-link/index.ts and shorten-url/index.ts
interface PersonInfo {
  id: string;
  name: string;
  slug: string;
  email: string;
}

async function validateApiKey(apiKey: string): Promise<PersonInfo | null> {
  const { data, error } = await supabase.rpc("validate_api_key", {
    p_api_key: apiKey,
  });
  if (error || !data) return null;
  return data as PersonInfo;
}
```

The Supabase client in edge functions uses `SUPABASE_SERVICE_ROLE_KEY` (bypasses RLS):

```typescript
const supabase = createClient(
  Deno.env.get("SUPABASE_URL") ?? "",
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
);
```

### Key Extraction from Requests

Edge functions accept the key from multiple places (header preferred):

```typescript
// Extract from header first, then fall back to body/query param
let apiKey = req.headers.get("x-api-key") || "";

if (req.method === "POST") {
  const body = await req.json();
  apiKey = apiKey || body.api_key || "";
} else {
  const url = new URL(req.url);
  apiKey = apiKey || url.searchParams.get("api_key") || "";
}
```

CORS headers must include `x-api-key` in `Access-Control-Allow-Headers`:

```typescript
const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type, x-api-key",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};
```

### Error Responses

```typescript
// Missing key → 401
if (!apiKey) {
  return new Response(
    JSON.stringify({ error: "API key required. Pass via x-api-key header or api_key parameter." }),
    { status: 401, headers: { "Content-Type": "application/json", ...corsHeaders } },
  );
}

// Invalid key → 401
const person = await validateApiKey(apiKey);
if (!person) {
  return new Response(
    JSON.stringify({ error: "Invalid API key" }),
    { status: 401, headers: { "Content-Type": "application/json", ...corsHeaders } },
  );
}
```

---

## 3. How the CLI Stores and Sends the Key

### Credentials File

The `als` CLI (`user-cli/als.py`) stores credentials at `~/.als.credentials` in INI format:

```ini
[default]
api_key = als_a1b2c3d4e5f6...
```

File is written with mode `0600` (owner-read-only):

```python
# user-cli/als.py
CREDENTIALS_FILE = Path.home() / ".als.credentials"

def _write_credentials(api_key: str) -> None:
    config = configparser.ConfigParser()
    config["default"] = {"api_key": api_key}
    CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CREDENTIALS_FILE, "w") as f:
        config.write(f)
    os.chmod(CREDENTIALS_FILE, 0o600)

def _read_credentials() -> dict[str, str]:
    if not CREDENTIALS_FILE.exists():
        return {}
    config = configparser.ConfigParser()
    config.read(CREDENTIALS_FILE)
    if "default" not in config:
        return {}
    return dict(config["default"])
```

### Sending the Key in Requests

Every authenticated request attaches the key as `x-api-key`:

```python
# user-cli/als.py
API_BASE = "https://dumhbtxskncofwwzrmfx.supabase.co/functions/v1"

def _api_request(function, *, method="POST", api_key=None, json_body=None, params=None):
    if api_key is None:
        api_key = _get_api_key()   # reads from ~/.als.credentials
    url = f"{API_BASE}/{function}"
    headers = {"x-api-key": api_key}
    if method == "POST":
        resp = requests.post(url, json=json_body or {}, headers=headers, timeout=30)
    else:
        resp = requests.get(url, params=params or {}, headers=headers, timeout=30)
    return resp
```

### Login Command

```bash
als login --api-key als_abc123xyz
```

The `login` command validates the key by calling `get-link` with no article URL and
checking that it returns 400 (missing article) rather than 401 (invalid key):

```python
@cli.command()
@click.option("--api-key", required=True, help="Your personal API key (als_...)")
def login(api_key: str):
    resp = _api_request("get-link", api_key=api_key, json_body={})
    if resp.status_code == 401:
        click.echo("Invalid API key.", err=True)
        sys.exit(1)
    _write_credentials(api_key)
    click.echo(f"Logged in. Credentials saved to {CREDENTIALS_FILE}")
```

---

## 4. How to Add Auth to a New Edge Function

Copy this pattern into your new `supabase/functions/<name>/index.ts`:

```typescript
import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL") ?? "",
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
);

interface PersonInfo {
  id: string;
  name: string;
  slug: string;
  email: string;
}

async function validateApiKey(apiKey: string): Promise<PersonInfo | null> {
  const { data, error } = await supabase.rpc("validate_api_key", {
    p_api_key: apiKey,
  });
  if (error || !data) return null;
  return data as PersonInfo;
}

Deno.serve(async (req) => {
  const corsHeaders = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers":
      "authorization, x-client-info, apikey, content-type, x-api-key",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  };

  // Handle CORS preflight
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders });
  }

  // Extract API key
  let apiKey = req.headers.get("x-api-key") || "";
  // ... also extract from body/query as needed

  // Validate
  if (!apiKey) {
    return new Response(
      JSON.stringify({ error: "API key required. Pass via x-api-key header or api_key parameter." }),
      { status: 401, headers: { "Content-Type": "application/json", ...corsHeaders } },
    );
  }

  const person = await validateApiKey(apiKey);
  if (!person) {
    return new Response(
      JSON.stringify({ error: "Invalid API key" }),
      { status: 401, headers: { "Content-Type": "application/json", ...corsHeaders } },
    );
  }

  // person.id, person.name, person.slug, person.email are now available
  // ... your function logic here ...

  return new Response(
    JSON.stringify({ ok: true, person }),
    { headers: { "Content-Type": "application/json", ...corsHeaders } },
  );
});
```

**Key points:**
- Use `SUPABASE_SERVICE_ROLE_KEY` (not anon key) so the function can bypass RLS for lookups.
- Always handle OPTIONS preflight with a 204.
- Include `x-api-key` in `Access-Control-Allow-Headers`.
- Return 401 (not 403) for both missing and invalid keys — the CLI checks for 401.
- The `person` object gives you `slug` which is used as the `ref` in tracking variants.

### Deploy the Function

Edge functions are **auto-deployed by CI** when changes land on `main`. See
`.github/workflows/deploy-edge-functions.yml` for details. Do not deploy
manually unless it is an emergency hotfix.

```bash
# CI auto-deploys on push to main — no manual step needed
# Emergency hotfix only:
supabase functions deploy <name>
```

---

## 5. RLS Policies Involved

The API key mechanism bypasses Supabase RLS entirely because edge functions use the
**service role key**, which has superuser access. RLS policies on `people`,
`person_sources`, `links`, and `tracking_variants` do **not** apply inside edge functions.

RLS is only relevant for the **admin dashboard** (`admin-site/index.html`), which
uses the anon key + a real OAuth session. Relevant policies:

### `people` table

```sql
-- Authenticated users can update their own row
create policy authenticated_update_own_people
  on public.people for update
  using (
    auth.role() = 'authenticated'
    and email = coalesce(auth.jwt() ->> 'email', '')
  );
```

### `person_sources` table

```sql
-- Authenticated users can read their own sources
create policy authenticated_read_own_person_sources
  on public.person_sources for select
  using (
    auth.role() = 'authenticated'
    and exists (
      select 1 from public.people p
      where p.id = person_sources.person_id
        and p.email = coalesce(auth.jwt() ->> 'email', '')
    )
  );

-- Service role has full access (used by edge functions)
create policy service_role_all_person_sources
  on public.person_sources for all
  using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');
```

The `api_key` column itself has no dedicated RLS policy — it is protected by the
row-level policies on `people`. An authenticated user can read their own row (including
`api_key`) because the admin site does a `.select('api_key').eq('id', currentPerson.id)`
and the authenticated user's JWT matches their own person row via `get_or_create_person`.

---

## Quick Reference

| Component | Location | Role |
|-----------|----------|------|
| `api_key` column | `public.people` table | Stores the key; auto-generated on insert |
| `idx_people_api_key` | Postgres index | Fast lookup by key value |
| `validate_api_key(p_api_key)` | Postgres RPC | Returns person info or NULL |
| `x-api-key` header | HTTP requests | How the key is transmitted |
| `~/.als.credentials` | User's machine | Where the CLI persists the key |
| `als login --api-key <key>` | CLI command | Writes the credentials file |
| `_api_request()` | `user-cli/als.py` | Attaches key to all outbound requests |
| `validateApiKey()` | Edge functions | TypeScript wrapper around the RPC |
