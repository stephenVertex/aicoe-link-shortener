#!/usr/bin/env python3
"""Demo: Compare als CLI vs MCP server — latency and token cost.

Runs the same three queries (search, last, authors) via:
  (a) the als CLI (subprocess)
  (b) the MCP server (fastmcp Python client over SSE)

Measures wall-clock latency and estimates LLM token cost (≈ chars/4) from
the JSON response payload.  Output is a formatted table suitable for
screenshots or pasting into team chat.

Usage:
    # Requires: ALS_API_KEY set (or als login'd), MCP server running
    uv run scripts/demo-mcp-vs-cli.py [--mcp-url URL]

    # Default MCP endpoint (ECS ALB):
    uv run scripts/demo-mcp-vs-cli.py

    # Local MCP server:
    uv run scripts/demo-mcp-vs-cli.py --mcp-url http://localhost:8000/sse
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_MCP_URL = "http://als-mcp-alb-1979469047.us-east-1.elb.amazonaws.com/sse"
SEARCH_QUERY = "generative AI"
LAST_COUNT = 5

# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Rough LLM token estimate: ~4 chars per token."""
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------


def run_cli(args: list[str]) -> tuple[str, float]:
    """Run an als CLI command. Returns (stdout, elapsed_seconds)."""
    t0 = time.perf_counter()
    result = subprocess.run(
        ["als", *args],
        capture_output=True,
        text=True,
        timeout=60,
    )
    elapsed = time.perf_counter() - t0
    if result.returncode != 0:
        raise RuntimeError(
            f"als {' '.join(args)} failed (rc={result.returncode}): "
            f"{result.stderr.strip()}"
        )
    return result.stdout, elapsed


def cli_search(query: str, count: int) -> tuple[str, float]:
    return run_cli(["search", query, "--count", str(count)])


def cli_last(n: int) -> tuple[str, float]:
    return run_cli(["last", str(n)])


def cli_authors() -> tuple[str, float]:
    return run_cli(["authors"])


# ---------------------------------------------------------------------------
# MCP client runner (using fastmcp)
# ---------------------------------------------------------------------------


def mcp_call(
    mcp_url: str, api_key: str, tool: str, arguments: dict
) -> tuple[str, float]:
    """Call an MCP tool via the SSE transport and return (response_text, elapsed).

    Uses httpx directly to speak the MCP JSON-RPC protocol over SSE,
    avoiding the need for a heavy async MCP client library.
    """
    import httpx

    # Step 1: Connect to SSE endpoint to get the messages URL
    sse_url = f"{mcp_url}?api_key={api_key}" if api_key else mcp_url
    base_url = mcp_url.rsplit("/sse", 1)[0]

    t0 = time.perf_counter()

    with httpx.Client(timeout=30.0) as client:
        # Open SSE stream to get session endpoint
        with client.stream("GET", sse_url) as sse_resp:
            sse_resp.raise_for_status()
            messages_url = None
            for line in sse_resp.iter_lines():
                if line.startswith("data: /messages/"):
                    messages_url = base_url + line[len("data: ") :]
                    break
                elif line.startswith("data: http"):
                    messages_url = line[len("data: ") :]
                    break

            if not messages_url:
                raise RuntimeError("Could not obtain messages URL from SSE stream")

            # Step 2: Initialize
            init_resp = client.post(
                messages_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "als-demo", "version": "0.1.0"},
                    },
                },
            )
            init_resp.raise_for_status()

            # Send initialized notification
            client.post(
                messages_url,
                json={
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                },
            )

            # Step 3: Call the tool
            call_resp = client.post(
                messages_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": tool,
                        "arguments": arguments,
                    },
                },
            )
            call_resp.raise_for_status()

            # Read the tool result from the SSE stream
            result_text = ""
            for line in sse_resp.iter_lines():
                if line.startswith("data: "):
                    data = line[len("data: ") :]
                    try:
                        msg = json.loads(data)
                        if msg.get("id") == 2 and "result" in msg:
                            content = msg["result"].get("content", [])
                            result_text = json.dumps(content, indent=2)
                            break
                    except json.JSONDecodeError:
                        continue

    elapsed = time.perf_counter() - t0
    return result_text, elapsed


