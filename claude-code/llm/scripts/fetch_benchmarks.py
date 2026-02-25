#!/usr/bin/env python3
"""Fetch LLM benchmarks from public leaderboards and save as local CSV.

Sources:
  1. Chatbot Arena (LMArena) — Elo from human preference voting
  2. Epoch AI — benchmark scores (GPQA, MMLU, MATH, SWE-bench, etc.)
  3. OpenRouter — pricing, context length, model metadata
  4. Artificial Analysis — Intelligence Index, speed metrics (TPS/TTFT)

Quality methodology informed by BetterBench (arxiv:2411.12990, NeurIPS 2024).

Saves:
  benchmarks/rankings.csv   — unified rankings (THE file other skills read)
  benchmarks/_meta.json     — fetch timestamps and source status

Usage:
    python3 fetch_benchmarks.py                      # fetch all, update rankings
    python3 fetch_benchmarks.py --source arena       # only Chatbot Arena
    python3 fetch_benchmarks.py --source epoch       # only Epoch AI
    python3 fetch_benchmarks.py --source openrouter  # only OpenRouter
    python3 fetch_benchmarks.py --source aa          # only Artificial Analysis
    python3 fetch_benchmarks.py --list               # show local rankings table
    python3 fetch_benchmarks.py --list --top 50      # show top 50
    python3 fetch_benchmarks.py --model opus         # show benchmarks for a model
    python3 fetch_benchmarks.py --json               # output as JSON

Stdlib only — no pip dependencies.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SKILL_DIR = Path.home() / ".claude" / "skills" / "llm"
BENCHMARKS_DIR = SKILL_DIR / "benchmarks"
RANKINGS_PATH = BENCHMARKS_DIR / "rankings.csv"
META_PATH = BENCHMARKS_DIR / "_meta.json"
REGISTRY_PATH = SKILL_DIR / "settings" / "model-registry.json"

DEBATE_AGENT_ENV = (
    Path.home() / ".claude" / "skills" / "convolutional-debate-agent"
    / "api-keys" / "provider-keys.env"
)

# ---------------------------------------------------------------------------
# CSV schema
# ---------------------------------------------------------------------------
COLUMNS = [
    "model",              # Display name (from best available source)
    "provider",           # Organization (anthropic, openai, google, etc.)
    "arena_elo",          # Chatbot Arena Elo score
    "gpqa",               # GPQA Diamond score (%)
    "mmlu",               # MMLU score (%) — renamed from mmlu_pro
    "coding",             # Best coding score (HumanEval/LiveCodeBench, %)
    "math",               # MATH/AIME score (%)
    "swe_bench",          # SWE-bench Verified resolve rate (%)
    "aa_index",           # Artificial Analysis Intelligence Index (0-100)
    "eci",                # Epoch Capabilities Index (composite, ~100-160 scale)
    "quality_index",      # LiveBench global average (from Epoch AI)
    "simpleqa",           # SimpleQA factual accuracy (%)
    "arc_agi",            # ARC-AGI abstract reasoning (%)
    "frontier_math",      # FrontierMath advanced math (%)
    "speed_tps",          # Tokens per second (median)
    "speed_ttft",         # Time to first token in seconds (from AA)
    "context",            # Context window (tokens)
    "price_in",           # Input price ($/1M tokens)
    "price_out",          # Output price ($/1M tokens)
    "benchmark_quality",  # BetterBench-informed quality tier: high/medium/low
    "registry_name",      # Matching name in model-registry.json (empty if none)
    "sources",            # Comma-separated list of data sources
]

# ---------------------------------------------------------------------------
# Model name normalization + alias mapping
# ---------------------------------------------------------------------------

def _normalize(name: str) -> str:
    """Normalize model name: lowercase, keep alphanumeric + hyphens + dots + slashes."""
    return re.sub(r'[^a-z0-9.\-/]', '', name.lower().strip())


# Tier1 registry models -> known aliases from various benchmark sources
_TIER1_ALIASES: dict[str, list[str]] = {
    # NOTE: Each numbered version (4.0, 4.1, 4.5, 4.6) is a SEPARATE model.
    # Only aliases for the CURRENT latest version of each tier belong here.
    # See references/model-lineup-2026-02.md for the full version history.
    "opus": [
        "opus", "claude-opus-4-6", "claude opus 4.6",
        "anthropic/claude-opus-4-6", "anthropic/claude-opus-4.6", "claude-opus-4.6",
        # Epoch AI model version names (4.6 with context variants)
        "claude-opus-4-6_120k", "claude-opus-4-6_32k", "claude-opus-4-6_16k",
        # Arena (arena-catalog) names — "thinking" suffix = same model, extended thinking on
        "claude-opus-4-6-thinking-32k", "claude-opus-4-6-thinking-16k",
        # Artificial Analysis names
        "Claude Opus 4.6",
    ],
    "sonnet": [
        "sonnet", "claude-sonnet-4-6", "claude sonnet 4.6",
        "anthropic/claude-sonnet-4.6", "claude-sonnet-4.6",
        # Epoch AI model version names (4.6 with context variants)
        "claude-sonnet-4-6_32k", "claude-sonnet-4-6_16k",
        # Arena (arena-catalog) names
        "claude-sonnet-4-6-thinking-32k", "claude-sonnet-4-6-thinking-16k",
        # Artificial Analysis names
        "Claude Sonnet 4.6",
    ],
    "haiku": [
        "haiku", "claude-haiku-4-5", "claude haiku 4.5",
        "anthropic/claude-haiku-4-5-20251001", "anthropic/claude-haiku-4.5",
        "claude-haiku-4.5", "claude-haiku-4-5-20251001",
        # Artificial Analysis names
        "Claude Haiku 4.5",
    ],
    "gpt-5.3-codex": [
        "gpt-5.3-codex", "gpt-5.3", "openai/gpt-5.3",
        "openai/gpt-5.3-codex", "gpt5.3",
        # Artificial Analysis names
        "GPT-5.3", "GPT-5.3 Codex",
    ],
    "gpt-5.2": [
        "gpt-5.2", "openai/gpt-5.2", "gpt5.2",
        "openai/gpt-5.2-chat", "openai/gpt-5.2-codex",
        "gpt-5.2-2025-12-11",
        # Arena (arena-catalog) names
        "gpt-5.2-high", "gpt-5.2-chat-latest",
        # Artificial Analysis names
        "GPT-5.2",
    ],
    "gemini-3-pro": [
        "gemini-3-pro", "gemini-3-pro-preview", "gemini 3 pro",
        "google/gemini-3-pro-preview", "gemini3pro",
        # Artificial Analysis names
        "Gemini 3 Pro", "Gemini 3 Pro Preview",
    ],
    "gemini-3-flash": [
        "gemini-3-flash", "gemini-3-flash-preview", "gemini 3 flash",
        "google/gemini-3-flash-preview", "gemini3flash",
        # Artificial Analysis names
        "Gemini 3 Flash", "Gemini 3 Flash Preview",
    ],
    "kimi-2.5": [
        "kimi-2.5", "kimi2.5", "moonshot/kimi-2.5",
        "moonshotai/kimi-k2.5", "kimi-k2.5",
        # Artificial Analysis names
        "Kimi 2.5", "Kimi K2.5",
    ],
    "glm-5": [
        "glm-5", "z-ai/glm-5", "glm5",
        # Artificial Analysis names
        "GLM-5",
    ],
    "minimax-m2.5": [
        "minimax-m2.5", "minimax/minimax-m2.5", "minimaxm2.5",
        # Artificial Analysis names
        "MiniMax M2.5",
    ],
}

# Build reverse lookup: normalized_alias -> registry_name
_ALIAS_MAP: dict[str, str] = {}
for _reg_name, _aliases in _TIER1_ALIASES.items():
    for _alias in _aliases:
        _ALIAS_MAP[_normalize(_alias)] = _reg_name
    _ALIAS_MAP[_reg_name] = _reg_name


def _canonical(raw_name: str) -> str:
    """Get canonical key for merging. Uses registry name if known, else normalized."""
    norm = _normalize(raw_name)
    return _ALIAS_MAP.get(norm, norm)


def _find_registry_name(raw_name: str) -> str:
    """Find registry name for a model, or return empty string."""
    norm = _normalize(raw_name)
    if norm in _ALIAS_MAP:
        return _ALIAS_MAP[norm]
    # No substring matching — too many false positives (e.g., "Claude 3 Haiku" -> "haiku")
    # Only exact alias matches are reliable
    return ""


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _http_get_json(url: str, headers: dict | None = None, timeout: int = 30) -> dict:
    """HTTP GET returning parsed JSON."""
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get_text(url: str, headers: dict | None = None, timeout: int = 30) -> str:
    """HTTP GET returning text."""
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read().decode("utf-8")


def _http_get_bytes(url: str, headers: dict | None = None, timeout: int = 60) -> bytes:
    """HTTP GET returning raw bytes."""
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read()


def _get_key(env_key: str) -> str | None:
    """Try env var -> debate agent keys."""
    key = os.environ.get(env_key)
    if key:
        return key
    if DEBATE_AGENT_ENV.exists():
        for line in DEBATE_AGENT_ENV.read_text().splitlines():
            line = line.strip()
            if line.startswith(env_key + "="):
                return line.split("=", 1)[1].strip().strip("\"'")
    return None


# ---------------------------------------------------------------------------
# Source fetchers
# ---------------------------------------------------------------------------

def fetch_chatbot_arena() -> dict[str, dict]:
    """Fetch Chatbot Arena Elo rankings from arena-catalog JSON.

    Primary source: lmarena/arena-catalog on GitHub (official LMArena data).
    Fallback: fboulnois/llm-leaderboard-csv (community mirror, often stale).

    The arena-catalog JSON has per-category Elo scores with 95% CIs.
    We use the "full" category for the overall Arena Elo.
    """
    print("  Chatbot Arena (LMArena)...", end=" ", flush=True)
    try:
        # Primary: arena-catalog JSON (official, updated ~monthly)
        data = _http_get_json(
            "https://raw.githubusercontent.com/lmarena/arena-catalog/main/data/leaderboard-text.json",
            timeout=30,
        )

        results: dict[str, dict] = {}

        # The JSON has category keys; "full" is the overall ranking
        full_scores = data.get("full", {})
        if not full_scores:
            # Try alternative structures
            full_scores = data if isinstance(data, dict) and not any(
                isinstance(v, dict) and "rating" in v for v in data.values()
            ) else data

        for name, score_data in full_scores.items():
            if not isinstance(score_data, dict):
                continue
            elo = score_data.get("rating", "")
            if not elo:
                continue

            canon = _canonical(name)
            results[canon] = {
                "model": name,
                "provider": "",  # arena-catalog doesn't include org
                "arena_elo": f"{float(elo):.0f}" if elo else "",
                "_source": "arena",
            }

        if results:
            print(f"{len(results)} models (arena-catalog)")
            return results

        # Fallback: fboulnois/llm-leaderboard-csv (community mirror)
        raise RuntimeError("arena-catalog returned no data, trying fallback")

    except Exception:
        # Fallback to the old CSV mirror
        try:
            release = _http_get_json(
                "https://api.github.com/repos/fboulnois/llm-leaderboard-csv/releases/latest",
                headers={"Accept": "application/vnd.github.v3+json"},
            )
            csv_url = None
            for asset in release.get("assets", []):
                if asset.get("name", "") == "lmarena_text.csv":
                    csv_url = asset["browser_download_url"]
                    break
            if not csv_url:
                for asset in release.get("assets", []):
                    if asset.get("name", "").endswith(".csv"):
                        csv_url = asset["browser_download_url"]
                        break
            if not csv_url:
                raise RuntimeError("No CSV asset in release")

            csv_data = _http_get_text(csv_url, timeout=30)
            reader = csv.DictReader(io.StringIO(csv_data))

            results: dict[str, dict] = {}
            for row in reader:
                name = (row.get("model") or row.get("Model") or
                        row.get("name") or row.get("Model Name") or "")
                elo = (row.get("arena_score") or row.get("Arena Score") or
                       row.get("Elo") or row.get("elo") or
                       row.get("Rating") or row.get("rating") or "")
                org = (row.get("organization") or row.get("Organization") or
                       row.get("Provider") or row.get("provider") or "")
                if not name:
                    continue
                canon = _canonical(name)
                results[canon] = {
                    "model": name,
                    "provider": org,
                    "arena_elo": str(elo).strip(),
                    "_source": "arena",
                }
            print(f"{len(results)} models (CSV fallback)")
            return results
        except Exception as e:
            print(f"failed ({e})")
            return {}


def fetch_epoch_ai() -> dict[str, dict]:
    """Fetch benchmark scores from Epoch AI.

    The zip contains one CSV per benchmark. Each CSV has columns:
      Model version, mean_score, Release date, Organization, ...
    The filename indicates which benchmark it is.
    """
    # Map CSV filename -> our schema column
    BENCHMARK_FILES: dict[str, str] = {
        "gpqa_diamond.csv": "gpqa",
        "math_level_5.csv": "math",
        "swe_bench_verified.csv": "swe_bench",
        "aider_polyglot_external.csv": "coding",
        "live_bench_external.csv": "quality_index",
        "mmlu_external.csv": "mmlu",
        "epoch_capabilities_index.csv": "eci",
        "simpleqa_verified.csv": "simpleqa",
        "arc_agi_external.csv": "arc_agi",
        "frontiermath.csv": "frontier_math",
    }

    print("  Epoch AI benchmarks...", end=" ", flush=True)
    try:
        data = _http_get_bytes(
            "https://epoch.ai/data/benchmark_data.zip", timeout=60
        )
        results: dict[str, dict] = {}
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for fname in zf.namelist():
                if not fname.endswith(".csv"):
                    continue

                # Determine which schema column this file maps to
                basename = fname.split("/")[-1]  # Handle nested paths
                dst_col = BENCHMARK_FILES.get(basename)

                with zf.open(fname) as f:
                    text = f.read().decode("utf-8", errors="replace")
                    reader = csv.DictReader(io.StringIO(text))
                    for row in reader:
                        name = (row.get("Model version") or row.get("Model") or
                                row.get("model") or "").strip()
                        if not name:
                            continue
                        # Strip suffixes like "_32K", "_16K", "_high", "_xhigh"
                        clean_name = re.sub(r'_\d+K$', '', name)
                        clean_name = re.sub(r'_(high|xhigh|medium|low)$', '', clean_name)

                        canon = _canonical(clean_name)
                        if canon not in results:
                            org = (row.get("Organization") or "").strip()
                            results[canon] = {
                                "model": clean_name,
                                "provider": org,
                                "_source": "epoch",
                            }

                        # Store the score in the mapped column
                        if dst_col:
                            score = (row.get("mean_score") or
                                     row.get("Percent correct") or
                                     row.get("Global average") or
                                     row.get("% Resolved") or
                                     row.get("EM") or
                                     row.get("ECI Score") or
                                     row.get("Score") or "").strip()
                            if score and not results[canon].get(dst_col):
                                try:
                                    val = float(score)
                                    if dst_col == "eci":
                                        # ECI: absolute scale (~100-160), store as-is
                                        score = f"{val:.1f}"
                                    elif dst_col == "quality_index":
                                        # LiveBench: already 0-100
                                        score = f"{val:.1f}"
                                    elif val <= 1.0:
                                        # 0-1 fraction → percentage
                                        score = f"{val * 100:.1f}"
                                    else:
                                        score = f"{val:.1f}"
                                except ValueError:
                                    pass
                                results[canon][dst_col] = score

        print(f"{len(results)} models")
        return results
    except Exception as e:
        print(f"failed ({e})")
        return {}


def fetch_openrouter() -> dict[str, dict]:
    """Fetch pricing and context info from OpenRouter."""
    print("  OpenRouter pricing...", end=" ", flush=True)
    try:
        resp = _http_get_json("https://openrouter.ai/api/v1/models")
        results: dict[str, dict] = {}
        for m in resp.get("data", []):
            model_id = m.get("id", "")
            if not model_id:
                continue
            pricing = m.get("pricing", {})
            ctx = m.get("context_length", 0) or 0

            # Convert per-token pricing to $/1M tokens
            price_in = ""
            price_out = ""
            try:
                pin = float(pricing.get("prompt", "0") or "0")
                if pin > 0:
                    price_in = f"{pin * 1_000_000:.2f}"
            except (ValueError, TypeError):
                pass
            try:
                pout = float(pricing.get("completion", "0") or "0")
                if pout > 0:
                    price_out = f"{pout * 1_000_000:.2f}"
            except (ValueError, TypeError):
                pass

            provider = model_id.split("/")[0] if "/" in model_id else ""
            canon = _canonical(model_id)
            results[canon] = {
                "model": m.get("name", model_id),
                "provider": provider,
                "context": str(ctx) if ctx else "",
                "price_in": price_in,
                "price_out": price_out,
                "_source": "openrouter",
            }
        print(f"{len(results)} models")
        return results
    except Exception as e:
        print(f"failed ({e})")
        return {}


def fetch_artificial_analysis() -> dict[str, dict]:
    """Fetch Intelligence Index and speed metrics from Artificial Analysis.

    API docs: https://artificialanalysis.ai/api-access-preview
    Returns per-model: intelligence index, speed (TPS/TTFT), and eval scores.
    """
    api_key = _get_key("ARTIFICIAL_ANALYSIS_API_KEY")
    if not api_key:
        print("  Artificial Analysis... skipped (no ARTIFICIAL_ANALYSIS_API_KEY found)")
        return {}

    print("  Artificial Analysis...", end=" ", flush=True)
    try:
        resp = _http_get_json(
            "https://artificialanalysis.ai/api/v2/data/llms/models",
            headers={"x-api-key": api_key},
            timeout=30,
        )

        # Response is a list of model objects
        models = resp if isinstance(resp, list) else resp.get("data", resp.get("models", []))
        results: dict[str, dict] = {}

        for m in models:
            name = m.get("name", "")
            if not name:
                continue

            creator = m.get("model_creator", {})
            provider = creator.get("name", "") if isinstance(creator, dict) else ""

            # Intelligence Index — the composite score (0-100, average of 10 evals)
            aa_index = ""
            intelligence = m.get("intelligence_index") or m.get("quality_index")
            if intelligence is not None:
                try:
                    aa_index = f"{float(intelligence):.1f}"
                except (ValueError, TypeError):
                    pass

            # Speed metrics
            speed_tps = ""
            tps = m.get("median_output_tokens_per_second") or m.get("tokens_per_second")
            if tps is not None:
                try:
                    speed_tps = f"{float(tps):.1f}"
                except (ValueError, TypeError):
                    pass

            speed_ttft = ""
            ttft = m.get("median_time_to_first_token_seconds") or m.get("time_to_first_token")
            if ttft is not None:
                try:
                    speed_ttft = f"{float(ttft):.3f}"
                except (ValueError, TypeError):
                    pass

            # Individual evaluation scores from the evaluations array
            evals = m.get("evaluations", [])
            gpqa = ""
            mmlu_pro = ""
            coding = ""
            math_score = ""
            if isinstance(evals, list):
                for ev in evals:
                    ev_name = (ev.get("name") or ev.get("benchmark_name") or "").lower()
                    score = ev.get("score") or ev.get("value")
                    if score is None:
                        continue
                    try:
                        val = float(score)
                    except (ValueError, TypeError):
                        continue
                    # Map evaluation names to our schema columns
                    if "gpqa" in ev_name and not gpqa:
                        gpqa = f"{val:.1f}" if val <= 100 else f"{val:.1f}"
                    elif "mmlu" in ev_name and "pro" in ev_name and not mmlu_pro:
                        mmlu_pro = f"{val:.1f}"
                    elif ("code" in ev_name or "humaneval" in ev_name
                          or "livecodebench" in ev_name) and not coding:
                        coding = f"{val:.1f}"
                    elif "math" in ev_name and not math_score:
                        math_score = f"{val:.1f}"

            # Context window from AA
            context = ""
            ctx_val = m.get("context_window") or m.get("max_context_window")
            if ctx_val is not None:
                try:
                    context = str(int(ctx_val))
                except (ValueError, TypeError):
                    pass

            canon = _canonical(name)
            row: dict[str, str] = {
                "model": name,
                "provider": provider,
                "aa_index": aa_index,
                "speed_tps": speed_tps,
                "speed_ttft": speed_ttft,
                "_source": "aa",
            }
            # Only set eval scores if present (don't overwrite Epoch AI data)
            if gpqa:
                row["gpqa"] = gpqa
            if mmlu_pro:
                row["mmlu"] = mmlu_pro
            if coding:
                row["coding"] = coding
            if math_score:
                row["math"] = math_score
            if context:
                row["context"] = context

            results[canon] = row

        print(f"{len(results)} models")
        return results
    except Exception as e:
        print(f"failed ({e})")
        return {}


# ---------------------------------------------------------------------------
# BetterBench quality tiers (arxiv:2411.12990)
# ---------------------------------------------------------------------------

def _compute_benchmark_quality(row: dict) -> str:
    """Assign a BetterBench-informed quality tier based on data completeness.

    Tiers:
      "high"   — has GPQA score (BetterBench 11.0) + Arena Elo + AA index
      "medium" — has at least 2 of: Arena Elo, GPQA, coding score, AA index
      "low"    — only 1 data point or only pricing data

    This heuristic reflects BetterBench's finding that benchmark quality varies
    widely. Models with more high-quality data points get higher confidence tiers.
    """
    signals = 0
    if row.get("arena_elo"):
        signals += 1
    if row.get("gpqa"):
        signals += 1
    if row.get("coding"):
        signals += 1
    if row.get("aa_index"):
        signals += 1

    # "high" requires GPQA (highest BetterBench score) + at least 2 others
    if row.get("gpqa") and row.get("arena_elo") and row.get("aa_index"):
        return "high"
    if signals >= 2:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def merge_sources(*sources: dict[str, dict]) -> list[dict]:
    """Merge data from multiple sources into unified rankings."""
    merged: dict[str, dict] = {}

    for source in sources:
        for canon, data in source.items():
            if canon not in merged:
                merged[canon] = {col: "" for col in COLUMNS}
                merged[canon]["model"] = data.get("model", canon)
            row = merged[canon]

            # Merge non-empty fields (first source wins for each field)
            for key in COLUMNS:
                if key in ("sources", "registry_name"):
                    continue
                val = data.get(key, "")
                if val and not row.get(key):
                    row[key] = str(val)

            # Track sources
            src = data.get("_source", "")
            if src:
                existing = row.get("sources", "")
                if src not in existing:
                    row["sources"] = f"{existing},{src}".lstrip(",") if existing else src

    # Set registry names and benchmark quality tiers
    for canon, row in merged.items():
        row["registry_name"] = (
            _find_registry_name(row["model"]) or
            _find_registry_name(canon)
        )
        row["benchmark_quality"] = _compute_benchmark_quality(row)

    # Sort: registry models first, then by arena_elo descending
    def sort_key(r):
        has_reg = 0 if r.get("registry_name") else 1
        elo = 0.0
        try:
            elo = -float(r.get("arena_elo") or "0")
        except ValueError:
            pass
        return (has_reg, elo, r.get("model", ""))

    return sorted(merged.values(), key=sort_key)


# ---------------------------------------------------------------------------
# Save / load
# ---------------------------------------------------------------------------

def save_rankings(data: list[dict], path: Path) -> None:
    """Save rankings to CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)


