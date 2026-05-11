# AGENTS.md

This file provides persistent context for AI agents working on this repository.

## Project Overview

<!-- Describe your project here. What does it do? What problem does it solve? -->

## Technology Stack

<!-- List your technologies: languages, frameworks, databases, etc. -->

- Language: <!-- e.g., Python 3.11, TypeScript 5.0 -->
- Framework: <!-- e.g., FastAPI, React, Next.js -->
- Database: <!-- e.g., PostgreSQL, SQLite -->
- Testing: <!-- e.g., pytest, vitest -->

## Coding Standards

### General

- Keep functions small and focused
- Write self-documenting code with clear names
- Add comments only for "why", not "what"
- Follow existing patterns in the codebase

### Formatting

<!-- Add your formatting commands -->

- Format command: `<!-- e.g., make format, npm run format -->`
- Lint command: `<!-- e.g., make lint, npm run lint -->`
- Type check: `<!-- e.g., make typecheck, npm run typecheck -->`

### Testing

<!-- Add your testing requirements -->

- Test command: `<!-- e.g., make test, npm test -->`
- Coverage requirement: <!-- e.g., 80%, 100% for critical paths -->
- Test location: `<!-- e.g., tests/, __tests__/ -->`

## Project Structure

```
<!-- Customize this structure for your project -->
.
├── src/                    # Source code
├── tests/                  # Test files
├── docs/                   # Documentation
├── configs/                # Configuration files
├── scripts/                # Utility scripts
├── AGENTS.md               # This file
└── README.md               # Project readme
```

## Key Directories

<!-- Document important directories -->

- `src/` - <!-- Main source code -->
- `tests/` - <!-- Test files -->
- `docs/` - <!-- Documentation -->

## Dependencies

### Runtime

<!-- List key runtime dependencies -->

### Development

<!-- List key dev dependencies -->

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `EXAMPLE_VAR` | <!-- Description --> | Yes/No |

## Local Development Setup

<!-- Steps to set up local development -->

```bash
# Example setup steps
# 1. Install dependencies
# 2. Configure environment
# 3. Run tests
```

## PR Requirements

Before submitting a PR:

1. All tests pass
2. Code is formatted
3. Lint checks pass
4. New code has tests
5. Documentation updated if needed

## Architecture Decisions

<!-- Document key architecture decisions -->

### Decision 1

- **Context**: <!-- Why this decision was needed -->
- **Decision**: <!-- What was decided -->
- **Consequences**: <!-- Impact and trade-offs -->

## Known Issues / Gotchas

<!-- Document any quirks or known issues -->

## References

<!-- Links to relevant external documentation -->

