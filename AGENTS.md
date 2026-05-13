# AGENTS.md

This file provides persistent context for AI agents working on this repository.

## Non-Interactive Shell Commands

**ALWAYS use non-interactive flags** with file operations to avoid hanging on confirmation prompts.

Shell commands like `cp`, `mv`, and `rm` may be aliased to include `-i` (interactive) mode on some systems, causing the agent to hang indefinitely waiting for y/n input.

**Use these forms instead:**
```bash
# Force overwrite without prompting
cp -f source dest           # NOT: cp source dest
mv -f source dest           # NOT: mv source dest
rm -f file                  # NOT: rm file

# For recursive operations
rm -rf directory            # NOT: rm -r directory
cp -rf source dest          # NOT: cp -r source dest
```

**Other commands that may prompt:**
- `scp` - use `-o BatchMode=yes` for non-interactive
- `ssh` - use `-o BatchMode=yes` to fail instead of prompting
- `apt-get` - use `-y` flag
- `brew` - use `HOMEBREW_NO_AUTO_UPDATE=1` env var

## Issue Tracking

- **Internal**: `yesod` — personal local registry for tools, processes, and workflow knowledge
- **External**: GitHub Issues — for bugs, features, and tasks visible to the public

Use the right tracker for the audience. Internal workflow tweaks go to yesod; user-facing bugs and feature requests go to GitHub Issues.

### yesod

yesod is a local knowledge registry. Use it to capture tool preferences, workflow tips, and process knowledge that agents should reuse across sessions.

**Example — the `als` CLI tool:**

```bash
# Record a workflow tip
yesod tool als usage-note "Use --dry-run to preview changes before running"

# Log a bug you hit
yesod tool als bug-report "als analytics fails when stub has no clicks"

# Request a feature
yesod tool als feature-request "Add --output json flag to all commands"

# See all notes for this tool
yesod tool als notes

# Edit an existing note
yesod tool als note-edit <note-id>

# Replace an outdated note with a newer one (preserves history)
yesod tool als supersede <old-note-id> "Updated workflow: ..."

# Get an LLM-distilled summary of current tool state
yesod tool als distill
```

**Key yesod commands:**
- `feature-request` — Record a feature request
- `usage-note` — Record tips, gotchas, how you use it
- `bug-report` — Record a bug
- `notes` — List all notes for the tool
- `note-edit` — Edit an existing note
- `supersede` — Create a new note that replaces an old one (history preserved)
- `distill` — LLM-distilled summary of the tool's current notes

Query your catalog anytime: `yesod search <query>` or `yesod what <question>`.

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds

## CLI Architecture — API Key Only

**CRITICAL RULE**: All `als` CLI commands MUST authenticate using the user's API key (`x-api-key` header). No CLI command may require `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, or any other Supabase credential.

### Why

The `als` CLI is a multi-tenant user tool. Users have API keys, not service-role keys. Requiring Supabase credentials would make the CLI unusable for anyone outside the admin team, and leaks internal infrastructure details.

### How to implement a new command

1. **Build a Supabase edge function** that accepts `x-api-key` (validated via the `api_keys` table) and performs the database operation server-side.
2. **Call that edge function** from the CLI using `_api_request(...)` with `api_key=api_key`.
3. **Never** call Supabase directly from the CLI (no `supabase` SDK, no REST calls to `supabase.co`).

### If you see `_get_supabase()` or `SUPABASE_SERVICE_ROLE_KEY` in CLI code

That is a bug. Create a GitHub issue (`fix: move <command> off service-role to API`) and refactor it to use an edge function before shipping.

### Edge function pattern

```typescript
// supabase/functions/my-command/index.ts
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

Deno.serve(async (req) => {
  const apiKey = req.headers.get("x-api-key");
  // validate apiKey against api_keys table, get person_id
  // ... do the work ...
  return new Response(JSON.stringify(result), {
    headers: { "Content-Type": "application/json" },
  });
});
```

Deploy: commit and push to main — CI auto-deploys via `.github/workflows/deploy-edge-functions.yml`.

## Supabase MCP Access

This project uses the `supabase_aicoe` MCP server for direct database operations (queries, migrations, edge function deployment).

**If `supabase_aicoe` MCP tools are not available in your session:**

- **DO NOT** go searching for config files, env vars, or try to work around it
- **DO NOT** try to use the Supabase CLI, psql, or other alternatives
- **STOP and tell the human**: "I need the `supabase_aicoe` MCP server but it's not available. Please reconnect it (run `/mcp` in Claude Code)."

The human can fix this in seconds. Chasing it yourself wastes time and context.

## Upgrading als

The `als` CLI has a built-in self-upgrade command that pulls the latest release wheel from GitHub:

```bash
als upgrade
```

This downloads and installs the latest `als-py3-none-any.whl` from `releases/latest/download/`.

For developers working on the CLI locally, reinstall from the repo instead:

```bash
cd user-cli
uv tool install --reinstall .
```

## Releasing a New Version

To release a new version of the `als` CLI:

