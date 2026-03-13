#!/usr/bin/env python3
"""Analytics finding evaluator for the Ralph Loop.

Replaces idea_evaluator.py for analytics presets. Scores findings on three
dimensions (novelty, actionability, evidence), deduplicates via Jaccard,
and updates the findings bank.

Usage:
    python analytics_evaluator.py \
        --result result.json \
        --findings-bank findings-bank.json \
        --config ralph-config.json
"""

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Stopwords
# ---------------------------------------------------------------------------

STOPWORDS: set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "have",
    "has", "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "shall", "can", "need", "to", "of", "in", "for", "on",
    "with", "at", "by", "from", "as", "into", "through", "during", "before",
    "after", "above", "below", "between", "out", "off", "over", "under",
    "again", "further", "then", "once", "and", "but", "or", "nor", "not",
    "so", "very", "just", "about", "up", "down", "no", "its", "that",
    "this", "these", "those", "which", "what", "who", "whom", "when",
    "where", "how", "all", "each", "every", "both", "few", "more", "most",
    "other", "some", "such", "than", "data", "table", "query", "select",
    "count", "users", "user", "grapple",
}

# Keywords that signal cross-table analysis (higher novelty)
CROSS_TABLE_KEYWORDS: list[list[str]] = [
    ["session_messages", "users_subscriptions"],
    ["emails", "sessions"],
    ["users_media", "session_messages"],
    ["subscriptions", "engagement"],
    ["paywall", "conversion"],
    ["cohort", "retention"],
    ["case_score", "settlement"],
]

# Funnel stage keywords
FUNNEL_STAGE_KEYWORDS: dict[int, list[str]] = {
    1: ["visitor", "landing", "site"],
    2: ["registered", "signup", "registration", "created_at"],
    3: ["first message", "initial message", "first chat"],
    4: ["engaged", "engagement", "5 messages", "return"],
    5: ["case score", "case_score", "scoring", "rating"],
    6: ["plan", "subscription", "pricing", "pending_plan"],
    7: ["agreement", "signed", "conversion", "active subscription"],
    8: ["letter", "email sent", "outbound", "correspondence"],
    9: ["settlement", "outcome", "resolution"],
}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_eval_config(config_path: str) -> dict:
    """Load analytics_evaluation section from ralph-config.json."""
    defaults = {
        "novelty_weight": 0.35,
        "actionability_weight": 0.35,
        "evidence_weight": 0.30,
        "dedup_jaccard_threshold": 0.7,
        "min_key_terms": 5,
    }
    try:
        with open(config_path, "r") as f:
            cfg = json.load(f)
        ae = cfg.get("analytics_evaluation", {})
        defaults.update({k: ae[k] for k in defaults if k in ae})
    except (OSError, json.JSONDecodeError):
        pass
    return defaults


# ---------------------------------------------------------------------------
# Findings bank I/O
# ---------------------------------------------------------------------------

def read_findings_bank(path: str) -> dict:
    """Read or initialize the findings bank."""
    try:
        with open(path, "r") as f:
            bank = json.load(f)
        if "findings" not in bank:
            bank["findings"] = []
        if "stats" not in bank:
            bank["stats"] = {}
        return bank
    except (OSError, json.JSONDecodeError):
        return {
            "findings": [],
            "stats": {
                "total": 0,
                "unique": 0,
                "duplicates": 0,
                "avg_combined_score": 0.0,
                "top3_ids": [],
            },
        }