- [Framework Docs](https://example.com)
- [API Reference](https://example.com/api)

# Agent Instructions

This project uses **bd** (beads) for issue tracking. Run `bd onboard` to get started.

## Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work atomically
bd close <id>         # Complete work
bd dolt push          # Push beads data to remote
```

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

<!-- BEGIN BEADS INTEGRATION -->
## Issue Tracking with bd (beads)

**IMPORTANT**: This project uses **bd (beads)** for ALL issue tracking. Do NOT use markdown TODOs, task lists, or other tracking methods.

### Why bd?

- Dependency-aware: Track blockers and relationships between issues
- Version-controlled: Built on Dolt with cell-level merge
- Agent-optimized: JSON output, ready work detection, discovered-from links
- Prevents duplicate tracking systems and confusion

### Quick Start

**Check for ready work:**

```bash
bd ready --json
```

**Create new issues:**

```bash
bd create "Issue title" --description="Detailed context" -t bug|feature|task -p 0-4 --json
bd create "Issue title" --description="What this issue is about" -p 1 --deps discovered-from:bd-123 --json
```

**Claim and update:**

```bash
bd update <id> --claim --json
bd update bd-42 --priority 1 --json
```

**Complete work:**

```bash
bd close bd-42 --reason "Completed" --json
```

### Issue Types

- `bug` - Something broken
- `feature` - New functionality
- `task` - Work item (tests, docs, refactoring)
- `epic` - Large feature with subtasks
- `chore` - Maintenance (dependencies, tooling)

### Priorities

- `0` - Critical (security, data loss, broken builds)
- `1` - High (major features, important bugs)
- `2` - Medium (default, nice-to-have)
- `3` - Low (polish, optimization)
- `4` - Backlog (future ideas)

### Workflow for AI Agents

1. **Check ready work**: `bd ready` shows unblocked issues
2. **Claim your task atomically**: `bd update <id> --claim`
3. **Work on it**: Implement, test, document
4. **Discover new work?** Create linked issue:
   - `bd create "Found bug" --description="Details about what was found" -p 1 --deps discovered-from:<parent-id>`
5. **Complete**: `bd close <id> --reason "Done"`

### Auto-Sync

bd automatically syncs with git:

- Exports to `.beads/issues.jsonl` after changes (5s debounce)
- Imports from JSONL when newer (e.g., after `git pull`)
- No manual export/import needed!

### Important Rules

- ✅ Use bd for ALL task tracking
- ✅ Always use `--json` flag for programmatic use
- ✅ Link discovered work with `discovered-from` dependencies
- ✅ Check `bd ready` before asking "what should I work on?"
- ❌ Do NOT create markdown TODO lists
- ❌ Do NOT use external issue trackers
- ❌ Do NOT duplicate tracking systems

For more details, see README.md and docs/QUICKSTART.md.

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

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

<!-- END BEADS INTEGRATION -->

## CLI Architecture — API Key Only

**CRITICAL RULE**: All `als` CLI commands MUST authenticate using the user's API key (`x-api-key` header). No CLI command may require `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, or any other Supabase credential.

### Why

The `als` CLI is a multi-tenant user tool. Users have API keys, not service-role keys. Requiring Supabase credentials would make the CLI unusable for anyone outside the admin team, and leaks internal infrastructure details.

### How to implement a new command

1. **Build a Supabase edge function** that accepts `x-api-key` (validated via the `api_keys` table) and performs the database operation server-side.
2. **Call that edge function** from the CLI using `_api_request(...)` with `api_key=api_key`.
3. **Never** call Supabase directly from the CLI (no `supabase` SDK, no REST calls to `supabase.co`).

### If you see `_get_supabase()` or `SUPABASE_SERVICE_ROLE_KEY` in CLI code

That is a bug. File a bead (`bd create "fix: move <command> off service-role to API" -t bug -p 1`) and refactor it to use an edge function before shipping.

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

---

## Supabase MCP Access

This project uses the `supabase_aicoe` MCP server for direct database operations (queries, migrations, edge function deployment).

**If `supabase_aicoe` MCP tools are not available in your session:**

- **DO NOT** go searching for config files, env vars, or try to work around it
- **DO NOT** try to use the Supabase CLI, psql, or other alternatives
- **STOP and tell the human**: "I need the `supabase_aicoe` MCP server but it's not available. Please reconnect it (run `/mcp` in Claude Code)."

The human can fix this in seconds. Chasing it yourself wastes time and context.

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

## Supabase Edge Functions

### Edge Function Deployment Protocol

Edge functions are **auto-deployed by CI** when changes land on `main`. Polecats do NOT deploy via MCP — they commit and push; CI handles the rest.

**How it works:**
- `.github/workflows/deploy-edge-functions.yml` triggers on push to `main` when `supabase/functions/**` changes
- CI uses `git diff` to detect which functions changed and deploys only those via the Supabase CLI
- If `supabase/functions/_shared/` changes, ALL functions are redeployed
- Smoke tests run automatically after deployment

**When your bead involves edge function changes:**

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

**Do NOT use `supabase_aicoe` MCP `deploy_edge_function` for routine deploys.** MCP deploy is reserved for emergency hotfixes that can't wait for CI. If you must use it, document why in the bead notes.

The project uses Supabase Edge Functions for various operations. Functions are consolidated to reduce cold-start surface.

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
