from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path


DEFAULT_COMPLEXITY_THRESHOLD = 8
DEFAULT_NOVELTY_THRESHOLD = 0.90

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "he",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "that",
    "the",
    "to",
    "was",
    "were",
    "will",
    "with",
}

IDENTIFIABILITY_KEYWORDS = [
    "IV",
    "instrumental variable",
    "diff-in-diff",
    "difference-in-differences",
    "regression discontinuity",
    "RDD",
    "structural model",
    "calibration",
    "GMM",
    "maximum likelihood",
    "Bayesian estimation",
    "natural experiment",
    "quasi-experimental",
    "event study",
    "propensity score",
]

ETHICS_RED_FLAGS = [
    "insider trading",
    "front-running",
    "market manipulation",
    "PII",
    "personally identifiable",
    "scrape private",
    "GDPR violation",
]


def _as_list(value: object) -> list[str]:
    """Normalize a scalar/list value into a list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, dict):
                candidate = item.get("name")
                if candidate is not None:
                    out.append(str(candidate))
                else:
                    out.append(str(item))
            else:
                out.append(str(item))
        return out
    return [str(value)]


def get_idea_text(idea: dict[str, object]) -> str:
    """Concatenate key text fields from a normalized idea."""
    data = idea.get("data")
    data_sources: list[str] = []
    if isinstance(data, dict):
        data_sources = _as_list(data.get("sources"))
    parts = [
        *[_x for _x in _as_list(idea.get("title")) if _x],
        *[_x for _x in _as_list(idea.get("research_question")) if _x],
        *[_x for _x in _as_list(idea.get("hypothesis")) if _x],
        *[_x for _x in _as_list(idea.get("identification")) if _x],
        *[_x for _x in data_sources if _x],
        *[_x for _x in _as_list(idea.get("contribution")) if _x],
        *[_x for _x in _as_list(idea.get("risk")) if _x],
        *[_x for _x in _as_list(idea.get("mvp")) if _x],
        *[_x for _x in _as_list(idea.get("body")) if _x],
    ]
    return " ".join(parts).strip()


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    """Build a case-insensitive regex allowing spaces/hyphens between terms."""
    pieces = [re.escape(p) for p in re.split(r"[\s-]+", keyword.lower()) if p]
    pattern = r"\b" + r"[-\s]+".join(pieces) + r"\b"
    return re.compile(pattern, re.IGNORECASE)


def _is_truthy_flag(value: object) -> bool:
    """Interpret booleans and common string/int representations of true."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _is_named_source(source: str) -> bool:
    """Heuristic check for recognizable named datasets."""
    cleaned = re.sub(r"\s+", " ", source.strip().lower())
    if not cleaned:
        return False
    generic = {
        "various",
        "tbd",
        "unknown",
        "n/a",
        "na",
        "none",
        "dataset",
        "data",
        "multiple sources",
        "various sources",
        "public data",
        "private data",
        "to be determined",
    }
    if cleaned in generic:
        return False
    if re.fullmatch(r"(various|tbd|unknown|n/?a|none|misc(?:ellaneous)?)", cleaned):
        return False
    return bool(re.search(r"[a-z]{3,}", cleaned))


def gate_data(idea: dict[str, object]) -> dict[str, object]:
    """Data gate: verify sources and access clarity."""
    data = idea.get("data")
    if not isinstance(data, dict):
        return {"pass": False, "reason": "Missing 'data' object"}
    sources = _as_list(data.get("sources"))
    if not sources:
        return {"pass": False, "reason": "data.sources is empty"}
    access = str(data.get("access", "")).strip().lower()
    if not access or access == "unknown":
        return {"pass": False, "reason": "data.access is unknown"}
    named_sources = [s for s in sources if _is_named_source(s)]
    if not named_sources:
        return {"pass": False, "reason": "No recognizable named dataset in data.sources"}
    return {
        "pass": True,
        "reason": f"{len(named_sources)} named source(s) with known access",
    }


