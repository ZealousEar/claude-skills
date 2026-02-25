#!/usr/bin/env python3
"""Benchmark-driven stochastic model selection for the Ralph Loop.

Selects the next model for an iteration using weighted stochastic sampling.
Weights come from benchmark-profiles.json (domain-specific). Recently-used
models get a recency penalty to encourage diversity. Circuit-broken models
are excluded entirely.

Usage:
    python3 model_selector.py --config ralph-config.json --domain academic
    python3 model_selector.py --config ralph-config.json --domain academic \
        --history iterations.jsonl --circuit-state circuit-state.json

Output:
    Prints a single model name to stdout (e.g., "opus").
    Exit 0 on success, 1 on error (message to stderr).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def expand_path(raw: str, base_dir: Path | None = None) -> Path:
    """Expand ~ and resolve relative paths against an optional base."""
    p = Path(raw).expanduser()
    if not p.is_absolute() and base_dir is not None:
        p = base_dir / p
    return p.resolve()


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_json(path: Path, label: str) -> dict:
    """Load a JSON file or die with a clear error."""
    if not path.exists():
        fatal(f"{label} not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        fatal(f"Failed to parse {label} ({path}): {exc}")


def load_config(config_path: Path) -> dict:
    """Load and validate ralph-config.json."""
    cfg = load_json(config_path, "config")
    # Ensure required sections exist
    if "model_selection" not in cfg:
        fatal("Config missing 'model_selection' section")
    if "paths" not in cfg:
        fatal("Config missing 'paths' section")
    return cfg


def load_benchmark_profiles(cfg: dict, config_dir: Path) -> dict:
    """Load benchmark-profiles.json from the path declared in config."""
    raw_path = cfg.get("paths", {}).get("benchmark_profiles", "")
    if not raw_path:
        fatal("Config paths.benchmark_profiles not set")
    bp_path = expand_path(raw_path, base_dir=config_dir)
    return load_json(bp_path, "benchmark-profiles")


# ---------------------------------------------------------------------------
# Circuit breaker state
# ---------------------------------------------------------------------------

def load_circuit_state(path: Path | None) -> dict[str, str]:
    """Load circuit-state.json -> {model_name: state_string}.

    If file doesn't exist or path is None, returns empty dict (all CLOSED).
    Recognized states: CLOSED, OPEN, HALF_OPEN.
    """
    if path is None or not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Corrupt file -> treat as all-CLOSED (safe default)
        return {}

    states: dict[str, str] = {}
    # Support both flat {model: state} and nested {model: {state: ...}} forms
    if isinstance(raw, dict):
        for model, value in raw.items():
            if isinstance(value, str):
                states[model] = value.upper()
            elif isinstance(value, dict):
                states[model] = str(value.get("state", "CLOSED")).upper()
    return states


def is_circuit_open(states: dict[str, str], model: str) -> bool:
    """Return True if the model's circuit breaker is OPEN (skip it)."""
    return states.get(model, "CLOSED") == "OPEN"


# ---------------------------------------------------------------------------
# Iteration history (recency)
# ---------------------------------------------------------------------------

def load_recent_models(path: Path | None, window: int) -> list[str]:
    """Read the last `window` entries from iterations.jsonl, return model names.

    Returns an empty list if file doesn't exist or is empty.
    """
    if path is None or not path.exists() or window <= 0:
        return []
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return []

    # Take the last `window` non-empty lines
    recent_lines = [ln for ln in lines if ln.strip()][-window:]
    models: list[str] = []
    for line in recent_lines:
        try:
            entry = json.loads(line)
            m = entry.get("model")
            if isinstance(m, str) and m:
                models.append(m)
        except json.JSONDecodeError:
            continue
    return models


# ---------------------------------------------------------------------------
# Weight computation
# ---------------------------------------------------------------------------

def get_domain_weight(
    profiles: dict,
    domain: str,
    model: str,
    default_weight: float = 0.5,
) -> float:
    """Look up domain weight for a model from benchmark-profiles.json.

    Expected structure:
        domains.<domain>.models.<model>.weight  (float 0-1)

    Falls back to `default_weight` if not found.
    """
    domains = profiles.get("domains", {})
    domain_cfg = domains.get(domain, {})
    models_cfg = domain_cfg.get("models", {})
    model_cfg = models_cfg.get(model, {})

    weight = model_cfg.get("weight", default_weight)
    # Clamp to [0, 1]
    try:
        weight = float(weight)
    except (TypeError, ValueError):
        weight = default_weight
    return max(0.0, min(1.0, weight))


def compute_weights(
    candidates: list[str],
    profiles: dict,
    domain: str,
    recent_models: list[str],
    exploration_weight: float,
) -> dict[str, float]:
    """Compute sampling weights for each candidate model.

    Steps:
        1. Start with domain weight from benchmark-profiles.json.
        2. For each occurrence in recent history, multiply by (1 - exploration_weight).
        3. Ensure weight >= tiny epsilon so no model is completely zeroed out
           (circuit-open models are already excluded before this step).
    """
    weights: dict[str, float] = {}
    penalty_factor = 1.0 - exploration_weight

    for model in candidates:
        w = get_domain_weight(profiles, domain, model)

        # Apply recency penalty: one multiplicative hit per recent occurrence
        occurrences = recent_models.count(model)
        for _ in range(occurrences):
            w *= penalty_factor

        # Floor at a small epsilon so every eligible model has some chance
        weights[model] = max(w, 1e-6)

    return weights


