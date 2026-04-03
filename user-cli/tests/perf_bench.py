#!/usr/bin/env python3
"""als performance benchmark — run and see timings for all key operations.

Usage:
    uv run python user-cli/tests/perf_bench.py
    uv run python user-cli/tests/perf_bench.py --include-shorten
"""

import subprocess
import sys
import time


def run(label: str, args: list[str], timeout: int = 30) -> float:
    """Run an als command, print timing, return elapsed seconds."""
    cmd = ["als"] + args
    start = time.perf_counter()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        elapsed = time.perf_counter() - start
        ok = result.returncode == 0
    except subprocess.TimeoutExpired:
        elapsed = timeout
        ok = False

    status = "OK" if ok else "FAIL"
    ms = elapsed * 1000
    bar = "█" * min(int(ms / 50), 60)
    print(f"  {label:<35s} {ms:>7.0f} ms  {status}  {bar}")
    return elapsed


THRESHOLDS = {
    "search": 3000,
    "last": 3000,
    "get": 2000,
    "custom-links": 2000,
    "stats": 3000,
    "context list": 2000,
    "links list --pinned": 2000,
    "whoami": 2000,
    "help": 500,
    "shorten (new link)": 5000,
}


def main():
    include_shorten = "--include-shorten" in sys.argv

    print()
    print("  als performance benchmark")
    print("  " + "=" * 60)
    print(f"  {'Operation':<35s} {'Time':>7s}  {'Status'}  {'Visual'}")
    print("  " + "-" * 60)

    results = {}

    results["help"] = run("help", ["help"])
    results["whoami"] = run("whoami", ["whoami"])
    results["search"] = run("search 'Claude'", ["search", "Claude", "--count", "5"])
    results["search --me"] = run("search --me", ["search", "AI", "--me", "--count", "5"])
    results["last"] = run("last 5", ["last", "5"])
    results["get"] = run("get (by slug)", ["get", "your-agent-my-agent"])
    results["custom-links"] = run("custom-links", ["custom-links"])
    results["stats"] = run("stats (by slug)", ["stats", "your-agent-my-agent"])
    results["context list"] = run("context list", ["context", "list"])
    results["links list --pinned"] = run("links list --pinned", ["links", "list", "--pinned"])

    if include_shorten:
        # Creates a real link — use a disposable URL
        ts = int(time.time())
        results["shorten"] = run(
            "shorten (new link)",
            ["shorten", f"https://example.com/perf-test-{ts}", "--title", "perf test"],
        )

    print("  " + "-" * 60)

    # Summary
    total_ms = sum(v * 1000 for v in results.values())
    count = len(results)
    print(f"  {'TOTAL':<35s} {total_ms:>7.0f} ms  ({count} operations)")
    print()

    # Flag slow ones
    slow = []
    for name, elapsed in results.items():
        threshold = THRESHOLDS.get(name, 3000)
        if elapsed * 1000 > threshold:
            slow.append((name, elapsed * 1000, threshold))

    if slow:
        print("  ⚠ Slow operations:")
        for name, ms, threshold in slow:
            print(f"    {name}: {ms:.0f}ms (threshold: {threshold}ms)")
        print()
    else:
        print("  ✓ All operations within thresholds")
        print()


if __name__ == "__main__":
    main()
