#!/usr/bin/env python3
"""Synthesis pass for the Ralph analytics loop.

Post-loop script that reads all findings from findings-bank.json,
groups by funnel stage, identifies cross-cutting themes, ranks top 10
recommendations, and outputs synthesis-report.json.

Usage:
    python synthesis_pass.py --findings-bank /path/to/findings-bank.json \
        --output /path/to/synthesis-report.json
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


def load_findings(path: str) -> list[dict]:
    """Load findings from findings-bank.json."""
    try:
        with open(path, "r") as f:
            bank = json.load(f)
        return [f for f in bank.get("findings", []) if not f.get("parse_failed")]
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: Cannot load findings: {e}", file=sys.stderr)
        return []


def group_by_funnel_stage(findings: list[dict]) -> dict[int, list[dict]]:
    """Group findings by funnel stages they affect."""
    groups: dict[int, list[dict]] = defaultdict(list)
    for f in findings:
        stages = f.get("funnel_stages_affected", [])
        if isinstance(stages, list):
            for stage in stages:
                if isinstance(stage, int) and 1 <= stage <= 9:
                    groups[stage].append(f)
        # Also add to stage 0 (unclassified) if no stages
        if not stages:
            groups[0].append(f)
    return dict(groups)


def identify_themes(findings: list[dict]) -> list[dict]:
    """Identify cross-cutting themes across findings."""
    # Extract common terms across findings
    all_terms: dict[str, int] = defaultdict(int)
    finding_terms: list[set[str]] = []

    for f in findings:
        terms = set(f.get("key_terms", []))
        finding_terms.append(terms)
        for t in terms:
            all_terms[t] += 1

    # Theme candidates: terms that appear in 3+ findings
    min_count = min(3, max(2, len(findings) // 3))
    common = {t: c for t, c in all_terms.items() if c >= min_count}

    # Cluster common terms into themes
    themes = []

    # Predefined theme categories
    theme_defs = [
        {
            "name": "Paywall & Message Limits",
            "keywords": ["paywall", "message", "limit", "free", "locked", "thread", "max"],
            "findings": [],
        },
        {
            "name": "Case Score & Conversion",
            "keywords": ["case", "score", "conversion", "convert", "plan", "subscription"],
            "findings": [],
        },
        {
            "name": "Time & Speed Patterns",
            "keywords": ["time", "speed", "fast", "slow", "delay", "hours", "days", "minutes", "velocity"],
            "findings": [],
        },
        {
            "name": "Engagement Depth",
            "keywords": ["engagement", "messages", "sessions", "return", "active", "depth"],
            "findings": [],
        },
        {
            "name": "Email & Legal Pipeline",
            "keywords": ["email", "letter", "correspondence", "legal", "outbound", "inbound"],
            "findings": [],
        },
        {
            "name": "User Commitment Signals",
            "keywords": ["document", "upload", "verification", "terms", "marketing", "commitment"],
            "findings": [],
        },
    ]

    for f in findings:
        text = " ".join([
            f.get("finding_title", ""),
            f.get("finding_summary", ""),
        ]).lower()

        for theme in theme_defs:
            if any(kw in text for kw in theme["keywords"]):
                theme["findings"].append(f["finding_id"])

    # Only include themes with findings
    for theme in theme_defs:
        if theme["findings"]:
            themes.append({
                "theme": theme["name"],
                "finding_count": len(theme["findings"]),
                "finding_ids": theme["findings"],
            })

    return sorted(themes, key=lambda t: t["finding_count"], reverse=True)


def rank_recommendations(findings: list[dict]) -> list[dict]:
    """Rank top 10 recommendations by combined score."""
    # Filter to unique findings with recommendations
    candidates = [
        f for f in findings
        if not f.get("is_duplicate") and f.get("recommendation")
    ]

    # Sort by combined score
    ranked = sorted(candidates, key=lambda f: f.get("combined_score", 0), reverse=True)

    top10 = []
    for i, f in enumerate(ranked[:10], 1):
        top10.append({
            "rank": i,
            "finding_id": f["finding_id"],
            "finding_title": f.get("finding_title", ""),
            "recommendation": f.get("recommendation", ""),
            "combined_score": f.get("combined_score", 0),
            "confidence": f.get("confidence", ""),
            "funnel_stages_affected": f.get("funnel_stages_affected", []),
            "key_metrics": f.get("key_metrics", {}),
        })

    return top10


def compute_coverage(findings: list[dict]) -> dict:
    """Compute funnel stage coverage statistics."""
    stages_covered = set()
    for f in findings:
        for s in f.get("funnel_stages_affected", []):
            if isinstance(s, int):
                stages_covered.add(s)

    stage_names = {
        1: "Visitor",
        2: "Registered",
        3: "First Message",
        4: "Engaged",
        5: "Case Scored",
        6: "Plan Selected",
        7: "Agreement Signed",
        8: "First Letter Sent",
        9: "Settlement",
    }

    return {
        "stages_covered": sorted(stages_covered),
        "stages_missing": sorted(set(range(1, 10)) - stages_covered),
        "coverage_pct": round(len(stages_covered) / 9 * 100, 1),
        "stage_names": {str(s): stage_names.get(s, f"Stage {s}") for s in sorted(stages_covered)},
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Synthesis pass for Ralph analytics findings."
    )
    parser.add_argument("--findings-bank", required=True,
                        help="Path to findings-bank.json")
    parser.add_argument("--output", required=True,
                        help="Path to write synthesis-report.json")
    args = parser.parse_args()

    findings = load_findings(args.findings_bank)
    if not findings:
        print("No findings to synthesize.")
        report = {"error": "No findings to synthesize", "findings_count": 0}
        Path(args.output).write_text(json.dumps(report, indent=2))
        return 0

    unique_findings = [f for f in findings if not f.get("is_duplicate")]

    # Build synthesis
    stage_groups = group_by_funnel_stage(unique_findings)
    themes = identify_themes(unique_findings)
    top_recommendations = rank_recommendations(findings)
    coverage = compute_coverage(unique_findings)

    # Stage summaries
    stage_summaries = {}
    stage_names = {
        0: "Unclassified", 1: "Visitor", 2: "Registered", 3: "First Message",
        4: "Engaged", 5: "Case Scored", 6: "Plan Selected",
        7: "Agreement Signed", 8: "First Letter Sent", 9: "Settlement",
    }
    for stage, group in sorted(stage_groups.items()):
        stage_summaries[str(stage)] = {
            "stage_name": stage_names.get(stage, f"Stage {stage}"),
            "finding_count": len(group),
            "findings": [
                {
                    "finding_id": f["finding_id"],
                    "title": f.get("finding_title", ""),
                    "score": f.get("combined_score", 0),
                    "confidence": f.get("confidence", ""),
                }
                for f in sorted(group, key=lambda x: x.get("combined_score", 0), reverse=True)
            ],
        }

    # Aggregate stats
    scores = [f.get("combined_score", 0) for f in unique_findings]
    confidence_dist = defaultdict(int)
    for f in unique_findings:
        c = f.get("confidence", "unknown").lower()
        confidence_dist[c] += 1

    report = {
        "summary": {
            "total_findings": len(findings),
            "unique_findings": len(unique_findings),
            "duplicates": len(findings) - len(unique_findings),
            "avg_combined_score": round(sum(scores) / len(scores), 4) if scores else 0,
            "max_score": round(max(scores), 4) if scores else 0,
            "confidence_distribution": dict(confidence_dist),
        },
        "funnel_coverage": coverage,
        "stage_summaries": stage_summaries,
        "themes": themes,
        "top_recommendations": top_recommendations,
    }

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    # Print summary
    print(f"\n{'=' * 60}")
    print("  SYNTHESIS REPORT")
    print(f"{'=' * 60}")
    print(f"  Findings: {len(unique_findings)} unique / {len(findings)} total")
    print(f"  Funnel coverage: {coverage['coverage_pct']}% ({len(coverage['stages_covered'])}/9 stages)")
    print(f"  Themes identified: {len(themes)}")
    print(f"  Top recommendations: {len(top_recommendations)}")

    if top_recommendations:
        print(f"\n  TOP 3 RECOMMENDATIONS:")
        for rec in top_recommendations[:3]:
            title = rec["finding_title"][:50]
            print(f"  #{rec['rank']} [{rec['combined_score']:.3f}] {title}")

    if coverage["stages_missing"]:
        missing = [stage_names.get(s, f"Stage {s}") for s in coverage["stages_missing"]]
        print(f"\n  GAPS: No findings for stages: {', '.join(missing)}")

    print(f"\n  Report: {args.output}")
    print(f"{'=' * 60}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
