#!/usr/bin/env python3
"""als performance benchmark — run and see timings for all key operations.

Usage:
    python user-cli/tests/perf_bench.py
    python user-cli/tests/perf_bench.py --include-shorten
    python user-cli/tests/perf_bench.py --json results.json
    python user-cli/tests/perf_bench.py --markdown summary.md
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone


THRESHOLDS = {
    "help": 500,
    "whoami": 2000,
    "search": 3000,
    "search --me": 3000,
    "last": 3000,
    "get": 2000,
    "custom-links": 2000,
    "stats": 3000,
    "context list": 2000,
    "links list --pinned": 2000,
    "shorten": 5000,
}


def run(label: str, args: list[str], timeout: int = 30) -> dict:
    """Run an als command, return result dict."""
    cmd = ["als"] + args
    start = time.perf_counter()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        elapsed = time.perf_counter() - start
        ok = result.returncode == 0
        error = result.stderr.strip() if not ok else None
    except subprocess.TimeoutExpired:
        elapsed = timeout
        ok = False
        error = "timeout"

    ms = elapsed * 1000
    threshold = THRESHOLDS.get(label, 3000)
    status = "OK" if ok else "FAIL"
    within = ms <= threshold

    bar = "\u2588" * min(int(ms / 50), 60)
    print(f"  {label:<35s} {ms:>7.0f} ms  {status}  {bar}")

    return {
        "name": label,
        "ms": round(ms, 1),
        "ok": ok,
        "within_threshold": within,
        "threshold_ms": threshold,
        "error": error,
    }


def render_markdown(results: list[dict], meta: dict) -> str:
    """Render results as a markdown summary."""
    lines = []
    lines.append("## als Performance Benchmark")
    lines.append("")
    lines.append(f"**Date:** {meta['timestamp']}")
    lines.append(f"**Runner:** {meta.get('runner', 'local')}")
    lines.append("")
    lines.append("| Operation | Time (ms) | Threshold (ms) | Status |")
    lines.append("|-----------|----------:|--------------:|--------|")

    for r in results:
        status = r["ok"] and r["within_threshold"]
        icon = "\u2705" if status else ("\u26a0\ufe0f" if r["ok"] else "\u274c")
        lines.append(
            f"| {r['name']} | {r['ms']:.0f} | {r['threshold_ms']} | {icon} |"
        )

    total = sum(r["ms"] for r in results)
    passed = sum(1 for r in results if r["ok"] and r["within_threshold"])
    failed = len(results) - passed
    lines.append("")
    lines.append(f"**Total:** {total:.0f} ms across {len(results)} operations")
    if failed:
        lines.append(f"**{failed} operation(s) outside threshold or failed**")
    else:
        lines.append("**All operations within thresholds**")
    lines.append("")
    return "\n".join(lines)


def main():
    include_shorten = "--include-shorten" in sys.argv
    json_path = None
    md_path = None

    for i, arg in enumerate(sys.argv):
        if arg == "--json" and i + 1 < len(sys.argv):
            json_path = sys.argv[i + 1]
        if arg == "--markdown" and i + 1 < len(sys.argv):
            md_path = sys.argv[i + 1]

    print()
    print("  als performance benchmark")
    print("  " + "=" * 60)
    print(f"  {'Operation':<35s} {'Time':>7s}  {'Status'}  {'Visual'}")
    print("  " + "-" * 60)

    results = []
    results.append(run("help", ["help"]))
    results.append(run("whoami", ["whoami"]))
    results.append(run("search", ["search", "Claude", "--count", "5"]))
    results.append(run("search --me", ["search", "AI", "--me", "--count", "5"]))
    results.append(run("last", ["last", "5"]))
    results.append(run("get", ["get", "your-agent-my-agent"]))
    results.append(run("custom-links", ["custom-links"]))
    results.append(run("stats", ["stats", "your-agent-my-agent"]))
    results.append(run("context list", ["context", "list"]))
    results.append(run("links list --pinned", ["links", "list", "--pinned"]))

    if include_shorten:
        ts = int(time.time())
        results.append(run("shorten", [
            "shorten", f"https://example.com/perf-test-{ts}", "--note", "perf test"
        ]))

    print("  " + "-" * 60)

    total_ms = sum(r["ms"] for r in results)
    print(f"  {'TOTAL':<35s} {total_ms:>7.0f} ms  ({len(results)} operations)")
    print()

    slow = [r for r in results if not r["within_threshold"] or not r["ok"]]
    if slow:
        print("  Slow or failed operations:")
        for r in slow:
            reason = f"threshold: {r['threshold_ms']}ms" if r["ok"] else r["error"]
            print(f"    {r['name']}: {r['ms']:.0f}ms ({reason})")
        print()
    else:
        print("  All operations within thresholds")
        print()

    meta = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "runner": os.environ.get("GITHUB_RUNNER_NAME", "local"),
        "ref": os.environ.get("GITHUB_REF", ""),
        "sha": os.environ.get("GITHUB_SHA", ""),
    }

    if json_path:
        with open(json_path, "w") as f:
            json.dump({"meta": meta, "results": results}, f, indent=2)
        print(f"  Results saved to {json_path}")

    if md_path:
        md = render_markdown(results, meta)
        with open(md_path, "w") as f:
            f.write(md)
        print(f"  Markdown saved to {md_path}")

    # Write to GitHub Actions job summary if available
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        md = render_markdown(results, meta)
        with open(summary_path, "a") as f:
            f.write(md)

    # Exit non-zero if any failures (for CI)
    if any(not r["ok"] for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