def gate_complexity(
    idea: dict[str, object], idea_text: str, threshold: int
) -> dict[str, object]:
    """Complexity gate based on deterministic additive points."""
    lowered = idea_text.lower()
    compute = idea.get("compute_requirements")
    compute_map = compute if isinstance(compute, dict) else {}
    data = idea.get("data")
    data_map = data if isinstance(data, dict) else {}
    triggers: list[tuple[str, int]] = []

    def has_any(patterns: list[str]) -> bool:
        return any(re.search(p, lowered, re.IGNORECASE) for p in patterns)

    if _is_truthy_flag(compute_map.get("gpu")) or has_any([r"\bgpu\b", r"\bcuda\b"]):
        triggers.append(("GPU", 3))
    cost = str(data_map.get("cost", "")).strip().lower()
    if cost in {"high", "medium"} or has_any([r"\bproprietary\b", r"\blicensed\b", r"\bsubscription\b"]):
        triggers.append(("proprietary_data", 3))
    if has_any([r"manual label", r"\bannotation\b", r"hand[-\s]?coded", r"human[-\s]?labeled"]):
        triggers.append(("manual_labeling", 3))
    if has_any([r"\bscrape\b", r"\bscraping\b", r"\bcrawl\b", r"web crawl"]):
        triggers.append(("web_scraping", 2))
    if _is_truthy_flag(compute_map.get("hpc")) or has_any([r"\bhpc\b", r"\bcluster\b", r"\bdistributed\b"]):
        triggers.append(("HPC", 3))
    if has_any([r"construct dataset", r"build dataset", r"create dataset", r"collect data"]):
        triggers.append(("novel_data_construction", 2))
    if len(re.findall(r"\bapi\b", lowered, re.IGNORECASE)) >= 2:
        triggers.append(("multiple_apis", 1))
    if has_any([r"\bcollaboration\b", r"partner institution", r"cross[-\s]?institutional"]):
        triggers.append(("cross_institutional", 2))

    total = sum(points for _, points in triggers)
    breakdown = " + ".join(f"{name}:{points}" for name, points in triggers) if triggers else "none"
    passed = total <= threshold
    comp = "<=" if passed else ">"
    return {
        "pass": passed,
        "reason": f"{total} points ({breakdown}) {comp} threshold {threshold}",
    }


def gate_identifiability(idea_text: str) -> dict[str, object]:
    """Identifiability gate: check for recognized identification strategy keywords."""
    matches: list[str] = []
    for keyword in IDENTIFIABILITY_KEYWORDS:
        if _keyword_pattern(keyword).search(idea_text):
            matches.append(keyword)
    if matches:
        display = ", ".join(f"'{m}'" for m in matches)
        return {"pass": True, "reason": f"Found: {display}"}
    return {"pass": False, "reason": "No identification strategy keywords found"}


def _tokenize(text: str) -> list[str]:
    """Tokenize to lowercase alphabetic terms and remove stopwords."""
    return [tok for tok in re.findall(r"[a-z]+", text.lower()) if tok not in STOPWORDS]


def tfidf_vectors(docs: list[str]) -> tuple[list[dict[str, float]], list[str]]:
    """Compute TF-IDF vectors from raw documents using stdlib-only math."""
    tokenized = [_tokenize(doc) for doc in docs]
    total_docs = len(tokenized)
    doc_freq: Counter[str] = Counter()
    for tokens in tokenized:
        doc_freq.update(set(tokens))

    vectors: list[dict[str, float]] = []
    vocab_set: set[str] = set()
    for tokens in tokenized:
        if not tokens:
            vectors.append({})
            continue
        counts = Counter(tokens)
        denom = float(len(tokens))
        vec: dict[str, float] = {}
        for term, count in counts.items():
            tf = count / denom
            idf = math.log(total_docs / (1 + doc_freq[term])) if total_docs else 0.0
            value = tf * idf
            if value != 0.0:
                vec[term] = value
                vocab_set.add(term)
        vectors.append(vec)
    return vectors, sorted(vocab_set)


