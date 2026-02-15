#!/usr/bin/env python3
"""Compute judge reliability weights from calibration judgments."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

TIER_RANK: dict[str, int] = {"low": 1, "mid": 2, "high": 3}
TIER_KEYS: tuple[str, str, str] = ("high", "mid", "low")
PAIR_KEYS: tuple[str, str, str] = ("high_vs_mid", "high_vs_low", "mid_vs_low")
Z_95 = 1.959963984540054


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for calibration computation."""
    parser = argparse.ArgumentParser(
        description="Compute judge reliability weights from known-tier calibration judgments."
    )
    parser.add_argument("--pack", required=True, help="Path to calibration pack JSON file")
    parser.add_argument("--results", required=True, help="Path to calibration results JSON file")
    parser.add_argument(
        "--output",
        help="Output path for JSON report (defaults to stdout)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output with indentation",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate inputs and emit a validation report only",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a human-readable summary to stderr",
    )
    return parser.parse_args()


def load_json_file(path: Path) -> object:
    """Load and decode a JSON file."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Failed to read '{path}': {exc}") from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in '{path}' at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc


def extract_paper_tiers(pack_obj: object) -> dict[str, str]:
    """Validate calibration pack structure and return paper_id -> tier mapping."""
    if not isinstance(pack_obj, dict):
        raise ValueError("Calibration pack must be a JSON object")

    tiers_obj = pack_obj.get("tiers")
    if not isinstance(tiers_obj, dict):
        raise ValueError("Calibration pack must contain object key 'tiers'")

    errors: list[str] = []
    paper_tiers: dict[str, str] = {}

    for tier in TIER_KEYS:
        tier_block = tiers_obj.get(tier)
        # Accept both formats: flat list or nested {"papers": [...]}
        if isinstance(tier_block, list):
            papers = tier_block
        elif isinstance(tier_block, dict):
            papers = tier_block.get("papers")
            if not isinstance(papers, list):
                errors.append(f"tiers.{tier}.papers must be an array")
                continue
        else:
            errors.append(f"tiers.{tier} must be an object or array")
            continue

        for index, paper in enumerate(papers):
            location = f"tiers.{tier}.papers[{index}]"
            if not isinstance(paper, dict):
                errors.append(f"{location} must be an object")
                continue

            paper_id = paper.get("id")
            if not isinstance(paper_id, str) or not paper_id.strip():
                errors.append(f"{location}.id must be a non-empty string")
                continue

            declared_tier = paper.get("tier")
            if declared_tier is not None and declared_tier != tier:
                errors.append(
                    f"{location}.tier='{declared_tier}' mismatches containing tier '{tier}'"
                )

            if paper_id in paper_tiers:
                errors.append(f"Duplicate paper id '{paper_id}' in calibration pack")
                continue

            paper_tiers[paper_id] = tier

    if not paper_tiers:
        errors.append("Calibration pack has no usable paper ids")

    if errors:
        raise ValueError("Input validation failed:\n- " + "\n- ".join(errors))

    return paper_tiers


def normalize_judgments(
    results_obj: object,
    paper_tiers: dict[str, str],
) -> list[dict[str, object]]:
    """Validate results payload and normalize judgments to canonical fields."""
    if not isinstance(results_obj, list):
        raise ValueError("Results file must be a JSON array")

    errors: list[str] = []
    normalized: list[dict[str, object]] = []

    for index, item in enumerate(results_obj):
        location = f"results[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{location} must be an object")
            continue

        judge_model = item.get("judge_model")
        if not isinstance(judge_model, str) or not judge_model.strip():
            errors.append(f"{location}.judge_model must be a non-empty string")
            continue

        paper_a = item.get("paper_a")
        paper_b = item.get("paper_b")
        if not isinstance(paper_a, dict) or not isinstance(paper_b, dict):
            errors.append(f"{location}.paper_a and {location}.paper_b must be objects")
            continue

        paper_a_id = paper_a.get("id")
        paper_b_id = paper_b.get("id")
        if not isinstance(paper_a_id, str) or not paper_a_id.strip():
            errors.append(f"{location}.paper_a.id must be a non-empty string")
            continue
        if not isinstance(paper_b_id, str) or not paper_b_id.strip():
            errors.append(f"{location}.paper_b.id must be a non-empty string")
            continue
        if paper_a_id == paper_b_id:
            errors.append(f"{location} compares the same paper id '{paper_a_id}'")
            continue

        tier_a = paper_tiers.get(paper_a_id)
        tier_b = paper_tiers.get(paper_b_id)
        if tier_a is None:
            errors.append(f"{location}.paper_a.id '{paper_a_id}' not found in calibration pack")
            continue
        if tier_b is None:
            errors.append(f"{location}.paper_b.id '{paper_b_id}' not found in calibration pack")
            continue

        result_tier_a = paper_a.get("tier")
        result_tier_b = paper_b.get("tier")
        if result_tier_a is not None and result_tier_a != tier_a:
            errors.append(
                f"{location}.paper_a tier '{result_tier_a}' mismatches pack tier '{tier_a}'"
            )
            continue
        if result_tier_b is not None and result_tier_b != tier_b:
            errors.append(
                f"{location}.paper_b tier '{result_tier_b}' mismatches pack tier '{tier_b}'"
            )
            continue

        winner = item.get("winner")
        if not isinstance(winner, str) or winner not in {paper_a_id, paper_b_id}:
            errors.append(
                f"{location}.winner must equal either '{paper_a_id}' or '{paper_b_id}'"
            )
            continue

        pos_a = item.get("pos_a")
        if pos_a is None:
            pos_a = item.get("pos")  # fallback: judge_pairwise.py outputs "pos"
        if pos_a not in (-1, 1):
            errors.append(f"{location}.pos_a must be either 1 or -1")
            continue

        confidence = item.get("confidence")
        if confidence is not None and not isinstance(confidence, (int, float)):
            errors.append(f"{location}.confidence must be numeric when provided")
            continue

        normalized.append(
            {
                "judge_model": judge_model,
                "paper_a_id": paper_a_id,
                "paper_b_id": paper_b_id,
                "tier_a": tier_a,
                "tier_b": tier_b,
                "winner": winner,
                "pos_a": int(pos_a),
            }
        )

    if errors:
        raise ValueError("Input validation failed:\n- " + "\n- ".join(errors))

    return normalized


def pair_key(tier_a: str, tier_b: str) -> str:
    """Build canonical tier-pair key with higher tier on the left."""
    if TIER_RANK[tier_a] >= TIER_RANK[tier_b]:
        high_tier, low_tier = tier_a, tier_b
    else:
        high_tier, low_tier = tier_b, tier_a
    return f"{high_tier}_vs_{low_tier}"


def wilson_interval(correct: int, total: int, z: float = Z_95) -> tuple[float, float]:
    """Compute Wilson score interval for a Bernoulli proportion."""
    if total <= 0:
        return 0.0, 0.0

    p_hat = correct / total
    z2 = z * z
    denom = 1.0 + z2 / total
    center = (p_hat + z2 / (2.0 * total)) / denom
    spread = z * math.sqrt((p_hat * (1.0 - p_hat) + z2 / (4.0 * total)) / total) / denom
    lower = max(0.0, center - spread)
    upper = min(1.0, center + spread)
    return lower, upper


def confidence_label(cross_tier_count: int) -> str:
    """Classify confidence based on sample size."""
    if cross_tier_count < 10:
        return "low"
    return "high"


def rounded(value: float) -> float:
    """Round floating point metrics for stable JSON output."""
    return round(value, 6)


def compute_report(judgments: list[dict[str, object]]) -> dict[str, object]:
    """Compute per-judge reliability and tier-pair diagnostics."""
    judge_accumulators: dict[str, dict[str, int]] = {}
    tier_pair_accumulators: dict[str, dict[str, int]] = {
        key: {"total": 0, "correct": 0} for key in PAIR_KEYS
    }

    total_judgments = len(judgments)
    cross_tier_judgments = 0
    within_tier_excluded = 0

    for judgment in judgments:
        judge_name = str(judgment["judge_model"])
        judge_entry = judge_accumulators.setdefault(
            judge_name,
            {
                "total_judgments": 0,
                "cross_tier_judgments": 0,
                "correct": 0,
                "a_wins": 0,
                "position_obs": 0,
            },
        )

        judge_entry["total_judgments"] += 1
        judge_entry["position_obs"] += 1
        if judgment["winner"] == judgment["paper_a_id"]:
            judge_entry["a_wins"] += 1

        tier_a = str(judgment["tier_a"])
        tier_b = str(judgment["tier_b"])
        if tier_a == tier_b:
            within_tier_excluded += 1
            continue

        cross_tier_judgments += 1
        judge_entry["cross_tier_judgments"] += 1

        if TIER_RANK[tier_a] > TIER_RANK[tier_b]:
            correct_winner = str(judgment["paper_a_id"])
        else:
            correct_winner = str(judgment["paper_b_id"])

        key = pair_key(tier_a, tier_b)
        if key in tier_pair_accumulators:
            tier_pair_accumulators[key]["total"] += 1

        if str(judgment["winner"]) == correct_winner:
            judge_entry["correct"] += 1
            if key in tier_pair_accumulators:
                tier_pair_accumulators[key]["correct"] += 1

    judge_metrics: dict[str, dict[str, object]] = {}
    raw_rho: dict[str, float] = {}

    for judge_name in sorted(judge_accumulators):
        values = judge_accumulators[judge_name]
        cross_count = values["cross_tier_judgments"]
        correct = values["correct"]
        accuracy = (correct / cross_count) if cross_count else 0.0

        position_obs = values["position_obs"]
        mean_a_won = (values["a_wins"] / position_obs) if position_obs else 0.5
        position_bias = abs(mean_a_won - 0.5)

        rho = accuracy * (1.0 - abs(position_bias))
        raw_rho[judge_name] = rho

        ci_low, ci_high = wilson_interval(correct, cross_count)

        judge_metrics[judge_name] = {
            "rho": 0.0,
            "accuracy": rounded(accuracy),
            "position_bias": rounded(position_bias),
            "total_judgments": values["total_judgments"],
            "cross_tier_judgments": cross_count,
            "correct": correct,
            "confidence": confidence_label(cross_count),
            "accuracy_ci95": [rounded(ci_low), rounded(ci_high)],
        }

    max_rho = max(raw_rho.values(), default=0.0)
    if max_rho > 0.0:
        for judge_name, value in raw_rho.items():
            judge_metrics[judge_name]["rho"] = rounded(value / max_rho)
    else:
        for judge_name in judge_metrics:
            judge_metrics[judge_name]["rho"] = 0.0

    tier_pair_breakdown: dict[str, dict[str, object]] = {}
    for key in PAIR_KEYS:
        pair_values = tier_pair_accumulators[key]
        total = pair_values["total"]
        correct = pair_values["correct"]
        tier_pair_breakdown[key] = {
            "total": total,
            "correct": correct,
            "accuracy": rounded(correct / total) if total else 0.0,
        }

    return {
        "metadata": {
            "total_judgments": total_judgments,
            "cross_tier_judgments": cross_tier_judgments,
            "within_tier_excluded": within_tier_excluded,
            "unique_judges": len(judge_metrics),
        },
        "judges": judge_metrics,
        "tier_pair_breakdown": tier_pair_breakdown,
    }


def validation_report(
    paper_tiers: dict[str, str],
    judgments: list[dict[str, object]],
) -> dict[str, object]:
    """Build a lightweight validation-only payload."""
    unique_judges = sorted({str(item["judge_model"]) for item in judgments})
    return {
        "valid": True,
        "metadata": {
            "pack_papers": len(paper_tiers),
            "total_judgments": len(judgments),
            "unique_judges": len(unique_judges),
        },
    }


def format_metric(value: float) -> str:
    """Format metric values with three decimals for readable summaries."""
    return f"{value:.3f}"


def render_summary(report: dict[str, object]) -> str:
    """Render a concise human-readable summary for stderr."""
    metadata = report.get("metadata", {})
    judges = report.get("judges", {})
    tier_pairs = report.get("tier_pair_breakdown", {})

    lines: list[str] = []
    lines.append("Calibration Summary")
    lines.append(
        "Overall: total={total}, cross-tier={cross}, within-tier-excluded={within}, judges={judges}".format(
            total=metadata.get("total_judgments", 0),
            cross=metadata.get("cross_tier_judgments", 0),
            within=metadata.get("within_tier_excluded", 0),
            judges=metadata.get("unique_judges", 0),
        )
    )

    lines.append("")
    lines.append("Per Judge:")

    judge_rows: list[tuple[str, dict[str, object]]] = []
    if isinstance(judges, dict):
        for name, payload in judges.items():
            if isinstance(payload, dict):
                judge_rows.append((name, payload))

    judge_rows.sort(key=lambda item: float(item[1].get("rho", 0.0)), reverse=True)

    for name, payload in judge_rows:
        lines.append(
            "- {name}: accuracy={acc}, bias={bias}, rho={rho}, cross-tier={cross}, total={total}, confidence={conf}".format(
                name=name,
                acc=format_metric(float(payload.get("accuracy", 0.0))),
                bias=format_metric(float(payload.get("position_bias", 0.0))),
                rho=format_metric(float(payload.get("rho", 0.0))),
                cross=payload.get("cross_tier_judgments", 0),
                total=payload.get("total_judgments", 0),
                conf=payload.get("confidence", "low"),
            )
        )

    lines.append("")
    lines.append("Tier-Pair Breakdown:")
    for key in PAIR_KEYS:
        payload = tier_pairs.get(key, {}) if isinstance(tier_pairs, dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        lines.append(
            "- {key}: accuracy={acc}, correct={correct}/{total}".format(
                key=key,
                acc=format_metric(float(payload.get("accuracy", 0.0))),
                correct=payload.get("correct", 0),
                total=payload.get("total", 0),
            )
        )

    if judge_rows:
        accuracies = [float(payload.get("accuracy", 0.0)) for _, payload in judge_rows]
        rhos = [float(payload.get("rho", 0.0)) for _, payload in judge_rows]
        mean_accuracy = statistics.fmean(accuracies)
        mean_rho = statistics.fmean(rhos)
        best = max(judge_rows, key=lambda item: float(item[1].get("rho", 0.0)))[0]
        worst = min(judge_rows, key=lambda item: float(item[1].get("rho", 0.0)))[0]
        lines.append("")
        lines.append(
            "Judge Stats: mean_accuracy={acc}, mean_rho={rho}, best={best}, worst={worst}".format(
                acc=format_metric(mean_accuracy),
                rho=format_metric(mean_rho),
                best=best,
                worst=worst,
            )
        )

    return "\n".join(lines)


def emit_json(payload: dict[str, object], output: str | None, pretty: bool) -> None:
    """Write JSON payload to stdout or file."""
    if pretty:
        text = json.dumps(payload, indent=2)
    else:
        text = json.dumps(payload, separators=(",", ":"))

    if output:
        destination = Path(output).expanduser()
        if destination.parent and not destination.parent.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text + "\n", encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")


def run() -> int:
    """Execute CLI workflow and return process exit code."""
    args = parse_args()

    try:
        pack_path = Path(args.pack).expanduser()
        results_path = Path(args.results).expanduser()
        pack_obj = load_json_file(pack_path)
        results_obj = load_json_file(results_path)

        paper_tiers = extract_paper_tiers(pack_obj)
        judgments = normalize_judgments(results_obj, paper_tiers)
    except ValueError as exc:
        sys.stderr.write(json.dumps({"error": str(exc)}) + "\n")
        return 1

    if args.validate:
        payload = validation_report(paper_tiers, judgments)
        emit_json(payload, args.output, args.pretty)
        if args.summary:
            summary = (
                "Validation Summary\n"
                f"- Pack papers: {payload['metadata']['pack_papers']}\n"
                f"- Input judgments: {payload['metadata']['total_judgments']}\n"
                f"- Unique judges: {payload['metadata']['unique_judges']}"
            )
            sys.stderr.write(summary + "\n")
        return 0

    report = compute_report(judgments)
    emit_json(report, args.output, args.pretty)

    if args.summary:
        sys.stderr.write(render_summary(report) + "\n")

    return 0


def main() -> None:
    """Program entrypoint."""
    raise SystemExit(run())


if __name__ == "__main__":
    main()
