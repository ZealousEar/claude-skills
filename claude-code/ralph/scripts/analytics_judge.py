#!/usr/bin/env python3
"""analytics_judge.py — LLM-as-judge scoring for analytics findings.

Mirrors ralph_judge.py but scores analytics findings on three dimensions:
novelty, actionability, evidence. Uses the same 3-model cross-family
ensemble with median aggregation.

Usage:
    from analytics_judge import judge_finding
    scores = judge_finding(finding_dict)
    # → {"novelty": 3, "actionability": 4, "evidence": 2, "composite": 3.05,
    #    "low_confidence": False, "judge_models": [...]}
"""

import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLI_FREE_MODELS = {"sonnet", "chatgpt-5.4", "gpt-5.3-codex", "kimi-2.5", "opus"}
DEFAULT_JUDGE_MODELS = ["sonnet", "chatgpt-5.4", "kimi-2.5"]

NOVELTY_WEIGHT = 0.35
ACTIONABILITY_WEIGHT = 0.35
EVIDENCE_WEIGHT = 0.30

DIMENSIONS = ("novelty", "actionability", "evidence")

JUDGE_TIMEOUT = 120
LOW_CONFIDENCE_SPREAD = 1.5


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

JUDGE_SYSTEM_PROMPT = """You are an expert data analyst evaluating findings from an analytics discovery loop. Score the following finding on three dimensions, each on a 0-5 integer scale.

IMPORTANT: You MUST provide chain-of-thought reasoning (2-3 sentences) BEFORE each score. Then output the score as an integer.

## Scoring Anchors

### Novelty (0-5): How surprising or non-obvious is this finding?
- 0: Trivially obvious (e.g., "more users sign up on weekdays")
- 1: Expected result that confirms a well-known pattern
- 2: Mildly interesting — quantifies something suspected but not measured
- 3: Genuinely surprising — reveals a pattern that was not predicted, or contradicts an assumption
- 4: Cross-cutting insight combining multiple data dimensions in an unexpected way
- 5: Paradigm-shifting — reframes how the team should think about the funnel or user behavior

IMPORTANT: A finding that simply reports a metric is NOT novel. The insight must be unexpected or reveal a non-obvious relationship. Ask: "Would a smart analyst have predicted this before seeing the data?" If yes → score 0-2.

### Actionability (0-5): Can the team act on this finding with a specific, concrete change?
- 0: Pure observation with no clear action ("users exist")
- 1: Vague directional insight ("we should improve onboarding")
- 2: Identifies what to improve but not how (e.g., "drop-off is high at stage 4")
- 3: Specific recommendation with a clear mechanism (e.g., "send reminder email 24h after paywall hit")
- 4: Detailed recommendation with quantified expected impact and a concrete implementation path
- 5: Ready-to-execute recommendation with A/B test design, success metrics, and estimated lift

### Evidence (0-5): How well does the data support the conclusion?
- 0: No data cited — pure speculation
- 1: Anecdotal — references data but no specific numbers
- 2: Single metric cited without context (e.g., "conversion is 5%")
- 3: Multiple metrics with context, reasonable sample size, clear methodology
- 4: Rigorous analysis — statistical significance, cohort controls, sample sizes stated
- 5: Multi-faceted evidence with temporal validation, segment comparisons, and confidence intervals

## Output Format

You MUST respond with ONLY a JSON object (no markdown fences, no explanation outside the JSON):

{"novelty_reasoning": "2-3 sentences...", "novelty": N, "actionability_reasoning": "2-3 sentences...", "actionability": N, "evidence_reasoning": "2-3 sentences...", "evidence": N}

Where N is an integer from 0 to 5. Be discriminating — do NOT default to 3 for everything."""


