from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path


DEFAULT_CHANNELS = [
    "graph_explorer",
    "analogy_transfer",
    "exploit_refiner",
    "constraint_injection",
]
DEFAULT_FAILURE_REASONS = {
    "data_gate": 0,
    "complexity_gate": 0,
    "identifiability_gate": 0,
    "novelty_gate": 0,
    "ethics_gate": 0,
    "tournament_bottom": 0,
}
GATE_REASON_MAP = {
    "data": "data_gate",
    "data_gate": "data_gate",
    "complexity": "complexity_gate",
    "complexity_gate": "complexity_gate",
    "identifiability": "identifiability_gate",
    "identifiability_gate": "identifiability_gate",
    "novelty": "novelty_gate",
    "novelty_gate": "novelty_gate",
    "ethics": "ethics_gate",
    "ethics_gate": "ethics_gate",
}


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Persistent failure tracking and Thompson-Sampling channel reweighting."
    )
    parser.add_argument("--input", required=True, help="Path to current round idea outcomes JSON")
    parser.add_argument("--ledger", required=True, help="Path to persistent ledger JSON")
    parser.add_argument(
        "--success-quantile",
        type=float,
        default=0.5,
        help="Top q proportion is success (default: 0.5)",
    )
    parser.add_argument(
        "--exploration-floor",
        type=float,
        default=0.10,
        help="Minimum allocation floor per channel before renormalization (default: 0.10)",
    )
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for Thompson sampling")
    parser.add_argument("--output", default="-", help="Output path (default: stdout)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate input/ledger shape only without mutating ledger",
    )
    return parser.parse_args(argv)


def default_channel_state() -> dict[str, int]:
    """Create default Beta-Bernoulli state for a channel."""
    return {"alpha": 1, "beta": 1, "successes": 0, "failures": 0, "total": 0}


def default_ledger() -> dict[str, object]:
    """Create a new ledger object with default channels and reasons."""
    return {
        "channels": {name: default_channel_state() for name in DEFAULT_CHANNELS},
        "failure_reasons": dict(DEFAULT_FAILURE_REASONS),
        "history": [],
    }


def load_json_file(path: Path) -> object:
    """Load JSON from a path."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def write_json_file(path: Path, payload: object) -> None:
    """Write JSON to a file path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def emit_json(payload: object, output_path: str, pretty: bool) -> None:
    """Emit JSON payload to stdout or file."""
    rendered = json.dumps(payload, indent=2 if pretty else None)
    if output_path == "-":
        sys.stdout.write(rendered + "\n")
        return
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered + "\n", encoding="utf-8")