def write_findings_bank(path: str, bank: dict) -> None:
    """Atomically write the findings bank via temp file + rename."""
    out_dir = os.path.dirname(os.path.abspath(path))
    os.makedirs(out_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out_dir, suffix=".tmp", prefix=".findings_")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(bank, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def next_finding_id(bank: dict) -> str:
    """Generate the next finding-NNN id."""
    n = len(bank["findings"]) + 1
    return f"finding-{n:03d}"


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def extract_finding_json(response_text: str) -> dict | None:
    """Extract the finding JSON from an LLM response.

    Handles markdown code fences (```json ... ```) and bare JSON.
    Looks specifically for finding_title field to distinguish from other JSON.
    """
    # Try fenced blocks first
    fence_pattern = r"```(?:json)?\s*\n?(.*?)```"
    matches = re.findall(fence_pattern, response_text, re.DOTALL)
    for match in matches:
        try:
            obj = json.loads(match.strip())
            if isinstance(obj, dict) and "finding_title" in obj:
                return obj
        except json.JSONDecodeError:
            continue

    # Try the whole response as JSON
    try:
        obj = json.loads(response_text.strip())
        if isinstance(obj, dict) and "finding_title" in obj:
            return obj
    except json.JSONDecodeError:
        pass

    # Try to find any JSON with finding_title
    brace_pattern = r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
    for m in re.finditer(brace_pattern, response_text, re.DOTALL):
        try:
            obj = json.loads(m.group())
            if "finding_title" in obj:
                return obj
        except json.JSONDecodeError:
            continue

    return None


# ---------------------------------------------------------------------------
# Scoring — novelty
# ---------------------------------------------------------------------------

def score_novelty(finding: dict) -> float:
    """Heuristic novelty score in [0, 1].

    Rewards:
    - Cross-table joins / correlations
    - Temporal patterns
    - Segment comparisons
    - Counter-intuitive findings
    - Specific numbers cited
    """
    score = 0.2  # baseline

    text = " ".join([
        finding.get("finding_title", ""),
        finding.get("finding_summary", ""),
        finding.get("recommendation", ""),
    ]).lower()

    # Cross-table analysis (+0.2 per bridge, max +0.4)
    bridges = 0
    for cluster in CROSS_TABLE_KEYWORDS:
        if all(kw in text for kw in cluster):
            bridges += 1
    score += min(0.2 * bridges, 0.4)

    # Temporal patterns
    temporal_words = ["trend", "cohort", "week-over-week", "month", "time series",
                      "seasonal", "temporal", "over time", "trajectory"]
    if any(tw in text for tw in temporal_words):
        score += 0.15

    # Segment comparisons
    segment_words = ["vs", "versus", "compared to", "segment", "cohort",
                     "group", "percentile", "quartile", "decile"]
    if any(sw in text for sw in segment_words):
        score += 0.1

    # Counter-intuitive signals
    surprise_words = ["surprising", "unexpected", "counter-intuitive", "paradox",
                      "contrary", "despite", "although", "however"]
    if any(sw in text for sw in surprise_words):
        score += 0.15

    # Specific numbers cited (percentages, counts)
    numbers = re.findall(r'\d+\.?\d*%|\d{2,}', text)
    if len(numbers) >= 3:
        score += 0.15
    elif len(numbers) >= 1:
        score += 0.08

    return min(score, 1.0)


# ---------------------------------------------------------------------------
# Scoring — actionability
# ---------------------------------------------------------------------------

def score_actionability(finding: dict) -> float:
    """Heuristic actionability score in [0, 1].

    Rewards:
    - Specific, detailed recommendations
    - Funnel stages referenced
    - Quantified impact
    - Key metrics with values
    """
    score = 0.15  # baseline

    # Recommendation specificity
    rec = finding.get("recommendation", "")
    if len(rec) > 200:
        score += 0.3
    elif len(rec) > 100:
        score += 0.2
    elif len(rec) > 50:
        score += 0.1

    # Action verbs in recommendation
    action_words = ["implement", "add", "create", "send", "trigger", "show",
                    "display", "change", "reduce", "increase", "test", "a/b test",
                    "optimize", "remove", "move", "redesign"]
    rec_lower = rec.lower()
    if any(aw in rec_lower for aw in action_words):
        score += 0.1

    # Funnel stages affected
    stages = finding.get("funnel_stages_affected", [])
    if isinstance(stages, list):
        if len(stages) >= 3:
            score += 0.15
        elif len(stages) >= 1:
            score += 0.08

    # Quantified impact
    text = " ".join([
        finding.get("finding_summary", ""),
        rec,
    ]).lower()
    impact_words = ["increase by", "decrease by", "improve", "reduce",
                    "save", "gain", "boost", "lift"]
    if any(iw in text for iw in impact_words):
        score += 0.1

    # Key metrics count
    metrics = finding.get("key_metrics", {})
    if isinstance(metrics, dict):
        if len(metrics) >= 4:
            score += 0.2
        elif len(metrics) >= 2:
            score += 0.12
        elif len(metrics) >= 1:
            score += 0.06

    return min(score, 1.0)


# ---------------------------------------------------------------------------
# Scoring — evidence
# ---------------------------------------------------------------------------

def score_evidence(finding: dict) -> float:
    """Heuristic evidence quality score in [0, 1].

    Rewards:
    - SQL queries present
    - Numbers in summary
    - Confidence level
    - Tables referenced
    """
    score = 0.15  # baseline

    # SQL queries used
    queries = finding.get("sql_queries_used", [])
    if isinstance(queries, list):
        if len(queries) >= 3:
            score += 0.25
        elif len(queries) >= 1:
            score += 0.15

    # Numbers in summary (evidence of quantitative analysis)
    summary = finding.get("finding_summary", "")
    numbers = re.findall(r'\d+\.?\d*', summary)
    if len(numbers) >= 5:
        score += 0.2
    elif len(numbers) >= 2:
        score += 0.1

    # Confidence level
    confidence = finding.get("confidence", "").lower()
    if confidence == "high":
        score += 0.15
    elif confidence == "medium":
        score += 0.08

    # Tables referenced in text
    table_names = ["users", "sessions", "session_messages", "emails",
                   "users_subscriptions", "subscriptions", "users_media",
                   "subscription_capabilities", "subscriptions_features"]
    text = " ".join([
        summary,
        finding.get("recommendation", ""),
        str(finding.get("sql_queries_used", "")),
    ]).lower()

    tables_hit = sum(1 for t in table_names if t in text)
    if tables_hit >= 4:
        score += 0.2
    elif tables_hit >= 2:
        score += 0.1

    # Evidence strength description
    evidence_str = finding.get("evidence_strength", "")
    if len(evidence_str) > 50:
        score += 0.1

    return min(score, 1.0)


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def extract_key_terms(finding: dict) -> set[str]:
    """Tokenize finding title + summary + key metric names into terms."""
    text = " ".join([
        finding.get("finding_title", ""),
        finding.get("finding_summary", ""),
        " ".join(finding.get("key_metrics", {}).keys()) if isinstance(finding.get("key_metrics"), dict) else "",
    ])
    tokens = re.findall(r"[a-zA-Z]+", text.lower())
    return {t for t in tokens if len(t) >= 3 and t not in STOPWORDS}


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Jaccard index between two sets."""
    if not a and not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union > 0 else 0.0


def find_duplicate(
    new_terms: set[str],
    bank: dict,
    threshold: float,
) -> str | None:
    """Return the finding_id of the best duplicate match, or None."""
    best_id = None
    best_sim = 0.0

    for entry in bank["findings"]:
        existing_terms = set(entry.get("key_terms", []))
        sim = jaccard_similarity(new_terms, existing_terms)
        if sim > best_sim:
            best_sim = sim
            best_id = entry.get("finding_id")

    if best_sim >= threshold:
        return best_id
    return None


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def update_stats(bank: dict) -> None:
    """Recompute stats from findings list."""
    findings = bank["findings"]
    total = len(findings)
    dups = sum(1 for f in findings if f.get("is_duplicate", False))
    unique = total - dups

    scores = [f["combined_score"] for f in findings if "combined_score" in f]
    avg = sum(scores) / len(scores) if scores else 0.0

    ranked = sorted(findings, key=lambda f: f.get("combined_score", 0), reverse=True)
    top3 = [f["finding_id"] for f in ranked[:3]]

    bank["stats"] = {
        "total": total,
        "unique": unique,
        "duplicates": dups,
        "avg_combined_score": round(avg, 4),
        "top3_ids": top3,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Analytics finding evaluator for the Ralph Loop."
    )
    p.add_argument("--result", required=True, help="Path to LLM result JSON")
    p.add_argument("--findings-bank", required=True, help="Path to findings-bank.json")
    p.add_argument("--config", required=True, help="Path to ralph-config.json")
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # 1. Load config
    config = load_eval_config(args.config)

    # 2. Load result
    try:
        with open(args.result, "r") as f:
            result = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": f"Failed to read result: {exc}"}))
        return 1

    # 3. Load findings bank
    bank = read_findings_bank(args.findings_bank)

    # 4. Parse finding from LLM response
    response_text = result.get("response", "")
    finding = extract_finding_json(response_text)
    finding_id = next_finding_id(bank)

    if finding is None:
        # Record failed parse
        failed_entry = {
            "finding_id": finding_id,
            "source_model": result.get("model", "unknown"),
            "iteration": result.get("iteration"),
            "parse_failed": True,
            "is_duplicate": False,
            "novelty_score": 0.0,
            "actionability_score": 0.0,
            "evidence_score": 0.0,
            "combined_score": 0.0,
            "key_terms": [],
            "raw_response_snippet": response_text[:300],
        }
        bank["findings"].append(failed_entry)
        update_stats(bank)
        write_findings_bank(args.findings_bank, bank)

        summary = {
            "finding_id": finding_id,
            "title": None,
            "combined_score": 0.0,
            "is_duplicate": False,
            "novelty_score": 0.0,
            "actionability_score": 0.0,
            "evidence_score": 0.0,
            "error": "Failed to parse finding JSON from LLM response",
        }
        print(json.dumps(summary))
        return 0

    # 5. Score novelty
    novelty = score_novelty(finding)

    # 6. Score actionability
    actionability = score_actionability(finding)

    # 7. Score evidence
    evidence = score_evidence(finding)

    # 8. Combined score
    combined = (
        config["novelty_weight"] * novelty
        + config["actionability_weight"] * actionability
        + config["evidence_weight"] * evidence
    )
    combined = round(combined, 4)

    # 9. Extract key terms
    key_terms = extract_key_terms(finding)

    # 10. Deduplication
    is_duplicate = False
    duplicate_of = None

    if len(key_terms) >= config["min_key_terms"]:
        dup_id = find_duplicate(key_terms, bank, config["dedup_jaccard_threshold"])
        if dup_id is not None:
            is_duplicate = True
            duplicate_of = dup_id

    # 11. Build entry
    entry = {
        "finding_id": finding_id,
        "source_model": result.get("model", "unknown"),
        "iteration": result.get("iteration"),
        "finding_title": finding.get("finding_title", ""),
        "finding_summary": finding.get("finding_summary", ""),
        "funnel_stages_affected": finding.get("funnel_stages_affected", []),
        "key_metrics": finding.get("key_metrics", {}),
        "sql_queries_used": finding.get("sql_queries_used", []),
        "recommendation": finding.get("recommendation", ""),
        "confidence": finding.get("confidence", ""),
        "evidence_strength": finding.get("evidence_strength", ""),
        "novelty_score": round(novelty, 4),
        "actionability_score": round(actionability, 4),
        "evidence_score": round(evidence, 4),
        "combined_score": combined,
        "is_duplicate": is_duplicate,
        "key_terms": sorted(key_terms),
    }
    if duplicate_of is not None:
        entry["duplicate_of"] = duplicate_of

    # 12. Append and update
    bank["findings"].append(entry)
    update_stats(bank)
    write_findings_bank(args.findings_bank, bank)

    # 13. Print summary
    summary = {
        "finding_id": finding_id,
        "title": finding.get("finding_title", ""),
        "combined_score": combined,
        "is_duplicate": is_duplicate,
        "novelty_score": round(novelty, 4),
        "actionability_score": round(actionability, 4),
        "evidence_score": round(evidence, 4),
    }
    if duplicate_of is not None:
        summary["duplicate_of"] = duplicate_of

    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