def load_rankings(path: Path) -> list[dict]:
    """Load rankings from CSV."""
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def save_meta(meta: dict, path: Path) -> None:
    """Save fetch metadata."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2) + "\n")


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_rankings(
    data: list[dict],
    top: int = 30,
    model_filter: str | None = None,
) -> None:
    """Print rankings table."""
    if model_filter:
        norm = _normalize(model_filter)
        data = [
            r for r in data
            if norm in _normalize(r.get("model", ""))
            or norm in _normalize(r.get("registry_name", ""))
            or r.get("registry_name", "") == model_filter
        ]
        if not data:
            print(f"No models matching '{model_filter}'")
            return

    rows = data[:top]

    print(f"\n{'#':>3}  {'Model':30s}  {'Elo':>6}  {'GPQA':>5}  {'MMLU':>5}  "
          f"{'Code':>5}  {'Math':>5}  {'AA':>5}  {'Ctx':>7}  {'$/M in':>8}  {'Q':>3}")
    print(f"{'─' * 3}  {'─' * 30}  {'─' * 6}  {'─' * 5}  {'─' * 5}  "
          f"{'─' * 5}  {'─' * 5}  {'─' * 5}  {'─' * 7}  {'─' * 8}  {'─' * 3}")

    for i, r in enumerate(rows, 1):
        name = r.get("model", "?")[:30]
        elo = r.get("arena_elo", "")[:6]
        gpqa = r.get("gpqa", "")[:5]
        mmlu = r.get("mmlu", "")[:5]
        code = r.get("coding", "")[:5]
        math_s = r.get("math", "")[:5]
        aa = r.get("aa_index", "")[:5]

        ctx = r.get("context", "")
        if ctx:
            try:
                ctx = f"{int(ctx) // 1000}k"
            except ValueError:
                ctx = ctx[:7]

        price = r.get("price_in", "")
        if price:
            try:
                price = f"${float(price):.2f}"
            except ValueError:
                price = price[:8]

        # Quality tier: H/M/L
        bq = r.get("benchmark_quality", "")
        q = bq[0].upper() if bq else ""

        print(f"{i:3d}  {name:30s}  {elo:>6}  {gpqa:>5}  {mmlu:>5}  "
              f"{code:>5}  {math_s:>5}  {aa:>5}  {ctx:>7}  {price:>8}  {q:>3}")

    total = len(data)
    if total > top:
        print(f"\n  ({total - top} more — use --top {total} to show all)")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch LLM benchmarks and save as local rankings CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s                          # fetch all sources, update rankings
  %(prog)s --source arena           # fetch only Chatbot Arena
  %(prog)s --source aa              # fetch only Artificial Analysis
  %(prog)s --list                   # show local rankings table
  %(prog)s --list --top 50          # show top 50
  %(prog)s --model opus             # show benchmarks for opus
  %(prog)s --json                   # output as JSON
""",
    )
    parser.add_argument("--source", choices=["arena", "epoch", "openrouter", "aa", "all"],
                        default="all", help="Which source to fetch (default: all)")
    parser.add_argument("--list", action="store_true", help="Show local rankings (no fetch)")
    parser.add_argument("--model", help="Show benchmarks for a specific model (no fetch)")
    parser.add_argument("--top", type=int, default=30, help="Number of models to show (default: 30)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    # List/model mode — read local CSV, no fetching
    if args.list or args.model:
        data = load_rankings(RANKINGS_PATH)
        if not data:
            print("No local rankings found. Run without --list to fetch first.")
            sys.exit(1)
        if args.json:
            if args.model:
                norm = _normalize(args.model)
                data = [r for r in data if norm in _normalize(r.get("model", ""))
                        or norm in _normalize(r.get("registry_name", ""))
                        or r.get("registry_name", "") == args.model]
            print(json.dumps(data[:args.top], indent=2))
        else:
            print_rankings(data, top=args.top, model_filter=args.model)
        return

    # Fetch mode
    print("Fetching LLM benchmarks:\n")
    sources: list[dict[str, dict]] = []
    meta_sources: dict = {}
    now = datetime.now(timezone.utc).isoformat()

    if args.source in ("arena", "all"):
        arena = fetch_chatbot_arena()
        sources.append(arena)
        meta_sources["arena"] = {
            "status": "ok" if arena else "failed",
            "models": len(arena), "fetched": now,
        }

    if args.source in ("epoch", "all"):
        epoch = fetch_epoch_ai()
        sources.append(epoch)
        meta_sources["epoch"] = {
            "status": "ok" if epoch else "failed",
            "models": len(epoch), "fetched": now,
        }

    if args.source in ("openrouter", "all"):
        openrouter = fetch_openrouter()
        sources.append(openrouter)
        meta_sources["openrouter"] = {
            "status": "ok" if openrouter else "failed",
            "models": len(openrouter), "fetched": now,
        }

    if args.source in ("aa", "all"):
        aa = fetch_artificial_analysis()
        if aa:
            sources.append(aa)
        meta_sources["aa"] = {
            "status": "ok" if aa else ("skipped" if not _get_key("ARTIFICIAL_ANALYSIS_API_KEY") else "failed"),
            "models": len(aa), "fetched": now,
        }

    if not any(sources):
        print("\nAll sources failed. No data to save.")
        sys.exit(1)

    # If updating a single source, merge with existing data
    if args.source != "all" and RANKINGS_PATH.exists():
        existing: dict[str, dict] = {}
        for row in load_rankings(RANKINGS_PATH):
            canon = _canonical(row.get("model", ""))
            existing[canon] = row
        sources.insert(0, existing)

    # Merge all sources
    merged = merge_sources(*sources)

    # Count registry matches
    reg_count = sum(1 for r in merged if r.get("registry_name"))

    # Save
    save_rankings(merged, RANKINGS_PATH)
    save_meta({
        "last_fetch": now,
        "sources": meta_sources,
        "total_models": len(merged),
        "registry_matched": reg_count,
    }, META_PATH)

    print(f"\nSaved {len(merged)} models to {RANKINGS_PATH}")
    print(f"  Registry matches: {reg_count}")
    for src_name, src_meta in meta_sources.items():
        status = src_meta["status"]
        count = src_meta["models"]
        print(f"  {src_name}: {status} ({count} models)")

    if args.json:
        print(json.dumps(merged[:args.top], indent=2))
    else:
        print_rankings(merged, top=args.top)


if __name__ == "__main__":
    main()
