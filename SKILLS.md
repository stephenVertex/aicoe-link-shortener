# als — Command Reference

`als` is the aicoe.fit link shortener CLI. It fetches personalised tracking
links for articles on the AI Center of Excellence Substack
([trilogyai.substack.com](https://trilogyai.substack.com)).

Version: 0.2.2  
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

### `als search`

Search articles using semantic (meaning-based) search and get your
personalised tracking links for the results.

```bash
als search <QUERY> [--count N]
```

| Argument/Option | Default | Description |
|-----------------|---------|-------------|
| `QUERY` | (required) | Search terms (quoted if multi-word) |
| `--count` | 3 | Number of results to return |

**Examples:**
```bash
als search "GLM-5"
als search "cursor workshop" --count 5
als search "AI productivity"
```

**Example output:**
```
Search results for: cursor workshop

  1. Cursor Workshop: Practical AI Coding
     by Stephen
     Score: 0.92
     linkedin      https://aicoe.fit/workshop-cursor-practical-d7sc
     email         https://aicoe.fit/workshop-cursor-practical-a1b2
```

---

### `als last`

Show the most recently published articles with your personalised tracking
links. Optionally filter by author.

```bash
als last [N] [--author NAME]
```

| Argument/Option | Default | Description |
|-----------------|---------|-------------|
| `N` | 10 | Number of articles to show |
| `--author` | (none) | Filter by author name (case-insensitive substring match) |

**Examples:**
```bash
als last
als last 5
als last 3 --author "Simon"
als last 20 --author "stephen"
```

**Example output:**
```
Last 5 article(s):

  1. Cursor Workshop: Practical AI Coding
     by Stephen
     2026-03-10
     linkedin      https://aicoe.fit/workshop-cursor-practical-d7sc
     email         https://aicoe.fit/workshop-cursor-practical-a1b2
```

---

### `als authors`

List all authors in the database and how many articles each has published.

```bash
als authors
```

**Example output:**
```
Authors (4 total):

  Stephen  (42 articles)
  Simon    (38 articles)
  Rahul    (27 articles)
  David    (17 articles)
```

---

### `als stats`

Show high-level statistics about the link shortener database.

```bash
als stats
```

**Example output:**
```
Database statistics:

  Articles:          124
  Authors:           4
  People:            6
  Tracking variants: 744
  Total clicks:      1203
```

---

### `als upgrade`

Upgrade `als` to the latest version. Fetches the pre-built wheel from S3
and reinstalls via `uv`.

```bash
als upgrade [--force]
```

| Option | Description |
|--------|-------------|
| `--force` | Reinstall even if already up to date |

**Examples:**
```bash
als upgrade
als upgrade --force
```

---

### `als --version`

Print the installed version of `als`.

```bash
als --version
# als, version 0.2.2
```

---

## Typical Workflow

```bash
# 1. One-time setup
als login --api-key als_abc123xyz

# 2. Confirm who you are
als whoami

# 3. Find recent articles
als last 5

# 4. Search for something specific
als search "GLM-5" --count 5

# 5. Browse all authors
als authors

# 6. Check overall stats
als stats

# 7. Keep up to date
als upgrade
```

---

## Authentication

- API keys are stored in `~/.als.credentials` (INI format, mode `0600`)
- Keys must start with `als_`
- Pass the key once via `als login`; all subsequent commands read it
  automatically
- To check validity at any time: `als whoami`

---

## Troubleshooting

| Error | Fix |
|-------|-----|
| `Not logged in. Run: als login --api-key <your-key>` | Run `als login --api-key <key>` |
| `Invalid API key.` | Check the key starts with `als_` and was issued for you |
| `'uv' is not installed` (upgrade) | Install uv: `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Network timeout | Check internet connectivity; Supabase endpoint is `dumhbtxskncofwwzrmfx.supabase.co` |