def cosine_sim(v1: dict[str, float], v2: dict[str, float]) -> float:
    """Cosine similarity between sparse vectors."""
    if not v1 or not v2:
        return 0.0
    shared = set(v1).intersection(v2)
    dot = sum(v1[k] * v2[k] for k in shared)
    norm1 = math.sqrt(sum(x * x for x in v1.values()))
    norm2 = math.sqrt(sum(x * x for x in v2.values()))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (norm1 * norm2)


def gate_novelty(
    idea_text: str, existing_ideas: list[dict[str, str]], threshold: float
) -> dict[str, object]:
    """Novelty gate using TF-IDF cosine similarity against existing ideas."""
    if not existing_ideas:
        return {"pass": True, "reason": "No existing ideas provided for comparison"}

    docs = [idea_text] + [item.get("text", "") for item in existing_ideas]
    vectors, _ = tfidf_vectors(docs)
    current = vectors[0]
    best_id = "N/A"
    best_score = 0.0
    for idx, existing in enumerate(existing_ideas, start=1):
        score = cosine_sim(current, vectors[idx])
        if score > best_score:
            best_score = score
            best_id = existing.get("id", f"existing-{idx}")
    passed = best_score <= threshold
    comp = "<=" if passed else ">"
    return {
        "pass": passed,
        "reason": f"Max similarity {best_score:.2f} to {best_id} ({comp} {threshold:.2f})",
    }


def gate_ethics(idea_text: str) -> dict[str, object]:
    """Ethics gate: fail on explicit red-flag terms."""
    matches = [kw for kw in ETHICS_RED_FLAGS if _keyword_pattern(kw).search(idea_text)]
    if matches:
        display = ", ".join(f"'{m}'" for m in matches)
        return {"pass": False, "reason": f"Found red flags: {display}"}
    return {"pass": True, "reason": "No red flags found"}


