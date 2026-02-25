#!/usr/bin/env python3
"""3-state per-model circuit breaker for the Ralph Loop.

States: CLOSED (normal) -> OPEN (blocked) -> HALF_OPEN (test attempt).

Usage:
    python circuit_breaker.py --check --model opus --state circuit-state.json
    python circuit_breaker.py --cooldown-remaining --model opus --state circuit-state.json
    python circuit_breaker.py --record-success --model opus --state circuit-state.json
    python circuit_breaker.py --record-failure "timeout" --model opus --state circuit-state.json
"""

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

STATES = ("CLOSED", "OPEN", "HALF_OPEN")

DEFAULT_CONFIG_PATH = Path("~/.claude/skills/ralph/settings/ralph-config.json").expanduser()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """Load circuit_breaker defaults from ralph-config.json."""
    defaults = {"failure_threshold": 3, "cooldown_seconds": 300, "half_open_max_attempts": 1}
    try:
        with open(DEFAULT_CONFIG_PATH, "r") as f:
            cfg = json.load(f)
        cb = cfg.get("circuit_breaker", {})
        defaults.update({k: cb[k] for k in defaults if k in cb})
    except (OSError, json.JSONDecodeError):
        pass
    return defaults


# ---------------------------------------------------------------------------
# State I/O — atomic read-modify-write
# ---------------------------------------------------------------------------

def read_state(state_path: str) -> dict:
    """Read the circuit-state JSON file. Returns {} if missing or invalid."""
    try:
        with open(state_path, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def write_state(state_path: str, data: dict) -> None:
    """Atomically write state via temp file + rename in the same directory."""
    state_dir = os.path.dirname(os.path.abspath(state_path))
    os.makedirs(state_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=state_dir, suffix=".tmp", prefix=".cb_")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, state_path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def get_model_entry(state: dict, model: str, config: dict) -> dict:
    """Return the model's entry, initializing to CLOSED if absent."""
    if model not in state:
        state[model] = {
            "state": "CLOSED",
            "failures": 0,
            "cooldown_seconds": config["cooldown_seconds"],
            "opened_at": None,
            "last_failure": None,
            "last_failure_reason": None,
        }
    return state[model]


# ---------------------------------------------------------------------------
# State machine transitions
# ---------------------------------------------------------------------------

def check_state(entry: dict, config: dict) -> str:
    """Return the effective state, auto-transitioning OPEN -> HALF_OPEN on cooldown expiry."""
    if entry["state"] == "OPEN" and entry["opened_at"] is not None:
        elapsed = time.time() - entry["opened_at"]
        if elapsed >= entry["cooldown_seconds"]:
            entry["state"] = "HALF_OPEN"
    return entry["state"]


def cooldown_remaining(entry: dict) -> int:
    """Seconds until OPEN -> HALF_OPEN transition. 0 if not OPEN."""
    if entry["state"] != "OPEN" or entry["opened_at"] is None:
        return 0
    remaining = entry["cooldown_seconds"] - (time.time() - entry["opened_at"])
    return max(0, int(remaining))


def record_success(entry: dict, config: dict) -> str:
    """Record a successful call. Returns the new state name."""
    current = check_state(entry, config)
    # HALF_OPEN success -> CLOSED, reset everything
    # CLOSED success -> reset consecutive failures
    entry["state"] = "CLOSED"
    entry["failures"] = 0
    entry["opened_at"] = None
    return entry["state"]


def record_failure(entry: dict, reason: str, config: dict) -> str:
    """Record a failed call. Returns the new state name."""
    now = time.time()
    current = check_state(entry, config)
    entry["last_failure"] = now
    entry["last_failure_reason"] = reason

    if current == "HALF_OPEN":
        # Test attempt failed -> back to OPEN, double cooldown (max 3600s)
        entry["state"] = "OPEN"
        entry["opened_at"] = now
        entry["cooldown_seconds"] = min(entry["cooldown_seconds"] * 2, 3600)
        return entry["state"]

    if current == "CLOSED":
        entry["failures"] += 1
        if entry["failures"] >= config["failure_threshold"]:
            entry["state"] = "OPEN"
            entry["opened_at"] = now
        return entry["state"]

    # Already OPEN — just update failure metadata, stay OPEN
    entry["failures"] += 1
    return entry["state"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Per-model circuit breaker for the Ralph Loop."
    )

    action = p.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true",
                        help="Print the effective state (CLOSED|OPEN|HALF_OPEN)")
    action.add_argument("--cooldown-remaining", action="store_true",
                        help="Print seconds until OPEN -> HALF_OPEN (0 if not OPEN)")
    action.add_argument("--record-success", action="store_true",
                        help="Record a successful call for the model")
    action.add_argument("--record-failure", metavar="REASON", type=str, default=None,
                        help="Record a failed call with the given reason")

    p.add_argument("--model", required=True, help="Model name (e.g. opus, gemini-3-pro)")
    p.add_argument("--state", required=True, help="Path to circuit-state.json")
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    config = load_config()
    state = read_state(args.state)
    entry = get_model_entry(state, args.model, config)

    if args.check:
        effective = check_state(entry, config)
        # Write back in case OPEN -> HALF_OPEN transition occurred
        write_state(args.state, state)
        print(effective)
        return 0

    if args.cooldown_remaining:
        # Compute without mutating state
        secs = cooldown_remaining(entry)
        print(secs)
        return 0

    if args.record_success:
        new_state = record_success(entry, config)
        write_state(args.state, state)
        print(new_state)
        return 0

    if args.record_failure is not None:
        new_state = record_failure(entry, args.record_failure, config)
        write_state(args.state, state)
        print(new_state)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