def mcp_call_stdio(tool: str, arguments: dict) -> tuple[str, float]:
    """Call an MCP tool via the stdio transport (local process).

    Spawns `als-mcp` as a subprocess, speaks JSON-RPC over stdin/stdout.
    Requires ALS_API_KEY env var.
    """
    t0 = time.perf_counter()

    proc = subprocess.Popen(
        ["uv", "run", "--project", "mcp", "als-mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )

    try:
        # Initialize
        init_msg = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "als-demo", "version": "0.1.0"},
                    },
                }
            )
            + "\n"
        )
        proc.stdin.write(init_msg)
        proc.stdin.flush()

        # Read initialize response
        proc.stdout.readline()  # consume init response

        # Send initialized notification
        notif = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                }
            )
            + "\n"
        )
        proc.stdin.write(notif)
        proc.stdin.flush()

        # Call tool
        call_msg = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": tool,
                        "arguments": arguments,
                    },
                }
            )
            + "\n"
        )
        proc.stdin.write(call_msg)
        proc.stdin.flush()

        # Read tool response
        result_text = ""
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line.strip())
                if msg.get("id") == 2:
                    content = msg.get("result", {}).get("content", [])
                    result_text = json.dumps(content, indent=2)
                    break
            except json.JSONDecodeError:
                continue

    finally:
        proc.terminate()
        proc.wait(timeout=5)

    elapsed = time.perf_counter() - t0
    return result_text, elapsed


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

HEADER = "=" * 72
SUBHEADER = "-" * 72


def fmt_row(label: str, latency: float, tokens: int, chars: int) -> str:
    return f"  {label:<16s}  {latency:>7.2f}s  {tokens:>7,} tokens  {chars:>8,} chars"


