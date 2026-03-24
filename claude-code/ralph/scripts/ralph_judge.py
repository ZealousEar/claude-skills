#!/usr/bin/env python3
"""ralph_judge.py — LLM-as-judge scoring for research ideas.

Replaces keyword heuristics with a 3-model cross-family ensemble that
produces calibrated 0-5 scores with real variance.

Architecture (from 5-solver debate, winner Solver C):
  - 3 CLI-free models: sonnet, chatgpt-5.4, kimi-2.5
  - Pointwise scoring, 3 calls per idea, median aggregation
  - 3 dimensions: novelty (0-5), feasibility (0-5), impact (0-5)
  - CoT reasoning before scoring + reference anchors
  - Temperature 0.1
  - Async-capable but works synchronously too

Usage:
    from ralph_judge import judge_idea
    scores = judge_idea(idea_dict)
    # → {"novelty": 3, "feasibility": 4, "impact": 2, "composite": 3.05,
    #    "low_confidence": False, "judge_models": [...]}
"""

import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# CLI-free models only — hard gate (no API cost)
CLI_FREE_MODELS = {"sonnet", "chatgpt-5.4", "gpt-5.3-codex", "kimi-2.5", "opus"}

# Default 3-model cross-family ensemble
DEFAULT_JUDGE_MODELS = ["sonnet", "chatgpt-5.4", "kimi-2.5"]

# Composite weights (debate winner: feasibility decreased per user request)
NOVELTY_WEIGHT = 0.40
FEASIBILITY_WEIGHT = 0.30
IMPACT_WEIGHT = 0.30

TEMPERATURE = 0.1
LOW_CONFIDENCE_SPREAD = 1.5  # Flag if max-min > this
JUDGE_TIMEOUT = 120  # seconds per CLI call


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

JUDGE_SYSTEM_PROMPT = """You are an expert academic reviewer evaluating research ideas for a Financial Technology MSc dissertation. Score the following idea on three dimensions, each on a 0-5 integer scale.

IMPORTANT: You MUST provide chain-of-thought reasoning (2-3 sentences) BEFORE each score. Then output the score as an integer.

## Scoring Anchors

### Novelty (0-5): How original is the research question and methodology?
- 0: Direct replication of existing published work with no variation
- 1: Minor parameter change on a well-known approach (e.g., "apply LSTM to S&P 500")
- 2: Combines two known techniques in a straightforward way (e.g., "LLM + derivatives" without a specific mechanism)
- 3: Novel combination with a clear, specific mechanism — not just "bridge two fields" but explains HOW the bridge produces new insight
- 4: Introduces a testable hypothesis that challenges existing assumptions in the subfield, with a methodology that has not been applied to this specific problem before
- 5: Paradigm-shifting idea that reframes an open problem entirely — would surprise domain experts

IMPORTANT: Simply combining two research areas (e.g., NLP + finance) is NOT automatically a 4. Score 2-3 unless the specific mechanism of combination is itself novel. Ask: "Has anyone tried this exact approach before?" If yes → score 2. If the approach is new but the insight is obvious → score 3. If both approach AND insight are genuinely surprising → score 4-5.

### Feasibility (0-5): Can a single MSc student complete this in 12 months with public data?
- 0: Requires proprietary data, GPU clusters, or multi-year effort
- 1: Major infrastructure or data access barriers
- 2: Significant but surmountable challenges (specialized skills, moderate compute)
- 3: Achievable with focused effort, public data, standard hardware
- 4: Well-scoped with clear methodology and accessible data
- 5: Straightforward execution path with established tools and freely available data

### Impact (0-5): Would this contribution matter to the research community?
- 0: No audience — trivial or solved problem
- 1: Incremental — minor extension of existing work
- 2: Useful — fills a small gap in the literature
- 3: Significant — addresses a recognized open question
- 4: Important — could influence research direction in a subfield
- 5: High impact — addresses a fundamental question with broad implications

## Output Format

You MUST respond with ONLY a JSON object (no markdown fences, no explanation outside the JSON):

{"novelty_reasoning": "2-3 sentences analyzing originality...", "novelty": N, "feasibility_reasoning": "2-3 sentences analyzing feasibility...", "feasibility": N, "impact_reasoning": "2-3 sentences analyzing impact...", "impact": N}

Where N is an integer from 0 to 5. Be discriminating — do NOT default to 3 for everything."""