def normalize(weights: dict[str, float]) -> dict[str, float]:
    """Normalize weights to sum to 1.0."""
    total = sum(weights.values())
    if total <= 0:
        # Shouldn't happen after epsilon floor, but be safe
        n = len(weights)
        return {m: 1.0 / n for m in weights} if n > 0 else {}
    return {m: w / total for m, w in weights.items()}


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def select_model(
    config: dict,
    profiles: dict,
    domain: str,
    circuit_states: dict[str, str],
    recent_models: list[str],
) -> str:
    """Run the full selection algorithm and return a single model name."""

    ms_cfg = config["model_selection"]
    preferred = ms_cfg.get("preferred_models", [])
    excluded = set(ms_cfg.get("excluded_models", []))
    exploration_weight = float(ms_cfg.get("exploration_weight", 0.3))

    # Step 1: Start with preferred models, remove excluded
    candidates = [m for m in preferred if m not in excluded]

    # Step 2: Remove circuit-OPEN models
    candidates = [m for m in candidates if not is_circuit_open(circuit_states, m)]

    if not candidates:
        fatal("No eligible models: all are excluded or circuit-broken")

    # Step 3: Compute weights
    weights = compute_weights(
        candidates, profiles, domain, recent_models, exploration_weight
    )

    # Step 4: Normalize
    norm_weights = normalize(weights)

    # Step 5: Stochastic sample
    models = list(norm_weights.keys())
    probs = [norm_weights[m] for m in models]
    chosen = random.choices(models, weights=probs, k=1)[0]

    return chosen


# ---------------------------------------------------------------------------
# Diagnostics (stderr, never pollutes stdout)
# ---------------------------------------------------------------------------

def log_debug(msg: str) -> None:
    """Print a debug line to stderr."""
    print(f"[model_selector] {msg}", file=sys.stderr)


def fatal(msg: str) -> None:
    """Print error to stderr and exit 1. Typed as NoReturn but we avoid
    typing import to stay minimal."""
    print(f"[model_selector] ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark-driven stochastic model selector for Ralph Loop.",
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to ralph-config.json",
    )
    parser.add_argument(
        "--domain",
        required=True,
        help="Domain name for benchmark weighting (e.g., 'academic')",
    )
    parser.add_argument(
        "--preset",
        default=None,
        help="Preset name (reserved for future use — currently unused by selector)",
    )
    parser.add_argument(
        "--history",
        default=None,
        help="Path to iterations.jsonl for recency penalty",
    )
    parser.add_argument(
        "--circuit-state",
        default=None,
        help="Path to circuit-state.json",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducible selection (testing only)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print weight diagnostics to stderr",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Reproducibility hook (for tests)
    if args.seed is not None:
        random.seed(args.seed)

    # --- Load config ---
    config_path = expand_path(args.config)
    config = load_config(config_path)
    config_dir = config_path.parent

    # --- Load benchmark profiles ---
    profiles = load_benchmark_profiles(config, config_dir)

    # --- Domain ---
    domain = args.domain

    # --- Circuit breaker state ---
    cb_path = expand_path(args.circuit_state) if args.circuit_state else None
    circuit_states = load_circuit_state(cb_path)

    # --- History (recency) ---
    hist_path = expand_path(args.history) if args.history else None
    recency_window = int(
        config.get("model_selection", {}).get("recency_penalty_window", 5)
    )
    recent_models = load_recent_models(hist_path, recency_window)

    # --- Debug: show inputs ---
    if args.debug:
        ms_cfg = config["model_selection"]
        preferred = ms_cfg.get("preferred_models", [])
        excluded = ms_cfg.get("excluded_models", [])
        log_debug(f"domain={domain}")
        log_debug(f"preferred={preferred}")
        log_debug(f"excluded={excluded}")
        log_debug(f"circuit_states={circuit_states}")
        log_debug(f"recent_models (window={recency_window})={recent_models}")

    # --- Select ---
    chosen = select_model(config, profiles, domain, circuit_states, recent_models)

    # --- Debug: show weights ---
    if args.debug:
        ms_cfg = config["model_selection"]
        preferred = ms_cfg.get("preferred_models", [])
        excluded_set = set(ms_cfg.get("excluded_models", []))
        exploration_weight = float(ms_cfg.get("exploration_weight", 0.3))
        candidates = [
            m for m in preferred
            if m not in excluded_set and not is_circuit_open(circuit_states, m)
        ]
        weights = compute_weights(
            candidates, profiles, domain, recent_models, exploration_weight
        )
        norm = normalize(weights)
        log_debug("Final weights:")
        for m in sorted(norm, key=norm.get, reverse=True):
            log_debug(f"  {m}: {norm[m]:.4f} (raw={weights[m]:.6f})")
        log_debug(f"Selected: {chosen}")

    # --- Output ---
    print(chosen)


if __name__ == "__main__":
    main()
