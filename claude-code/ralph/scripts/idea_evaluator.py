#!/usr/bin/env python3
"""Novelty/feasibility scoring and deduplication for the Ralph Loop.

Takes a raw LLM result JSON, parses the idea, scores it for novelty and
feasibility, checks for duplicates against existing ideas, and updates the
ideas bank.

Usage:
    python idea_evaluator.py --result result.json --ideas-bank ideas-bank.json --config ralph-config.json
"""

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Stopwords — ~100 common English words
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
    "other", "some", "such", "than",
}

# Fields considered cross-domain bridges when referenced together
SUBFIELD_KEYWORDS: list[list[str]] = [
    ["derivatives", "pricing", "options"],
    ["portfolio", "optimization", "allocation"],
    ["risk", "management", "var", "cvar"],
    ["microstructure", "order", "book", "liquidity"],
    ["machine", "learning", "neural", "deep"],
    ["stochastic", "diffusion", "sde", "ito"],
    ["bayesian", "inference", "posterior"],
    ["reinforcement", "learning", "policy", "agent"],
    ["nlp", "text", "sentiment", "language"],
    ["blockchain", "crypto", "defi"],
]

DATA_SOURCE_KEYWORDS: set[str] = {
    "crsp", "compustat", "wrds", "bloomberg", "refinitiv", "yahoo",
    "fred", "quandl", "lobster", "taq", "sec", "edgar",
    "publicly", "available", "open", "source", "simulat",
    "synthetic", "generated", "api",
}

ESTABLISHED_METHOD_KEYWORDS: set[str] = {
    "regression", "garch", "var", "monte", "carlo", "bootstrap",
    "maximum", "likelihood", "gmm", "ols", "pca", "kalman",
    "lstm", "transformer", "random", "forest", "gradient",
    "boosting", "backtest", "cross-validation", "validation",
    "hypothesis", "test", "significance",
}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_eval_config(config_path: str) -> dict:
    """Load idea_evaluation section from ralph-config.json."""
    defaults = {
        "novelty_weight": 0.55,
        "feasibility_weight": 0.45,
        "dedup_jaccard_threshold": 0.6,
        "min_key_terms": 5,
    }
    try:
        with open(config_path, "r") as f:
            cfg = json.load(f)
        ie = cfg.get("idea_evaluation", {})
        defaults.update({k: ie[k] for k in defaults if k in ie})
    except (OSError, json.JSONDecodeError):
        pass
    return defaults


# ---------------------------------------------------------------------------
# Ideas bank I/O
# ---------------------------------------------------------------------------

def read_ideas_bank(path: str) -> dict:
    """Read or initialize the ideas bank."""
    try:
        with open(path, "r") as f:
            bank = json.load(f)
        if "ideas" not in bank:
            bank["ideas"] = []
        if "stats" not in bank:
            bank["stats"] = {}
        return bank
    except (OSError, json.JSONDecodeError):
        return {
            "ideas": [],
            "stats": {
                "total": 0,
                "unique": 0,
                "duplicates": 0,
                "avg_combined_score": 0.0,
                "top3_ids": [],
            },
        }


def write_ideas_bank(path: str, bank: dict) -> None:
    """Atomically write the ideas bank via temp file + rename."""
    out_dir = os.path.dirname(os.path.abspath(path))
    os.makedirs(out_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out_dir, suffix=".tmp", prefix=".ideas_")
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


def next_idea_id(bank: dict) -> str:
    """Generate the next idea-NNN id."""
    n = len(bank["ideas"]) + 1
    return f"idea-{n:03d}"


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def extract_idea_json(response_text: str) -> dict | None:
    """Extract the JSON object from an LLM response.

    Handles markdown code fences (```json ... ```) and bare JSON.
    """
    # Try fenced blocks first
    fence_pattern = r"```(?:json)?\s*\n?(.*?)```"
    matches = re.findall(fence_pattern, response_text, re.DOTALL)
    for match in matches:
        try:
            return json.loads(match.strip())
        except json.JSONDecodeError:
            continue

    # Try the whole response as JSON
    try:
        return json.loads(response_text.strip())
    except json.JSONDecodeError:
        pass

    # Balanced-brace parser (Rule 5) — handles arbitrarily nested JSON
    # including Opus extended-thinking preambles
    start = response_text.find("{")
    while start != -1:
        depth = 0
        for i, c in enumerate(response_text[start:], start):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(response_text[start:i + 1])
                    if "title" in obj or "research_question" in obj:
                        return obj
                except json.JSONDecodeError:
                    pass
                break
        # Try next opening brace
        start = response_text.find("{", start + 1)

    return None