def _build_user_prompt(idea: dict) -> str:
    """Build the user prompt from an idea dict."""
    title = idea.get("title", "Untitled")
    rq = idea.get("research_question", "")
    abstract = idea.get("abstract", "")
    methodology = idea.get("methodology", "")
    novelty_claim = idea.get("novelty_claim", "")
    feasibility = idea.get("feasibility_notes", "")
    mechanisms = idea.get("key_mechanisms", [])

    parts = [f"# Research Idea: {title}"]
    if rq:
        parts.append(f"\n**Research Question:** {rq}")
    if abstract:
        parts.append(f"\n**Abstract:** {abstract[:800]}")
    if methodology:
        parts.append(f"\n**Methodology:** {methodology[:500]}")
    if novelty_claim:
        parts.append(f"\n**Novelty Claim:** {novelty_claim[:300]}")
    if feasibility:
        parts.append(f"\n**Feasibility Notes:** {feasibility[:300]}")
    if mechanisms and isinstance(mechanisms, list):
        parts.append(f"\n**Key Mechanisms:** {', '.join(str(m) for m in mechanisms[:5])}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# LLM call via CLI
# ---------------------------------------------------------------------------

def _call_judge_model(model: str, idea: dict) -> dict | None:
    """Call a single judge model via CLI and parse the score."""
    if model not in CLI_FREE_MODELS:
        raise ValueError(f"Model '{model}' is not CLI-free. Allowed: {CLI_FREE_MODELS}")

    user_prompt = _build_user_prompt(idea)

    # Route to appropriate CLI
    if model in ("sonnet", "opus"):
        return _call_claude_cli(model, user_prompt)
    elif model in ("chatgpt-5.4", "gpt-5.3-codex"):
        return _call_codex_cli(model, user_prompt)
    elif model == "kimi-2.5":
        return _call_kimi_cli(user_prompt)
    else:
        return None


def _call_claude_cli(model: str, user_prompt: str) -> dict | None:
    """Call Claude via claude CLI."""
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
    """Call GPT via codex CLI. Uses stdin pipe to avoid prompt-rewriting."""
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
            # Codex rate limit or failure — try parsing stderr for useful info
            return None
        return _parse_judge_response(result.stdout)
    except (subprocess.TimeoutExpired, OSError):
        return None


def _call_kimi_cli(user_prompt: str) -> dict | None:
    """Call Kimi via kimi CLI."""
    kimi_bin = shutil.which("kimi")
    if not kimi_bin:
        return None

    full_prompt = f"{JUDGE_SYSTEM_PROMPT}\n\n---\n\n{user_prompt}"
    try:
        # Kimi CLI: pass prompt via stdin to avoid shell escaping issues
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
    """Parse judge response into {novelty, feasibility, impact} scores."""
    if not text:
        return None

    # Try JSON extraction — balanced brace parser (Rule 5)
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
                # Validate required fields
                scores = {}
                for dim in ("novelty", "feasibility", "impact"):
                    val = obj.get(dim)
                    if val is None:
                        return None
                    val = int(val)
                    if val < 0 or val > 5:
                        return None
                    scores[dim] = val
                # Include reasoning if present
                for dim in ("novelty", "feasibility", "impact"):
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

def judge_idea(
    idea: dict,
    models: list[str] | None = None,
    parallel: bool = True,
) -> dict:
    """Score an idea using the 3-model ensemble.

    Returns:
        {
            "novelty": float (0-5, median),
            "feasibility": float (0-5, median),
            "impact": float (0-5, median),
            "composite": float (weighted combination),
            "low_confidence": bool (True if max-min spread > 1.5 on any dim),
            "judge_models": list[str] (models that responded),
            "judge_scores": list[dict] (per-model raw scores),
        }

    On total failure, returns scores of None (not 1.0 — Rule 1).
    """
    if models is None:
        models = DEFAULT_JUDGE_MODELS

    # Hard gate: CLI-free only
    for m in models:
        if m not in CLI_FREE_MODELS:
            raise ValueError(f"Model '{m}' not in CLI_FREE_MODELS. No API cost allowed.")

    results = []

    if parallel and len(models) > 1:
        with ThreadPoolExecutor(max_workers=len(models)) as pool:
            futures = {
                pool.submit(_call_judge_model, m, idea): m
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
                scores = _call_judge_model(m, idea)
                if scores:
                    scores["_model"] = m
                    results.append(scores)
            except Exception:
                pass

    # If no models responded, return NULL scores (Rule 1: never silent fallback)
    if not results:
        return {
            "novelty": None,
            "feasibility": None,
            "impact": None,
            "composite": None,
            "low_confidence": True,
            "judge_models": [],
            "judge_scores": [],
            "error": "All judge models failed",
        }

    # Aggregate via median per dimension
    output = {"judge_models": [r["_model"] for r in results], "judge_scores": results}

    for dim in ("novelty", "feasibility", "impact"):
        values = [r[dim] for r in results if dim in r]
        if values:
            values.sort()
            mid = len(values) // 2
            median = values[mid] if len(values) % 2 == 1 else (values[mid - 1] + values[mid]) / 2
            output[dim] = median
            # Check spread for low_confidence
            spread = max(values) - min(values)
        else:
            output[dim] = None

    # Check low_confidence across all dimensions
    low_conf = False
    for dim in ("novelty", "feasibility", "impact"):
        values = [r[dim] for r in results if dim in r]
        if values and (max(values) - min(values)) > LOW_CONFIDENCE_SPREAD:
            low_conf = True
            break
    output["low_confidence"] = low_conf

    # Composite score
    n = output.get("novelty")
    f = output.get("feasibility")
    i = output.get("impact")
    if n is not None and f is not None and i is not None:
        output["composite"] = round(
            NOVELTY_WEIGHT * n + FEASIBILITY_WEIGHT * f + IMPACT_WEIGHT * i, 2
        )
    else:
        output["composite"] = None

    return output


# ---------------------------------------------------------------------------
# CLI for standalone testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LLM-as-judge for research ideas")
    parser.add_argument("--idea-json", required=True, help="Path to idea JSON file")
    parser.add_argument("--models", default=",".join(DEFAULT_JUDGE_MODELS),
                        help=f"Comma-separated judge models (default: {','.join(DEFAULT_JUDGE_MODELS)})")
    parser.add_argument("--sequential", action="store_true", help="Run models sequentially")
    args = parser.parse_args()

    with open(args.idea_json) as f:
        idea = json.load(f)

    models = [m.strip() for m in args.models.split(",")]
    result = judge_idea(idea, models=models, parallel=not args.sequential)
    print(json.dumps(result, indent=2))