def _build_user_prompt(finding: dict) -> str:
    """Build the user prompt from a finding dict."""
    title = finding.get("finding_title", "Untitled")
    summary = finding.get("finding_summary", "")
    recommendation = finding.get("recommendation", "")
    key_metrics = finding.get("key_metrics", {})
    evidence_str = finding.get("evidence_strength", "")
    confidence = finding.get("confidence", "")
    sql_queries = finding.get("sql_queries_used", [])

    parts = [f"# Analytics Finding: {title}"]
    if summary:
        parts.append(f"\n**Summary:** {summary[:800]}")
    if recommendation:
        parts.append(f"\n**Recommendation:** {recommendation[:500]}")
    if key_metrics and isinstance(key_metrics, dict):
        metrics_str = ", ".join(f"{k}: {v}" for k, v in list(key_metrics.items())[:10])
        parts.append(f"\n**Key Metrics:** {metrics_str}")
    if evidence_str:
        parts.append(f"\n**Evidence:** {evidence_str[:300]}")
    if confidence:
        parts.append(f"\n**Confidence:** {confidence}")
    if sql_queries and isinstance(sql_queries, list):
        parts.append(f"\n**SQL Queries Used:** {len(sql_queries)} queries")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# LLM calls via CLI (mirrors ralph_judge.py)
# ---------------------------------------------------------------------------

def _call_judge_model(model: str, finding: dict) -> dict | None:
    """Call a single judge model via CLI and parse the score."""
    if model not in CLI_FREE_MODELS:
        raise ValueError(f"Model '{model}' is not CLI-free. Allowed: {CLI_FREE_MODELS}")

    user_prompt = _build_user_prompt(finding)

    if model in ("sonnet", "opus"):
        return _call_claude_cli(model, user_prompt)
    elif model in ("chatgpt-5.4", "gpt-5.3-codex"):
        return _call_codex_cli(model, user_prompt)
    elif model == "kimi-2.5":
        return _call_kimi_cli(user_prompt)
    return None


def _call_claude_cli(model: str, user_prompt: str) -> dict | None:
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return None
    full_prompt = f"{JUDGE_SYSTEM_PROMPT}\n\n---\n\n{user_prompt}"
    try:
        result = subprocess.run(
            [claude_bin, "-p", full_prompt, "--model", model,
             "--output-format", "text", "--max-turns", "1"],
            capture_output=True, text=True, timeout=JUDGE_TIMEOUT,
        )
        if result.returncode != 0:
            return None
        return _parse_judge_response(result.stdout)
    except (subprocess.TimeoutExpired, OSError):
        return None


def _call_codex_cli(model: str, user_prompt: str) -> dict | None:
    codex_bin = shutil.which("codex")
    if not codex_bin:
        return None
    full_prompt = f"{JUDGE_SYSTEM_PROMPT}\n\n---\n\n{user_prompt}"
    model_id = "gpt-5.4" if model == "chatgpt-5.4" else model
    try:
        result = subprocess.run(
            [codex_bin, "exec", "--full-auto", "-m", model_id, "-q", full_prompt],
            capture_output=True, text=True, timeout=JUDGE_TIMEOUT,
        )
        if result.returncode != 0:
            return None
        return _parse_judge_response(result.stdout)
    except (subprocess.TimeoutExpired, OSError):
        return None


def _call_kimi_cli(user_prompt: str) -> dict | None:
    kimi_bin = shutil.which("kimi")
    if not kimi_bin:
        return None
    full_prompt = f"{JUDGE_SYSTEM_PROMPT}\n\n---\n\n{user_prompt}"
    try:
        result = subprocess.run(
            [kimi_bin],
            input=full_prompt,
            capture_output=True, text=True, timeout=JUDGE_TIMEOUT,
        )
        if result.returncode != 0:
            return None
        return _parse_judge_response(result.stdout)
    except (subprocess.TimeoutExpired, OSError):
        return None


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _parse_judge_response(text: str) -> dict | None:
    """Parse judge response into {novelty, actionability, evidence} scores."""
    if not text:
        return None

    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    for i, c in enumerate(text[start:], start):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        if depth == 0:
            try:
                obj = json.loads(text[start:i + 1])
                scores = {}
                for dim in DIMENSIONS:
                    val = obj.get(dim)
                    if val is None:
                        return None
                    val = int(val)
                    if val < 0 or val > 5:
                        return None
                    scores[dim] = val
                for dim in DIMENSIONS:
                    reasoning_key = f"{dim}_reasoning"
                    if reasoning_key in obj:
                        scores[reasoning_key] = obj[reasoning_key]
                return scores
            except (json.JSONDecodeError, ValueError, TypeError):
                return None

    return None


