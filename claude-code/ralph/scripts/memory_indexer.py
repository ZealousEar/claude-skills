#!/usr/bin/env python3
"""Pattern/decision/fix/signs taxonomy memory for the Ralph Loop.

Analyzes each iteration's result to extract learnable patterns and records
them in a structured memory file. Enables the loop to learn from its own
outputs across iterations.

Memory taxonomy (4 types):
  patterns  — Recurring themes or successful approaches.
  decisions — Choices made during the session (model, lens, etc.).
  fixes     — Error recoveries and parse failures.
  signs     — Early indicators of saturation or quality shifts.

Usage:
    python memory_indexer.py --result result.json --memory memory.json
    → updates memory.json, stdout: summary line

Exit code 0 on success, 1 on error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_ENTRIES_PER_CATEGORY = 50
PATTERN_INTERVAL = 5  # summarize every N iterations
REPETITION_THRESHOLD = 0.5  # >50% overlap triggers a sign
REPETITION_LOOKBACK = 3  # compare against last N pattern entries

EMPTY_MEMORY: dict = {
    "patterns": [],
    "decisions": [],
    "fixes": [],
    "signs": [],
}


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Return current UTC time as compact ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# File I/O (atomic write)
# ---------------------------------------------------------------------------

def load_json(path: str) -> dict | None:
    """Load a JSON file. Returns None on any error."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def write_json_atomic(path: str, data: dict) -> None:
    """Atomically write JSON via temp file + rename in the same directory."""
    abs_path = os.path.abspath(path)
    parent = os.path.dirname(abs_path)
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, suffix=".tmp", prefix=".mem_")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, abs_path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# JSON block extraction from LLM response text
# ---------------------------------------------------------------------------

