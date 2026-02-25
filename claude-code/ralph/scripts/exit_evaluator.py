#!/usr/bin/env python3
"""Dual-condition exit gate for the Ralph Loop.

Evaluates whether the loop should continue or stop based on:
  1. Saturation detection — score improvement stalls across recent ideas.
  2. Budget limits — hard caps on iteration count and wall-clock runtime.

Returns CONTINUE unless BOTH saturation is detected AND a minimum idea count
is met, OR a hard limit is hit.

Usage:
    python exit_evaluator.py --ideas-bank ideas-bank.json --session session.json --config ralph-config.json
    → stdout: "CONTINUE" | "SATURATION: <reason>" | "HARD_LIMIT: <reason>"

Exit code is always 0. The stdout value is the signal.
"""

import argparse
import json
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

def load_json(path: str) -> dict | None:
    """Load a JSON file. Returns None on any error."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def load_config(path: str) -> dict:
    """Load exit_gate section from ralph-config.json with safe defaults."""
    defaults = {
        "saturation_window": 10,
        "saturation_threshold": 0.15,
        "min_unique_ideas": 5,
        "hard_limit_iterations": 200,
        "hard_limit_hours": 8,
    }
    data = load_json(path)
    if data and "exit_gate" in data:
        gate = data["exit_gate"]
        defaults.update({k: gate[k] for k in defaults if k in gate})
    return defaults


# ---------------------------------------------------------------------------
# Hard limit checks
# ---------------------------------------------------------------------------

def check_hard_limits(session: dict, config: dict) -> str | None:
    """Return a HARD_LIMIT reason string, or None if within limits."""
    iteration = session.get("iteration", 0)
    max_iter = config["hard_limit_iterations"]
    if iteration >= max_iter:
        return f"HARD_LIMIT: reached {iteration} iterations"

    started_at = session.get("started_at")
    if started_at is not None:
        elapsed_hours = (time.time() - started_at) / 3600
        max_hours = config["hard_limit_hours"]
        if elapsed_hours >= max_hours:
            return f"HARD_LIMIT: exceeded {max_hours} hours runtime"

    return None


# ---------------------------------------------------------------------------
# Saturation detection
# ---------------------------------------------------------------------------

def extract_sorted_scores(ideas_bank: dict) -> list[float]:
    """Extract combined_score values from ideas, sorted by iteration (ascending).

    Looks for ideas in ideas_bank["ideas"] (list of dicts). Each idea should
    have a 'combined_score' field and an 'iteration' field for ordering.
    Falls back to list order if 'iteration' is missing.
    """
    ideas = ideas_bank.get("ideas", [])
    if not ideas:
        return []

    # Sort by iteration number; fall back to original order
    def sort_key(idea: dict) -> int:
        return idea.get("iteration", 0)

    sorted_ideas = sorted(ideas, key=sort_key)
    scores = []
    for idea in sorted_ideas:
        score = idea.get("combined_score")
        if score is not None:
            try:
                scores.append(float(score))
            except (TypeError, ValueError):
                continue
    return scores


def check_saturation(ideas_bank: dict, config: dict) -> str | None:
    """Return a SATURATION reason string, or None if not saturated.

    Algorithm:
      - Need at least min_unique_ideas unique ideas before checking.
      - Need at least 2 * saturation_window scores for a meaningful comparison.
      - Compare max score in the recent window vs max score in the previous window.
      - If improvement < threshold, ideas are saturating.
    """
    unique_count = 0
    stats = ideas_bank.get("stats", {})
    if stats:
        unique_count = stats.get("unique", 0)
    else:
        # Fallback: count ideas directly
        unique_count = len(ideas_bank.get("ideas", []))

    window = config["saturation_window"]
    threshold = config["saturation_threshold"]
    min_unique = config["min_unique_ideas"]

    # Not enough ideas to assess saturation
    if unique_count < min_unique:
        return None

    scores = extract_sorted_scores(ideas_bank)

    # Need at least 2 full windows for comparison
    if len(scores) < 2 * window:
        return None

    # Recent window: last `window` scores
    recent_max = max(scores[-window:])
    # Previous window: the `window` scores before that
    previous_max = max(scores[-2 * window : -window])

    improvement = recent_max - previous_max

    if improvement < threshold:
        return (
            f"SATURATION: score improvement {improvement:.3f} < "
            f"threshold {threshold} over last {window} ideas"
        )

    return None


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------

def evaluate(ideas_bank_path: str, session_path: str, config_path: str) -> str:
    """Run the full exit evaluation. Returns exactly one status line."""
    config = load_config(config_path)

    # Load session — if missing, no hard limit can fire on iteration/time
    session = load_json(session_path) or {}

    # Hard limits are checked first — they override everything
    hard = check_hard_limits(session, config)
    if hard:
        return hard

    # Load ideas bank — if missing or empty, always continue
    ideas_bank = load_json(ideas_bank_path) or {}

    saturation = check_saturation(ideas_bank, config)
    if saturation:
        return saturation

    return "CONTINUE"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Dual-condition exit gate for the Ralph Loop."
    )
    p.add_argument(
        "--ideas-bank", required=True,
        help="Path to ideas-bank.json",
    )
    p.add_argument(
        "--session", required=True,
        help="Path to session.json",
    )
    p.add_argument(
        "--config", required=True,
        help="Path to ralph-config.json",
    )
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    result = evaluate(args.ideas_bank, args.session, args.config)
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