# ---------------------------------------------------------------------------
# Ensemble scoring
# ---------------------------------------------------------------------------

def judge_finding(
    finding: dict,
    models: list[str] | None = None,
    parallel: bool = True,
) -> dict:
    """Score a finding using the 3-model ensemble.

    Returns:
        {
            "novelty": float (0-5, median),
            "actionability": float (0-5, median),
            "evidence": float (0-5, median),
            "composite": float (weighted combination),
            "low_confidence": bool,
            "judge_models": list[str],
            "judge_scores": list[dict],
        }

    On total failure, returns scores of None.
    """
    if models is None:
        models = DEFAULT_JUDGE_MODELS

    for m in models:
        if m not in CLI_FREE_MODELS:
            raise ValueError(f"Model '{m}' not in CLI_FREE_MODELS. No API cost allowed.")

    results = []

    if parallel and len(models) > 1:
        with ThreadPoolExecutor(max_workers=len(models)) as pool:
            futures = {
                pool.submit(_call_judge_model, m, finding): m
                for m in models
            }
            for future in as_completed(futures):
                model_name = futures[future]
                try:
                    scores = future.result()
                    if scores:
                        scores["_model"] = model_name
                        results.append(scores)
                except Exception:
                    pass
    else:
        for m in models:
            try:
                scores = _call_judge_model(m, finding)
                if scores:
                    scores["_model"] = m
                    results.append(scores)
            except Exception:
                pass

    if not results:
        return {
            "novelty": None,
            "actionability": None,
            "evidence": None,
            "composite": None,
            "low_confidence": True,
            "judge_models": [],
            "judge_scores": [],
            "error": "All judge models failed",
        }

    output = {"judge_models": [r["_model"] for r in results], "judge_scores": results}

    for dim in DIMENSIONS:
        values = [r[dim] for r in results if dim in r]
        if values:
            values.sort()
            mid = len(values) // 2
            median = values[mid] if len(values) % 2 == 1 else (values[mid - 1] + values[mid]) / 2
            output[dim] = median
        else:
            output[dim] = None

    low_conf = False
    for dim in DIMENSIONS:
        values = [r[dim] for r in results if dim in r]
        if values and (max(values) - min(values)) > LOW_CONFIDENCE_SPREAD:
            low_conf = True
            break
    output["low_confidence"] = low_conf

    n = output.get("novelty")
    a = output.get("actionability")
    e = output.get("evidence")
    if n is not None and a is not None and e is not None:
        output["composite"] = round(
            NOVELTY_WEIGHT * n + ACTIONABILITY_WEIGHT * a + EVIDENCE_WEIGHT * e, 2
        )
    else:
        output["composite"] = None

    return output


# ---------------------------------------------------------------------------
# CLI for standalone testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LLM-as-judge for analytics findings")
    parser.add_argument("--finding-json", required=True, help="Path to finding JSON file")
    parser.add_argument("--models", default=",".join(DEFAULT_JUDGE_MODELS),
                        help=f"Comma-separated judge models (default: {','.join(DEFAULT_JUDGE_MODELS)})")
    parser.add_argument("--sequential", action="store_true", help="Run models sequentially")
    args = parser.parse_args()

    with open(args.finding_json) as f:
        finding = json.load(f)

    models = [m.strip() for m in args.models.split(",")]
    result = judge_finding(finding, models=models, parallel=not args.sequential)
    print(json.dumps(result, indent=2))
