# aicoe.fit - Link Shortener with UTM Campaign Attribution

A link shortener for the Trilogy AI Center of Excellence. Tracks clicks across all content we share:

- **Trilogy AI CoE Substack** ([trilogyai.substack.com](https://trilogyai.substack.com)) — auto-imported every 6 hours
- **YouTube channel** — any video link can be shortened and tracked
- **Any URL** — team members can shorten any link they want to share and track

Every link gets per-person tracking variants with UTM parameters so you can see who drove which clicks. All `aicoe.fit` short links are **clean** — no UTM clutter in the URL you share. Parameters are appended transparently on redirect.

**Live:** [https://admin.aicoe.fit](https://admin.aicoe.fit)
**Short links:** `https://aicoe.fit/<slug>` (e.g. `https://aicoe.fit/workshop-cursor-practical-d7sc`)

## Architecture

```
                    +-----------------+
  aicoe.fit/<slug>  | Cloudflare      |  302 redirect
  ----------------->| Worker          |---------------> destination + UTM params
                    | (redirect only) |
                    +--------+--------+
                             |
                             v
                    +-----------------+
                    | Supabase Edge   |  slug/suffix lookup
                    | Function        |  click logging
                    | (redirect)      |
                    +--------+--------+
                             |
                             v
                    +-----------------+
                    | Supabase        |  links, tracking_variants,
                    | PostgreSQL      |  click_log, people
                    +-----------------+

  admin.aicoe.fit   +-----------------+
  ----------------->| AWS Amplify     |  static site
                    | (admin panel)   |  Google OAuth via Supabase Auth
                    +-----------------+
```

### Components

| Component | Tech | Purpose |
|-----------|------|---------|
| **Redirect proxy** | Cloudflare Worker on `aicoe.fit` | Intercepts short link requests, proxies to Supabase edge function |
| **Redirect logic** | Supabase Edge Function (`redirect`) | Resolves slug/suffix, appends UTM params, logs clicks, returns 302 |
| **Content sync** | Supabase Edge Function (`content-sync`) | Consolidated sync: Substack, YouTube, embeddings, chunking (runs every 6h via pg_cron with action parameter) |
| **Admin dashboard** | Static HTML on AWS Amplify (`admin.aicoe.fit`) | Google sign-in, view links/clicks, copy tracking URLs |
| **User CLI** | Python (click, uv) — `user-cli/` | `als` commands: search, last, shorten, stats, authors, upgrade |
| **Admin CLI** | Python (click, uv) — `cli/` | Internal tool: `links` commands for admin operations (requires Supabase credentials) |
| **Database** | Supabase PostgreSQL | links, tracking_variants, click_log, people tables with RLS |
| **Auth** | Supabase Auth + Google OAuth | Team members sign in with Google, auto-provisioned to people table |

## Database Schema

### `links`
| Column | Type | Notes |
|--------|------|-------|
| id | uuid | PK |
| slug | text | unique, e.g. `workshop-cursor-practical` |
| destination_url | text | full Substack article URL |
| title | text | article title from Substack |
| author | text | article author from Substack |
| published_at | timestamptz | article publication date |
| created_at | timestamptz | |

### `tracking_variants`
| Column | Type | Notes |
|--------|------|-------|
| id | uuid | PK |
| link_id | uuid | FK -> links |
| suffix | text | unique, 4-char hash (e.g. `d7sc`) |
| utm_source | text | e.g. `linkedin` |
| utm_medium | text | e.g. `social` |
| utm_campaign | text | e.g. `workshop-cursor-practical` |
| utm_content | text | nullable |
| utm_term | text | nullable |
| ref | text | person slug (e.g. `stephen`) |
| created_at | timestamptz | |

### `click_log`
| Column | Type | Notes |
|--------|------|-------|
| id | uuid | PK |
| link_id | uuid | FK -> links |
| variant_id | uuid | FK -> tracking_variants, nullable |
| clicked_at | timestamptz | |
| ip_hash | text | hashed IP for privacy |
| user_agent | text | |
| referer | text | |

### `people`
| Column | Type | Notes |
|--------|------|-------|
| id | uuid | PK |
| name | text | display name |
| slug | text | unique, used as `ref` in variants |
| email | text | unique, for Google auth matching |
| created_at | timestamptz | |

## How It Works

### Short link redirect

All `aicoe.fit` links are clean — the URL you copy and share contains no tracking parameters. UTM attribution is added transparently at redirect time.

1. User clicks `aicoe.fit/workshop-cursor-practical-d7sc`
2. Cloudflare Worker proxies to Supabase edge function
3. Edge function splits on last `-`: slug = `workshop-cursor-practical`, suffix = `d7sc`
4. Looks up the link and variant, appends UTM params to destination URL
5. Logs the click, returns 302 to `https://trilogyai.substack.com/p/workshop-cursor-practical?utm_source=linkedin&utm_medium=social&utm_campaign=workshop-cursor-practical&ref=stan`

### Suffix generation
Deterministic 4-char hash of `utm_source|utm_medium|utm_campaign|utm_content|utm_term|ref` using SHA-256 -> first 8 hex chars -> base36 -> first 4 chars. Same inputs always produce the same suffix.

### Content sync
A pg_cron job runs every 6 hours, calling the `content-sync` edge function with `action: substack`. It fetches the Substack sitemap, finds new articles, creates links with `published_at` dates, and generates tracking variants for all people. The same function also handles YouTube sync (`action: youtube`), article embedding (`action: embed`), and video chunking (`action: chunk`).

### Admin dashboard
- Google sign-in via Supabase Auth
- Auto-provisions new team members via `get_or_create_person()` SQL function
- Shows all links sorted by publication date (newest first)
- Displays article title, author, and publication date
- "My Links" / "All Links" toggle
- Click stats per variant
- "Copy table" buttons for sharing link tables in Google Chat (copies as rich HTML)
- "Copy all links for [person]" buttons for bulk export

## Team Members

| Name | Slug | Email |
|------|------|-------|
| Rahul | rahul | rahul.subramaniam@devfactory.com |
| Stan | stan | stanislav.huseletov@trilogy.com |
| Praveen | praveen | praveen.koka@trilogy.com |
| David | david | david.proctor@trilogy.com |
| Leo | leo | leonardo.gonzalez@trilogy.com |
| Stephen | stephen | stephen.barr@devfactory.com |

New team members are auto-provisioned when they sign in with Google.

## Semantic Search

Search across 97+ AI-First Show videos by meaning, not just keywords. Powered by OpenAI `text-embedding-3-small` embeddings and pgvector with HNSW indexing.

### CLI search (`als search`)

Find videos and articles by concept:

```
$ als search "cost of running AI agents" --source aifs --count 3

  1. lnk-yhv  📺 The Prius of Gastown: How I Slashed AI Agent Costs by 83%
     by AI-First Show · 2026-03-04 · ⏱ 1m 56s · Score: 0.51

  2. lnk-g19  📺 Rent a $1M AI "Lamborghini" for $25/hr? | The AI-First Show
     by AI-First Show · 2026-02-02 · ⏱ 1m 27s · Score: 0.49

  3. lnk-t9p  📺 The AI Agent Revolution: From Code to Command Center
     by AI-First Show · 2026-01-26 · ⏱ 1m 25s · Score: 0.44
```

```
$ als search "MCP servers" --source aifs --count 3

  1. lnk-t80  📺 So many MCP tools!
     by AI-First Show · 2025-12-10 · ⏱ 0m 30s · Score: 0.55

  2. lnk-iwu  📺 MCP Observability with Austin Born, CEO @ Shinzo Labs
     by AI-First Show · 2025-12-10 · ⏱ 52m 06s · Score: 0.39

  3. lnk-kge  📺 Fantasy Role Play - AI Prompt Injection Techniques
     by AI-First Show · 2025-12-09 · ⏱ 0m 41s · Score: 0.31
```

### Video search (API)

Use the `search-articles` edge function with `content_type=video` to search videos:

```
POST /functions/v1/search-articles
{"query": "agent orchestration swarms", "match_count": 3, "content_type": "video"}
```

### Test suite

Run the curated test suite to verify search quality:

```bash
bash scripts/test-semantic-search.sh
```

Tests 8 queries across topics like Cerebras inference, prompt injection, MCP servers, agent orchestration, and model releases. Each query checks that relevant content appears in the results.

## Setup

### Prerequisites
- Python 3.12+ with [uv](https://docs.astral.sh/uv/)
- Node.js (for Cloudflare Worker)
- Cloudflare account with `aicoe.fit` domain
- AWS account (for Amplify hosting)
- Supabase project

### User CLI (als)

Install with one command:
```bash
curl -fsSL aicoe.fit/install | bash
```
Or with wget:
```bash
wget -qO- aicoe.fit/install | bash
```

Then log in with your API key:
```bash
als login --api-key <your-key>
als shorten <article-url>
als search <query>
als last 5
```

### Admin CLI (internal)

The admin CLI under `cli/` is an internal tool that requires direct Supabase credentials. For day-to-day use, prefer the `als` user CLI instead.

> **Note:** Content sync (Substack, YouTube) runs automatically every 6 hours via pg_cron calling the `content-sync` edge function. The admin CLI's `sync-substack` and `import-substack` commands are for manual/one-off syncs only.

```bash
cd cli
cp .env.example .env  # fill in Supabase URL and service-role key
uv sync
uv run links --help
```

**Admin commands:**
```bash
uv run links list-links          # List all short links
uv run links list-people         # List team members
uv run links click-stats         # View click statistics
uv run links create-link         # Create a new short link
uv run links create-variant      # Create a tracking variant
uv run links generate-all        # Generate variants for all people
uv run links add-person          # Add a team member
uv run links import-substack     # Import articles from Substack
uv run links sync-substack       # Manual Substack sync (automated sync runs via content-sync + pg_cron)
```

### Cloudflare Worker
```bash
cd worker
npm install
npx wrangler deploy
```

### Admin Dashboard
The admin site is a static HTML app in `admin-site/`. Deployed to AWS Amplify:
- **App ID:** `d3er9dt9913cnv`
- **Domain:** `admin.aicoe.fit`
- **Amplify URL:** `main.d3er9dt9913cnv.amplifyapp.com`

Deployment is automatic via git-connected Amplify CI/CD — pushing to `main` triggers a
build and deploy using the `amplify.yml` build spec in the repo root.

> **Manual step (one-time):** Connect this repository to Amplify app `d3er9dt9913cnv` in
> the AWS Amplify console (Settings > Repository) so that pushes to `main` trigger builds.

The previous manual deploy script is archived at `scripts/deploy-admin.sh.archived`.

## Infrastructure

| Service | Resource | Notes |
|---------|----------|-------|
| Supabase | Project `dumhbtxskncofwwzrmfx` | Database, Auth, Edge Functions |
| Cloudflare | Zone `aicoe.fit` | Worker routes `aicoe.fit/*`, DNS |
| AWS Amplify | App `d3er9dt9913cnv` | Hosts admin panel at `admin.aicoe.fit` |

### DNS Records (Cloudflare)
| Type | Name | Target | Proxy |
|------|------|--------|-------|
| A | `@` | `192.0.2.1` | Proxied (orange) |
| CNAME | `admin` | `d1gri8r4u97tb8.cloudfront.net` | DNS only (grey) |
| CNAME | `_e1d5...` | `_417c...acm-validations.aws.` | DNS only (grey) |

### Supabase Edge Functions

#### Consolidated Functions (action-based routing)

| Function | Actions | Purpose | Auth |
|----------|---------|---------|------|
| `analytics` | article-stats, list-custom-links | Article statistics and custom link queries | Optional (API key for list-custom-links) |
| `manage-content` | list-tags, create-tag, delete-tag, tag-article, untag-article, update-transcript, list-authors, stats | Content management and database queries | API key required for write operations |
| `content-sync` | substack, youtube, embed, chunk | Content ingestion and processing | Optional (Bearer token) |

#### Standalone Functions (performance-critical)

| Function | Purpose | Auth |
|----------|---------|------|
| `redirect` | Slug lookup + click logging + 302 redirect | No |
| `log-click` | Async click logging | No |
| `get-link` | Single link lookup | No |
| `batch-get-links` | Multiple link lookup | No |
| `search-articles` | Semantic article search | No |

#### Utility Functions

| Function | Purpose | Auth |
|----------|---------|------|
| `aifs` | AI-First Show specific operations | Varies |
| `shorten-url` | Create short links | API key |
| `manage-links` | Link CRUD operations | API key |
| `manage-contexts` | Context management | API key |
| `manage-tracking-variants` | Tracking variant CRUD | API key |
| `last-articles` | Get recent articles | No |
| `validate-key` | API key validation | API key |
| `pre-publish` | Pre-publish link preparation and social snippet generation | API key |
| `sync-health-alert` | Monitor content sync freshness and send alerts | Bearer token |

> **Note:** Legacy standalone functions (`sync-substack`, `sync-youtube`, `embed-articles`, `chunk-videos`, `article-stats`, `list-custom-links`, `manage-tags`, `update-transcript`, `list-authors`, `db-stats`) still exist in the codebase but have been consolidated into the action-routed functions above. pg_cron jobs now call `content-sync` with an action parameter.

## Stats
- **124** articles imported from Substack
- **744** tracking variants (6 people x 124 articles)
- **6** team members with pre-configured emails
- Content sync runs every 6 hours via pg_cron (calls `content-sync` with `action: substack`)
