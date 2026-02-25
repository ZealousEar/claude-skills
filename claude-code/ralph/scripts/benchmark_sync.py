#!/usr/bin/env python3
"""Sync LLM benchmark data for the Ralph Loop.

Thin wrapper around the /llm skill's fetch_benchmarks.py that ensures
rankings.csv is up-to-date before a ralph session starts. Sync failure
is non-fatal -- stale data is better than no data.

Usage:
    python3 benchmark_sync.py            # sync if stale (>24h)
    python3 benchmark_sync.py --force    # re-fetch unconditionally
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BENCHMARKS_DIR = Path.home() / ".claude" / "skills" / "llm" / "benchmarks"
RANKINGS_CSV = BENCHMARKS_DIR / "rankings.csv"
VALS_JSON = BENCHMARKS_DIR / "vals.json"
META_JSON = BENCHMARKS_DIR / "_meta.json"
FETCH_SCRIPT = Path.home() / ".claude" / "skills" / "llm" / "scripts" / "fetch_benchmarks.py"

STALENESS_SECONDS = 24 * 60 * 60  # 24 hours


def _age_str(seconds: float) -> str:
    """Human-readable age string from seconds."""
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3600:
        return f"{int(seconds / 60)}m ago"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h ago"
    return f"{seconds / 86400:.1f}d ago"


def _file_age(path: Path) -> float | None:
    """Return file age in seconds, or None if missing."""
    if not path.exists():
        return None
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return (datetime.now(tz=timezone.utc) - mtime).total_seconds()


def _meta_summary() -> str:
    """One-line summary from _meta.json if available."""
    if not META_JSON.exists():
        return ""
    try:
        meta = json.loads(META_JSON.read_text())
        total = meta.get("total_models", "?")
        sources = meta.get("sources", {})
        ok = [k for k, v in sources.items() if v.get("status") == "ok"]
        return f"{total} models from {len(ok)} sources ({', '.join(ok)})"
    except (json.JSONDecodeError, KeyError):
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync LLM benchmark data for Ralph Loop."
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-fetch even if recently synced."
    )
    args = parser.parse_args()

    # --- Check rankings.csv freshness ---
    csv_age = _file_age(RANKINGS_CSV)

    if csv_age is not None and csv_age < STALENESS_SECONDS and not args.force:
        summary = f"benchmarks up-to-date (last synced {_age_str(csv_age)})"
        meta = _meta_summary()
        if meta:
            summary += f" -- {meta}"
        vals_age = _file_age(VALS_JSON)
        if vals_age is not None:
            summary += f" | vals.json {_age_str(vals_age)}"
        elif VALS_JSON.exists() is False:
            summary += " | vals.json missing"
        print(summary)
        return 0

    # --- Need to sync ---
    if not FETCH_SCRIPT.exists():
        print(
            f"fetch_benchmarks.py not found at {FETCH_SCRIPT}",
            file=sys.stderr,
        )
        print("benchmark sync skipped: fetch script missing")
        return 0

    reason = "forced" if args.force else (
        "rankings.csv missing" if csv_age is None else f"stale ({_age_str(csv_age)})"
    )
    print(f"syncing benchmarks ({reason})...")

    result = subprocess.run(
        [sys.executable, str(FETCH_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=300,  # 5 min generous timeout
    )

    if result.returncode == 0:
        # Extract last non-empty line of stdout as summary
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        short = lines[-1] if lines else "done"
        meta = _meta_summary()
        msg = f"benchmarks synced: {short}"
        if meta:
            msg += f" -- {meta}"
        print(msg)
    else:
        stderr_tail = result.stderr.strip().splitlines()
        err_msg = stderr_tail[-1] if stderr_tail else "unknown error"
        print(f"benchmark sync failed: {err_msg}", file=sys.stderr)
        print("continuing with stale data")

    # --- Vals.json age in summary ---
    vals_age = _file_age(VALS_JSON)
    if vals_age is not None:
        print(f"vals.json age: {_age_str(vals_age)}")
    else:
        print("vals.json: not found (run scrape_vals.py to populate)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
