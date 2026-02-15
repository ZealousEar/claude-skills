from __future__ import annotations

import argparse
import copy
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path


def clamp(value: float, lower: float, upper: float) -> float:
    """Clamp a floating-point value to [lower, upper]."""
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value


def stable_sigmoid(x: float) -> float:
    """Numerically stable sigmoid implementation."""
    if x >= 0.0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def percentile(sorted_values: list[float], q: float) -> float:
    """Compute an interpolated percentile from sorted values.

    Args:
        sorted_values: Values sorted in ascending order.
        q: Quantile in [0, 1].
    """
    if not sorted_values:
        return 0.0
    q = clamp(q, 0.0, 1.0)
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lower = int(math.floor(pos))
    upper = int(math.ceil(pos))
    if lower == upper:
        return sorted_values[lower]
    weight = pos - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command-line arguments for Bradley-Terry estimation."""
    parser = argparse.ArgumentParser(
        description=(
            "Estimate Bradley-Terry quality scores with fixed judge reliability "
            "and regularized position bias."
        )
    )
    parser.add_argument("--input", required=True, help="Path to judgments JSON file")
    parser.add_argument(
        "--calibration",
        required=True,
        help="Path to judge calibration JSON file (mandatory)",
    )
    parser.add_argument("--iterations", type=int, default=100, help="MM iterations")
    parser.add_argument(
        "--bootstrap",
        type=int,
        default=200,
        help="Bootstrap samples for uncertainty",
    )
    parser.add_argument(
        "--pi-lambda",
        dest="pi_lambda",
        type=float,
        default=0.1,
        help="L2 regularization strength for position bias",
    )
    parser.add_argument(
        "--min-matches",
        type=int,
        default=3,
        help="Minimum matches for ranked output",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument(
        "--output",
        default="-",
        help="Output file path (default: stdout)",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate inputs and exit without fitting",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print human-readable summary to stderr",
    )
    return parser.parse_args(argv)


def load_json(path: Path, calibration_required: bool = False) -> object:
    """Load and parse JSON from disk."""
    if not path.exists():
        if calibration_required:
            raise FileNotFoundError(
                "Calibration weights required. Run /geps calibrate first."
            )
        raise FileNotFoundError(f"File not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def normalize_pos(raw_pos: object) -> int:
    """Normalize position indicators to +1 or -1."""
    if isinstance(raw_pos, bool):
        return 1 if raw_pos else -1
    if isinstance(raw_pos, (int, float)):
        return 1 if raw_pos >= 0 else -1
    if isinstance(raw_pos, str):
        lowered = raw_pos.strip().lower()
        if lowered in {"a", "first", "+1", "1", "left"}:
            return 1
        if lowered in {"b", "second", "-1", "-", "right"}:
            return -1
    return 1


def extract_judge_id(entry: dict[str, object]) -> str:
    """Resolve judge key for model-level calibration mapping."""
    model = entry.get("model")
    if isinstance(model, str) and model.strip():
        return model.strip()
    judge_id = entry.get("judge_id")
    if isinstance(judge_id, str) and judge_id.strip():
        return judge_id.strip()
    return "unknown"


def validate_and_prepare_judgments(
    raw: object,
) -> tuple[list[dict[str, object]], list[str], int]:
    """Validate raw judgments and normalize valid entries."""
    errors: list[str] = []
    prepared: list[dict[str, object]] = []

    if not isinstance(raw, list):
        return prepared, ["Input must be a JSON array of judgment objects."], 0

    total = len(raw)
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            errors.append(f"Entry {idx} is not an object.")
            continue

        parse_status = item.get("parse_status", "ok")
        if isinstance(parse_status, str) and parse_status.lower() != "ok":
            continue

        winner = item.get("winner")
        loser = item.get("loser")

        if not isinstance(winner, str) or not winner.strip():
            errors.append(f"Entry {idx} has invalid winner.")
            continue
        if not isinstance(loser, str) or not loser.strip():
            errors.append(f"Entry {idx} has invalid loser.")
            continue

        winner_id = winner.strip()
        loser_id = loser.strip()
        if winner_id == loser_id:
            errors.append(f"Entry {idx} has winner equal to loser.")
            continue

        prepared.append(
            {
                "winner": winner_id,
                "loser": loser_id,
                "judge": extract_judge_id(item),
                "pos": normalize_pos(item.get("pos", 1)),
            }
        )

    return prepared, errors, total


def load_calibration_rho(calibration_raw: object) -> tuple[dict[str, float], list[str]]:
    """Extract judge rho values from calibration payload."""
    errors: list[str] = []
    rho_by_judge: dict[str, float] = {}

    if not isinstance(calibration_raw, dict):
        return rho_by_judge, ["Calibration must be a JSON object."]

    judges = calibration_raw.get("judges")
    if not isinstance(judges, dict):
        return rho_by_judge, ["Calibration must contain a 'judges' object."]

    for judge, payload in judges.items():
        if not isinstance(judge, str) or not judge:
            errors.append("Calibration contains a non-string judge key.")
            continue
        if not isinstance(payload, dict):
            errors.append(f"Calibration judge '{judge}' value must be an object.")
            continue
        raw_rho = payload.get("rho", 0.5)
        try:
            rho = float(raw_rho)
        except (TypeError, ValueError):
            errors.append(f"Calibration judge '{judge}' has invalid rho.")
            continue
        if not math.isfinite(rho):
            errors.append(f"Calibration judge '{judge}' rho must be finite.")
            continue
        rho_by_judge[judge] = rho

    return rho_by_judge, errors


def build_match_stats(
    judgments: list[dict[str, object]],
) -> tuple[dict[str, int], dict[str, int], dict[str, int], list[str], list[str]]:
    """Build per-idea and per-judge summary counts."""
    wins: dict[str, int] = defaultdict(int)
    losses: dict[str, int] = defaultdict(int)
    matches: dict[str, int] = defaultdict(int)
    idea_ids_set: set[str] = set()
    judge_ids_set: set[str] = set()

    for row in judgments:
        winner = str(row["winner"])
        loser = str(row["loser"])
        judge = str(row["judge"])

        wins[winner] += 1
        losses[loser] += 1
        matches[winner] += 1
        matches[loser] += 1

        idea_ids_set.add(winner)
        idea_ids_set.add(loser)
        judge_ids_set.add(judge)

    idea_ids = sorted(idea_ids_set)
    judge_ids = sorted(judge_ids_set)
    for idea in idea_ids:
        wins.setdefault(idea, 0)
        losses.setdefault(idea, 0)
        matches.setdefault(idea, 0)

    return wins, losses, matches, idea_ids, judge_ids


def recenter_theta(theta: dict[str, float]) -> None:
    """Enforce sum(theta) = 0 while keeping values numerically bounded."""
    if not theta:
        return
    mean = sum(theta.values()) / float(len(theta))
    for key in theta:
        theta[key] -= mean
    for key in theta:
        theta[key] = clamp(theta[key], -5.0, 5.0)
    mean_after = sum(theta.values()) / float(len(theta))
    for key in theta:
        theta[key] -= mean_after


def estimate_parameters(
    judgments: list[dict[str, object]],
    idea_ids: list[str],
    judge_ids: list[str],
    rho_by_judge: dict[str, float],
    iterations: int,
    pi_lambda: float,
) -> tuple[dict[str, float], dict[str, float], int, bool, dict[str, int], dict[str, int], dict[str, int]]:
    """Fit theta and pi via iterative MM-style updates.

    `rho_by_judge` is fixed from calibration and never updated.
    """
    wins, losses, matches, _, _ = build_match_stats(judgments)

    theta: dict[str, float] = {idea: 0.0 for idea in idea_ids}
    pi: dict[str, float] = {judge: 0.0 for judge in judge_ids}

    if not idea_ids or not judgments:
        return theta, pi, 0, True, wins, losses, matches

    converged = False
    iterations_used = 0

    for iteration in range(1, max(1, iterations) + 1):
        old_theta = copy.copy(theta)
        expected_wins: dict[str, float] = defaultdict(float)
        curvature: dict[str, float] = defaultdict(float)

        for row in judgments:
            winner = str(row["winner"])
            loser = str(row["loser"])
            judge = str(row["judge"])
            pos = int(row["pos"])

            rho = rho_by_judge.get(judge, 0.5)
            score = rho * (theta[winner] - theta[loser]) + pi[judge] * float(pos)
            p_winner = stable_sigmoid(score)
            p_loser = 1.0 - p_winner

            expected_wins[winner] += p_winner
            expected_wins[loser] += p_loser

            hess = max(1e-9, (rho * rho) * p_winner * (1.0 - p_winner))
            curvature[winner] += hess
            curvature[loser] += hess

        for idea in idea_ids:
            numer = float(wins.get(idea, 0)) - expected_wins.get(idea, 0.0)
            denom = curvature.get(idea, 0.0)
            step = 0.0 if denom <= 0.0 else numer / denom
            theta[idea] = clamp(theta[idea] + clamp(step, -1.0, 1.0), -5.0, 5.0)

        judge_pos_sum: dict[str, float] = defaultdict(float)
        judge_count: dict[str, int] = defaultdict(int)
        for row in judgments:
            judge = str(row["judge"])
            pos = float(int(row["pos"]))
            judge_pos_sum[judge] += pos
            judge_count[judge] += 1

        for judge in judge_ids:
            n = judge_count.get(judge, 0)
            if n <= 0:
                continue
            raw_pi = judge_pos_sum.get(judge, 0.0) / (float(n) + 2.0 * pi_lambda)
            shrink = 1.0 + (2.0 * pi_lambda / float(n))
            pi[judge] = clamp(raw_pi / shrink, -5.0, 5.0)

        recenter_theta(theta)

        max_abs_delta = 0.0
        for idea in idea_ids:
            diff = abs(theta[idea] - old_theta[idea])
            if diff > max_abs_delta:
                max_abs_delta = diff

        iterations_used = iteration
        if max_abs_delta < 1e-6:
            converged = True
            break

    return theta, pi, iterations_used, converged, wins, losses, matches


def bootstrap_theta_statistics(
    judgments: list[dict[str, object]],
    idea_ids: list[str],
    judge_ids: list[str],
    rho_by_judge: dict[str, float],
    iterations: int,
    pi_lambda: float,
    bootstrap_samples: int,
    seed: int,
) -> dict[str, dict[str, float]]:
    """Estimate bootstrap mean/std/confidence intervals for theta."""
    stats: dict[str, dict[str, float]] = {}
    if bootstrap_samples <= 0 or not idea_ids:
        return stats

    draws: dict[str, list[float]] = {idea: [] for idea in idea_ids}
    rng = random.Random(seed)
    n = len(judgments)

    for _ in range(bootstrap_samples):
        if n == 0:
            sampled = []
        else:
            sampled = [judgments[rng.randrange(n)] for _ in range(n)]
        theta_b, _, _, _, _, _, _ = estimate_parameters(
            sampled,
            idea_ids,
            judge_ids,
            rho_by_judge,
            iterations,
            pi_lambda,
        )
        for idea in idea_ids:
            draws[idea].append(float(theta_b.get(idea, 0.0)))

    for idea in idea_ids:
        values = draws.get(idea, [])
        if not values:
            stats[idea] = {
                "mu": 0.0,
                "sigma": 0.0,
                "ci_lower": 0.0,
                "ci_upper": 0.0,
            }
            continue
        mu = sum(values) / float(len(values))
        variance = sum((v - mu) * (v - mu) for v in values) / float(len(values))
        sigma = math.sqrt(max(0.0, variance))
        sorted_values = sorted(values)
        stats[idea] = {
            "mu": mu,
            "sigma": sigma,
            "ci_lower": percentile(sorted_values, 0.025),
            "ci_upper": percentile(sorted_values, 0.975),
        }

    return stats


def build_rankings(
    theta: dict[str, float],
    bootstrap_stats: dict[str, dict[str, float]],
    matches: dict[str, int],
    wins: dict[str, int],
    losses: dict[str, int],
    min_matches: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Build ranked and insufficient-match idea outputs."""
    sufficient_ids = [idea for idea in theta if matches.get(idea, 0) >= min_matches]
    sufficient_ids.sort(key=lambda idea: (-theta[idea], idea))

    rankings: list[dict[str, object]] = []
    for idx, idea in enumerate(sufficient_ids, start=1):
        b = bootstrap_stats.get(idea)
        if b is None:
            b = {
                "mu": theta[idea],
                "sigma": 0.0,
                "ci_lower": theta[idea],
                "ci_upper": theta[idea],
            }
        rankings.append(
            {
                "id": idea,
                "rank": idx,
                "theta": theta[idea],
                "mu": b["mu"],
                "sigma": b["sigma"],
                "ci_lower": b["ci_lower"],
                "ci_upper": b["ci_upper"],
                "matches": int(matches.get(idea, 0)),
                "wins": int(wins.get(idea, 0)),
                "losses": int(losses.get(idea, 0)),
            }
        )

    insufficient: list[dict[str, object]] = []
    for idea in sorted(theta):
        m = int(matches.get(idea, 0))
        if m >= min_matches:
            continue
        insufficient.append(
            {
                "id": idea,
                "matches": m,
                "reason": f"Below minimum {min_matches} matches",
            }
        )

    return rankings, insufficient