# ---------------------------------------------------------------------------
# Scoring — novelty
# ---------------------------------------------------------------------------

def count_subfield_bridges(idea: dict) -> int:
    """Count how many distinct subfield clusters the idea references."""
    text = " ".join([
        idea.get("title", ""),
        idea.get("research_question", ""),
        idea.get("abstract", ""),
        idea.get("novelty_claim", ""),
        idea.get("methodology", ""),
    ]).lower()

    bridges = 0
    for cluster in SUBFIELD_KEYWORDS:
        if any(kw in text for kw in cluster):
            bridges += 1
    return bridges


def score_novelty(idea: dict) -> float:
    """Heuristic novelty score in [0, 1]."""
    score = 0.3  # baseline for any coherent idea

    # Cross-domain bridges: +0.2 per bridge beyond the first, max +0.4
    bridges = count_subfield_bridges(idea)
    if bridges >= 2:
        score += min(0.2 * (bridges - 1), 0.4)

    # Novelty claim length and specificity
    claim = idea.get("novelty_claim", "")
    if len(claim) > 200:
        score += 0.5
    elif len(claim) > 100:
        score += 0.3

    # Key mechanisms count
    mechanisms = idea.get("key_mechanisms", [])
    if isinstance(mechanisms, list):
        if len(mechanisms) >= 5:
            score += 0.3
        elif len(mechanisms) >= 3:
            score += 0.2

    return min(score, 1.0)


# ---------------------------------------------------------------------------
# Scoring — feasibility
# ---------------------------------------------------------------------------

def score_feasibility(idea: dict) -> float:
    """Heuristic feasibility score in [0, 1]."""
    score = 0.2  # baseline

    text = " ".join([
        idea.get("methodology", ""),
        idea.get("feasibility_notes", ""),
        idea.get("abstract", ""),
    ]).lower()

    # Publicly available data sources
    if any(kw in text for kw in DATA_SOURCE_KEYWORDS):
        score += 0.3

    # Established techniques
    if any(kw in text for kw in ESTABLISHED_METHOD_KEYWORDS):
        score += 0.2

    # Concrete feasibility notes
    notes = idea.get("feasibility_notes", "")
    if len(notes) > 50:
        score += 0.2

    # Timeline mentioned
    timeline_words = ["year", "month", "semester", "quarter", "timeline", "phase", "stage"]
    if any(tw in text for tw in timeline_words):
        score += 0.1

    return min(score, 1.0)


# ---------------------------------------------------------------------------
# Deduplication — Jaccard on key terms
# ---------------------------------------------------------------------------

