# aicoe.fit - Link Shortener with UTM Campaign Attribution

A link shortener for the AI Center of Excellence Substack ([trilogyai.substack.com](https://trilogyai.substack.com)). Every article gets per-person tracking variants with UTM parameters, so you can see who drove which clicks.

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
| **Substack sync** | Supabase Edge Function (`sync-substack`) | Crawls sitemap for new articles, creates links + variants (runs every 6h via pg_cron) |
| **Admin dashboard** | Static HTML on AWS Amplify (`admin.aicoe.fit`) | Google sign-in, view links/clicks, copy tracking URLs |
| **CLI** | Python (typer/click, uv) | Create links, manage people, import articles, view stats |
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
1. User clicks `aicoe.fit/workshop-cursor-practical-d7sc`
2. Cloudflare Worker proxies to Supabase edge function
3. Edge function splits on last `-`: slug = `workshop-cursor-practical`, suffix = `d7sc`
4. Looks up the link and variant, appends UTM params to destination URL
5. Logs the click, returns 302 to `https://trilogyai.substack.com/p/workshop-cursor-practical?utm_source=linkedin&utm_medium=social&utm_campaign=workshop-cursor-practical&ref=stan`

### Suffix generation
Deterministic 4-char hash of `utm_source|utm_medium|utm_campaign|utm_content|utm_term|ref` using SHA-256 -> first 8 hex chars -> base36 -> first 4 chars. Same inputs always produce the same suffix.

### Substack sync
A pg_cron job runs every 6 hours, calling the `sync-substack` edge function. It fetches the Substack sitemap, finds new articles, creates links with `published_at` dates, and generates tracking variants for all people.

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

## Setup

### Prerequisites
- Python 3.14+ with [uv](https://docs.astral.sh/uv/)
- Node.js (for Cloudflare Worker)
- Cloudflare account with `aicoe.fit` domain
- AWS account (for Amplify hosting)
- Supabase project

### CLI
```bash
cd cli
cp .env.example .env  # fill in Supabase URL and keys
uv sync
uv run links --help
```

### CLI Commands
```bash
uv run links list-links          # List all short links
uv run links list-people         # List team members
uv run links click-stats         # View click statistics
uv run links create-link         # Create a new short link
uv run links create-variant      # Create a tracking variant
uv run links generate-all        # Generate variants for all people
uv run links add-person          # Add a team member
uv run links import-substack     # Import articles from Substack
uv run links sync-substack       # Trigger Substack sync
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
| Function | Purpose | JWT |
|----------|---------|-----|
| `redirect` | Slug lookup + click logging + 302 redirect | No |
| `sync-substack` | Crawl sitemap, create links + variants | No |
| `admin` | (Legacy, replaced by Amplify) | No |

## Stats
- **124** articles imported from Substack
- **744** tracking variants (6 people x 124 articles)
- **6** team members with pre-configured emails
- Substack sync runs every 6 hours via pg_cron