def build_judge_diagnostics(
    judge_ids: list[str],
    rho_by_judge: dict[str, float],
    pi: dict[str, float],
    judgments: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Build judge diagnostics with fixed rho and estimated pi."""
    counts: dict[str, int] = defaultdict(int)
    for row in judgments:
        counts[str(row["judge"])] += 1

    diagnostics: list[dict[str, object]] = []
    for judge in sorted(judge_ids):
        diagnostics.append(
            {
                "model": judge,
                "rho": float(rho_by_judge.get(judge, 0.5)),
                "estimated_pi": float(pi.get(judge, 0.0)),
                "total_judgments": int(counts.get(judge, 0)),
                "note": "rho loaded from calibration",
            }
        )
    return diagnostics


def summarize_result(result: dict[str, object]) -> str:
    """Create a concise human-readable summary."""
    metadata = result.get("metadata", {}) if isinstance(result, dict) else {}
    rankings = result.get("rankings", []) if isinstance(result, dict) else []

    lines = [
        "Bradley-Terry estimation summary",
        f"- total judgments: {metadata.get('total_judgments', 0)}",
        f"- valid judgments: {metadata.get('valid_judgments', 0)}",
        f"- unique ideas: {metadata.get('unique_ideas', 0)}",
        f"- unique judges: {metadata.get('unique_judges', 0)}",
        f"- converged: {metadata.get('converged', False)}",
        f"- iterations used: {metadata.get('iterations_used', 0)}",
        f"- bootstrap samples: {metadata.get('bootstrap_samples', 0)}",
    ]

    if isinstance(rankings, list) and rankings:
        top = rankings[0]
        if isinstance(top, dict):
            lines.append(
                f"- top idea: {top.get('id', 'n/a')} (theta={top.get('theta', 0):.4f})"
            )

    return "\n".join(lines)


def write_output(payload: dict[str, object], pretty: bool, output: str) -> None:
    """Write JSON payload to stdout or output file."""
    indent = 2 if pretty else None
    text = json.dumps(payload, indent=indent, sort_keys=False)
    if output == "-":
        sys.stdout.write(text)
        sys.stdout.write("\n")
        return
    path = Path(output)
    path.write_text(text + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for Bradley-Terry estimation."""
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.iterations < 0:
        sys.stderr.write("--iterations must be >= 0\n")
        raise SystemExit(2)
    if args.bootstrap < 0:
        sys.stderr.write("--bootstrap must be >= 0\n")
        raise SystemExit(2)
    if args.min_matches < 1:
        sys.stderr.write("--min-matches must be >= 1\n")
        raise SystemExit(2)

    try:
        calibration_raw = load_json(Path(args.calibration), calibration_required=True)
    except FileNotFoundError as exc:
        sys.stderr.write(str(exc) + "\n")
        raise SystemExit(1)
    except ValueError as exc:
        sys.stderr.write(str(exc) + "\n")
        raise SystemExit(1)

    try:
        judgments_raw = load_json(Path(args.input), calibration_required=False)
    except (FileNotFoundError, ValueError) as exc:
        sys.stderr.write(str(exc) + "\n")
        raise SystemExit(1)

    prepared_judgments, judgment_errors, total_judgments = validate_and_prepare_judgments(
        judgments_raw
    )
    rho_by_judge, calibration_errors = load_calibration_rho(calibration_raw)

    all_errors = judgment_errors + calibration_errors
    wins, losses, matches, idea_ids, judge_ids = build_match_stats(prepared_judgments)

    missing_judges: list[str] = []
    for judge in judge_ids:
        if judge not in rho_by_judge:
            rho_by_judge[judge] = 0.5
            missing_judges.append(judge)

    for judge in missing_judges:
        sys.stderr.write(
            f"Warning: judge '{judge}' missing calibration rho; using default rho=0.5\n"
        )

    if args.validate:
        validation_payload: dict[str, object] = {
            "valid": len(all_errors) == 0,
            "errors": all_errors,
            "metadata": {
                "total_judgments": total_judgments,
                "valid_judgments": len(prepared_judgments),
                "unique_ideas": len(idea_ids),
                "unique_judges": len(judge_ids),
            },
        }
        if args.summary:
            sys.stderr.write(summarize_result({"metadata": validation_payload["metadata"]}))
            sys.stderr.write("\n")
        write_output(validation_payload, args.pretty, args.output)
        return

    theta, pi, iterations_used, converged, wins, losses, matches = estimate_parameters(
        prepared_judgments,
        idea_ids,
        judge_ids,
        rho_by_judge,
        args.iterations,
        args.pi_lambda,
    )

    bootstrap_stats = bootstrap_theta_statistics(
        prepared_judgments,
        idea_ids,
        judge_ids,
        rho_by_judge,
        args.iterations,
        args.pi_lambda,
        args.bootstrap,
        args.seed,
    )

    rankings, insufficient_matches = build_rankings(
        theta,
        bootstrap_stats,
        matches,
        wins,
        losses,
        args.min_matches,
    )
    judge_diagnostics = build_judge_diagnostics(
        judge_ids,
        rho_by_judge,
        pi,
        prepared_judgments,
    )

    payload: dict[str, object] = {
        "metadata": {
            "total_judgments": total_judgments,
            "valid_judgments": len(prepared_judgments),
            "unique_ideas": len(idea_ids),
            "unique_judges": len(judge_ids),
            "iterations_used": iterations_used,
            "converged": converged,
            "bootstrap_samples": args.bootstrap,
            "pi_lambda": args.pi_lambda,
            "min_matches": args.min_matches,
        },
        "rankings": rankings,
        "insufficient_matches": insufficient_matches,
        "judge_diagnostics": judge_diagnostics,
    }

    if args.summary:
        sys.stderr.write(summarize_result(payload))
        sys.stderr.write("\n")

    write_output(payload, args.pretty, args.output)


if __name__ == "__main__":
    main()
