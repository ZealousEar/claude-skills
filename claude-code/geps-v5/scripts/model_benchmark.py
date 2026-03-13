#!/usr/bin/env python3
"""Model benchmark system for GEPS v5.

Evaluates candidate LLM models for generation, judging, and verification stages.
Supports two scoring modes: quality_per_dollar (cost-normalized) and raw_performance.
Optionally auto-updates geps-config.json with the winning model.

Usage:
    python3 model_benchmark.py \
      --stage generation \
      --candidate-models "glm-5,minimax-m2.5" \
      --mode quality_per_dollar \
      --output benchmark_results.json \
      --history-file benchmark_history.jsonl \
      --auto-update \
      --judge-model opus
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SKILL_DIR = Path.home() / ".claude" / "skills" / "geps-v5"
DEFAULT_GEPS_CONFIG = SKILL_DIR / "settings" / "geps-config.json"
DEFAULT_PRICING = SKILL_DIR / "settings" / "model_pricing.json"
DEFAULT_MODEL_SETTINGS = (
    Path.home() / ".claude" / "skills" / "convolutional-debate-agent"
    / "settings" / "model-settings.json"
)
LLM_RUNNER = (
    Path.home() / ".claude" / "skills" / "convolutional-debate-agent"
    / "scripts" / "llm_runner.py"
)

# ---------------------------------------------------------------------------
# Hardcoded benchmark data
# ---------------------------------------------------------------------------

GENERATION_PROMPTS = [
    (
        "Generate a novel research idea combining network analysis with asset "
        "pricing. Include a clear hypothesis, proposed methodology, and data "
        "sources. Focus on identification strategy."
    ),
    (
        "Propose a testable hypothesis about market microstructure using "
        "natural language processing. Specify the NLP technique, the "
        "microstructure mechanism, and how you would identify the causal effect."
    ),
    (
        "Design a quasi-experimental study examining the impact of social media "
        "on stock volatility. Describe the identification strategy, the "
        "treatment and control construction, and potential confounders."
    ),
    (
        "Suggest an identification strategy for measuring the causal effect of "
        "ESG disclosure on firm value. Address endogeneity concerns and propose "
        "an instrument or natural experiment."
    ),
    (
        "Propose a research design using instrumental variables to study "
        "algorithmic trading effects on price discovery. Specify the instrument, "
        "exclusion restriction argument, and data requirements."
    ),
]

JUDGE_SYSTEM = (
    "You are an expert academic finance reviewer evaluating research idea quality. "
    "Rate the idea on four dimensions, each 1-10:\n"
    "- Novelty: How original is the contribution?\n"
    "- Feasibility: Can this be executed with publicly available data in 6 months?\n"
    "- Identification Rigor: How credible is the causal identification strategy?\n"
    "- Overall: Holistic quality score.\n\n"
    "Respond ONLY with a JSON object: "
    '{"novelty": N, "feasibility": N, "rigor": N, "overall": N}'
)

# 15 calibration pairs for judging benchmark: (idea_A, idea_B, expected_winner)
# expected_winner is "A" or "B" — the clearly stronger idea.
JUDGING_CALIBRATION_PAIRS = [
    (
        "Use firm-level network centrality from supply-chain graphs as an instrument for information asymmetry in cross-sectional asset pricing tests.",
        "Regress stock returns on sentiment scores from Twitter.",
        "A",
    ),
    (
        "Look at whether stocks go up or down after earnings announcements.",
        "Exploit staggered adoption of SEC XBRL filing mandates as a natural experiment to identify the effect of disclosure standardization on bid-ask spreads.",
        "B",
    ),
    (
        "Apply a regression discontinuity design around index reconstitution thresholds to measure passive ownership effects on corporate governance.",
        "Run a correlation between ESG scores and stock returns.",
        "A",
    ),
    (
        "Check if high-beta stocks have higher returns.",
        "Use the 2010 Flash Crash as an exogenous shock to market-maker inventory to identify the causal effect of liquidity provision on price efficiency via difference-in-differences.",
        "B",
    ),
    (
        "Instrument analyst coverage with brokerage mergers to identify the causal effect of information production on stock price synchronicity.",
        "See if analyst recommendations predict returns.",
        "A",
    ),
    (
        "Test whether momentum profits exist internationally.",
        "Exploit randomized SEC comment letter assignments to identify the real effects of disclosure enforcement on corporate investment.",
        "B",
    ),
    (
        "Use the staggered rollout of 5G infrastructure across US counties as an instrument for high-frequency trading intensity to estimate causal effects on price discovery.",
        "Compute the average return of tech stocks over the last decade.",
        "A",
    ),
    (
        "Plot the S&P 500 index over time.",
        "Combine satellite imagery of parking lots with a structural model of consumer demand to nowcast retail firm revenues before earnings announcements, using event-study methodology.",
        "B",
    ),
    (
        "Apply a shift-share instrument using pre-period industry employment shares and aggregate trade shocks to identify the causal effect of trade exposure on local bank lending.",
        "Test if small-cap stocks outperform large-cap stocks.",
        "A",
    ),
    (
        "Calculate Sharpe ratios for different sectors.",
        "Use the random assignment of judges in SEC enforcement cases as an instrument to identify the deterrence effect of financial penalties on peer firms' earnings management.",
        "B",
    ),
    (
        "Exploit the SEC's EDGAR server log data to construct a measure of investor attention, using rainfall at institutional investor headquarters as an instrument in IV regressions of attention on trading volume.",
        "Check whether value stocks outperform growth stocks.",
        "A",
    ),
    (
        "Look at the correlation between oil prices and airline stocks.",
        "Design a bunching estimator around the $75M public float threshold for accelerated filer status to identify the real effects of disclosure regulation on firm investment.",
        "B",
    ),
    (
        "Use the staggered introduction of circuit breakers across international exchanges as a natural experiment, applying difference-in-differences with heterogeneous treatment timing corrections, to measure the causal effect of trading halts on volatility clustering.",
        "Run a simple regression of returns on book-to-market ratio.",
        "A",
    ),
    (
        "Compute moving averages for technical trading rules.",
        "Exploit the quasi-random assignment of firms to NYSE specialists (pre-2008) as an instrument for market-maker quality, identifying causal effects on IPO underpricing and long-run survival.",
        "B",
    ),
    (
        "Construct a granular instrumental variable from the geographic overlap of mutual fund investor bases and local economic shocks to identify fire-sale spillovers in corporate bond markets.",
        "Test if dividends predict future stock returns.",
        "A",
    ),
]

# 3 verification tasks: finalist ideas with a planted fatal flaw.
# Each entry: (idea_text, planted_flaw_description)
VERIFICATION_TASKS = [
    (
        "We propose using daily Google Trends data as an instrument for retail "
        "investor attention in IV regressions of attention on stock returns. The "
        "exclusion restriction holds because Google search volume affects returns "
        "only through attention. We use the full cross-section of US equities "
        "from 2004-2024 with Fama-French factors as controls.",
        "The exclusion restriction is violated: Google Trends search volume is "
        "well-documented to directly predict returns through channels other than "
        "attention (e.g., correlated with economic fundamentals, news shocks). "
        "This is not a valid instrument.",
    ),
    (
        "We exploit the 2020 Robinhood outage as a natural experiment. During "
        "the March 2020 outage, Robinhood users could not trade while users of "
        "other brokerages could. We compare price dynamics of high-Robinhood-"
        "ownership stocks (treatment) to low-Robinhood-ownership stocks (control) "
        "using a difference-in-differences framework to identify the causal effect "
        "of retail trading on price efficiency.",
        "The March 2020 outage coincided with extreme COVID-19 market stress. "
        "The parallel trends assumption is fatally violated because high-Robinhood-"
        "ownership stocks (meme stocks, speculative growth) had systematically "
        "different exposure to the COVID crash than the control group. Any "
        "treatment effect is confounded by differential COVID sensitivity.",
    ),
    (
        "We propose a structural model of dealer inventory management calibrated "
        "to TRACE corporate bond transaction data. The model features a "
        "representative dealer optimizing over inventory costs and adverse "
        "selection. We calibrate 47 parameters using simulated method of moments "
        "with 12 moment conditions targeting bid-ask spreads, trading volume, "
        "and price impact coefficients.",
        "The model is severely under-identified: 47 parameters with only 12 "
        "moment conditions means the system has 35 degrees of under-identification. "
        "The parameters cannot be uniquely pinned down. This is a fundamental "
        "identification failure, not a data or estimation issue.",
    ),
]

VERIFICATION_SYSTEM = (
    "You are an expert methodologist reviewing a finance research proposal for "
    "fatal identification or methodological flaws. Examine the proposal carefully "
    "and identify any FATAL flaw that would invalidate the research design. "
    "A fatal flaw is one that cannot be fixed with minor adjustments.\n\n"
    "Respond with a JSON object: "
    '{"flaw_detected": true/false, "flaw_description": "..."}'
)

JUDGING_SYSTEM = (
    "You are an expert research evaluator. You will be given two research ideas "
    "(Idea A and Idea B). Determine which idea is stronger based on: novelty, "
    "identification rigor, feasibility, and overall research quality.\n\n"
    "Respond ONLY with a JSON object: "
    '{"winner": "A" or "B", "reasoning": "brief explanation"}'
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path: Path) -> dict:
    """Load a JSON file and return parsed dict."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return json.loads(path.read_text())


