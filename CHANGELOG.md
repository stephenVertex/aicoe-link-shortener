# Changelog

All notable performance improvements, bug fixes, and feature requests for aicoe.fit.

## 2026-08-01 — Substack Web Redirect Compatibility

### Bug Fixes

#### Personalized Substack links showed “page croaked” — FIXED
- **Issue**: [#14](https://github.com/stephenVertex/aicoe-link-shortener/issues/14)
- **Commit**: `c657dcf`
- **Problem**: Personalized Substack links initially rendered the correct article in web browsers, then Substack's client-side application replaced it with an “Oh no—this page croaked” error. The shortener was exposing its internal person reference as Substack's reserved `ref` query parameter.
- **Fix**: Substack destinations now omit `ref` while retaining every UTM parameter. Non-Substack destinations retain the existing `ref` behavior.
- **Result**: Existing short URLs, suffixes, database records, and internal per-person click attribution remain unchanged. Regression tests cover Substack hosts, nested Substack hosts, stored `ref` cleanup, lookalike domains, and non-Substack destinations.

## 2026-07-16 — AIFS Link Tags

### Features

#### Tag/label categorization for AIFS submissions
- **ID**: `ys-als-nwbt`
- **Change**: Added a `--tag` option (repeatable) to `aifs submit`, `aifs vote`, and `aifs list`. Submissions can now be categorized with tags like `model-release`, `agent-tooling`, `open-weights`, `api-design`. Tags enable filtering (`aifs list --tag model-release`) and grouping for episode segmentation.
- **Commands**: `aifs submit <url> --tag model-release`, `aifs vote <id> --tag model-release`, `aifs list --tag model-release`. The deprecated `als aifs` shim also supports `--tag`.
- **Database**: New `aifs_submission_tags` junction table (many-to-many between `aifs_submissions` and the existing `tags` table) with RLS policies matching the `article_tags` pattern. Reuses the shared `tags` vocabulary so a single tag set serves both articles and AIFS submissions.
- **Edge function**: `aifs` function updated — submit/vote find-or-create tags and attach them; list filters by tag (OR semantics) and includes tags in each submission response.
- **Tests**: 13 new tests covering single/multiple tags, tag display, tag omission, and shim pass-through.

## 2026-06-11 — Dedicated `aifs` CLI (v0.9.0)

### Features

#### AIFS split into its own binary
- **ID**: `ys-als-p58i`
- **Change**: The AI First Show functionality (`als aifs ...`) now ships as a dedicated `aifs` binary with proper subcommands: `aifs submit <url>`, `aifs vote <id>`, `aifs list`, `aifs archive`, `aifs unarchive`, `aifs episodes`, and `aifs login`. A bare URL still works as shorthand for submit (`aifs https://...`).
- **Install**: Both binaries ship in the same `als` wheel — a single `uv tool install` (or `als upgrade`) installs both. Credentials (`~/.als.credentials`) are shared; logging in with either CLI authenticates both.
- **Deprecation**: `als aifs <subcommand>` still works identically but prints a deprecation notice on stderr pointing at the new binary.
- **Internals**: Shared Supabase/auth/config helpers extracted into `als_common.py`; no logic duplicated between the two CLIs.

## 2026-06-11 — Test Data Exclusion from Search

### Bug Fixes

#### Test links leaking into production search results — FIXED
- **ID**: `ys-als-ev45`
- **Commit**: `dfc44a8`
- **Problem**: Searches for nonsense queries (e.g. `xyz123notfound`) returned test/dev links with near-zero similarity, diluting result quality and confusing semantic search output. Known offender slugs: `mytestslug123`, `bz11id`, `8hr`, `fi2`, `0hsnqq`, `xa0thn`, `cra`.
- **Fix**: Added `is_test` boolean column to `links` table (default `false`). Updated `hybrid_match_articles`, `search_video_chunks`, `match_articles`, and `last-articles` to filter `is_test = false`. Flagged all known test slugs via migration without deleting data.
- **Result**: Test links are completely excluded from production search and `last` endpoints. Normal links unaffected. Developer documentation added to README showing how to flag future test links.

## 2026-05-12 — Performance Sprint

A focused performance and reliability sprint that eliminated all known bottlenecks and resolved every open bug report and feature request.

### Bug Fixes

#### `batch-get-links` sequential RPC storm — FIXED
- **ID**: `ys-als-xewx`
- **Commit**: `c194d18`
- **Problem**: `batch-get-links` called `ensure_tracking_variant` RPC once per link per source in a nested loop, causing 30+ sequential round-trips for typical batches (10 links x 3 sources). Average latency: 979ms.
- **Fix**: Gather all missing variants first, then create them all in parallel via `Promise.all`.
- **Result**: 55% improvement (979ms -> 440ms). Scale is now 3-5 RPCs regardless of batch size.

#### `analytics` sequential DB round-trips — FIXED
- **ID**: `ys-als-b0tq`
- **Commit**: `c194d18`
- **Problem**: `analytics` (article-stats) fired 5-7 sequential DB round-trips per request and transferred an ever-larger `variant_id` result set as `click_log` grew. Average latency: 630ms.
- **Fix**: Parallelized all independent queries with `Promise.all`.
- **Result**: Eliminated waterfall latency. Article stats now read from precomputed counters.

#### `search-articles` OpenAI embedding latency — FIXED
- **ID**: `ys-als-lt5q`
- **Commit**: `4a9c50d`
- **Problem**: `search-articles` edge function averaged 1,100-1,800ms per request. OpenAI embedding API alone cost 300-500ms, plus subsequent `hybrid_match_articles` + `search_video_chunks` RPCs.
- **Fix**: Added an in-memory LRU cache (500 entries, 1-hour TTL) for query embeddings.
- **Result**: Cache hit: ~640ms. Cache miss: ~850ms. Eliminates OpenAI API round-trip for repeated queries.

#### `last-articles` full-table scan — FIXED
- **ID**: `ys-als-8f45`
- **Commit**: `eb4c410`
- **Problem**: `last-articles` edge function did a full-table scan with `ORDER BY published_at DESC NULLS LAST LIMIT ... OFFSET ...` on the `links` table. With only 309 rows it still averaged 193ms per call.
- **Fix**: Added composite index `links(published_at DESC NULLS LAST, id)`.
- **Result**: Replaced full-table scan with ~5ms index scan. Eliminated 22,619ms of total query time.

#### `tracking_variants` unfiltered OFFSET pagination — FIXED
- **ID**: `ys-als-kjse`
- **Commit**: `aa781da`
- **Problem**: `SELECT * FROM tracking_variants ORDER BY created_at ASC, id ASC LIMIT OFFSET` averaged 207ms per call and consumed 212 seconds of total execution time over 1,026 calls — the #1 DB performance killer.
- **Fix**: Added composite index `tracking_variants(created_at, id)`.
- **Result**: Replaced 207ms OFFSET pagination with ~5ms index scan.

#### `als --help` missing `aifs` subcommand — FIXED
- **ID**: `ys-als-vkay`
- **Commit**: `640130f`
- **Problem**: Top-level `als help` showed no reference to `submit`, `vote`, `list`, `archive`, `unarchive`, or Discord delegation features.
- **Fix**: Added `aifs` to the Usage section with all subcommands documented.

#### Cloudflare Worker 404 cache gap — FIXED
- **ID**: `ys-als-yr51`
- **Commit**: `5b59b8d`
- **Problem**: Cloudflare Worker did not cache 404 responses, so every bot scan (`/.env`, `/.git/config`, `/wp-admin/install.php`, etc.) hit the redirect edge function directly. These requests took 700-1,400ms and consumed 42% of total edge function time.
- **Fix**: Worker now caches 404s for 60 seconds in `SLUG_CACHE`.
- **Result**: Bot scans drop from ~1,000ms to ~15ms after the first miss.

### Feature Requests

#### Precomputed all-time counters (`link_stats`)
- **ID**: `ys-als-wz6q`
- **Commit**: `b1d755a`
- **Request**: Real-time analytics that stay fast as `click_log` grows past 10k+ rows.
- **Implementation**: Created `link_stats` table with a trigger on `click_log` insert that rebuilds all counters (total_clicks, by_variant, by_source, by_referrer, by_country, by_person) for the affected link. The `link_analytics` action reads from `link_stats` single row instead of aggregating the full `click_log` table.

#### Precomputed daily time-series (`link_daily_clicks`)
- **ID**: `ys-als-b8dh`
- **Commit**: `6d7295f`
- **Request**: Click-over-time graphs that don't scan the full `click_log` table.
- **Implementation**: Created `link_daily_clicks(link_id, date, clicks, by_variant, by_source)` table with PK `(link_id, date)` and index for range scans. A consolidated trigger refreshes both `link_stats` (all-time) and `link_daily_clicks` (affected date) on every `click_log` insert. Weekly rollups are computed in JS from daily rows.

#### `top-links` cache prewarming
- **ID**: `ys-als-c35v`
- **Commit**: `bf1b756`
- **Request**: Pre-warm the Cloudflare Worker `SLUG_CACHE` with the top 50 most-clicked links so the first request after a cold start doesn't hit the edge function.
- **Implementation**: Added `top-links` action to `analytics` edge function. Worker `scheduled` trigger runs every 5 minutes, calls `analytics?action=top-links&count=50`, and writes top 50 slugs into `SLUG_CACHE` with 5-minute TTL.

#### `last-articles` cache headers
- **ID**: `ys-als-n8xn`
- **Commit**: `bf1b756`
- **Request**: Add `Cache-Control` headers to the `last-articles` edge function so Cloudflare can cache the article list.
- **Implementation**: Returns `Cache-Control: public, max-age=60`. Article list changes slowly (new articles are synced on a schedule), so a 60-second cache is safe.

#### Composite/covering database indexes
- **ID**: `ys-als-wkln`
- **Commit**: `956d1b4`
- **Request**: Add composite DB indexes to eliminate full-table scans.
- **Implementation**:
  1. `tracking_variants(created_at, id)` — replaces 207ms OFFSET pagination with ~5ms index scan
  2. `links(published_at DESC NULLS LAST, id)` — replaces 193ms full-table scan with ~5ms index scan
  3. `click_log(link_id, clicked_at DESC, variant_id)` — covering index for per-link analytics queries; eliminates a second table lookup

#### Batch `ensure_tracking_variant` optimization
- **ID**: `ys-als-ex69`
- **Commit**: `c194d18`
- **Request**: Optimize `batch-get-links` variant creation.
- **Implementation**: Already fixed by the `ys-als-xewx` parallelization. Superseded by the in-memory LRU cache in `search-articles`.

#### Admin dashboard loading UI
- **ID**: `ys-als-zjxj`
- **Commit**: `bf1b756`
- **Request**: Show what is actively loading with descriptive labels and fast-moving progress bars instead of a static spinner.
- **Implementation**: Replaced static "Loading dashboard..." with animated hacker-style progress bars showing 5 steps: Authenticating -> Sources -> Articles & Variants -> Click Data -> Rendering.

#### 404 caching (duplicate request)
- **ID**: `ys-als-zkhm`
- **Commit**: `5b59b8d`
- **Note**: Superseded by `ys-als-yr51`. Same fix — Cloudflare Worker now caches 404s with 60s TTL.

### Infrastructure

- **wrangler v4 upgrade** (`a9a07c5`): Updated Cloudflare Worker tooling from wrangler v3 to v4.
- **YouTube auto-sync**: `pg_cron` job `sync-youtube` runs every 6 hours calling `content-sync?action=youtube`.
- **Admin dashboard column selection** (`ffa7241`): `refreshDashboardData` now fetches only needed columns (8 for links, 5 for variants) instead of `select('*')`, eliminating pulling massive unused columns (`transcript`, `body_text`, `embedding`, `description`) which can be 50KB+ per row.

### Benchmark Results (2026-05-13)

All commands now run within thresholds:

| Command | Latency | Threshold | Status |
|---------|---------|-----------|--------|
| `help` | 103ms | 500ms | PASS |
| `whoami` | 181ms | 2000ms | PASS |
| `search` | 1,105ms | 3000ms | PASS |
| `search --me` | 948ms | 3000ms | PASS |
| `last` | 450ms | 1000ms | PASS |
| `get` | 890ms | 2000ms | PASS |
| `custom-links` | 551ms | 2000ms | PASS |
| `stats` | 483ms | 3000ms | PASS |
| `context list` | 905ms | 2000ms | PASS |
| `links list --pinned` | 685ms | 2000ms | PASS |

### Sync Bug Fix (2026-05-12)

- **Commit**: `411affa`
- **Problem**: `content-sync` edge function was silently skipping articles where the Substack API returned short random slugs (e.g. `ktrdc8`) differing from sitemap URLs (e.g. `how-the-machines-finally-learned`).
- **Fix**: Matching now tries `canonical_url` first, then falls back to slug. Also fixed `sync_operations` logging to properly `await` the insert instead of fire-and-forget `.then()`.
- **Article renames**: 11 articles updated from unreadable 6-char random IDs to readable Substack slugs, preserving all clicks.

---

*Tracked via [yesod](https://github.com/yesod/yesod) under tool `als`.*
