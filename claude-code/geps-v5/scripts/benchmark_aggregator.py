#!/usr/bin/env python3
"""Multi-source benchmark aggregator for GEPS model evaluation.

Fetches scores from external benchmark APIs, normalizes via Z-scores,
and produces a weighted composite ranking across all configured models.

Usage:
    python3 benchmark_aggregator.py \\
        --sources benchmark-sources.json \\
        --models "opus,chatgpt-5.4,gpt-5.2,gemini-3.1-pro,gemini-3-flash,kimi-2.5,glm-5,minimax-m2.5" \\
        --output composite_ranking.json \\
        --pretty --summary
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SKILL_DIR = Path.home() / ".claude" / "skills" / "geps-v5"
DEFAULT_SOURCES = SKILL_DIR / "settings" / "benchmark-sources.json"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "gib"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HTTP_TIMEOUT = 30
DRY_RUN_TIMEOUT = 10
DEFAULT_CACHE_HOURS = 24
USER_AGENT = "GEPS-Benchmark-Aggregator/1.0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(message: str) -> None:
    """Print a timestamped log message to stderr."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    sys.stderr.write(f"[{ts}] {message}\n")
    sys.stderr.flush()


def load_json(path: Path) -> object:
    """Load and parse a JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: object, pretty: bool = True) -> None:
    """Write JSON data to a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    indent = 2 if pretty else None
    path.write_text(json.dumps(data, indent=indent) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

def fetch_url(url: str, timeout: int = HTTP_TIMEOUT) -> str:
    """Fetch URL content via HTTP GET.

    Uses stdlib urllib only (no pip dependencies). Returns the response
    body as a UTF-8 string.

    Raises RuntimeError on HTTP errors or connection failures.
    """
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {e.code} from {url}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Connection error to {url}: {e.reason}") from e


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

def _cache_path(source_id: str, url: str, cache_dir: Path) -> Path:
    """Compute the cache file path for a given source and URL."""
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return cache_dir / f"{source_id}_{url_hash}.json"


def _cache_is_fresh(path: Path, max_age_hours: float) -> bool:
    """Check if a cache file exists and is younger than max_age_hours."""
    if not path.exists():
        return False
    mtime = path.stat().st_mtime
    age_hours = (time.time() - mtime) / 3600
    return age_hours < max_age_hours


def get_cached_or_fetch(
    source_id: str,
    url: str,
    cache_dir: Path,
    cache_hours: float = DEFAULT_CACHE_HOURS,
    no_cache: bool = False,
) -> str:
    """Return cached data if fresh, otherwise fetch from URL and cache.

    Cache filename format: {source_id}_{url_hash}.json where url_hash
    is the first 12 hex characters of the SHA-256 of the URL.
    """
    cp = _cache_path(source_id, url, cache_dir)

    if not no_cache and _cache_is_fresh(cp, cache_hours):
        log(f"  cache hit for {source_id} ({cp.name})")
        return cp.read_text(encoding="utf-8")

    log(f"  fetching {source_id} from {url}")
    body = fetch_url(url)

    # Write to cache
    cache_dir.mkdir(parents=True, exist_ok=True)
    cp.write_text(body, encoding="utf-8")
    log(f"  cached {source_id} -> {cp.name}")

    return body


# ---------------------------------------------------------------------------
# Score extraction
# ---------------------------------------------------------------------------

def extract_scores(
    raw_data: object,
    source_config: dict,
    models: list[str],
) -> dict[str, float | None]:
    """Parse fetched data and extract per-model scores.

    For each model in *models*, look up its mapped name in
    source_config["model_mappings"], then find that name's score in
    the raw data using the configured score_path.

    Returns a dict mapping each model name to its score (float) or
    None if the model was not found in this source.
    """
    mappings = source_config.get("model_mappings", {})
    score_path = source_config.get("score_path", "scores")
    higher_is_better = source_config.get("higher_is_better", True)

    # Navigate to the scores object using dot-separated path
    scores_obj = raw_data
    for key in score_path.split("."):
        if isinstance(scores_obj, dict):
            scores_obj = scores_obj.get(key)
        elif isinstance(scores_obj, list) and key.isdigit():
            idx = int(key)
            scores_obj = scores_obj[idx] if idx < len(scores_obj) else None
        else:
            scores_obj = None
        if scores_obj is None:
            log(f"  WARN: score_path '{score_path}' not found in response")
            return {m: None for m in models}

    result: dict[str, float | None] = {}
    for model in models:
        mapped_name = mappings.get(model, model)

        # Try exact match first, then case-insensitive
        score = None
        if isinstance(scores_obj, dict):
            if mapped_name in scores_obj:
                score = scores_obj[mapped_name]
            else:
                lower_map = {k.lower(): v for k, v in scores_obj.items()}
                score = lower_map.get(mapped_name.lower())

        if score is not None:
            try:
                score = float(score)
                # If lower is better, negate so that Z-score direction is uniform
                if not higher_is_better:
                    score = -score
            except (TypeError, ValueError):
                score = None

        result[model] = score

    return result


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def z_score_normalize(scores: dict[str, float | None]) -> dict[str, float | None]:
    """Compute Z-scores from the non-None values.

    Z = (x - mean) / std for each value. None stays None.
    If fewer than 2 non-None values exist, all non-None values
    become 0.0 (no meaningful spread to normalize).
    """
    values = [v for v in scores.values() if v is not None]
    if len(values) < 2:
        return {k: (0.0 if v is not None else None) for k, v in scores.items()}
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    std = math.sqrt(variance) if variance > 0 else 1.0
    return {k: ((v - mean) / std if v is not None else None) for k, v in scores.items()}


# ---------------------------------------------------------------------------
# Composite ranking
# ---------------------------------------------------------------------------

def compute_composite(
    all_z_scores: dict[str, dict[str, float | None]],
    source_weights: dict[str, float],
    models: list[str],
) -> list[dict[str, object]]:
    """Compute weighted-average composite score for each model.

    For models with missing sources, reweight proportionally among
    available sources so that the composite is still comparable.
    """
    total_possible_weight = sum(source_weights.values())
    results = []

    for model in models:
        available: dict[str, float] = {}
        for source_id, z_scores in all_z_scores.items():
            z = z_scores.get(model)
            if z is not None:
                available[source_id] = z

        if not available:
            results.append({
                "model": model,
                "composite_score": None,
                "data_completeness": 0.0,
                "sources_available": 0,
                "sources_total": len(source_weights),
            })
            continue

        # Reweight proportionally among available sources
        total_weight = sum(source_weights[sid] for sid in available)
        if total_weight <= 0:
            total_weight = 1.0

        weighted_sum = sum(
            (source_weights[sid] / total_weight) * z
            for sid, z in available.items()
        )

        data_completeness = (
            sum(source_weights[sid] for sid in available) / total_possible_weight
        )

        results.append({
            "model": model,
            "composite_score": round(weighted_sum, 4),
            "data_completeness": round(data_completeness, 4),
            "sources_available": len(available),
            "sources_total": len(source_weights),
        })

    # Sort by composite_score descending (None at bottom)
    results.sort(
        key=lambda r: (
            r["composite_score"] is not None,
            r.get("composite_score", -999),
        ),
        reverse=True,
    )

    # Assign ranks
    for i, r in enumerate(results):
        r["rank"] = i + 1 if r["composite_score"] is not None else None

    return results


# ---------------------------------------------------------------------------
# Summary formatting
# ---------------------------------------------------------------------------

def format_summary(report: dict) -> None:
    """Print an aligned human-readable summary table to stderr."""
    composite = report.get("composite_ranking", [])
    per_source = report.get("per_source_scores", {})

    sys.stderr.write("\n")
    sys.stderr.write("Multi-Source Benchmark Composite Ranking\n")
    sys.stderr.write("=" * 56 + "\n")

    # Header
    sys.stderr.write(
        f"{'Rank':>4}  {'Model':<22} {'Composite':>9}  {'Complete':>8}  {'Sources':>7}\n"
    )
    sys.stderr.write("-" * 56 + "\n")

    for entry in composite:
        rank = entry["rank"]
        model = entry["model"]
        score = entry["composite_score"]
        comp = entry["data_completeness"]
        avail = entry["sources_available"]
        total = entry["sources_total"]

        rank_str = f"{rank:>4}" if rank is not None else "   -"
        score_str = f"{score:>9.4f}" if score is not None else "      N/A"
        comp_str = f"{comp:>8.4f}" if comp is not None else "     N/A"
        sources_str = f"{avail}/{total}"

        sys.stderr.write(
            f"{rank_str}  {model:<22} {score_str}  {comp_str}  {sources_str:>7}\n"
        )

    # Per-source breakdown
    if per_source:
        sys.stderr.write("\n")
        sys.stderr.write("Per-Source Breakdown\n")
        sys.stderr.write("-" * 56 + "\n")

        for source_id, source_data in per_source.items():
            sys.stderr.write(f"\n  {source_id}:\n")
            raw = source_data.get("raw", {})
            z = source_data.get("z_score", {})

            # Collect models that have data in this source
            scored_models = [
                m for m in raw if raw[m] is not None
            ]
            scored_models.sort(
                key=lambda m: z.get(m, -999) if z.get(m) is not None else -999,
                reverse=True,
            )

            if not scored_models:
                sys.stderr.write("    (no data)\n")
                continue

            sys.stderr.write(
                f"    {'Model':<22} {'Raw':>10}  {'Z-Score':>8}\n"
            )
            for m in scored_models:
                raw_val = raw[m]
                z_val = z.get(m)
                raw_str = f"{raw_val:>10.2f}" if raw_val is not None else "       N/A"
                z_str = f"{z_val:>8.4f}" if z_val is not None else "     N/A"
                sys.stderr.write(f"    {m:<22} {raw_str}  {z_str}\n")

    sys.stderr.write("\n")
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------

def run_dry_run(sources: list[dict], cache_dir: Path) -> None:
    """Test API connectivity for each source without parsing responses.

    For each configured source, attempt a GET with a short timeout.
    Report success or failure to stderr, then exit 0 if all succeed,
    exit 1 otherwise.
    """
    log("Dry-run mode: testing API connectivity...")
    failures = 0
    total = len(sources)

    for source in sources:
        sid = source["id"]
        url = source["endpoint_url"]
        try:
            body = fetch_url(url, timeout=DRY_RUN_TIMEOUT)
            size_kb = len(body.encode("utf-8")) / 1024
            log(f"  OK: {source['name']} ({sid}) -- {size_kb:.1f} KB response")
        except RuntimeError as e:
            log(f"  FAIL: {source['name']} ({sid}) -- {e}")
            failures += 1

    log(f"Dry-run complete: {total - failures}/{total} sources reachable")

    if failures > 0:
        log(f"WARNING: {failures} source(s) failed connectivity check")
        sys.exit(1)
    else:
        log("All sources reachable.")
        sys.exit(0)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Fetch external benchmarks, Z-score normalize, "
            "and produce composite ranking."
        ),
    )
    parser.add_argument(
        "--sources",
        default=str(DEFAULT_SOURCES),
        help="Path to benchmark-sources.json",
    )
    parser.add_argument(
        "--models",
        required=True,
        help="Comma-separated model names",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="Output path (default: stdout)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print human-readable summary to stderr",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Test API connectivity without full fetch",
    )
    parser.add_argument(
        "--cache-dir",
        default=str(DEFAULT_CACHE_DIR),
        help="Cache directory",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable caching (always fetch fresh)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Build the full report
# ---------------------------------------------------------------------------

def build_report(
    all_raw: dict[str, dict[str, float | None]],
    all_z: dict[str, dict[str, float | None]],
    source_weights: dict[str, float],
    models: list[str],
    sources: list[dict],
) -> dict:
    """Assemble the complete output report from collected data."""
    composite = compute_composite(all_z, source_weights, models)

    # Per-source scores section
    per_source_scores: dict[str, dict] = {}
    for source in sources:
        sid = source["id"]
        raw_scores = all_raw.get(sid, {})
        z_scores = all_z.get(sid, {})

        # For display, undo the negation we applied for "lower_is_better"
        # sources -- show the original positive values in raw output
        display_raw: dict[str, float | None] = {}
        higher_is_better = source.get("higher_is_better", True)
        for m, v in raw_scores.items():
            if v is not None and not higher_is_better:
                display_raw[m] = -v  # undo negation
            else:
                display_raw[m] = v

        per_source_scores[sid] = {
            "raw": display_raw,
            "z_score": z_scores,
        }

    # Data completeness per model
    data_completeness: dict[str, float] = {}
    total_possible_weight = sum(source_weights.values())
    for model in models:
        avail_weight = sum(
            source_weights[sid]
            for sid in all_z
            if all_z[sid].get(model) is not None
        )
        data_completeness[model] = (
            round(avail_weight / total_possible_weight, 4)
            if total_possible_weight > 0
            else 0.0
        )

    return {
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "models_requested": len(models),
            "sources_configured": len(sources),
            "normalization": "z_score",
            "missing_model_handling": "reweight_proportional",
        },
        "composite_ranking": composite,
        "per_source_scores": per_source_scores,
        "data_completeness": data_completeness,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point: fetch sources, normalize, rank, and output."""
    args = parse_args()
    sources_path = Path(args.sources)

    if not sources_path.exists():
        log(f"ERROR: sources file not found: {sources_path}")
        sys.exit(1)

    sources_cfg = load_json(sources_path)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    cache_dir = Path(args.cache_dir)

    if not models:
        log("ERROR: no models specified")
        sys.exit(1)

    sources = sources_cfg.get("sources", [])
    if not sources:
        log("ERROR: No sources configured in sources file")
        sys.exit(1)

    log(f"Models: {', '.join(models)}")
    log(f"Sources: {len(sources)} configured")
    log(f"Cache dir: {cache_dir}")

    # Dry-run exits early
    if args.dry_run:
        run_dry_run(sources, cache_dir)
        return

    # Fetch and process all sources
    all_raw: dict[str, dict[str, float | None]] = {}
    all_z: dict[str, dict[str, float | None]] = {}
    source_weights: dict[str, float] = {}
    successes = 0
    failures = 0

    for source in sources:
        sid = source["id"]
        source_weights[sid] = source.get("weight", 1.0)
        cache_hours = source.get("cache_hours", DEFAULT_CACHE_HOURS)

        log(f"Processing source: {source['name']} ({sid})")
        try:
            raw_body = get_cached_or_fetch(
                sid,
                source["endpoint_url"],
                cache_dir,
                cache_hours,
                args.no_cache,
            )
            data = json.loads(raw_body)
            scores = extract_scores(data, source, models)
            all_raw[sid] = scores
            all_z[sid] = z_score_normalize(scores)

            found = sum(1 for v in scores.values() if v is not None)
            log(f"  OK: {source['name']} -- {found}/{len(models)} models found")
            successes += 1
        except Exception as e:
            log(f"  WARN: {source['name']} failed: {e}")
            all_raw[sid] = {m: None for m in models}
            all_z[sid] = {m: None for m in models}
            failures += 1

    log(f"Fetch complete: {successes} succeeded, {failures} failed")

    if successes == 0:
        log("ERROR: All sources failed. Cannot produce ranking.")
        sys.exit(1)

    # Build report
    report = build_report(all_raw, all_z, source_weights, models, sources)

    # Summary to stderr
    if args.summary:
        format_summary(report)

    # Write output
    output_str = json.dumps(report, indent=2 if args.pretty else None) + "\n"

    if args.output == "-":
        sys.stdout.write(output_str)
    else:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_str, encoding="utf-8")
        log(f"Report written to {out_path}")


if __name__ == "__main__":
    main()