def call_llm(model: str, prompt: str, system: str | None = None,
             model_settings: Path = DEFAULT_MODEL_SETTINGS) -> str:
    """Call llm_runner.py via subprocess and return the response text."""
    cmd = [
        sys.executable, str(LLM_RUNNER),
        "--model", model,
        "--prompt", prompt,
        "--settings", str(model_settings),
        "--temperature", "0.7",
        "--max-tokens", "2048",
    ]
    if system:
        cmd.extend(["--system", system])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"llm_runner failed for {model}: {result.stderr.strip()[:500]}"
        )
    return result.stdout.strip()


def parse_json_from_response(text: str) -> dict:
    """Extract a JSON object from an LLM response, tolerating markdown fences."""
    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    cleaned = cleaned.strip().rstrip("`")
    # Find the first { ... } block
    match = re.search(r"\{[^{}]*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    # Fallback: try parsing the whole cleaned string
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {}


def get_output_price(model: str, pricing: dict) -> float:
    """Get output price per 1M tokens for a model. Returns 0.0 if unknown."""
    models = pricing.get("models", {})
    entry = models.get(model, {})
    return float(entry.get("output_per_1m", 0.0))


# ---------------------------------------------------------------------------
# Benchmark functions
# ---------------------------------------------------------------------------

def benchmark_generation(
    candidates: list[str],
    judge_model: str,
    pricing: dict,
    mode: str,
    model_settings: Path,
) -> dict[str, dict]:
    """Benchmark models for the generation stage (Stage B).

    Runs 5 prompts through each candidate, then has the judge evaluate each.
    Returns {model: {metric, cost, score}}.
    """
    results: dict[str, dict] = {}

    for model in candidates:
        scores: list[float] = []
        for i, prompt in enumerate(GENERATION_PROMPTS):
            print(f"  [{model}] generation prompt {i+1}/5 ...", flush=True)
            try:
                output = call_llm(model, prompt, model_settings=model_settings)
            except Exception as e:
                print(f"    WARN: generation call failed: {e}", file=sys.stderr)
                scores.append(0.0)
                continue

            # Judge the output
            judge_prompt = (
                f"Evaluate this research idea:\n\n{output}\n\n"
                "Provide your rating as specified."
            )
            print(f"  [{model}] judging prompt {i+1}/5 ...", flush=True)
            try:
                judge_resp = call_llm(
                    judge_model, judge_prompt, system=JUDGE_SYSTEM,
                    model_settings=model_settings,
                )
                parsed = parse_json_from_response(judge_resp)
                overall = float(parsed.get("overall", 0))
                scores.append(max(0.0, min(10.0, overall)))
            except Exception as e:
                print(f"    WARN: judging call failed: {e}", file=sys.stderr)
                scores.append(0.0)

        metric = sum(scores) / len(scores) if scores else 0.0
        output_price = get_output_price(model, pricing)
        # 5 generation calls + 5 judging calls = 10 total calls
        cost_estimate = output_price  # per-1M output price as proxy

        if mode == "quality_per_dollar" and output_price > 0:
            score = metric / output_price
        else:
            score = metric

        results[model] = {
            "metric": round(metric, 4),
            "cost_per_1m_output": output_price,
            "score": round(score, 4),
            "individual_scores": [round(s, 2) for s in scores],
        }

    return results


def benchmark_judging(
    candidates: list[str],
    pricing: dict,
    mode: str,
    model_settings: Path,
) -> dict[str, dict]:
    """Benchmark models for the judging stage (Stage D).

    Tests 15 calibration pairs. Metric: rho = accuracy * (1 - bias).
    Returns {model: {metric, cost, score}}.
    """
    results: dict[str, dict] = {}

    for model in candidates:
        correct = 0
        chose_a = 0
        total = len(JUDGING_CALIBRATION_PAIRS)

        for i, (idea_a, idea_b, expected) in enumerate(JUDGING_CALIBRATION_PAIRS):
            prompt = (
                f"Idea A:\n{idea_a}\n\nIdea B:\n{idea_b}\n\n"
                "Which idea is stronger? Respond as specified."
            )
            print(f"  [{model}] judging pair {i+1}/{total} ...", flush=True)
            try:
                resp = call_llm(
                    model, prompt, system=JUDGING_SYSTEM,
                    model_settings=model_settings,
                )
                parsed = parse_json_from_response(resp)
                winner = parsed.get("winner", "").strip().upper()

                if winner == "A":
                    chose_a += 1
                if winner == expected:
                    correct += 1
            except Exception as e:
                print(f"    WARN: judging call failed: {e}", file=sys.stderr)

        accuracy = correct / total if total > 0 else 0.0
        bias = abs((chose_a / total) - 0.5) if total > 0 else 0.5
        rho = accuracy * (1.0 - bias)

        output_price = get_output_price(model, pricing)
        if mode == "quality_per_dollar" and output_price > 0:
            score = rho / output_price
        else:
            score = rho

        results[model] = {
            "metric": round(rho, 4),
            "accuracy": round(accuracy, 4),
            "bias": round(bias, 4),
            "cost_per_1m_output": output_price,
            "score": round(score, 4),
            "correct": correct,
            "chose_a": chose_a,
            "total": total,
        }

    return results


def benchmark_verification(
    candidates: list[str],
    pricing: dict,
    mode: str,
    model_settings: Path,
) -> dict[str, dict]:
    """Benchmark models for the verification stage (Stage E).

    Tests 3 ideas with planted fatal flaws. Metric: flaw detection rate.
    Returns {model: {metric, cost, score}}.
    """
    results: dict[str, dict] = {}

    for model in candidates:
        detected = 0
        total = len(VERIFICATION_TASKS)

        for i, (idea_text, _planted_flaw) in enumerate(VERIFICATION_TASKS):
            prompt = (
                f"Review this research proposal for fatal methodological flaws:"
                f"\n\n{idea_text}\n\nRespond as specified."
            )
            print(f"  [{model}] verification task {i+1}/{total} ...", flush=True)
            try:
                resp = call_llm(
                    model, prompt, system=VERIFICATION_SYSTEM,
                    model_settings=model_settings,
                )
                parsed = parse_json_from_response(resp)
                if parsed.get("flaw_detected") is True:
                    detected += 1
            except Exception as e:
                print(f"    WARN: verification call failed: {e}", file=sys.stderr)

        detection_rate = detected / total if total > 0 else 0.0
        output_price = get_output_price(model, pricing)

        if mode == "quality_per_dollar" and output_price > 0:
            score = detection_rate / output_price
        else:
            score = detection_rate

        results[model] = {
            "metric": round(detection_rate, 4),
            "detected": detected,
            "total": total,
            "cost_per_1m_output": output_price,
            "score": round(score, 4),
        }

    return results


# ---------------------------------------------------------------------------
# Auto-update
# ---------------------------------------------------------------------------

def auto_update_config(
    stage: str,
    winner: str,
    geps_config_path: Path,
) -> str | None:
    """Update geps-config.json with the benchmark winner. Returns a description
    of the change made, or None if no change was needed."""
    config = load_json(geps_config_path)

    change = None

    if stage == "generation":
        # Replace the model of the lowest-weighted generation channel
        channels = config.get("generation", {}).get("channels", {})
        if not channels:
            return None
        lowest_name = min(channels, key=lambda c: channels[c].get("weight", 1.0))
        old_model = channels[lowest_name].get("model")
        if old_model != winner:
            channels[lowest_name]["model"] = winner
            change = (
                f"generation: replaced channel '{lowest_name}' model "
                f"'{old_model}' -> '{winner}'"
            )

    elif stage == "judging":
        judge_pool = config.get("tournament", {}).get("judge_pool", [])
        if winner not in judge_pool:
            judge_pool.append(winner)
            config["tournament"]["judge_pool"] = judge_pool
            change = f"judging: appended '{winner}' to tournament.judge_pool"

    elif stage == "verification":
        verifier_models = config.get("verification", {}).get("verifier_models", [])
        if winner not in verifier_models:
            verifier_models.append(winner)
            config["verification"]["verifier_models"] = verifier_models
            change = f"verification: appended '{winner}' to verification.verifier_models"

    if change:
        geps_config_path.write_text(json.dumps(config, indent=2) + "\n")
        print(f"  AUTO-UPDATE: {change}")

    return change


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def append_history(
    history_file: Path,
    stage: str,
    mode: str,
    candidates: list[str],
    results: dict[str, dict],
    winner: str,
) -> None:
    """Append one JSON line to the benchmark history file."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "mode": mode,
        "candidates": candidates,
        "scores": {m: r.get("score", 0) for m, r in results.items()},
        "winner": winner,
        "cost_estimate": {m: r.get("cost_per_1m_output", 0) for m, r in results.items()},
    }
    with open(history_file, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"  History appended to {history_file}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="GEPS v5 model benchmark — evaluate candidate LLMs per stage."
    )
    parser.add_argument(
        "--stage", required=True,
        choices=["generation", "judging", "verification"],
        help="Pipeline stage to benchmark.",
    )
    parser.add_argument(
        "--candidate-models", required=True,
        help="Comma-separated model names (e.g. 'glm-5,minimax-m2.5').",
    )
    parser.add_argument(
        "--mode", default="quality_per_dollar",
        choices=["quality_per_dollar", "raw_performance"],
        help="Scoring mode (default: quality_per_dollar).",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Write full results JSON to this file.",
    )
    parser.add_argument(
        "--history-file", type=Path, default=None,
        help="Append one JSONL entry per run to this file.",
    )
    parser.add_argument(
        "--auto-update", action="store_true",
        help="Auto-update geps-config.json with the winning model.",
    )
    parser.add_argument(
        "--judge-model", default="opus",
        help="Model used to judge generation outputs (default: opus).",
    )
    parser.add_argument(
        "--geps-config", type=Path, default=DEFAULT_GEPS_CONFIG,
        help="Path to geps-config.json.",
    )
    parser.add_argument(
        "--model-settings", type=Path, default=DEFAULT_MODEL_SETTINGS,
        help="Path to model-settings.json for llm_runner.",
    )
    parser.add_argument(
        "--pricing", type=Path, default=DEFAULT_PRICING,
        help="Path to model_pricing.json.",
    )

    args = parser.parse_args()

    candidates = [m.strip() for m in args.candidate_models.split(",") if m.strip()]
    if not candidates:
        parser.error("--candidate-models must list at least one model.")

    pricing = load_json(args.pricing)

    print(f"=== GEPS v5 Model Benchmark ===")
    print(f"Stage: {args.stage}")
    print(f"Mode:  {args.mode}")
    print(f"Candidates: {', '.join(candidates)}")
    if args.stage == "generation":
        print(f"Judge model: {args.judge_model}")
    print()

    # Run the appropriate benchmark
    if args.stage == "generation":
        results = benchmark_generation(
            candidates, args.judge_model, pricing, args.mode, args.model_settings,
        )
    elif args.stage == "judging":
        results = benchmark_judging(candidates, pricing, args.mode, args.model_settings)
    elif args.stage == "verification":
        results = benchmark_verification(candidates, pricing, args.mode, args.model_settings)
    else:
        parser.error(f"Unknown stage: {args.stage}")

    # Determine winner
    winner = max(results, key=lambda m: results[m].get("score", 0))

    # Build output
    output = {
        "stage": args.stage,
        "mode": args.mode,
        "judge_model": args.judge_model if args.stage == "generation" else None,
        "candidates": candidates,
        "results": results,
        "winner": winner,
        "winner_score": results[winner].get("score", 0),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Print summary
    print("\n=== Results ===")
    print(json.dumps(output, indent=2))
    print(f"\nWinner: {winner} (score={results[winner].get('score', 0):.4f})")

    # Write output file
    if args.output:
        args.output.write_text(json.dumps(output, indent=2) + "\n")
        print(f"Results written to {args.output}")

    # Append history
    if args.history_file:
        append_history(
            args.history_file, args.stage, args.mode, candidates, results, winner,
        )

    # Auto-update config
    if args.auto_update:
        change = auto_update_config(args.stage, winner, args.geps_config)
        if not change:
            print("  AUTO-UPDATE: no change needed (winner already configured).")


if __name__ == "__main__":
    main()
