#!/usr/bin/env python3
"""RWEA (Reliability-Weighted Evidence Aggregation) scorer for debate candidates.

Computes deterministic scores from debater reviews and pairwise comparisons.
Supports domain-aware scoring with benchmark-based model reliability weights.

Usage:
    python3 rwea_score.py --input payload.json --pretty
    python3 rwea_score.py --input payload.json --domain coding --pretty
    python3 rwea_score.py --input payload.json --domain math --summary
    echo '{"candidates": [...]}' | python3 rwea_score.py --stdin --pretty
    python3 rwea_score.py --validate payload.json
    python3 rwea_score.py --list-domains
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import mean
from typing import TextIO

# Default scoring weights (used when no domain is specified)
W_BASE = 0.50
W_PAIRWISE = 2.00
W_RISK = 0.70
W_RELIABILITY = 0.00  # no reliability bonus without domain
W_FORMAL = 0.00       # no formal verification bonus without domain/Aristotle

# Thresholds
CRITICAL_FAIL_ELIMINATION = 2  # eliminate if >= this many critical_fail flags
HYBRID_GAP_THRESHOLD = 0.40    # synthesize hybrid if top-two gap < this
MIN_VIABLE_SCORE = 1.20        # ask follow-up if top score < this

# Default paths
SKILL_DIR = Path.home() / ".claude" / "skills" / "convolutional-debate-agent"
BENCHMARKS_PATH = SKILL_DIR / "settings" / "benchmark-profiles.json"


def load_benchmark_profiles(path: Path) -> dict:
    """Load benchmark profiles from JSON file."""
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def get_domain_config(profiles: dict, domain: str) -> dict | None:
    """Get the configuration for a specific domain."""
    domains = profiles.get("domains", {})
    return domains.get(domain)


def _validate_range(name: str, value: int, lo: int, hi: int) -> None:
    """Validate that a value is an integer within [lo, hi]."""
    if not isinstance(value, int) or value < lo or value > hi:
        raise ValueError(f"{name} must be an int in [{lo}, {hi}], got {value!r}")


def _validate_review(review: dict, candidate_id: str, review_idx: int) -> None:
    """Validate a single review object has all required fields."""
    required = {"support": (0, 2), "evidence": (0, 2), "major_risks": (0, 2), "critical_fail": (0, 1)}
    for field, (lo, hi) in required.items():
        val = review.get(field)
        if val is None:
            raise ValueError(
                f"candidate {candidate_id!r} review {review_idx}: missing required field '{field}'"
            )
        _validate_range(f"candidate {candidate_id!r} review {review_idx} {field}", val, lo, hi)


def _candidate_metrics(
    candidate: dict,
    max_wins: int,
    w_base: float = W_BASE,
    w_pairwise: float = W_PAIRWISE,
    w_risk: float = W_RISK,
    w_reliability: float = W_RELIABILITY,
    w_formal: float = W_FORMAL,
    model_weight: float = 0.0,
    formal_score: float = 0.0,
) -> dict:
    """Compute all metrics for a single candidate.

    Formula: score = w_base*base + w_pairwise*pairwise - w_risk*risk + w_reliability*model_weight + w_formal*formal_score
    """
    candidate_id = candidate.get("id", "<unknown>")
    model_id = candidate.get("model", None)
    wins = candidate.get("wins")
    reviews = candidate.get("reviews")

    if not isinstance(reviews, list) or not reviews:
        raise ValueError(f"candidate {candidate_id!r} has no valid reviews list")
    if not isinstance(wins, int) or wins < 0 or wins > max_wins:
        raise ValueError(
            f"candidate {candidate_id!r} wins must be int in [0, {max_wins}], got {wins!r}"
        )

    support_evidence = []
    risk_values = []
    critical_count = 0

    for idx, review in enumerate(reviews, start=1):
        if not isinstance(review, dict):
            raise ValueError(f"candidate {candidate_id!r} review {idx} must be an object")

        _validate_review(review, candidate_id, idx)

        support = review["support"]
        evidence = review["evidence"]
        major_risks = review["major_risks"]
        critical_fail = review["critical_fail"]

        support_evidence.append(support + evidence)
        risk_values.append(major_risks + 2 * critical_fail)
        critical_count += critical_fail

    base = mean(support_evidence)
    risk = mean(risk_values)
    pairwise = wins / max_wins if max_wins else 0.0
    reliability_bonus = w_reliability * model_weight
    formal_bonus = w_formal * formal_score
    raw_score = w_base * base + w_pairwise * pairwise - w_risk * risk + reliability_bonus + formal_bonus
    eliminated = critical_count >= CRITICAL_FAIL_ELIMINATION

    result = {
        "id": candidate_id,
        "wins": wins,
        "base": round(base, 4),
        "risk": round(risk, 4),
        "pairwise": round(pairwise, 4),
        "score": round(raw_score, 4),
        "critical_fails": critical_count,
        "eliminated": eliminated,
    }

    # Include model info and reliability bonus when domain scoring is active
    if model_id:
        result["model"] = model_id
    if w_reliability > 0:
        result["model_weight"] = round(model_weight, 4)
        result["reliability_bonus"] = round(reliability_bonus, 4)
    if w_formal > 0 and formal_score != 0.0:
        result["formal_score"] = round(formal_score, 4)
        result["formal_bonus"] = round(formal_bonus, 4)

    return result


def score(payload: dict, domain: str | None = None, benchmarks_path: Path = BENCHMARKS_PATH) -> dict:
    """Score all candidates and determine the winner.

    When domain is specified, loads benchmark profiles and applies:
    - Domain-specific RWEA weight overrides (w_base, w_pairwise, w_risk)
    - Per-model reliability bonuses based on benchmark performance

    Returns a dict with:
        - winner: ID of the winning candidate (or None)
        - decision: "winner", "hybrid", "insufficient", or "all_eliminated"
        - hybrid_candidates: list of IDs if decision is "hybrid"
        - results: ranked list of candidate metrics
        - domain: domain used (if any)
        - weights: RWEA weights applied
    """
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) < 2:
        raise ValueError("payload must include at least two candidates")

    # Resolve scoring weights
    w_base = W_BASE
    w_pairwise = W_PAIRWISE
    w_risk = W_RISK
    w_reliability = W_RELIABILITY
    w_formal = W_FORMAL
    domain_config = None
    model_weights = {}

    if domain:
        profiles = load_benchmark_profiles(benchmarks_path)
        domain_config = get_domain_config(profiles, domain)
        if domain_config:
            rwea = domain_config.get("rwea_weights", {})
            w_base = rwea.get("w_base", W_BASE)
            w_pairwise = rwea.get("w_pairwise", W_PAIRWISE)
            w_risk = rwea.get("w_risk", W_RISK)
            w_reliability = rwea.get("w_reliability", W_RELIABILITY)
            w_formal = rwea.get("w_formal", W_FORMAL)
            # Build model weight lookup
            models = domain_config.get("models", {})
            for model_name, model_info in models.items():
                model_weights[model_name] = model_info.get("weight", 0.5)

    max_wins = len(candidates) - 1
    results = []
    for c in candidates:
        model_id = c.get("model")
        mw = model_weights.get(model_id, 0.5) if model_id else 0.0
        fs = c.get("formal_score", 0.0)
        results.append(_candidate_metrics(
            c, max_wins,
            w_base=w_base, w_pairwise=w_pairwise,
            w_risk=w_risk, w_reliability=w_reliability,
            w_formal=w_formal, model_weight=mw,
            formal_score=fs,
        ))

    # Sort: non-eliminated first, then by score desc, base desc, risk asc
    ranking = sorted(
        results,
        key=lambda r: (r["eliminated"], -r["score"], -r["base"], r["risk"]),
    )

    # Filter to non-eliminated
    viable = [r for r in ranking if not r["eliminated"]]

    output = {
        "domain": domain or "none",
        "weights": {
            "w_base": w_base,
            "w_pairwise": w_pairwise,
            "w_risk": w_risk,
            "w_reliability": w_reliability,
            "w_formal": w_formal,
        },
    }

    if not viable:
        output.update({
            "winner": None,
            "decision": "all_eliminated",
            "hybrid_candidates": [],
            "results": ranking,
        })
        return output

    top = viable[0]

    if top["score"] < MIN_VIABLE_SCORE:
        output.update({
            "winner": None,
            "decision": "insufficient",
            "hybrid_candidates": [],
            "results": ranking,
        })
        return output

    if len(viable) >= 2:
        runner_up = viable[1]
        gap = top["score"] - runner_up["score"]
        if gap < HYBRID_GAP_THRESHOLD:
            output.update({
                "winner": top["id"],
                "decision": "hybrid",
                "hybrid_candidates": [top["id"], runner_up["id"]],
                "results": ranking,
            })
            return output

    output.update({
        "winner": top["id"],
        "decision": "winner",
        "hybrid_candidates": [],
        "results": ranking,
    })
    return output


def validate_payload(payload: dict) -> list[str]:
    """Validate a payload without scoring. Returns list of error messages."""
    errors = []
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return ["'candidates' must be a list"]
    if len(candidates) < 2:
        errors.append(f"need at least 2 candidates, got {len(candidates)}")

    max_wins = len(candidates) - 1
    seen_ids = set()

    for i, c in enumerate(candidates):
        cid = c.get("id", f"<index {i}>")
        if cid in seen_ids:
            errors.append(f"duplicate candidate id: {cid!r}")
        seen_ids.add(cid)

        wins = c.get("wins")
        if not isinstance(wins, int) or wins < 0 or wins > max_wins:
            errors.append(f"candidate {cid!r}: wins must be int in [0, {max_wins}]")

        reviews = c.get("reviews")
        if not isinstance(reviews, list):
            errors.append(f"candidate {cid!r}: 'reviews' must be a list")
            continue

        for j, r in enumerate(reviews, 1):
            if not isinstance(r, dict):
                errors.append(f"candidate {cid!r} review {j}: must be an object")
                continue
            for field, (lo, hi) in [("support", (0, 2)), ("evidence", (0, 2)),
                                     ("major_risks", (0, 2)), ("critical_fail", (0, 1))]:
                val = r.get(field)
                if val is None:
                    errors.append(f"candidate {cid!r} review {j}: missing '{field}'")
                elif not isinstance(val, int) or val < lo or val > hi:
                    errors.append(f"candidate {cid!r} review {j}: {field} must be int in [{lo}, {hi}]")

    return errors


def format_summary(result: dict) -> str:
    """Format scoring results as a human-readable summary."""
    lines = []
    lines.append("RWEA Scoring Results")
    lines.append("=" * 60)

    # Show domain and weights
    domain = result.get("domain", "none")
    weights = result.get("weights", {})
    if domain != "none":
        lines.append(f"  Domain: {domain}")
        lines.append(f"  Weights: base={weights.get('w_base', '?')}"
                      f"  pairwise={weights.get('w_pairwise', '?')}"
                      f"  risk={weights.get('w_risk', '?')}"
                      f"  reliability={weights.get('w_reliability', '?')}"
                      f"  formal={weights.get('w_formal', '?')}")
    lines.append("")

    for r in result["results"]:
        status = " [ELIMINATED]" if r["eliminated"] else ""
        marker = " << WINNER" if r["id"] == result.get("winner") else ""
        model_str = f"  model={r['model']}" if "model" in r else ""
        rel_str = f"  rel_bonus=+{r['reliability_bonus']:.2f}" if "reliability_bonus" in r else ""
        formal_str = f"  formal={r['formal_score']:+.2f}(+{r['formal_bonus']:.2f})" if "formal_bonus" in r else ""
        lines.append(f"  {r['id']}: score={r['score']:.2f}  base={r['base']:.2f}  "
                      f"risk={r['risk']:.2f}  pairwise={r['pairwise']:.2f}  "
                      f"crits={r['critical_fails']}{model_str}{rel_str}{formal_str}{status}{marker}")

    lines.append("")
    lines.append(f"Decision: {result['decision']}")
    if result["decision"] == "hybrid":
        lines.append(f"Hybrid from: {', '.join(result['hybrid_candidates'])}")
    elif result["decision"] == "insufficient":
        lines.append("Top score below threshold — ask follow-up questions.")
    elif result["decision"] == "all_eliminated":
        lines.append("All candidates eliminated — ask follow-up questions.")

    return "\n".join(lines)


def list_domains(benchmarks_path: Path) -> None:
    """Print available domains from benchmark profiles."""
    profiles = load_benchmark_profiles(benchmarks_path)
    domains = profiles.get("domains", {})
    if not domains:
        print("No benchmark profiles found.")
        return

    print("Available domains:\n")
    for name, cfg in sorted(domains.items()):
        desc = cfg.get("description", "")
        rwea = cfg.get("rwea_weights", {})
        models = cfg.get("models", {})
        model_weights = ", ".join(
            f"{m}={info.get('weight', '?')}" for m, info in sorted(models.items())
        )
        print(f"  {name:12s}  {desc}")
        print(f"               weights: base={rwea.get('w_base','?')} "
              f"pairwise={rwea.get('w_pairwise','?')} "
              f"risk={rwea.get('w_risk','?')} "
              f"reliability={rwea.get('w_reliability','?')} "
              f"formal={rwea.get('w_formal','?')}")
        print(f"               models:  {model_weights}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RWEA candidate scorer for the Convolutional Debate Agent."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--input", type=Path,
        help="Path to JSON payload with candidate reviews.",
    )
    group.add_argument(
        "--stdin", action="store_true",
        help="Read JSON payload from stdin.",
    )
    group.add_argument(
        "--validate", type=Path, metavar="FILE",
        help="Validate a payload file without scoring.",
    )
    group.add_argument(
        "--list-domains", action="store_true",
        help="List available domains from benchmark profiles.",
    )

    parser.add_argument("--domain", help="Domain for benchmark-aware scoring (e.g., coding, math, finance).")
    parser.add_argument("--benchmarks", type=Path, default=BENCHMARKS_PATH,
                        help="Path to benchmark-profiles.json.")
    parser.add_argument("--pretty", action="store_true", help="Print indented JSON.")
    parser.add_argument("--summary", action="store_true", help="Print human-readable summary.")
    args = parser.parse_args()

    if args.list_domains:
        list_domains(args.benchmarks)
        sys.exit(0)

    if args.validate:
        payload = json.loads(args.validate.read_text())
        errors = validate_payload(payload)
        if errors:
            print(f"Validation failed ({len(errors)} errors):", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
            sys.exit(1)
        else:
            print("Payload is valid.")
            sys.exit(0)

    if args.stdin:
        payload = json.load(sys.stdin)
    else:
        payload = json.loads(args.input.read_text())

    output = score(payload, domain=args.domain, benchmarks_path=args.benchmarks)

    if args.summary:
        print(format_summary(output))
    elif args.pretty:
        print(json.dumps(output, indent=2))
    else:
        print(json.dumps(output))


if __name__ == "__main__":
    main()
