#!/usr/bin/env python3
"""Aggregate GIB results into per-model benchmark report.

Consumes outputs from the GIB pipeline (Bradley-Terry rankings, mechanical gate
results, tournament judgments, and the ideas manifest) and produces a unified
per-model report with scores, gate pass rates, and an optional head-to-head win
matrix.

Usage:
    python3 gib_report.py \
      --rankings bt_rankings.json \
      --gate-results gate_results.json \
      --ideas-manifest manifest.json \
      --judgments judgments.json \
      --output report.json \
      --pretty --summary
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for GIB report generation."""
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate GIB results into per-model benchmark report with "
            "scores, gate pass rates, and H2H matrix."
        )
    )
    parser.add_argument(
        "--rankings",
        required=True,
        help="Path to Bradley-Terry rankings JSON",
    )
    parser.add_argument(
        "--gate-results",
        required=True,
        help="Path to gate results JSON",
    )
    parser.add_argument(
        "--tournament",
        help="Path to tournament results JSON (optional, for H2H)",
    )
    parser.add_argument(
        "--judgments",
        help="Path to all judgments JSON (optional, for H2H)",
    )
    parser.add_argument(
        "--ideas-manifest",
        required=True,
        help="Path to ideas manifest JSON (maps idea_id to source model)",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="Output path (default: stdout)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print human-readable summary to stderr",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def load_json_file(path: Path) -> object:
    """Load and parse JSON from disk."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


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


# ---------------------------------------------------------------------------
# Manifest mapping
# ---------------------------------------------------------------------------

def build_idea_model_map(manifest: object) -> dict[str, str]:
    """Build a mapping from idea_id to source model name.

    The manifest is a list of objects produced by gib_idea_generator.py, each
    containing at least ``id`` and ``model`` fields.

    Returns:
        Dictionary mapping idea_id (str) to model name (str).
    """
    if not isinstance(manifest, list):
        raise ValueError("Ideas manifest must be a JSON array")

    idea_model: dict[str, str] = {}
    for idx, entry in enumerate(manifest):
        if not isinstance(entry, dict):
            sys.stderr.write(f"Warning: manifest entry {idx} is not an object, skipping\n")
            continue
        idea_id = entry.get("id")
        model = entry.get("model")
        if idea_id is None or model is None:
            sys.stderr.write(
                f"Warning: manifest entry {idx} missing 'id' or 'model', skipping\n"
            )
            continue
        idea_model[str(idea_id)] = str(model)

    return idea_model


# ---------------------------------------------------------------------------
# Model score aggregation
# ---------------------------------------------------------------------------

def compute_model_scores(
    rankings_data: object,
    idea_model_map: dict[str, str],
) -> list[dict[str, object]]:
    """Aggregate Bradley-Terry theta scores per model.

    Args:
        rankings_data: Parsed BT output containing a ``rankings`` list.  Each
            entry has ``id``, ``theta``, ``mu``, ``sigma``, ``ci_lower``,
            ``ci_upper``, ``wins``, ``losses``.
        idea_model_map: Mapping from idea_id to source model.

    Returns:
        Sorted list (descending mean_theta) of per-model score records.
    """
    if not isinstance(rankings_data, dict):
        raise ValueError("Rankings data must be a JSON object")

    rankings = rankings_data.get("rankings", [])
    if not isinstance(rankings, list):
        raise ValueError("Rankings data must contain a 'rankings' array")

    # Accumulate per-model statistics
    model_thetas: dict[str, list[float]] = defaultdict(list)
    model_sigmas: dict[str, list[float]] = defaultdict(list)
    model_ci_lower: dict[str, list[float]] = defaultdict(list)
    model_ci_upper: dict[str, list[float]] = defaultdict(list)
    model_wins: dict[str, int] = defaultdict(int)
    model_losses: dict[str, int] = defaultdict(int)

    for entry in rankings:
        if not isinstance(entry, dict):
            continue
        idea_id = str(entry.get("id", ""))
        model = idea_model_map.get(idea_id)
        if model is None:
            continue

        theta = float(entry.get("theta", 0.0))
        sigma = float(entry.get("sigma", 0.0))
        ci_lo = float(entry.get("ci_lower", theta))
        ci_hi = float(entry.get("ci_upper", theta))
        wins = int(entry.get("wins", 0))
        losses = int(entry.get("losses", 0))

        model_thetas[model].append(theta)
        model_sigmas[model].append(sigma)
        model_ci_lower[model].append(ci_lo)
        model_ci_upper[model].append(ci_hi)
        model_wins[model] += wins
        model_losses[model] += losses

    # Build per-model records
    records: list[dict[str, object]] = []
    for model in sorted(model_thetas):
        thetas = model_thetas[model]
        n = len(thetas)
        mean_theta = sum(thetas) / n if n > 0 else 0.0
        min_theta = min(thetas) if thetas else 0.0
        max_theta = max(thetas) if thetas else 0.0

        # Average sigma across ideas as a model-level uncertainty proxy
        avg_sigma = sum(model_sigmas[model]) / n if n > 0 else 0.0
        avg_ci_lower = sum(model_ci_lower[model]) / n if n > 0 else 0.0
        avg_ci_upper = sum(model_ci_upper[model]) / n if n > 0 else 0.0

        records.append({
            "model": model,
            "mean_theta": round(mean_theta, 4),
            "min_theta": round(min_theta, 4),
            "max_theta": round(max_theta, 4),
            "sigma": round(avg_sigma, 4),
            "ci_lower": round(avg_ci_lower, 4),
            "ci_upper": round(avg_ci_upper, 4),
            "ideas_ranked": n,
            "total_wins": model_wins[model],
            "total_losses": model_losses[model],
        })

    # Sort by descending mean_theta, then alphabetical model name for ties
    records.sort(key=lambda r: (-r["mean_theta"], r["model"]))

    # Assign ranks
    for idx, record in enumerate(records, start=1):
        record["rank"] = idx

    return records


# ---------------------------------------------------------------------------
# Gate analysis
# ---------------------------------------------------------------------------

GATE_NAMES = ["data", "complexity", "identifiability", "novelty", "ethics"]


def compute_gate_analysis(
    gate_results: object,
    idea_model_map: dict[str, str],
) -> dict[str, dict[str, object]]:
    """Compute per-model gate pass rates from mechanical gate results.

    Args:
        gate_results: List of gate result objects, each with ``id``, ``gates``
            (a dict of gate_name -> {pass, reason}), ``overall_pass``, and
            ``failed_gates``.
        idea_model_map: Mapping from idea_id to source model.

    Returns:
        Dictionary keyed by model name with gate statistics.
    """
    if not isinstance(gate_results, list):
        raise ValueError("Gate results must be a JSON array")

    model_total: dict[str, int] = defaultdict(int)
    model_passed_all: dict[str, int] = defaultdict(int)
    model_per_gate: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: {g: {"passed": 0, "total": 0} for g in GATE_NAMES}
    )

    for entry in gate_results:
        if not isinstance(entry, dict):
            continue
        idea_id = str(entry.get("id", ""))
        model = idea_model_map.get(idea_id)
        if model is None:
            continue

        model_total[model] += 1
        overall_pass = bool(entry.get("overall_pass", False))
        if overall_pass:
            model_passed_all[model] += 1

        gates = entry.get("gates", {})
        if not isinstance(gates, dict):
            continue

        for gate_name in GATE_NAMES:
            gate_outcome = gates.get(gate_name)
            if not isinstance(gate_outcome, dict):
                continue
            model_per_gate[model][gate_name]["total"] += 1
            if bool(gate_outcome.get("pass", False)):
                model_per_gate[model][gate_name]["passed"] += 1

    # Build output
    analysis: dict[str, dict[str, object]] = {}
    for model in sorted(set(model_total)):
        total = model_total[model]
        passed = model_passed_all.get(model, 0)
        per_gate: dict[str, dict[str, object]] = {}
        for gate_name in GATE_NAMES:
            g = model_per_gate[model][gate_name]
            g_total = g["total"]
            g_passed = g["passed"]
            rate = g_passed / g_total if g_total > 0 else 0.0
            per_gate[gate_name] = {
                "passed": g_passed,
                "total": g_total,
                "rate": round(rate, 4),
            }

        overall_rate = passed / total if total > 0 else 0.0
        analysis[model] = {
            "total_ideas": total,
            "passed_all": passed,
            "overall_pass_rate": round(overall_rate, 4),
            "per_gate": per_gate,
        }

    return analysis


# ---------------------------------------------------------------------------
# Head-to-head matrix
# ---------------------------------------------------------------------------

def compute_h2h_matrix(
    judgments: object,
    idea_model_map: dict[str, str],
) -> dict[str, dict[str, int]]:
    """Build a head-to-head win matrix from pairwise judgments.

    Each judgment has ``winner`` and ``loser`` fields containing idea IDs.
    These are mapped through ``idea_model_map`` to their source models to
    produce a model-vs-model win count matrix.

    Args:
        judgments: List of judgment objects with winner/loser idea IDs.
        idea_model_map: Mapping from idea_id to source model.

    Returns:
        Nested dict: h2h[model_a][model_b] = number of times model_a's ideas
        beat model_b's ideas.  Self-play entries are omitted.
    """
    if judgments is None:
        return {}

    if not isinstance(judgments, list):
        raise ValueError("Judgments must be a JSON array")

    wins: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    all_models: set[str] = set()

    for entry in judgments:
        if not isinstance(entry, dict):
            continue

        # Skip entries with parse errors
        parse_status = entry.get("parse_status", "ok")
        if isinstance(parse_status, str) and parse_status.lower() != "ok":
            continue

        winner_id = str(entry.get("winner", ""))
        loser_id = str(entry.get("loser", ""))

        winner_model = idea_model_map.get(winner_id)
        loser_model = idea_model_map.get(loser_id)

        if winner_model is None or loser_model is None:
            continue
        if winner_model == loser_model:
            continue

        wins[winner_model][loser_model] += 1
        all_models.add(winner_model)
        all_models.add(loser_model)

    # Convert to regular dicts, ensuring all model pairs are present
    matrix: dict[str, dict[str, int]] = {}
    for model_a in sorted(all_models):
        row: dict[str, int] = {}
        for model_b in sorted(all_models):
            if model_a == model_b:
                continue
            row[model_b] = wins[model_a][model_b]
        matrix[model_a] = row

    return matrix


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

def build_metadata(
    idea_model_map: dict[str, str],
    model_scores: list[dict[str, object]],
) -> dict[str, object]:
    """Build the top-level metadata block for the report."""
    models = set(idea_model_map.values())
    total_generated = len(idea_model_map)
    total_ranked = sum(int(ms.get("ideas_ranked", 0)) for ms in model_scores)

    return {
        "total_models": len(models),
        "total_ideas_generated": total_generated,
        "total_ideas_ranked": total_ranked,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Human-readable summary
# ---------------------------------------------------------------------------

def format_summary(report: dict[str, object]) -> None:
    """Print a human-readable summary table to stderr.

    Includes a ranked model scores table, per-model gate analysis, and the
    head-to-head win matrix when available.
    """
    model_scores = report.get("model_scores", [])
    gate_analysis = report.get("gate_analysis", {})
    h2h_matrix = report.get("h2h_matrix", {})
    metadata = report.get("metadata", {})

    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("GIB REPORT SUMMARY")
    lines.append("=" * 80)
    lines.append("")

    # Metadata
    lines.append(f"Models evaluated:       {metadata.get('total_models', 0)}")
    lines.append(f"Total ideas generated:  {metadata.get('total_ideas_generated', 0)}")
    lines.append(f"Total ideas ranked:     {metadata.get('total_ideas_ranked', 0)}")
    lines.append(f"Timestamp:              {metadata.get('timestamp', 'N/A')}")
    lines.append("")

    # --- Model scores table ---
    lines.append("-" * 80)
    lines.append("MODEL SCORES (ranked by mean BT theta)")
    lines.append("-" * 80)

    header = (
        f"{'Rank':<6}"
        f"{'Model':<20}"
        f"{'Mean':>8}"
        f"{'CI Low':>8}"
        f"{'CI High':>8}"
        f"{'Ideas':>7}"
        f"{'Wins':>6}"
        f"{'Losses':>8}"
        f"{'Gate%':>7}"
    )
    lines.append(header)
    lines.append("-" * len(header))

    for ms in model_scores:
        rank = ms.get("rank", "-")
        model = str(ms.get("model", ""))
        mean_t = ms.get("mean_theta", 0.0)
        ci_lo = ms.get("ci_lower", 0.0)
        ci_hi = ms.get("ci_upper", 0.0)
        ideas = ms.get("ideas_ranked", 0)
        wins = ms.get("total_wins", 0)
        losses = ms.get("total_losses", 0)
        gate_rate = ms.get("gate_pass_rate", 0.0)

        # Truncate long model names
        display_model = model[:18] if len(model) > 18 else model
        gate_pct = f"{gate_rate * 100:.0f}%" if isinstance(gate_rate, (int, float)) else "N/A"

        row = (
            f"{rank:<6}"
            f"{display_model:<20}"
            f"{mean_t:>8.3f}"
            f"{ci_lo:>8.3f}"
            f"{ci_hi:>8.3f}"
            f"{ideas:>7}"
            f"{wins:>6}"
            f"{losses:>8}"
            f"{gate_pct:>7}"
        )
        lines.append(row)

    lines.append("")

    # --- Gate analysis ---
    if gate_analysis:
        lines.append("-" * 80)
        lines.append("GATE PASS RATES")
        lines.append("-" * 80)

        gate_header = (
            f"{'Model':<20}"
            f"{'Total':>7}"
            f"{'All OK':>7}"
            f"{'Data':>7}"
            f"{'Cmplx':>7}"
            f"{'Ident':>7}"
            f"{'Novel':>7}"
            f"{'Ethics':>7}"
        )
        lines.append(gate_header)
        lines.append("-" * len(gate_header))

        for model in sorted(gate_analysis):
            ga = gate_analysis[model]
            total = ga.get("total_ideas", 0)
            passed = ga.get("passed_all", 0)
            pg = ga.get("per_gate", {})

            def rate_str(gate_name: str) -> str:
                g = pg.get(gate_name, {})
                r = g.get("rate", 0.0)
                return f"{r * 100:.0f}%"

            display_model = model[:18] if len(model) > 18 else model
            gate_row = (
                f"{display_model:<20}"
                f"{total:>7}"
                f"{passed:>7}"
                f"{rate_str('data'):>7}"
                f"{rate_str('complexity'):>7}"
                f"{rate_str('identifiability'):>7}"
                f"{rate_str('novelty'):>7}"
                f"{rate_str('ethics'):>7}"
            )
            lines.append(gate_row)

        lines.append("")

    # --- H2H matrix ---
    if h2h_matrix:
        lines.append("-" * 80)
        lines.append("HEAD-TO-HEAD WIN MATRIX")
        lines.append("-" * 80)

        models_sorted = sorted(h2h_matrix.keys())
        col_width = 8
        name_width = 16

        # Abbreviate model names for the matrix header
        abbrevs: list[str] = []
        for m in models_sorted:
            abbrev = m[:col_width - 1] if len(m) > col_width - 1 else m
            abbrevs.append(abbrev)

        # Header row
        h2h_header = f"{'':>{name_width}}"
        for abbrev in abbrevs:
            h2h_header += f"{abbrev:>{col_width}}"
        lines.append(h2h_header)
        lines.append("-" * len(h2h_header))

        # Data rows
        for i, model_a in enumerate(models_sorted):
            display = model_a[:name_width - 1] if len(model_a) > name_width - 1 else model_a
            row_str = f"{display:>{name_width}}"
            row_data = h2h_matrix.get(model_a, {})
            for j, model_b in enumerate(models_sorted):
                if model_a == model_b:
                    row_str += f"{'---':>{col_width}}"
                else:
                    count = row_data.get(model_b, 0)
                    row_str += f"{count:>{col_width}}"
            lines.append(row_str)

        lines.append("")

    lines.append("=" * 80)

    sys.stderr.write("\n".join(lines))
    sys.stderr.write("\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point for GIB report generation."""
    args = parse_args()

    # Load required inputs
    try:
        rankings_data = load_json_file(Path(args.rankings))
    except ValueError as exc:
        sys.stderr.write(f"Error loading rankings: {exc}\n")
        raise SystemExit(1)

    try:
        gate_data = load_json_file(Path(args.gate_results))
    except ValueError as exc:
        sys.stderr.write(f"Error loading gate results: {exc}\n")
        raise SystemExit(1)

    try:
        manifest_data = load_json_file(Path(args.ideas_manifest))
    except ValueError as exc:
        sys.stderr.write(f"Error loading ideas manifest: {exc}\n")
        raise SystemExit(1)

    # Load optional inputs
    judgments_data = None
    if args.judgments:
        try:
            judgments_data = load_json_file(Path(args.judgments))
        except ValueError as exc:
            sys.stderr.write(f"Warning: could not load judgments: {exc}\n")

    # Build the idea-to-model mapping
    try:
        idea_model_map = build_idea_model_map(manifest_data)
    except ValueError as exc:
        sys.stderr.write(f"Error building idea-model map: {exc}\n")
        raise SystemExit(1)

    if not idea_model_map:
        sys.stderr.write("Warning: idea-model map is empty; report will be sparse\n")

    # Compute model scores from BT rankings
    try:
        model_scores = compute_model_scores(rankings_data, idea_model_map)
    except ValueError as exc:
        sys.stderr.write(f"Error computing model scores: {exc}\n")
        raise SystemExit(1)

    # Compute gate analysis
    try:
        gate_analysis = compute_gate_analysis(gate_data, idea_model_map)
    except ValueError as exc:
        sys.stderr.write(f"Error computing gate analysis: {exc}\n")
        raise SystemExit(1)

    # Compute head-to-head matrix (optional)
    h2h_matrix: dict[str, dict[str, int]] = {}
    if judgments_data is not None:
        try:
            h2h_matrix = compute_h2h_matrix(judgments_data, idea_model_map)
        except ValueError as exc:
            sys.stderr.write(f"Warning: could not compute H2H matrix: {exc}\n")

    # Enrich model_scores with gate pass information and generation counts
    for ms in model_scores:
        model = ms["model"]
        ga = gate_analysis.get(model, {})
        ms["ideas_generated"] = ga.get("total_ideas", 0)
        ms["ideas_passed_gates"] = ga.get("passed_all", 0)
        ms["gate_pass_rate"] = ga.get("overall_pass_rate", 0.0)

    # Build metadata
    metadata = build_metadata(idea_model_map, model_scores)

    # Assemble full report
    report: dict[str, object] = {
        "metadata": metadata,
        "model_scores": model_scores,
        "gate_analysis": gate_analysis,
        "h2h_matrix": h2h_matrix,
    }

    # Print human-readable summary if requested
    if args.summary:
        format_summary(report)

    # Write output
    write_output(report, args.pretty, args.output)


if __name__ == "__main__":
    main()
