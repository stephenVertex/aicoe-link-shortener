# als-mcp: MCP Server for aicoe.fit Link Shortener

The `als-mcp` server exposes the same functionality as the `als` CLI through the
[Model Context Protocol](https://modelcontextprotocol.io/), so LLM-powered
tools (Claude Desktop, claude-code, Cursor, etc.) can search articles, generate
tracking links, and query stats without shelling out to a CLI.

## Available Tools

| Tool | Description |
|------|-------------|
| `search(query, count)` | Semantic article search with personalised tracking links |
| `last(n, author)` | Recent articles with tracking links |
| `authors()` | List all authors and article counts |
| `stats()` | Database statistics |
| `whoami()` | Authenticated user identity |
| `shorten(url, source)` | Create tracking short links for any URL |

## Transports

| Transport | Use case | Auth |
|-----------|----------|------|
| **stdio** | Local single-user (Claude Desktop, claude-code) | `ALS_API_KEY` env var |
| **SSE** | Shared server (ECS, team use) | `?api_key=als_...` query param or `ALS_API_KEY` env |

## Client Configuration

### Claude Desktop (`claude_desktop_config.json`)

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

#### Option A: Local stdio (recommended for personal use)

```json
{
  "mcpServers": {
    "als": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/aicoe-link-shortener/mcp", "als-mcp"],
      "env": {
        "ALS_API_KEY": "als_your_key_here"
      }
    }
  }
}
```

#### Option B: Remote SSE (shared team server on ECS)

```json
{
  "mcpServers": {
    "als": {
      "transport": "sse",
      "url": "http://als-mcp-alb-1979469047.us-east-1.elb.amazonaws.com/sse?api_key=als_your_key_here"
    }
  }
}
```

### claude-code (OpenCode) (`settings.json` or `opencode.json`)

#### Option A: Local stdio

Add to your project's `opencode.json` or `~/.opencode/settings.json`:

```json
{
  "mcpServers": {
    "als": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--project", "/path/to/aicoe-link-shortener/mcp", "als-mcp"],
      "env": {
        "ALS_API_KEY": "als_your_key_here"
      }
    }
  }
}
```

#### Option B: Remote SSE

```json
{
  "mcpServers": {
    "als": {
      "type": "sse",
      "url": "http://als-mcp-alb-1979469047.us-east-1.elb.amazonaws.com/sse?api_key=als_your_key_here"
    }
  }
}
```

### Cursor (`.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "als": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/aicoe-link-shortener/mcp", "als-mcp"],
      "env": {
        "ALS_API_KEY": "als_your_key_here"
      }
    }
  }
}
```

## Running Locally

```bash
# stdio (default)
ALS_API_KEY=als_... uv run --project mcp als-mcp

# SSE (single-user)
ALS_API_KEY=als_... uv run --project mcp als-mcp --sse

# SSE (multi-user — each client passes key in URL)
uv run --project mcp als-mcp --sse
# Connect: http://localhost:8000/sse?api_key=als_yourkey
```

## Demo: CLI vs MCP Performance

A demo script compares the same queries run via the `als` CLI and the MCP
server, measuring latency and estimated token cost:

```bash
# Using stdio transport (local MCP server, requires ALS_API_KEY)
ALS_API_KEY=als_... uv run scripts/demo-mcp-vs-cli.py

# Using SSE transport (remote or local)
ALS_API_KEY=als_... uv run scripts/demo-mcp-vs-cli.py \
  --mcp-url http://als-mcp-alb-1979469047.us-east-1.elb.amazonaws.com/sse
```

The script runs `search`, `last`, and `authors` via both interfaces and prints
a comparison table:

```
========================================================================
  als CLI vs MCP Server — Performance Comparison
========================================================================
  Date:       2026-03-18 10:30:00
  Transport:  stdio (local)
  Queries:    search('generative AI'), last(5), authors()

------------------------------------------------------------------------
  Query: search('generative AI')
------------------------------------------------------------------------
  Method            Latency    Est Tokens      Raw Size
  ------            -------    ----------      --------
  als CLI             3.21s      412 tokens     1,648 chars
  MCP (stdio)         2.85s      589 tokens     2,356 chars

  MCP is 1.1x faster for this query
```

Raw results are also saved as `scripts/demo-results.json` for further analysis.

## Deployment

The MCP server is deployed to AWS ECS Fargate. See
[`mcp-server/INFRASTRUCTURE.md`](mcp-server/INFRASTRUCTURE.md) for full
infrastructure reference.

```bash
./mcp-server/deploy.sh            # Full deploy (build + push + ECS update)
./mcp-server/deploy.sh --build-only  # Just build and push image
```