def extract_key_terms(idea: dict) -> set[str]:
    """Tokenize title + research_question + novelty_claim into a set of
    non-stopword terms (>= 3 chars, lowered)."""
    text = " ".join([
        idea.get("title", ""),
        idea.get("research_question", ""),
        idea.get("novelty_claim", ""),
    ])
    tokens = re.findall(r"[a-zA-Z]+", text.lower())
    return {t for t in tokens if len(t) >= 3 and t not in STOPWORDS}


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Jaccard index between two sets. Returns 0.0 if both empty."""
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
    """Return the idea_id of the best duplicate match, or None."""
    best_id = None
    best_sim = 0.0

    for entry in bank["ideas"]:
        existing_terms = set(entry.get("key_terms", []))
        sim = jaccard_similarity(new_terms, existing_terms)
        if sim > best_sim:
            best_sim = sim
            best_id = entry.get("idea_id")

    if best_sim >= threshold:
        return best_id
    return None


# ---------------------------------------------------------------------------
# Stats update
# ---------------------------------------------------------------------------

def update_stats(bank: dict) -> None:
    """Recompute stats from the ideas list."""
    ideas = bank["ideas"]
    total = len(ideas)
    dups = sum(1 for i in ideas if i.get("is_duplicate", False))
    unique = total - dups

    scores = [i["combined_score"] for i in ideas if "combined_score" in i]
    avg = sum(scores) / len(scores) if scores else 0.0

    # Top 3 by combined score (non-duplicate preferred, but include all)
    ranked = sorted(ideas, key=lambda i: i.get("combined_score", 0), reverse=True)
    top3 = [i["idea_id"] for i in ranked[:3]]

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
        description="Novelty/feasibility scoring and deduplication for the Ralph Loop."
    )
    p.add_argument("--result", required=True, help="Path to LLM result JSON")
    p.add_argument("--ideas-bank", required=True, help="Path to ideas-bank.json")
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

    # 3. Load ideas bank (or create empty)
    bank = read_ideas_bank(args.ideas_bank)

    # 4. Parse the idea from LLM response
    response_text = result.get("response", "")
    idea = extract_idea_json(response_text)
    idea_id = next_idea_id(bank)

    if idea is None:
        # Record a failed parse entry
        failed_entry = {
            "idea_id": idea_id,
            "source_model": result.get("model", "unknown"),
            "iteration": result.get("iteration"),
            "parse_failed": True,
            "is_duplicate": False,
            "novelty_score": 0.0,
            "feasibility_score": 0.0,
            "combined_score": 0.0,
            "key_terms": [],
            "raw_response_snippet": response_text[:300],
        }
        bank["ideas"].append(failed_entry)
        update_stats(bank)
        write_ideas_bank(args.ideas_bank, bank)

        summary = {
            "idea_id": idea_id,
            "title": None,
            "combined_score": 0.0,
            "is_duplicate": False,
            "novelty_score": 0.0,
            "feasibility_score": 0.0,
            "error": "Failed to parse idea JSON from LLM response",
        }
        print(json.dumps(summary))
        return 0  # parse failure is not a fatal error

    # 5-7. Score via LLM judge (fallback to heuristics if judge unavailable)
    judge_result = None
    try:
        from ralph_judge import judge_idea as _judge_idea
        judge_result = _judge_idea(idea)
    except Exception as e:
        print(f"WARNING: LLM judge failed ({e}), falling back to heuristics", file=sys.stderr)

    if judge_result and judge_result.get("composite") is not None:
        # LLM judge scores are already on 0-5 scale; normalize to 0-1 for
        # compatibility with combined_score consumers
        novelty = judge_result["novelty"] / 5.0
        feasibility = judge_result["feasibility"] / 5.0
        combined = judge_result["composite"] / 5.0
        combined = round(combined, 4)
    else:
        # Heuristic fallback (produces 0-1 scores)
        novelty = score_novelty(idea)
        feasibility = score_feasibility(idea)
        combined = (
            config["novelty_weight"] * novelty
            + config["feasibility_weight"] * feasibility
        )
        combined = round(combined, 4)

    # 8. Extract key terms
    key_terms = extract_key_terms(idea)

    # 9. Deduplication
    is_duplicate = False
    duplicate_of = None

    if len(key_terms) >= config["min_key_terms"]:
        dup_id = find_duplicate(key_terms, bank, config["dedup_jaccard_threshold"])
        if dup_id is not None:
            is_duplicate = True
            duplicate_of = dup_id

    # 10. Build entry
    entry = {
        "idea_id": idea_id,
        "source_model": result.get("model", "unknown"),
        "iteration": result.get("iteration"),
        "title": idea.get("title", ""),
        "research_question": idea.get("research_question", ""),
        "abstract": idea.get("abstract", ""),
        "methodology": idea.get("methodology", ""),
        "key_mechanisms": idea.get("key_mechanisms", []),
        "novelty_claim": idea.get("novelty_claim", ""),
        "key_references": idea.get("key_references", []),
        "feasibility_notes": idea.get("feasibility_notes", ""),
        "novelty_score": round(novelty, 4),
        "feasibility_score": round(feasibility, 4),
        "combined_score": combined,
        "is_duplicate": is_duplicate,
        "key_terms": sorted(key_terms),
    }
    if duplicate_of is not None:
        entry["duplicate_of"] = duplicate_of

    # Store judge metadata if LLM judge was used
    if judge_result and judge_result.get("composite") is not None:
        entry["judge_scores"] = judge_result.get("judge_scores", [])
        entry["judge_models"] = judge_result.get("judge_models", [])
        entry["low_confidence"] = judge_result.get("low_confidence", False)
        entry["scoring_method"] = "llm_judge"
    else:
        entry["scoring_method"] = "heuristic_fallback"

    # 11. Append and update
    bank["ideas"].append(entry)
    update_stats(bank)
    write_ideas_bank(args.ideas_bank, bank)

    # 12. Print summary
    summary = {
        "idea_id": idea_id,
        "title": idea.get("title", ""),
        "combined_score": combined,
        "is_duplicate": is_duplicate,
        "novelty_score": round(novelty, 4),
        "feasibility_score": round(feasibility, 4),
    }
    if duplicate_of is not None:
        summary["duplicate_of"] = duplicate_of

    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