def extract_json_from_response(response: str) -> dict | None:
    """Try to extract a JSON object from an LLM response.

    Looks for ```json fenced blocks first, then falls back to finding
    the first top-level { ... } pair.
    """
    # Strategy 1: fenced code block
    match = re.search(r"```json\s*\n(.*?)```", response, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Strategy 2: any fenced block that looks like JSON
    match = re.search(r"```\s*\n(\{.*?\})\s*\n```", response, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Strategy 3: first { ... } in the raw text
    start = response.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(response)):
            if response[i] == "{":
                depth += 1
            elif response[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(response[start : i + 1])
                    except json.JSONDecodeError:
                        break

    return None


# ---------------------------------------------------------------------------
# Key mechanism extraction and repetition detection
# ---------------------------------------------------------------------------

def extract_key_mechanisms(idea: dict) -> list[str]:
    """Pull key_mechanisms from a parsed idea object.

    Handles both flat and nested structures:
      - idea["key_mechanisms"]
      - idea["data"]["key_mechanisms"]
    Returns lowercased mechanism strings for comparison.
    """
    mechanisms = idea.get("key_mechanisms")
    if mechanisms is None:
        data = idea.get("data", {})
        if isinstance(data, dict):
            mechanisms = data.get("key_mechanisms")
    if not isinstance(mechanisms, list):
        return []
    return [str(m).lower().strip() for m in mechanisms if m]


def compute_overlap(current: list[str], previous: list[str]) -> float:
    """Fraction of current mechanisms that appear in previous set.

    Returns 0.0 if current is empty.
    """
    if not current:
        return 0.0
    prev_set = set(previous)
    hits = sum(1 for m in current if m in prev_set)
    return hits / len(current)


def check_theme_repetition(
    mechanisms: list[str],
    recent_patterns: list[dict],
) -> list[str] | None:
    """Check if mechanisms overlap with recent pattern entries' mechanisms.

    Returns the list of repeated mechanisms, or None if below threshold.
    """
    if not mechanisms or not recent_patterns:
        return None

    # Collect all mechanisms from recent patterns that recorded them
    prev_mechanisms: list[str] = []
    for entry in recent_patterns:
        detail = entry.get("detail", "")
        # Patterns may store mechanisms in their detail or mechanisms field
        stored = entry.get("mechanisms", [])
        if isinstance(stored, list):
            prev_mechanisms.extend(str(m).lower().strip() for m in stored)

    if not prev_mechanisms:
        return None

    overlap = compute_overlap(mechanisms, prev_mechanisms)
    if overlap > REPETITION_THRESHOLD:
        repeated = [m for m in mechanisms if m in set(prev_mechanisms)]
        return repeated

    return None


# ---------------------------------------------------------------------------
# Memory entry builders
# ---------------------------------------------------------------------------

def make_fix_entry(iteration: int, model: str, detail: str) -> dict:
    return {
        "iteration": iteration,
        "model": model,
        "type": "error",
        "detail": detail,
        "timestamp": _now_iso(),
    }


def make_decision_entry(iteration: int, model: str) -> dict:
    return {
        "iteration": iteration,
        "model": model,
        "type": "model_lens",
        "detail": f"Used {model}",
        "timestamp": _now_iso(),
    }


def make_sign_entry(iteration: int, repeated: list[str]) -> dict:
    return {
        "iteration": iteration,
        "type": "theme_repetition",
        "detail": f"Repeated mechanisms: {repeated}",
        "timestamp": _now_iso(),
    }


def make_pattern_summary(
    iteration: int,
    decisions: list[dict],
    fixes: list[dict],
) -> dict:
    """Build a pattern summary entry for the last PATTERN_INTERVAL iterations.

    Summarizes: model distribution, success rate, common themes.
    """
    window_start = max(0, iteration - PATTERN_INTERVAL + 1)
    # Filter decisions and fixes within the window
    window_decisions = [
        d for d in decisions
        if isinstance(d.get("iteration"), int) and window_start <= d["iteration"] <= iteration
    ]
    window_fixes = [
        f for f in fixes
        if isinstance(f.get("iteration"), int) and window_start <= f["iteration"] <= iteration
    ]

    # Model distribution
    models = [d.get("model", "?") for d in window_decisions]
    model_dist = dict(Counter(models).most_common())

    # Success rate
    total = len(window_decisions) + len(window_fixes)
    successes = len(window_decisions)
    rate = (successes / total * 100) if total > 0 else 0

    detail = (
        f"Iterations {window_start}-{iteration}: "
        f"models={model_dist}, success_rate={rate:.0f}% ({successes}/{total})"
    )

    return {
        "iteration": iteration,
        "type": "periodic_summary",
        "detail": detail,
        "timestamp": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Cap helper
# ---------------------------------------------------------------------------

def cap_entries(entries: list, max_size: int = MAX_ENTRIES_PER_CATEGORY) -> list:
    """Keep only the last max_size entries (FIFO)."""
    if len(entries) > max_size:
        return entries[-max_size:]
    return entries


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def update_memory(result: dict, memory: dict) -> int:
    """Analyze result and update memory in-place. Returns count of new entries."""
    added = 0
    iteration = result.get("iteration", 0)
    model = result.get("model", "unknown")
    success = result.get("success", False)
    error = result.get("error")
    response = result.get("response", "")

    # --- Failed iteration → fix entry ---
    if not success:
        detail = error if error else "Unknown failure"
        memory["fixes"].append(make_fix_entry(iteration, model, detail))
        added += 1

    # --- Successful iteration → decision + optional sign ---
    if success:
        # Record model choice as decision
        memory["decisions"].append(make_decision_entry(iteration, model))
        added += 1

        # Try to parse response as idea JSON
        idea = extract_json_from_response(response) if response else None
        if idea and isinstance(idea, dict):
            mechanisms = extract_key_mechanisms(idea)

            if mechanisms:
                # Check for theme repetition against recent patterns
                recent = memory["patterns"][-REPETITION_LOOKBACK:]
                repeated = check_theme_repetition(mechanisms, recent)
                if repeated:
                    memory["signs"].append(make_sign_entry(iteration, repeated))
                    added += 1

    # --- Periodic pattern summary every PATTERN_INTERVAL iterations ---
    if iteration > 0 and iteration % PATTERN_INTERVAL == 0:
        summary = make_pattern_summary(
            iteration, memory["decisions"], memory["fixes"]
        )
        memory["patterns"].append(summary)
        added += 1

    # --- Cap all categories ---
    for key in ("patterns", "decisions", "fixes", "signs"):
        memory[key] = cap_entries(memory[key])

    return added


# ---------------------------------------------------------------------------
# Summary line
# ---------------------------------------------------------------------------

def format_summary(added: int, memory: dict) -> str:
    """Build the stdout summary string."""
    p = len(memory["patterns"])
    d = len(memory["decisions"])
    f = len(memory["fixes"])
    s = len(memory["signs"])
    return f"memory: +{added} entries ({p}p/{d}d/{f}f/{s}s total)"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Pattern/decision/fix/signs taxonomy memory for the Ralph Loop.",
    )
    p.add_argument(
        "--result", required=True,
        help="Path to the iteration result JSON file.",
    )
    p.add_argument(
        "--memory", required=True,
        help="Path to memory.json (created if missing).",
    )
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Load result
    result = load_json(args.result)
    if result is None:
        # Can't parse result — still record a fix about the parse failure
        memory = load_json(args.memory)
        if not isinstance(memory, dict):
            memory = dict(EMPTY_MEMORY)
        for key in EMPTY_MEMORY:
            if key not in memory:
                memory[key] = []
        memory["fixes"].append(make_fix_entry(
            0, "unknown",
            f"Failed to parse result file: {args.result}",
        ))
        memory["fixes"] = cap_entries(memory["fixes"])
        try:
            write_json_atomic(args.memory, memory)
        except OSError as e:
            print(f"ERROR: failed to write memory: {e}", file=sys.stderr)
            return 1
        print(format_summary(1, memory))
        return 0

    # Load or initialize memory
    memory = load_json(args.memory)
    if not isinstance(memory, dict):
        memory = dict(EMPTY_MEMORY)
    # Ensure all categories exist
    for key in EMPTY_MEMORY:
        if key not in memory:
            memory[key] = []

    # Update
    added = update_memory(result, memory)

    # Write
    try:
        write_json_atomic(args.memory, memory)
    except OSError as e:
        print(f"ERROR: failed to write memory: {e}", file=sys.stderr)
        return 1

    print(format_summary(added, memory))
    return 0


if __name__ == "__main__":
    sys.exit(main())