def coerce_bool(value: object) -> bool:
    """Coerce common truthy/falsy encodings into bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def normalize_reason_token(raw: object) -> str | None:
    """Normalize a gate reason token to canonical failure reason key."""
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip().lower().replace("-", "_").replace(" ", "_")
    if cleaned in GATE_REASON_MAP:
        return GATE_REASON_MAP[cleaned]
    return None


def percentile_from_item(item: dict[str, object], idx: int) -> float:
    """Extract percentile in [0, 1] from item or rank/total fallback."""
    raw = item.get("tournament_percentile")
    if raw is not None:
        try:
            pct = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"Entry {idx} has invalid tournament_percentile")
        if not math.isfinite(pct) or pct < 0.0 or pct > 1.0:
            raise ValueError(f"Entry {idx} tournament_percentile must be in [0, 1]")
        return pct
    rank = item.get("tournament_rank")
    total = item.get("total_in_tournament")
    if rank is None or total is None:
        raise ValueError(
            f"Entry {idx} must provide tournament_percentile or both tournament_rank and total_in_tournament"
        )
    try:
        rank_value = int(rank)
        total_value = int(total)
    except (TypeError, ValueError):
        raise ValueError(f"Entry {idx} has invalid tournament rank fields")
    if total_value <= 0 or rank_value <= 0 or rank_value > total_value:
        raise ValueError(f"Entry {idx} has out-of-range rank/total values")
    if total_value == 1:
        return 1.0
    return 1.0 - (rank_value - 1) / (total_value - 1)


def extract_failure_reason(item: dict[str, object]) -> str:
    """Infer canonical failure reason key for a failed item."""
    direct = normalize_reason_token(item.get("failure_reason"))
    if direct is not None:
        return direct
    failed_gates = item.get("failed_gates")
    if isinstance(failed_gates, list):
        for gate in failed_gates:
            mapped = normalize_reason_token(gate)
            if mapped is not None:
                return mapped
    gates = item.get("gates")
    if isinstance(gates, dict):
        for gate, gate_payload in gates.items():
            if isinstance(gate_payload, dict):
                if not coerce_bool(gate_payload.get("pass", False)):
                    mapped = normalize_reason_token(gate)
                    if mapped is not None:
                        return mapped
    return "data_gate"


def normalize_channel_state(payload: object) -> dict[str, int]:
    """Normalize channel state dict with required numeric fields."""
    base = default_channel_state()
    state = payload if isinstance(payload, dict) else {}
    normalized: dict[str, int] = {}
    for key, minimum in (("alpha", 1), ("beta", 1), ("successes", 0), ("failures", 0), ("total", 0)):
        raw = state.get(key, base[key]) if isinstance(state, dict) else base[key]
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = base[key]
        if value < minimum:
            value = minimum
        normalized[key] = value
    return normalized


def load_or_create_ledger(path: Path) -> dict[str, object]:
    """Load an existing ledger, or create default structure."""
    if not path.exists():
        return default_ledger()
    raw = load_json_file(path)
    if not isinstance(raw, dict):
        raise ValueError("Ledger must be a JSON object")
    channels_raw = raw.get("channels")
    channels: dict[str, dict[str, int]] = {}
    if isinstance(channels_raw, dict):
        for channel, state in channels_raw.items():
            if isinstance(channel, str) and channel.strip():
                channels[channel.strip()] = normalize_channel_state(state)
    for channel in DEFAULT_CHANNELS:
        channels.setdefault(channel, default_channel_state())

    reasons_raw = raw.get("failure_reasons")
    reasons = dict(DEFAULT_FAILURE_REASONS)
    if isinstance(reasons_raw, dict):
        for key, value in reasons_raw.items():
            if isinstance(key, str) and key in reasons:
                try:
                    reasons[key] = max(0, int(value))
                except (TypeError, ValueError):
                    reasons[key] = reasons[key]

    history_raw = raw.get("history")
    history = history_raw if isinstance(history_raw, list) else []
    return {"channels": channels, "failure_reasons": reasons, "history": history}


def validate_round_input(ideas_raw: object) -> list[dict[str, object]]:
    """Validate and normalize the round input payload."""
    if not isinstance(ideas_raw, list):
        raise ValueError("Input must be a JSON array")
    normalized: list[dict[str, object]] = []
    for idx, item in enumerate(ideas_raw):
        if not isinstance(item, dict):
            raise ValueError(f"Entry {idx} is not an object")
        channel = item.get("channel")
        if not isinstance(channel, str) or not channel.strip():
            raise ValueError(f"Entry {idx} has invalid channel")
        _ = percentile_from_item(item, idx)
        normalized.append(item)
    return normalized


def sample_channel_weights(
    channels: dict[str, dict[str, int]], exploration_floor: float
) -> tuple[dict[str, float], dict[str, float]]:
    """Draw Beta samples per channel, normalize, and apply allocation floor."""
    sampled = {
        name: random.betavariate(float(state["alpha"]), float(state["beta"]))
        for name, state in channels.items()
    }
    total = sum(sampled.values())
    if total <= 0:
        normalized = {name: 1.0 / len(sampled) for name in sampled}
    else:
        normalized = {name: sampled[name] / total for name in sampled}

    n_channels = len(normalized)
    if n_channels == 0:
        return {}, sampled
    floor = max(0.0, min(float(exploration_floor), 1.0 / n_channels))
    adjusted = {name: max(weight, floor) for name, weight in normalized.items()}
    adjusted_total = sum(adjusted.values())
    weights = {name: adjusted[name] / adjusted_total for name in adjusted}
    return weights, sampled


def unchanged_weights_from_history(ledger: dict[str, object]) -> dict[str, float]:
    """Return last known weights if available, otherwise uniform."""
    channels = ledger["channels"]
    history = ledger.get("history")
    if isinstance(history, list) and history:
        last = history[-1]
        if isinstance(last, dict):
            prev = last.get("channel_weights")
            if isinstance(prev, dict):
                copied: dict[str, float] = {}
                for channel in channels:
                    raw = prev.get(channel, 0.0)
                    try:
                        copied[channel] = max(0.0, float(raw))
                    except (TypeError, ValueError):
                        copied[channel] = 0.0
                total = sum(copied.values())
                if total > 0.0:
                    return {channel: copied[channel] / total for channel in copied}
    return {channel: 1.0 / len(channels) for channel in channels}


def build_recommendation(channel_stats: dict[str, dict[str, float]]) -> str:
    """Build recommendation text from observed success rates."""
    if not channel_stats:
        return "No channels available."
    sorted_items = sorted(channel_stats.items(), key=lambda kv: kv[1]["success_rate"], reverse=True)
    best_name, best_stats = sorted_items[0]
    worst_name, worst_stats = sorted_items[-1]
    if math.isclose(best_stats["success_rate"], worst_stats["success_rate"], rel_tol=1e-12, abs_tol=1e-12):
        return "Maintain balanced allocation across channels (similar observed success rates)."
    return (
        f"Increase {best_name} allocation (highest success rate). "
        f"Reduce {worst_name} (lowest)."
    )


def process_round(
    ideas: list[dict[str, object]],
    ledger: dict[str, object],
    success_quantile: float,
    exploration_floor: float,
) -> tuple[dict[str, object], dict[str, object]]:
    """Update ledger with current round outcomes and compute next-round weights."""
    threshold = 1.0 - success_quantile
    channels: dict[str, dict[str, int]] = ledger["channels"]  # type: ignore[assignment]
    failure_reasons: dict[str, int] = ledger["failure_reasons"]  # type: ignore[assignment]

    round_failure = {name: 0 for name in failure_reasons}
    successes = 0
    failures = 0
    per_channel_round: dict[str, dict[str, int]] = {}

    for idx, item in enumerate(ideas):
        channel = str(item["channel"]).strip()
        channels.setdefault(channel, default_channel_state())
        percentile = percentile_from_item(item, idx)
        gates_passed = coerce_bool(item.get("gates_passed", item.get("overall_pass", False)))
        is_success = gates_passed and percentile >= threshold
        per_channel_round.setdefault(channel, {"successes": 0, "failures": 0})
        if is_success:
            channels[channel]["alpha"] += 1
            channels[channel]["successes"] += 1
            channels[channel]["total"] += 1
            per_channel_round[channel]["successes"] += 1
            successes += 1
            continue
        channels[channel]["beta"] += 1
        channels[channel]["failures"] += 1
        channels[channel]["total"] += 1
        per_channel_round[channel]["failures"] += 1
        failures += 1
        reason = extract_failure_reason(item) if not gates_passed else "tournament_bottom"
        failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
        round_failure[reason] = round_failure.get(reason, 0) + 1

    if ideas:
        weights, sampled = sample_channel_weights(channels, exploration_floor)
    else:
        weights = unchanged_weights_from_history(ledger)
        sampled = {name: weights[name] for name in weights}

    channel_stats: dict[str, dict[str, float | int]] = {}
    for channel, state in channels.items():
        total = float(state["total"])
        success_rate = (float(state["successes"]) / total) if total > 0.0 else 0.0
        channel_stats[channel] = {
            "alpha": state["alpha"],
            "beta": state["beta"],
            "success_rate": success_rate,
            "sampled_theta": float(sampled.get(channel, 0.0)),
        }

    total_ideas = len(ideas)
    round_summary = {
        "total_ideas": total_ideas,
        "successes": successes,
        "failures": failures,
        "success_rate": (float(successes) / float(total_ideas)) if total_ideas else 0.0,
    }
    payload = {
        "channel_weights": weights,
        "channel_stats": channel_stats,
        "round_summary": round_summary,
        "failure_breakdown": round_failure,
        "recommendation": build_recommendation(channel_stats),
    }
    history_entry = {
        "timestamp": 0.0,
        "success_quantile": success_quantile,
        "exploration_floor": exploration_floor,
        "round_summary": round_summary,
        "failure_breakdown": round_failure,
        "channel_deltas": per_channel_round,
        "channel_weights": weights,
    }
    ledger["history"].append(history_entry)  # type: ignore[index]
    return payload, ledger


def main() -> None:
    """CLI entrypoint."""
    args = parse_args(sys.argv[1:])
    try:
        if not 0.0 <= args.success_quantile <= 1.0:
            raise ValueError("--success-quantile must be in [0, 1]")
        if args.exploration_floor < 0.0:
            raise ValueError("--exploration-floor must be >= 0")

        ideas = validate_round_input(load_json_file(Path(args.input)))
        ledger_path = Path(args.ledger)
        ledger = load_or_create_ledger(ledger_path)

        if args.validate:
            emit_json(
                {
                    "valid": True,
                    "metadata": {
                        "ideas": len(ideas),
                        "channels": len(ledger["channels"]),
                        "ledger_exists": ledger_path.exists(),
                    },
                },
                args.output,
                args.pretty,
            )
            return

        random.seed(args.seed)
        output_payload, updated_ledger = process_round(
            ideas=ideas,
            ledger=ledger,
            success_quantile=float(args.success_quantile),
            exploration_floor=float(args.exploration_floor),
        )

        write_json_file(ledger_path, updated_ledger)
        timestamp = float(ledger_path.stat().st_mtime)
        history = updated_ledger["history"]
        if isinstance(history, list) and history:
            latest = history[-1]
            if isinstance(latest, dict):
                latest["timestamp"] = timestamp
                write_json_file(ledger_path, updated_ledger)

        emit_json(output_payload, args.output, args.pretty)
    except (ValueError, FileNotFoundError) as exc:
        sys.stderr.write(f"{exc}\n")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