def print_comparison(
    name: str,
    cli_output: str,
    cli_latency: float,
    mcp_output: str,
    mcp_latency: float,
) -> dict:
    """Print a side-by-side comparison and return metrics dict."""
    cli_tokens = estimate_tokens(cli_output)
    mcp_tokens = estimate_tokens(mcp_output)

    print(f"\n{SUBHEADER}")
    print(f"  Query: {name}")
    print(SUBHEADER)
    print(f"  {'Method':<16s}  {'Latency':>8s}  {'Est Tokens':>13s}  {'Raw Size':>10s}")
    print(f"  {'------':<16s}  {'-------':>8s}  {'----------':>13s}  {'--------':>10s}")
    print(fmt_row("als CLI", cli_latency, cli_tokens, len(cli_output)))
    print(fmt_row("MCP (stdio)", mcp_latency, mcp_tokens, len(mcp_output)))

    if mcp_latency > 0 and cli_latency > 0:
        ratio = cli_latency / mcp_latency
        faster = "CLI" if ratio < 1 else "MCP"
        factor = ratio if ratio < 1 else 1 / ratio
        print(f"\n  {faster} is {1 / factor:.1f}x faster for this query")

    return {
        "query": name,
        "cli_latency": cli_latency,
        "cli_tokens": cli_tokens,
        "cli_chars": len(cli_output),
        "mcp_latency": mcp_latency,
        "mcp_tokens": mcp_tokens,
        "mcp_chars": len(mcp_output),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Compare als CLI vs MCP server performance"
    )
    parser.add_argument(
        "--mcp-url",
        default=None,
        help=f"MCP SSE endpoint URL (default: use stdio transport)",
    )
    parser.add_argument(
        "--search-query",
        default=SEARCH_QUERY,
        help=f"Search query to test (default: {SEARCH_QUERY!r})",
    )
    parser.add_argument(
        "--last-count",
        type=int,
        default=LAST_COUNT,
        help=f"Number of articles for 'last' query (default: {LAST_COUNT})",
    )
    args = parser.parse_args()

    api_key = os.environ.get("ALS_API_KEY", "")
    use_sse = args.mcp_url is not None

    print(HEADER)
    print("  als CLI vs MCP Server — Performance Comparison")
    print(HEADER)
    print(f"  Date:       {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(
        f"  Transport:  {'SSE (' + args.mcp_url + ')' if use_sse else 'stdio (local)'}"
    )
    print(
        f"  Queries:    search({args.search_query!r}), last({args.last_count}), authors()"
    )
    if use_sse and not api_key:
        print(f"  Warning:    ALS_API_KEY not set — MCP SSE calls may fail")
    print()

    results = []

    # --- 1. Search ---
    print("Running: search ...")
    try:
        cli_out, cli_time = cli_search(args.search_query, 3)
    except Exception as e:
        print(f"  CLI search failed: {e}")
        cli_out, cli_time = str(e), 0.0

    try:
        if use_sse:
            mcp_out, mcp_time = mcp_call(
                args.mcp_url,
                api_key,
                "search",
                {"query": args.search_query, "count": 3},
            )
        else:
            mcp_out, mcp_time = mcp_call_stdio(
                "search",
                {"query": args.search_query, "count": 3},
            )
    except Exception as e:
        print(f"  MCP search failed: {e}")
        mcp_out, mcp_time = str(e), 0.0

    results.append(
        print_comparison(
            f"search({args.search_query!r})",
            cli_out,
            cli_time,
            mcp_out,
            mcp_time,
        )
    )

    # --- 2. Last ---
    print(f"\nRunning: last {args.last_count} ...")
    try:
        cli_out, cli_time = cli_last(args.last_count)
    except Exception as e:
        print(f"  CLI last failed: {e}")
        cli_out, cli_time = str(e), 0.0

    try:
        if use_sse:
            mcp_out, mcp_time = mcp_call(
                args.mcp_url,
                api_key,
                "last",
                {"n": args.last_count},
            )
        else:
            mcp_out, mcp_time = mcp_call_stdio(
                "last",
                {"n": args.last_count},
            )
    except Exception as e:
        print(f"  MCP last failed: {e}")
        mcp_out, mcp_time = str(e), 0.0

    results.append(
        print_comparison(
            f"last({args.last_count})",
            cli_out,
            cli_time,
            mcp_out,
            mcp_time,
        )
    )

    # --- 3. Authors ---
    print("\nRunning: authors ...")
    try:
        cli_out, cli_time = cli_authors()
    except Exception as e:
        print(f"  CLI authors failed: {e}")
        cli_out, cli_time = str(e), 0.0

    try:
        if use_sse:
            mcp_out, mcp_time = mcp_call(
                args.mcp_url,
                api_key,
                "authors",
                {},
            )
        else:
            mcp_out, mcp_time = mcp_call_stdio("authors", {})
    except Exception as e:
        print(f"  MCP authors failed: {e}")
        mcp_out, mcp_time = str(e), 0.0

    results.append(
        print_comparison(
            "authors()",
            cli_out,
            cli_time,
            mcp_out,
            mcp_time,
        )
    )

    # --- Summary ---
    print(f"\n{HEADER}")
    print("  SUMMARY")
    print(HEADER)
    print()

    total_cli_time = sum(r["cli_latency"] for r in results)
    total_mcp_time = sum(r["mcp_latency"] for r in results)
    total_cli_tokens = sum(r["cli_tokens"] for r in results)
    total_mcp_tokens = sum(r["mcp_tokens"] for r in results)

    print(f"  {'':16s}  {'CLI':>12s}  {'MCP':>12s}")
    print(f"  {'':16s}  {'---':>12s}  {'---':>12s}")
    print(
        f"  {'Total latency':16s}  {total_cli_time:>10.2f}s  {total_mcp_time:>10.2f}s"
    )
    print(f"  {'Total tokens':16s}  {total_cli_tokens:>10,}  {total_mcp_tokens:>10,}")
    print()

    print("  Key insight: CLI output is human-formatted text (lower token count).")
    print("  MCP returns structured JSON (higher token count but machine-parseable).")
    print("  For LLM tool-use, MCP avoids subprocess overhead and provides typed data.")
    print()

    # Output JSON for programmatic use
    json_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "demo-results.json",
    )
    with open(json_path, "w") as f:
        json.dump(
            {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "transport": "sse" if use_sse else "stdio",
                "mcp_url": args.mcp_url or "stdio",
                "results": results,
                "totals": {
                    "cli_latency": total_cli_time,
                    "mcp_latency": total_mcp_time,
                    "cli_tokens": total_cli_tokens,
                    "mcp_tokens": total_mcp_tokens,
                },
            },
            f,
            indent=2,
        )
    print(f"  Raw data saved to: {json_path}")
    print()


if __name__ == "__main__":
    main()