1. Bump the version in `user-cli/pyproject.toml`
2. Commit and push to main
3. Tag and push:
   ```bash
   git tag v0.2.5
   git push origin v0.2.5
   ```

GitHub Actions will automatically:
- Build the wheel
- Create a GitHub release with the wheel attached as `als-py3-none-any.whl`
- Deploy the Cloudflare Worker (`aicoe.fit/*`)

The install script and `als upgrade` always pull from `releases/latest/download/` so no URL updates are needed.

After a tagged release has been built and published, update your local install:

```bash
als upgrade
```

## Supabase Edge Functions

### Edge Function Deployment Protocol

Edge functions are **auto-deployed by CI** when changes land on `main`. Do NOT deploy via MCP for routine changes — CI handles the rest.

**How it works:**
- `.github/workflows/deploy-edge-functions.yml` triggers on push to `main` when `supabase/functions/**` changes
- CI uses `git diff` to detect which functions changed and deploys only those via the Supabase CLI
- If `supabase/functions/_shared/` changes, ALL functions are redeployed
- Smoke tests run automatically after deployment

**When your issue involves edge function changes:**

1. **Edit the edge function code** in `supabase/functions/<name>/index.ts`
2. **Commit and push** — CI will auto-deploy when your branch merges to main
3. **Verify locally** before pushing (optional but recommended):
   ```bash
   cd user-cli && uv run pytest tests/test_smoke.py -v
   ```

**Required GitHub secrets** (already configured):
- `SUPABASE_PROJECT_REF` — the Supabase project reference
- `SUPABASE_ACCESS_TOKEN` — Supabase Management API access token
- `AICOE_API_KEY` — API key for post-deploy smoke tests

**Do NOT use `supabase_aicoe` MCP `deploy_edge_function` for routine deploys.** MCP deploy is reserved for emergency hotfixes that can't wait for CI. If you must use it, document why in the issue notes.

### Consolidated Functions

| Function | Actions | Purpose | Auth |
|----------|---------|---------|------|
| `analytics` | article-stats, list-custom-links | Article statistics and custom link queries | Optional (API key for list-custom-links) |
| `manage-content` | list-tags, create-tag, delete-tag, tag-article, untag-article, update-transcript, list-authors, stats | Content management and database queries | API key required for write operations |
| `content-sync` | substack, youtube, embed, chunk | Content ingestion and processing | Optional (Bearer token) |

### Standalone Functions (Performance-Critical)

| Function | Purpose | Auth | Notes |
|----------|---------|------|-------|
| `redirect` | Slug lookup + click logging + 302 redirect | No | Called from Cloudflare Worker |
| `log-click` | Async click logging | No | Called from Cloudflare Worker |
| `get-link` | Single link lookup | No | Hot path |
| `batch-get-links` | Multiple link lookup | No | Hot path |
| `search-articles` | Semantic article search | No | Has own cold-start profile |

### Utility Functions

| Function | Purpose | Auth |
|----------|---------|------|
| `aifs` | AI-First Show specific operations | Varies |
| `shorten-url` | Create short links | API key |
| `manage-links` | Link CRUD operations | API key |
| `manage-contexts` | Context management | API key |
| `manage-tracking-variants` | Tracking variant CRUD | API key |
| `last-articles` | Get recent articles | No |
| `validate-key` | API key validation | API key |

### Migration Notes

- **2026-04-02**: Consolidated 10 functions into 3 to reduce cold-start surface:
  - `article-stats` + `list-custom-links` → `analytics`
  - `manage-tags` + `update-transcript` + `list-authors` + `db-stats` → `manage-content`
  - `sync-substack` + `sync-youtube` + `embed-articles` + `chunk-videos` → `content-sync`
- pg_cron jobs updated to call `content-sync` with action parameter
- CLI and MCP server updated to use consolidated endpoints

## Changelog

We maintain a public changelog so users and contributors can see what changed, why, and when.

### Files

- **`CHANGELOG.md`** (repo root) — Markdown changelog with full details on performance improvements, bug fixes, and feature requests. Includes benchmark results, commit hashes, yesod note IDs, and before/after metrics.
- **`admin-site/changelog.html`** — Dashboard page mirroring `CHANGELOG.md` with matching theme support (Synthwave, Solarized, Light). Auto-deploys via Amplify on push to `main`.

### What to document

- **Bug fixes**: Root cause, fix approach, result/measurement, yesod note ID, commit hash
- **Feature requests**: Request description, implementation approach, yesod note ID, commit hash
- **Performance improvements**: Baseline latency, optimization applied, benchmark results after
- **Infrastructure changes**: Wrangler upgrades, index additions, table schema changes

### Workflow

When you fix a bug or implement a feature tracked in yesod:

1. Implement the change, commit, and push
2. Update the yesod note status to `done` with `--commit <hash>`
3. Append the entry to `CHANGELOG.md` under the appropriate section
4. Mirror the entry in `admin-site/changelog.html` (copy the HTML card pattern)
5. Commit both files with `docs:` prefix and push

This keeps the changelog in sync with the code and gives future agents (and humans) a complete paper trail from yesod note → commit → changelog entry.