def _load_json(path: Path) -> object:
    """Load and parse JSON from a file path."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"File not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from None


def _normalize_ideas(payload: object) -> list[dict[str, object]]:
    """Normalize input payload into a list of idea dictionaries."""
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
        return payload
    raise ValueError("Input JSON must be an object or an array of objects")


def _normalize_existing(payload: object) -> list[dict[str, str]]:
    """Normalize existing ideas payload into id/text pairs."""
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise ValueError("--existing-ideas must be a JSON array")
    normalized: list[dict[str, str]] = []
    for idx, item in enumerate(payload):
        if isinstance(item, dict):
            idea_id = str(item.get("id", f"existing-{idx + 1}"))
            text = str(item.get("text") or get_idea_text(item))
        else:
            idea_id = f"existing-{idx + 1}"
            text = str(item)
        normalized.append({"id": idea_id, "text": text})
    return normalized


def _load_config(path: Path | None) -> dict[str, object]:
    """Load optional configuration file."""
    if path is None:
        return {}
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ValueError("--config must be a JSON object")
    return payload


def _resolve_thresholds(
    args: argparse.Namespace, config: dict[str, object]
) -> tuple[int, float]:
    """Resolve thresholds from CLI overrides, config, and defaults."""
    cfg = config.get("mechanical_gates")
    cfg_map = cfg if isinstance(cfg, dict) else config
    if args.complexity_threshold is not None:
        complexity = args.complexity_threshold
    else:
        complexity = int(cfg_map.get("complexity_threshold", DEFAULT_COMPLEXITY_THRESHOLD))
    if args.novelty_threshold is not None:
        novelty = args.novelty_threshold
    else:
        novelty = float(cfg_map.get("novelty_threshold", DEFAULT_NOVELTY_THRESHOLD))
    return complexity, novelty


def run_gates(
    ideas: list[dict[str, object]],
    existing_ideas: list[dict[str, str]],
    complexity_threshold: int,
    novelty_threshold: float,
) -> list[dict[str, object]]:
    """Run all mechanical gates across normalized ideas."""
    results: list[dict[str, object]] = []
    for idx, idea in enumerate(ideas, start=1):
        idea_id = str(idea.get("id", f"IDEA-{idx:03d}"))
        idea_text = get_idea_text(idea)
        gates = {
            "data": gate_data(idea),
            "complexity": gate_complexity(idea, idea_text, complexity_threshold),
            "identifiability": gate_identifiability(idea_text),
            "novelty": gate_novelty(idea_text, existing_ideas, novelty_threshold),
            "ethics": gate_ethics(idea_text),
        }
        failed = [name for name, outcome in gates.items() if not bool(outcome["pass"])]
        results.append(
            {
                "id": idea_id,
                "gates": gates,
                "overall_pass": not failed,
                "failed_gates": failed,
            }
        )
    return results


def _build_summary(results: list[dict[str, object]]) -> str:
    """Build a human-readable summary for gate outcomes."""
    gate_names = ["data", "complexity", "identifiability", "novelty", "ethics"]
    total = len(results)
    passed = sum(1 for r in results if bool(r.get("overall_pass")))
    lines = [
        f"Ideas evaluated: {total}",
        f"Overall survivors: {passed}/{total} ({(100.0 * passed / total) if total else 0.0:.1f}%)",
    ]
    for gate in gate_names:
        gate_pass = 0
        gate_fail = 0
        for result in results:
            gate_map = result.get("gates")
            if isinstance(gate_map, dict) and isinstance(gate_map.get(gate), dict):
                if bool(gate_map[gate].get("pass")):
                    gate_pass += 1
                else:
                    gate_fail += 1
        lines.append(f"{gate}: pass={gate_pass}, fail={gate_fail}")
    return "\n".join(lines)


def _write_output(payload: object, output_path: Path | None, pretty: bool) -> None:
    """Write JSON payload to stdout or file."""
    text = json.dumps(payload, indent=2 if pretty else None)
    if output_path is None:
        sys.stdout.write(text + "\n")
        return
    output_path.write_text(text + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Run deterministic mechanical gates on ideas.")
    parser.add_argument("--input", required=True, help="Path to input JSON file")
    parser.add_argument("--existing-ideas", help="Path to existing ideas JSON file")
    parser.add_argument("--output", help="Path to output JSON file (default: stdout)")
    parser.add_argument("--config", help="Path to optional config JSON file")
    parser.add_argument(
        "--complexity-threshold",
        type=int,
        default=None,
        help=f"Complexity gate threshold override (default: {DEFAULT_COMPLEXITY_THRESHOLD})",
    )
    parser.add_argument(
        "--novelty-threshold",
        type=float,
        default=None,
        help=f"Novelty gate threshold override (default: {DEFAULT_NOVELTY_THRESHOLD})",
    )
    parser.add_argument("--pretty", action="store_true", help="Emit indented JSON output")
    parser.add_argument("--validate", action="store_true", help="Validate inputs without running gates")
    parser.add_argument("--summary", action="store_true", help="Print human-readable summary")
    return parser.parse_args()


def main() -> None:
    """CLI entrypoint."""
    args = parse_args()
    try:
        input_payload = _load_json(Path(args.input))
        ideas = _normalize_ideas(input_payload)
        existing_payload = _load_json(Path(args.existing_ideas)) if args.existing_ideas else None
        existing_ideas = _normalize_existing(existing_payload)
        config = _load_config(Path(args.config) if args.config else None)
        complexity_threshold, novelty_threshold = _resolve_thresholds(args, config)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    if args.validate:
        validation_payload = {
            "valid": True,
            "idea_count": len(ideas),
            "existing_ideas_count": len(existing_ideas),
        }
        _write_output(validation_payload, Path(args.output) if args.output else None, args.pretty)
        if args.summary:
            print(
                f"Validation OK: {len(ideas)} idea(s), {len(existing_ideas)} existing idea(s)",
                file=sys.stderr,
            )
        return

    results = run_gates(ideas, existing_ideas, complexity_threshold, novelty_threshold)
    _write_output(results, Path(args.output) if args.output else None, args.pretty)
    if args.summary:
        print(_build_summary(results), file=sys.stderr)


if __name__ == "__main__":
    main()
