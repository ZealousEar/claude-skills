#!/usr/bin/env python3
"""Scrape vals.ai benchmark leaderboards using Playwright headless browser.

Fetches model scores from all active vals.ai benchmarks and saves structured
JSON output for consumption by fetch_benchmarks.py.

Requirements:
    pip install playwright
    playwright install chromium

Usage:
    python3 scrape_vals.py                    # scrape all benchmarks
    python3 scrape_vals.py --benchmark lcb    # scrape only LiveCodeBench
    python3 scrape_vals.py --list             # show local vals data
    python3 scrape_vals.py --json             # output as JSON

The venv is at: ~/.claude/skills/llm/scripts/.venv/
Run with: ~/.claude/skills/llm/scripts/.venv/bin/python3 scrape_vals.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SKILL_DIR = Path.home() / ".claude" / "skills" / "llm"
BENCHMARKS_DIR = SKILL_DIR / "benchmarks"
VALS_PATH = BENCHMARKS_DIR / "vals.json"

BASE_URL = "https://www.vals.ai/benchmarks"

# ---------------------------------------------------------------------------
# Benchmark definitions
# ---------------------------------------------------------------------------
# Each benchmark: slug -> {column for rankings.csv, category, description}
BENCHMARKS: dict[str, dict] = {
    # Composites
    "vals_index": {
        "column": "vals_index",
        "category": "composite",
        "description": "Weighted composite: finance/law/coding by GDP contribution",
    },
    "vals_multimodal_index": {
        "column": "vals_mm_index",
        "category": "composite",
        "description": "Weighted multimodal composite: finance/law/coding/education",
    },
    # Finance
    "corp_fin_v2": {
        "column": "vals_corpfin",
        "category": "finance",
        "description": "Long-context credit agreement understanding",
    },
    "finance_agent": {
        "column": "vals_fin_agent",
        "category": "finance",
        "description": "Core financial analyst tasks (agent eval)",
    },
    "tax_eval_v2": {
        "column": "vals_tax",
        "category": "finance",
        "description": "Tax-related question answering",
    },
    "mortgage_tax": {
        "column": "vals_mortgage",
        "category": "finance",
        "description": "Reading/understanding tax certificates as images",
    },
    # Legal
    "case_law_v2": {
        "column": "vals_caselaw",
        "category": "legal",
        "description": "QA on Canadian court cases",
    },
    "legal_bench": {
        "column": "vals_legalbench",
        "category": "legal",
        "description": "Open-source legal reasoning tasks",
    },
    # Healthcare
    "medcode": {
        "column": "vals_medcode",
        "category": "healthcare",
        "description": "Medical billing support capability",
    },
    "medscribe": {
        "column": "vals_medscribe",
        "category": "healthcare",
        "description": "Physician administrative work support",
    },
    "medqa": {
        "column": "vals_medqa",
        "category": "healthcare",
        "description": "Medical question answering / bias detection",
    },
    # Academic
    "gpqa": {
        "column": "vals_gpqa",
        "category": "academic",
        "description": "Graduate-level deep reasoning questions",
    },
    "mmlu_pro": {
        "column": "vals_mmlu",
        "category": "academic",
        "description": "Multiple-choice across 14 subjects",
    },
    "mmmu": {
        "column": "vals_mmmu",
        "category": "academic",
        "description": "Multimodal multi-task performance",
    },
    # Math
    "aime": {
        "column": "vals_aime",
        "category": "math",
        "description": "National math exam (AIME) performance",
    },
    "proof_bench": {
        "column": "vals_proofbench",
        "category": "math",
        "description": "Formally verified math proofs",
    },
    # Coding
    "lcb": {
        "column": "vals_lcb",
        "category": "coding",
        "description": "LiveCodeBench implementation",
    },
    "swebench": {
        "column": "vals_swe",
        "category": "coding",
        "description": "Production software engineering tasks",
    },
    "terminal-bench-2": {
        "column": "vals_terminal",
        "category": "coding",
        "description": "Difficult terminal-based tasks",
    },
    "ioi": {
        "column": "vals_ioi",
        "category": "coding",
        "description": "International Olympiad in Informatics",
    },
    "vibe-code": {
        "column": "vals_vibecode",
        "category": "coding",
        "description": "Building web apps from scratch",
    },
    # Education
    "sage": {
        "column": "vals_sage",
        "category": "education",
        "description": "Student assessment with generative evaluation",
    },
    # Beta
    "poker_agent": {
        "column": "vals_poker",
        "category": "beta",
        "description": "Poker strategy agent evaluation",
    },
}

# ---------------------------------------------------------------------------
# Model name normalization (mirrors fetch_benchmarks.py)
# ---------------------------------------------------------------------------

def _normalize(name: str) -> str:
    """Normalize model name for matching."""
    return re.sub(r'[^a-z0-9.\-/]', '', name.lower().strip())


# Map vals.ai display names to our canonical registry names
_VALS_TO_REGISTRY: dict[str, str] = {
    # Anthropic — only map CURRENT generation (4.6/4.5)
    "claude opus 4.6 (thinking)": "opus",
    "claude opus 4.6": "opus",
    # NOTE: "Claude Opus 4.5 (Thinking)", "Claude Sonnet 4.5 (Thinking)" are
    # previous-gen — intentionally NOT mapped to registry names.
    # OpenAI
    "gpt 5.2": "gpt-5.2",
    "chatgpt 5.4": "chatgpt-5.4",
    "gpt 5.3 codex": "gpt-5.3-codex",
    "gpt 5.3": "gpt-5.3-codex",
    # NOTE: "GPT 5.2 Codex" is a separate model from GPT 5.3 Codex — not mapped.
    # Google — map both dated versions (same model family)
    "gemini 3 pro (11/25)": "gemini-3-pro",
    "gemini 3 flash (12/25)": "gemini-3-flash",
    "gemini 3.1 pro preview (02/26)": "gemini-3-pro",
    # Moonshot
    "kimi k2.5": "kimi-2.5",
    "kimi 2.5": "kimi-2.5",
    # ZhipuAI
    "glm 5": "glm-5",
    # MiniMax
    "minimax-m2.5": "minimax-m2.5",
}


def _find_registry_name(vals_name: str) -> str:
    """Map vals.ai model name to our registry name."""
    lower = vals_name.lower().strip()
    if lower in _VALS_TO_REGISTRY:
        return _VALS_TO_REGISTRY[lower]
    # Try partial matches for common patterns
    for pattern, reg_name in _VALS_TO_REGISTRY.items():
        if pattern in lower:
            return reg_name
    return ""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_leaderboard_text(text: str, benchmark_slug: str) -> list[dict]:
    """Parse the text content of a vals.ai benchmark page into structured data.

    The text follows this repeating pattern:
        <rank>
        <model_name>
        <accuracy>
        %
        <cost_info>
        <latency>
        s

    Cost info is either:
        $X.XX           (Cost / Test)
        $X / $Y         (Cost In / Out per 1M tokens)
    """
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    # Find the start of leaderboard data (after "Settings" line)
    start_idx = None
    for i, line in enumerate(lines):
        if line == "Settings":
            start_idx = i + 1
            break
    if start_idx is None:
        return []

    # Find the end (before "Best Performing" or "Show less" or methodology section)
    end_idx = len(lines)
    for i in range(start_idx, len(lines)):
        if lines[i] in ("Best Performing", "Show less", "Motivation", "Methodology",
                         "Key Takeaways", "Results"):
            end_idx = i
            break

    data_lines = lines[start_idx:end_idx]

    # Parse entries
    entries: list[dict] = []
    i = 0
    while i < len(data_lines):
        # Look for a rank number
        if not data_lines[i].isdigit():
            i += 1
            continue

        rank = int(data_lines[i])
        i += 1
        if i >= len(data_lines):
            break

        # Model name (next non-numeric, non-% line)
        model_name = data_lines[i]
        i += 1
        if i >= len(data_lines):
            break

        # Accuracy (numeric value)
        accuracy = None
        if i < len(data_lines):
            try:
                accuracy = float(data_lines[i])
                i += 1
            except ValueError:
                # Might be a different format, skip
                i += 1
                continue

        # Skip "%" line
        if i < len(data_lines) and data_lines[i] == "%":
            i += 1

        # Cost info - could be "$X.XX" or "$X / $Y"
        cost_str = ""
        if i < len(data_lines) and data_lines[i].startswith("$"):
            cost_str = data_lines[i]
            i += 1

        # Latency (numeric)
        latency = None
        if i < len(data_lines):
            try:
                latency = float(data_lines[i])
                i += 1
            except ValueError:
                pass

        # Skip "s" line
        if i < len(data_lines) and data_lines[i] == "s":
            i += 1

        entry = {
            "rank": rank,
            "model": model_name,
            "accuracy": accuracy,
            "cost": cost_str,
            "latency_s": latency,
            "benchmark": benchmark_slug,
            "registry_name": _find_registry_name(model_name),
        }
        entries.append(entry)

    return entries


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

async def scrape_benchmark(page, slug: str) -> list[dict]:
    """Scrape a single benchmark page."""
    url = f"{BASE_URL}/{slug}"
    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        # Click "See X more models" button to expand full leaderboard
        try:
            more_btn = await page.query_selector('text=/See \\d+ more/')
            if more_btn:
                await more_btn.click()
                await page.wait_for_timeout(2000)
        except Exception:
            pass

        text = await page.inner_text("body")
        entries = parse_leaderboard_text(text, slug)
        return entries

    except Exception as e:
        print(f"  {slug}: failed ({e})", file=sys.stderr)
        return []


async def scrape_all(
    benchmark_filter: str | None = None,
) -> dict:
    """Scrape all (or filtered) vals.ai benchmarks."""
    from playwright.async_api import async_playwright

    slugs = list(BENCHMARKS.keys())
    if benchmark_filter:
        slugs = [s for s in slugs if benchmark_filter in s]
        if not slugs:
            print(f"No benchmark matching '{benchmark_filter}'", file=sys.stderr)
            return {}

    print(f"Scraping {len(slugs)} vals.ai benchmarks...\n")

    all_data: dict[str, list[dict]] = {}
    meta: dict = {
        "fetched": datetime.now(timezone.utc).isoformat(),
        "benchmarks": {},
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Use a single page and navigate sequentially to avoid rate limiting
        page = await browser.new_page()

        for slug in slugs:
            info = BENCHMARKS[slug]
            print(f"  {slug} ({info['category']})...", end=" ", flush=True)

            entries = await scrape_benchmark(page, slug)
            all_data[slug] = entries

            meta["benchmarks"][slug] = {
                "models": len(entries),
                "category": info["category"],
                "status": "ok" if entries else "empty",
            }

            print(f"{len(entries)} models")

        await browser.close()

    # Build per-model aggregated view
    models: dict[str, dict] = {}
    for slug, entries in all_data.items():
        col = BENCHMARKS[slug]["column"]
        for entry in entries:
            name = entry["model"]
            norm = _normalize(name)

            if norm not in models:
                models[norm] = {
                    "model": name,
                    "registry_name": entry.get("registry_name", ""),
                    "benchmarks": {},
                }
            # Update registry name if found
            if entry.get("registry_name") and not models[norm]["registry_name"]:
                models[norm]["registry_name"] = entry["registry_name"]

            models[norm]["benchmarks"][slug] = {
                "accuracy": entry["accuracy"],
                "rank": entry["rank"],
                "cost": entry["cost"],
                "latency_s": entry["latency_s"],
                "column": col,
            }

    result = {
        "meta": meta,
        "models": models,
        "raw": {slug: entries for slug, entries in all_data.items()},
    }

    total_models = len(models)
    total_entries = sum(len(e) for e in all_data.values())
    reg_matched = sum(1 for m in models.values() if m.get("registry_name"))

    meta["total_models"] = total_models
    meta["total_entries"] = total_entries
    meta["registry_matched"] = reg_matched

    print(f"\nDone: {total_entries} entries across {len(all_data)} benchmarks")
    print(f"  Unique models: {total_models}")
    print(f"  Registry matches: {reg_matched}")

    return result


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_vals_data(data: dict, benchmark_filter: str | None = None) -> None:
    """Print vals.ai data summary."""
    meta = data.get("meta", {})
    models = data.get("models", {})
    raw = data.get("raw", {})

    print(f"\nVals.ai benchmarks (fetched: {meta.get('fetched', 'unknown')})")
    print(f"  Total models: {meta.get('total_models', '?')}")
    print(f"  Registry matches: {meta.get('registry_matched', '?')}")
    print()

    # Per-benchmark summary
    benchmarks = meta.get("benchmarks", {})
    if benchmark_filter:
        benchmarks = {k: v for k, v in benchmarks.items() if benchmark_filter in k}

    print(f"{'Benchmark':25s}  {'Category':12s}  {'Models':>6s}  {'Status':>8s}")
    print(f"{'─' * 25}  {'─' * 12}  {'─' * 6}  {'─' * 8}")
    for slug, info in sorted(benchmarks.items()):
        cat = info.get("category", "")
        count = info.get("models", 0)
        status = info.get("status", "")
        print(f"{slug:25s}  {cat:12s}  {count:6d}  {status:>8s}")
    print()

    # Top models by vals_index
    print("Top 15 by Vals Index:")
    print(f"{'#':>3}  {'Model':35s}  {'Vals Idx':>8s}  {'LCB':>6s}  {'SWE':>6s}  {'Finance':>7s}  {'Legal':>6s}  {'Registry'}")
    print(f"{'─' * 3}  {'─' * 35}  {'─' * 8}  {'─' * 6}  {'─' * 6}  {'─' * 7}  {'─' * 6}  {'─' * 12}")

    # Sort by vals_index score
    sorted_models = sorted(
        models.values(),
        key=lambda m: m.get("benchmarks", {}).get("vals_index", {}).get("accuracy") or 0,
        reverse=True,
    )

    for i, m in enumerate(sorted_models[:15], 1):
        name = m["model"][:35]
        bm = m.get("benchmarks", {})
        vi = bm.get("vals_index", {}).get("accuracy", "")
        lcb = bm.get("lcb", {}).get("accuracy", "")
        swe = bm.get("swebench", {}).get("accuracy", "")
        fin = bm.get("corp_fin_v2", {}).get("accuracy", "")
        legal = bm.get("case_law_v2", {}).get("accuracy", "")
        reg = m.get("registry_name", "")

        vi_s = f"{vi:.1f}" if isinstance(vi, (int, float)) else ""
        lcb_s = f"{lcb:.1f}" if isinstance(lcb, (int, float)) else ""
        swe_s = f"{swe:.1f}" if isinstance(swe, (int, float)) else ""
        fin_s = f"{fin:.1f}" if isinstance(fin, (int, float)) else ""
        legal_s = f"{legal:.1f}" if isinstance(legal, (int, float)) else ""

        print(f"{i:3d}  {name:35s}  {vi_s:>8s}  {lcb_s:>6s}  {swe_s:>6s}  {fin_s:>7s}  {legal_s:>6s}  {reg}")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape vals.ai benchmark leaderboards.",
    )
    parser.add_argument("--benchmark", "-b", help="Only scrape this benchmark slug")
    parser.add_argument("--list", action="store_true", help="Show local vals data (no scrape)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if args.list:
        if not VALS_PATH.exists():
            print("No local vals data. Run without --list to scrape first.")
            sys.exit(1)
        data = json.loads(VALS_PATH.read_text())
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print_vals_data(data, args.benchmark)
        return

    # Scrape
    data = asyncio.run(scrape_all(args.benchmark))
    if not data:
        print("No data scraped.", file=sys.stderr)
        sys.exit(1)

    # Save
    BENCHMARKS_DIR.mkdir(parents=True, exist_ok=True)
    VALS_PATH.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Saved to {VALS_PATH}")

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print_vals_data(data, args.benchmark)


if __name__ == "__main__":
    main()
