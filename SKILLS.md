# als — Command Reference

`als` is the aicoe.fit link shortener CLI. It fetches personalised tracking
links for articles on the AI Center of Excellence Substack
([trilogyai.substack.com](https://trilogyai.substack.com)) and the
AI-First Show YouTube channel.

Credentials stored at: `~/.als.credentials`

---

## Installation

```bash
curl -fsSL aicoe.fit/install | bash
# or
wget -qO- aicoe.fit/install | bash
```

---

## Commands

### `als login`

Save your personal API key so all other commands work without further
authentication.

```bash
als login --api-key <your-key>
```

| Option | Required | Description |
|--------|----------|-------------|
| `--api-key` | yes | Your personal API key (must start with `als_`) |

**Example:**
```bash
als login --api-key als_abc123xyz
# Logged in. Credentials saved to /Users/you/.als.credentials
```

---

### `als whoami`

Show the currently authenticated user and confirm the API key is valid.

```bash
als whoami
```

**Example output:**
```
Logged in as: Stephen (stephen)
Credentials: /Users/you/.als.credentials
```

---

### `als set-author-name`

Cache your author name in credentials for use with `--me` filters.

```bash
als set-author-name <NAME>
```

| Argument | Description |
|----------|-------------|
| `NAME` | Your author name as it appears in `als authors` output. Pass `""` to clear. |

**Examples:**
```bash
als authors                           # find your exact name
als set-author-name "Stephen Barr"    # cache it
als set-author-name ""                # clear cached name
```

---

### `als search`

Search articles using semantic (meaning-based) search and get your
personalised tracking links for the results.

```bash
als search <QUERY> [--count N] [--source SOURCE] [--me] [--tracking]
```

| Argument/Option | Default | Description |
|-----------------|---------|-------------|
| `QUERY` | (required) | Search terms (quoted if multi-word) |
| `--count` | 3 | Number of results to return |
| `--source` | both | Filter: `aifs` (videos), `blog` (articles), or `both` |
| `--me` | off | Filter to articles written by you |
| `--tracking` | off | Include personalised tracking links |

**Examples:**
```bash
als search "GLM-5"
als search "cursor workshop" --count 5
als search "AI productivity" --source aifs
```

---

### `als last`

Show the most recently published articles with your personalised tracking
links. Optionally filter by author.

```bash
als last [N] [--author NAME] [--me] [--tracking] [--summary]
```

| Argument/Option | Default | Description |
|-----------------|---------|-------------|
| `N` | 10 | Number of articles to show |
| `--author` | (none) | Filter by author name (case-insensitive substring match) |
| `--me` | off | Filter to your own articles |
| `--tracking` | off | Include personalised tracking links |
| `--summary` | off | Show a compact summary table instead of full output |

**Examples:**
```bash
als last
als last 5
als last 3 --author "Simon"
als last 10 --me --tracking
```

---

### `als get`

Get full details and tracking links for a single article by slug, URL, or
short ID.

```bash
als get <SLUG_OR_URL> [--tracking/--no-tracking]
```

| Argument/Option | Default | Description |
|-----------------|---------|-------------|
| `SLUG_OR_URL` | (required) | Article slug, URL, or `lnk-xxx` short ID |
| `--tracking` | on | Include personalised tracking links. Use `--no-tracking` for fast metadata-only lookup. |

**Examples:**
```bash
als get workshop-cursor-practical
als get https://trilogyai.substack.com/p/workshop-cursor-practical
als get lnk-edk
als get lnk-edk --no-tracking
```

---

### `als shorten`

Get your personalised tracking link(s) for any URL or link ID. With
`--note`, uses AI to infer UTM source/medium from the description.

```bash
als shorten <URL_OR_ID> [--source SOURCE] [--slug SLUG] [--note NOTE] [--expires ND] [--no-expires]
```

| Argument/Option | Description |
|-----------------|-------------|
| `URL_OR_ID` | Destination URL or `lnk-xxx` ID |
| `--source` | Filter to a specific source (e.g. `linkedin`) |
| `--slug` | Custom slug for the short link |
| `--note` | Describe where you're sharing — AI infers UTM params |
| `--expires` | Expiry in days (e.g. `30d`, `90d`). Default: `60d` when `--note` is used |
| `--no-expires` | Keep variant in active list indefinitely |

**Examples:**
```bash
als shorten https://example.com
als shorten https://example.com --slug my-link
als shorten lnk-abc --note "replying to @mike on twitter"
als shorten lnk-abc --note "linkedin post" --expires 90d
```

---

### `als pre-publish`

Create tracking links for an unpublished Substack article. When the article
is later published and sync runs, title/author/date are filled in automatically.

```bash
als pre-publish <SLUG_OR_URL>
```

| Argument | Description |
|----------|-------------|
| `SLUG_OR_URL` | Substack URL or just the article slug |

**Examples:**
```bash
als pre-publish https://trilogyai.substack.com/p/my-upcoming-post
als pre-publish my-upcoming-post
```

---

### `als stats`

Show statistics for a specific article, or overall database stats.

```bash
als stats [ARTICLE] [--days N] [--everybody]
```

| Argument/Option | Default | Description |
|-----------------|---------|-------------|
| `ARTICLE` | (none) | Article slug, URL, or `lnk-xxx` ID. Omit for database overview. |
| `--days` | 30 | Number of days to look back for click history |
| `--everybody` | off | Show per-person click breakdown (all team members) |

**Examples:**
```bash
als stats                        # database overview
als stats cursor-mar26           # article stats by slug
als stats cursor-mar26 --days 7  # last 7 days only
als stats cursor-mar26 --everybody  # show per-person breakdown
```

---

### `als analytics`

Show per-link analytics for a shortened link stub: daily/weekly click
counts, referrer breakdown, and comparison links.

```bash
als analytics <STUB> [--days N]
```

| Argument/Option | Default | Description |
|-----------------|---------|-------------|
| `STUB` | (required) | Link slug or stub |
| `--days` | 30 | Number of days for the analytics window |

**Example:**
```bash
als analytics workshop-cursor-practical
als analytics workshop-cursor-practical --days 7
```

---

### `als authors`

List all authors in the database and how many articles each has published.

```bash
als authors
```

---

### `als custom-links`

List your custom short links (created via `als shorten`), not auto-imported
Substack articles.

```bash
als custom-links [--count N] [--all]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--count` | 10 | Number of results to return |
| `--all` | off | Show all custom links (ignores `--count`) |

---

### `als links`

Manage pinned links — permanent destinations (Substack, Discord, etc.) that
participate in bulk context generation.

```bash
als links list [--pinned]
als links pin <SLUG_OR_ID>
```

| Sub-command | Description |
|-------------|-------------|
| `list` | List links, optionally filtered to pinned only |
| `pin` | Pin a link so it participates in context generation |

---

### `als context`

Manage link contexts for grouped tracking variants — e.g. a YouTube video
description, a conference talk, or a newsletter issue.

```bash
als context create <LABEL> [--expires ND]
als context generate <CTX_ID> [--pinned] [--note NOTE]
als context show <CTX_ID>
als context list [--expired]
als context archive <CTX_ID>
```

| Sub-command | Description |
|-------------|-------------|
| `create` | Create a new context with a label and optional expiry |
| `generate` | Generate tracking links for all pinned links in a context |
| `show` | Display context details and its tracking links |
| `list` | List contexts (active by default, use `--expired` for archived) |
| `archive` | Archive a context |

---

### `als tags`

Manage article tags for categorization and filtering.

```bash
als tags list [--article SLUG]
als tags create <NAME>
als tags delete <NAME>
als tags assign --article <SLUG> --tag <TAG>
als tags remove --article <SLUG> --tag <TAG>
```

| Sub-command | Description |
|-------------|-------------|
| `list` | List all tags (with counts), or tags on a specific article |
| `create` | Create a new tag |
| `delete` | Delete a tag |
| `assign` | Assign a tag to an article |
| `remove` | Remove a tag from an article |

---

### `als tracking-variants`

Manage your tracking variant channels (Discord, LinkedIn, X, etc.).

```bash
als tracking-variants list
als tracking-variants add --source <SOURCE> --label <LABEL>
als tracking-variants delete --label <LABEL>
```

| Sub-command | Description |
|-------------|-------------|
| `list` | List your channels with labels and UTM params |
| `add` | Add a custom tracking variant channel |
| `delete` | Delete a custom variant (system defaults cannot be removed) |

---

### `als aifs`

AI-First Show episode candidate submission and voting.

```bash
als aifs <URL> [--comment COMMENT]        # submit/vote
als aifs --item <ID> --comment COMMENT    # vote by short ID
als aifs list [--archived] [--all]        # show candidates
als aifs archive <IDS...> --note NOTE     # archive specific
als aifs unarchive <IDS...>              # unarchive
```

| Sub-command / Argument | Description |
|------------------------|-------------|
| `URL` | Submit a URL as a candidate for the next episode |
| `list` | Show active (default), `--archived`, or `--all` submissions |
| `archive` | Archive submissions by ID, `--before` date, or `--archive-all` |
| `unarchive` | Unarchive previously archived submissions |
| `--comment` | Add a comment with your vote |
| `--item` | Vote on an existing submission by its short ID |

---

### `als sync-substack`

Trigger a sync of the latest articles from the Trilogy Substack. (Automated
sync runs every 6 hours via `content-sync` + pg_cron; this command is for
manual/one-off syncs.)

```bash
als sync-substack [--force]
```

| Option | Description |
|--------|-------------|
| `--force` | Re-sync and update existing article metadata |

---

### `als sync-youtube`

Trigger a sync of videos from the AI-First Show YouTube channel.

```bash
als sync-youtube [--force] [--limit N]
```

| Option | Description |
|--------|-------------|
| `--force` | Re-sync and update existing video metadata |
| `--limit` | Limit the number of new videos to import (0 = no limit) |

---

### `als update-transcript`

Update or add a transcript for an existing video.

```bash
als update-transcript --url <YOUTUBE_URL> --transcript-file <FILE>
als update-transcript --url <YOUTUBE_URL> --transcript <TEXT>
```

| Option | Description |
|--------|-------------|
| `--url` | YouTube video URL (destination_url to match in the database) |
| `--transcript-file` | Path to a file containing the transcript text |
| `--transcript` | Transcript text to set (alternative to `--transcript-file`) |

---

### `als upgrade`

Upgrade `als` to the latest version. Fetches the pre-built wheel from
GitHub Releases and reinstalls via `uv`.

```bash
als upgrade [--force]
```

| Option | Description |
|--------|-------------|
| `--force` | Reinstall even if already up to date |

---

### `als --version`

Print the installed version of `als`.

```bash
als --version
# als, version X.Y.Z
```

---

### `als help`

Show use-case-driven guidance for common workflows.

```bash
als help
```

---

## Typical Workflow

```bash
# 1. One-time setup
als login --api-key als_abc123xyz
als set-author-name "Your Name"

# 2. Find recent articles
als last 5 --tracking

# 3. Get details for a specific article
als get lnk-edk

# 4. Search by topic
als search "GLM-5" --count 5

# 5. Shorten any URL
als shorten https://example.com --note "sharing on LinkedIn"

# 6. Pre-publish an upcoming article
als pre-publish my-upcoming-post

# 7. Check article stats
als stats cursor-mar26

# 8. Submit for AI-First Show
als aifs https://example.com/article --comment "Great demo!"

# 9. Keep up to date
als upgrade
```

---

## Authentication

- API keys are stored in `~/.als.credentials` (INI format, mode `0600`)
- Keys must start with `als_`
- Pass the key once via `als login`; all subsequent commands read it
  automatically
- To check validity at any time: `als whoami`
- Use `als set-author-name` to cache your author name for `--me` filters

---

## Troubleshooting

| Error | Fix |
|-------|-----|
| `Not logged in. Run: als login --api-key <your-key>` | Run `als login --api-key <key>` |
| `Invalid API key.` | Check the key starts with `als_` and was issued for you |
| `'uv' is not installed` (upgrade) | Install uv: `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Network timeout | Check internet connectivity; Supabase endpoint is `dumhbtxskncofwwzrmfx.supabase.co` |
