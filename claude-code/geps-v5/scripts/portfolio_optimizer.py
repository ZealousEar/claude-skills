from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


DIMENSIONS = {
    "method": "method_classes",
    "data": "data_classes",
    "contribution": "contribution_classes",
}

MIN_COVERAGE_KEYS = {
    "method": "min_method_coverage",
    "data": "min_data_coverage",
    "contribution": "min_contribution_coverage",
}

DEFAULT_K = 5
DEFAULT_LAMBDA_UNCERTAINTY = 0.3
DEFAULT_LAMBDA_RISK = 0.2
DEFAULT_LAMBDA_REDUNDANCY = 0.4
DEFAULT_LAMBDA_EVIDENCE = 0.1
REDUNDANCY_ALERT_THRESHOLD = 0.40

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


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI flags for portfolio optimization."""
    parser = argparse.ArgumentParser(
        description=(
            "Greedy forward selection of a diverse research-idea portfolio "
            "with taxonomy quotas and redundancy penalties."
        )
    )
    parser.add_argument("--input", required=True, help="Path to rankings JSON from bradley_terry.py")
    parser.add_argument("--taxonomy", required=True, help="Path to taxonomy.json")
    parser.add_argument("--labels", help="Optional path to taxonomy labels JSON")
    parser.add_argument("--evidence", help="Optional path to verification evidence JSON")
    parser.add_argument("-K", type=int, default=DEFAULT_K, help="Portfolio size (default: 5)")
    parser.add_argument(
        "--lambda-uncertainty",
        type=float,
        default=DEFAULT_LAMBDA_UNCERTAINTY,
        help="Uncertainty penalty weight (default: 0.3)",
    )
    parser.add_argument(
        "--lambda-risk",
        type=float,
        default=DEFAULT_LAMBDA_RISK,
        help="Risk penalty weight (default: 0.2)",
    )
    parser.add_argument(
        "--lambda-redundancy",
        type=float,
        default=DEFAULT_LAMBDA_REDUNDANCY,
        help="Redundancy penalty weight (default: 0.4)",
    )
    parser.add_argument("--output", default="-", help="Output JSON path (default: stdout)")
    parser.add_argument("--pretty", action="store_true", help="Emit indented JSON")
    parser.add_argument("--validate", action="store_true", help="Validate inputs and exit")
    parser.add_argument("--summary", action="store_true", help="Print human-readable summary")
    return parser.parse_args(argv)


def load_json(path: Path) -> object:
    """Load JSON from disk using json.loads."""
    try:
        return json.loads(path.expanduser().read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def write_json(payload: object, output: str, pretty: bool) -> None:
    """Write JSON to stdout or to a file path."""
    text = json.dumps(payload, indent=2 if pretty else None)
    if output == "-":
        sys.stdout.write(text)
        sys.stdout.write("\n")
        return
    Path(output).expanduser().write_text(text + "\n", encoding="utf-8")


def parse_float(value: object, default: float = 0.0) -> float:
    """Parse numeric value into a finite float with default fallback."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def parse_metric(value: object) -> float | None:
    """Parse metric-like values from bool/int/float/str into float or None."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if not text:
            return None
        if text in {"pass", "passed", "true", "yes", "y"}:
            return 1.0
        if text in {"fail", "failed", "false", "no", "n"}:
            return 0.0
        try:
            parsed = float(text)
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) else None
    return None


def as_list(value: object) -> list[str]:
    """Normalize a scalar/list/dict into a flat list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(as_list(item))
        return out
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(as_list(item))
        return out
    text = str(value).strip()
    return [text] if text else []


def dedupe(items: list[str]) -> list[str]:
    """Deduplicate string list while preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def collect_strings(value: object) -> list[str]:
    """Recursively collect all string leaves from nested JSON-like values."""
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(collect_strings(item))
        return out
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(collect_strings(item))
        return out
    return []


def build_idea_text(entry: dict[str, object]) -> str:
    """Build searchable text for TF-IDF from key idea fields."""
    keys = [
        "title",
        "description",
        "research_question",
        "hypothesis",
        "identification",
        "data",
        "contribution",
        "risk",
        "mvp",
        "summary",
        "abstract",
        "body",
        "text",
    ]
    parts: list[str] = []
    for key in keys:
        parts.extend(collect_strings(entry.get(key)))
    nested = entry.get("idea")
    if isinstance(nested, dict):
        parts.extend(collect_strings(nested))
    return "\n".join(parts).strip()


def extract_risk(entry: dict[str, object]) -> float:
    """Extract risk as number of mechanical gate failures where available."""
    failed = entry.get("failed_gates")
    if isinstance(failed, list):
        return float(len(failed))

    gates = entry.get("gates")
    if isinstance(gates, dict):
        failures = 0
        for outcome in gates.values():
            if isinstance(outcome, dict) and "pass" in outcome and not bool(outcome.get("pass")):
                failures += 1
        if failures > 0:
            return float(failures)

    nested = entry.get("mechanical")
    if isinstance(nested, dict) and isinstance(nested.get("failed_gates"), list):
        return float(len(nested.get("failed_gates", [])))

    if "risk" in entry:
        parsed = parse_metric(entry.get("risk"))
        if parsed is not None:
            return max(0.0, parsed)
    return 0.0


def validate_taxonomy(taxonomy: object) -> list[str]:
    """Validate required taxonomy structure and quota fields."""
    if not isinstance(taxonomy, dict):
        return ["taxonomy JSON must be an object"]

    errors: list[str] = []
    for dim in DIMENSIONS.values():
        classes = taxonomy.get(dim)
        if not isinstance(classes, dict) or not classes:
            errors.append(f"taxonomy missing required non-empty object: '{dim}'")
            continue
        for category, config in classes.items():
            if not isinstance(config, dict):
                errors.append(f"{dim}.{category} must be an object")
                continue
            keywords = config.get("keywords")
            if not isinstance(keywords, list) or not keywords:
                errors.append(f"{dim}.{category}.keywords must be a non-empty list")
            if "max_quota" in config and (
                not isinstance(config.get("max_quota"), int) or config.get("max_quota") < 0
            ):
                errors.append(f"{dim}.{category}.max_quota must be a non-negative integer")

    quotas = taxonomy.get("quotas")
    if quotas is not None and not isinstance(quotas, dict):
        errors.append("taxonomy.quotas must be an object when provided")
    elif isinstance(quotas, dict):
        for key in (
            "max_per_method_class",
            "min_method_coverage",
            "min_data_coverage",
            "min_contribution_coverage",
        ):
            if key in quotas and (not isinstance(quotas.get(key), int) or quotas.get(key) < 0):
                errors.append(f"taxonomy.quotas.{key} must be a non-negative integer")

    return errors


def normalize_rankings(payload: object) -> tuple[list[dict[str, object]], list[str]]:
    """Normalize rankings payload into candidate rows."""
    rows_raw: object
    if isinstance(payload, dict):
        rows_raw = payload.get("rankings")
    else:
        rows_raw = payload

    if not isinstance(rows_raw, list):
        return [], ["input JSON must be a list or an object containing 'rankings' list"]

    errors: list[str] = []
    rows: list[dict[str, object]] = []
    seen_ids: set[str] = set()

    for idx, item in enumerate(rows_raw, start=1):
        if not isinstance(item, dict):
            errors.append(f"rankings[{idx}] must be an object")
            continue

        idea_id = str(item.get("id", "")).strip()
        if not idea_id:
            errors.append(f"rankings[{idx}] missing non-empty 'id'")
            continue
        if idea_id in seen_ids:
            errors.append(f"Duplicate ranking id: {idea_id}")
            continue
        seen_ids.add(idea_id)

        rows.append(
            {
                "id": idea_id,
                "mu": parse_float(item.get("mu", item.get("theta", 0.0))),
                "sigma": max(0.0, parse_float(item.get("sigma", 0.0))),
                "risk": extract_risk(item),
                "text": build_idea_text(item),
                "raw": item,
            }
        )

    if not rows:
        errors.append("No valid ranking entries found")
    return rows, errors


def normalize_labels(payload: object) -> tuple[dict[str, dict[str, list[str]]], list[str]]:
    """Normalize optional taxonomy-label payload into id keyed labels."""
    rows_raw: object
    if isinstance(payload, dict) and isinstance(payload.get("labels"), list):
        rows_raw = payload.get("labels")
    else:
        rows_raw = payload

    if not isinstance(rows_raw, list):
        return {}, ["labels JSON must be a list or an object containing 'labels' list"]

    out: dict[str, dict[str, list[str]]] = {}
    errors: list[str] = []
    for idx, item in enumerate(rows_raw, start=1):
        if not isinstance(item, dict):
            errors.append(f"labels[{idx}] must be an object")
            continue

        idea_id = str(item.get("id", "")).strip()
        if not idea_id:
            errors.append(f"labels[{idx}] missing non-empty 'id'")
            continue

        out[idea_id] = {
            "method": dedupe(as_list(item.get("method"))),
            "data": dedupe(as_list(item.get("data"))),
            "contribution": dedupe(as_list(item.get("contribution"))),
        }
    return out, errors


def extract_id(record: dict[str, object]) -> str | None:
    """Extract idea id from an evidence-like record."""
    for key in ("id", "idea_id", "candidate_id"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested = record.get("idea")
    if isinstance(nested, dict):
        nested_id = nested.get("id")
        if isinstance(nested_id, str) and nested_id.strip():
            return nested_id.strip()
    return None


def extract_evidence_score(record: dict[str, object]) -> float | None:
    """Extract evidence score using common key conventions."""
    for key in ("E", "evidence_score", "score", "evidence"):
        value = record.get(key)
        if not isinstance(value, (dict, list)):
            parsed = parse_metric(value)
            if parsed is not None:
                return parsed

    components = []
    for key in (
        "e_novelty",
        "novelty_score",
        "novelty_pass",
        "e_identification",
        "identification_score",
        "identification_pass",
        "e_data",
        "data_score",
        "data_pass",
    ):
        if key in record:
            parsed = parse_metric(record.get(key))
            if parsed is not None:
                components.append(parsed)

    if components:
        return sum(components) / float(len(components))

    nested = record.get("evidence")
    if isinstance(nested, dict):
        return extract_evidence_score(nested)
    return None


def normalize_evidence(payload: object) -> tuple[dict[str, float], list[str]]:
    """Normalize optional evidence payload into id -> score map."""
    scores: dict[str, float] = {}

    if isinstance(payload, dict) and payload:
        maybe_map = True
        for key, value in payload.items():
            if not isinstance(key, str) or parse_metric(value) is None:
                maybe_map = False
                break
        if maybe_map:
            for key, value in payload.items():
                parsed = parse_metric(value)
                if parsed is not None:
                    scores[key.strip()] = parsed
            return scores, []

    stack: list[object] = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(node)
            continue
        if not isinstance(node, dict):
            continue

        idea_id = extract_id(node)
        score = extract_evidence_score(node)
        if idea_id and score is not None:
            scores[idea_id] = score

        for value in node.values():
            if isinstance(value, (list, dict)):
                stack.append(value)

    if not scores:
        return {}, ["Could not extract any evidence scores from evidence payload"]
    return scores, []


def keyword_match(text: str, lowered: str, keyword: str) -> bool:
    """Match keyword via word boundaries for short tokens, substring otherwise."""
    token = keyword.strip()
    if not token:
        return False
    if len(token) <= 3:
        return re.search(r"\b" + re.escape(token) + r"\b", text, flags=re.IGNORECASE) is not None
    return token.lower() in lowered


def classify_text(text: str, taxonomy: dict[str, object]) -> dict[str, list[str]]:
    """Classify text into method/data/contribution taxonomy labels."""
    result = {"method": [], "data": [], "contribution": []}
    lowered = text.lower()

    for dim_out, dim_tax in DIMENSIONS.items():
        classes = taxonomy.get(dim_tax)
        if not isinstance(classes, dict):
            continue
        labels: list[str] = []
        for category, config in classes.items():
            if not isinstance(category, str) or not isinstance(config, dict):
                continue
            keywords = config.get("keywords")
            if not isinstance(keywords, list):
                continue
            if any(isinstance(kw, str) and keyword_match(text, lowered, kw) for kw in keywords):
                labels.append(category)
        result[dim_out] = labels

    return result


def tokenize(text: str) -> list[str]:
    """Tokenize text into alphabetic lowercase terms excluding stopwords."""
    return [token for token in re.findall(r"[a-z]+", text.lower()) if token not in STOPWORDS]


def tfidf_vectors(docs: list[str]) -> list[dict[str, float]]:
    """Build sparse TF-IDF vectors (stdlib only)."""
    tokenized = [tokenize(doc) for doc in docs]
    n_docs = len(tokenized)

    doc_freq: Counter[str] = Counter()
    for tokens in tokenized:
        doc_freq.update(set(tokens))

    vectors: list[dict[str, float]] = []
    for tokens in tokenized:
        if not tokens:
            vectors.append({})
            continue

        counts = Counter(tokens)
        denom = float(len(tokens))
        vec: dict[str, float] = {}
        for term, count in counts.items():
            tf = count / denom
            idf = math.log(n_docs / (1 + doc_freq[term])) if n_docs else 0.0
            value = tf * idf
            if value != 0.0:
                vec[term] = value
        vectors.append(vec)

    return vectors


def cosine_sim(left: dict[str, float], right: dict[str, float]) -> float:
    """Cosine similarity between two sparse vectors."""
    if not left or not right:
        return 0.0
    shared = set(left).intersection(right)
    if not shared:
        return 0.0

    dot = sum(left[k] * right[k] for k in shared)
    norm_left = math.sqrt(sum(v * v for v in left.values()))
    norm_right = math.sqrt(sum(v * v for v in right.values()))
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    return dot / (norm_left * norm_right)


def prepare_candidates(
    rows: list[dict[str, object]],
    taxonomy: dict[str, object],
    labels_by_id: dict[str, dict[str, list[str]]],
    evidence_by_id: dict[str, float],
    lambda_uncertainty: float,
) -> list[dict[str, object]]:
    """Build scored candidate objects and attach TF-IDF vectors."""
    candidates: list[dict[str, object]] = []
    for row in rows:
        idea_id = str(row["id"])
        labels = labels_by_id.get(idea_id)
        if labels is None:
            labels = classify_text(str(row.get("text", "")), taxonomy)

        base_score = parse_float(row.get("mu"), 0.0) - lambda_uncertainty * parse_float(
            row.get("sigma"), 0.0
        )
        if idea_id in evidence_by_id:
            base_score += DEFAULT_LAMBDA_EVIDENCE * evidence_by_id[idea_id]

        candidates.append(
            {
                "id": idea_id,
                "mu": parse_float(row.get("mu"), 0.0),
                "sigma": parse_float(row.get("sigma"), 0.0),
                "risk": max(0.0, parse_float(row.get("risk"), 0.0)),
                "text": str(row.get("text", "")),
                "method": dedupe(as_list(labels.get("method"))),
                "data": dedupe(as_list(labels.get("data"))),
                "contribution": dedupe(as_list(labels.get("contribution"))),
                "base_score": base_score,
                "vector": {},
            }
        )

    vectors = tfidf_vectors([str(c["text"]) for c in candidates])
    for candidate, vector in zip(candidates, vectors):
        candidate["vector"] = vector

    candidates.sort(key=lambda x: str(x["id"]))
    return candidates


def resolve_method_quotas(taxonomy: dict[str, object]) -> tuple[int | None, dict[str, int]]:
    """Resolve global and per-method quota values from taxonomy."""
    global_quota: int | None = None
    quotas = taxonomy.get("quotas")
    if isinstance(quotas, dict) and isinstance(quotas.get("max_per_method_class"), int):
        q = quotas.get("max_per_method_class")
        if q is not None and q >= 0:
            global_quota = q

    per_method: dict[str, int] = {}
    classes = taxonomy.get("method_classes")
    if isinstance(classes, dict):
        for method, config in classes.items():
            if not isinstance(method, str) or not isinstance(config, dict):
                continue
            q = config.get("max_quota")
            if isinstance(q, int) and q >= 0:
                per_method[method] = q

    return global_quota, per_method


def redundancy(
    candidate: dict[str, object], selected: list[dict[str, object]]
) -> tuple[float, float, float, str | None]:
    """Compute max cosine redundancy + taxonomy overlap penalty."""
    if not selected:
        return 0.0, 0.0, 0.0, None

    cand_method = set(as_list(candidate.get("method")))
    cand_vec = candidate.get("vector") if isinstance(candidate.get("vector"), dict) else {}

    max_sim = 0.0
    nearest: str | None = None
    overlap_count = 0

    for chosen in selected:
        chosen_vec = chosen.get("vector") if isinstance(chosen.get("vector"), dict) else {}
        sim = cosine_sim(cand_vec, chosen_vec)
        if sim > max_sim:
            max_sim = sim
            nearest = str(chosen.get("id"))

        chosen_method = set(as_list(chosen.get("method")))
        if cand_method and chosen_method and cand_method.intersection(chosen_method):
            overlap_count += 1

    tax_penalty = 0.1 * float(overlap_count)
    return max_sim, tax_penalty, max_sim + tax_penalty, nearest


def quota_reason(
    candidate: dict[str, object],
    method_counts: dict[str, int],
    global_quota: int | None,
    per_method: dict[str, int],
) -> str | None:
    """Return exclusion reason if adding candidate would exceed a method quota."""
    for method in as_list(candidate.get("method")):
        quota = per_method.get(method, global_quota)
        current = int(method_counts.get(method, 0))
        if quota is not None and current + 1 > quota:
            return f"Excluded: would exceed {method} quota ({current}/{quota} already selected)"
    return None


def greedy_select(
    candidates: list[dict[str, object]],
    k: int,
    lambda_risk: float,
    lambda_redundancy: float,
    global_quota: int | None,
    per_method: dict[str, int],
) -> tuple[list[dict[str, object]], dict[str, str]]:
    """Run greedy forward selection with quota filtering."""
    selected: list[dict[str, object]] = []
    selected_ids: set[str] = set()
    method_counts: dict[str, int] = defaultdict(int)
    quota_log: dict[str, str] = {}

    target = min(k, len(candidates))
    for _ in range(target):
        best: dict[str, object] | None = None

        for candidate in candidates:
            idea_id = str(candidate["id"])
            if idea_id in selected_ids:
                continue

            reason = quota_reason(candidate, method_counts, global_quota, per_method)
            if reason is not None:
                quota_log.setdefault(idea_id, reason)
                continue

            max_sim, tax_penalty, red_total, nearest = redundancy(candidate, selected)
            gain = (
                parse_float(candidate.get("base_score"), 0.0)
                - lambda_redundancy * red_total
                - lambda_risk * parse_float(candidate.get("risk"), 0.0)
            )

            current = {
                "candidate": candidate,
                "gain": gain,
                "max_similarity": max_sim,
                "taxonomy_penalty": tax_penalty,
                "redundancy": red_total,
                "nearest": nearest,
            }

            if best is None:
                best = current
                continue

            best_gain = parse_float(best.get("gain"), -1e12)
            if gain > best_gain + 1e-12:
                best = current
                continue
            if abs(gain - best_gain) <= 1e-12:
                base = parse_float(candidate.get("base_score"), 0.0)
                best_base = parse_float(best["candidate"].get("base_score"), 0.0)
                if base > best_base + 1e-12:
                    best = current
                    continue
                if abs(base - best_base) <= 1e-12 and idea_id < str(best["candidate"]["id"]):
                    best = current

        if best is None:
            break

        chosen = dict(best["candidate"])
        chosen["score"] = parse_float(best.get("gain"), 0.0)
        chosen["max_similarity"] = parse_float(best.get("max_similarity"), 0.0)
        chosen["taxonomy_overlap_penalty"] = parse_float(best.get("taxonomy_penalty"), 0.0)
        chosen["redundancy"] = parse_float(best.get("redundancy"), 0.0)
        chosen["nearest_selected"] = best.get("nearest")

        selected.append(chosen)
        selected_ids.add(str(chosen["id"]))
        for method in as_list(chosen.get("method")):
            method_counts[method] = int(method_counts.get(method, 0)) + 1

    return selected, quota_log


def build_exclusion_log(
    candidates: list[dict[str, object]],
    selected: list[dict[str, object]],
    quota_log: dict[str, str],
    lambda_risk: float,
    lambda_redundancy: float,
) -> list[dict[str, str]]:
    """Build exclusion reasons for top non-selected candidates."""
    selected_ids = {str(item["id"]) for item in selected}
    unselected = [c for c in candidates if str(c["id"]) not in selected_ids]
    unselected.sort(key=lambda c: (-parse_float(c.get("base_score"), 0.0), str(c["id"])))

    cutoff = min((parse_float(item.get("score"), 0.0) for item in selected), default=0.0)

    entries: list[dict[str, str]] = []
    added: set[str] = set()

    for item in unselected:
        idea_id = str(item["id"])
        if idea_id in quota_log:
            entries.append({"id": idea_id, "reason": quota_log[idea_id]})
            added.add(idea_id)

    limit = max(10, len(selected) + 2)
    for item in unselected:
        if len(entries) >= limit:
            break

        idea_id = str(item["id"])
        if idea_id in added:
            continue

        max_sim, _, red_total, nearest = redundancy(item, selected)
        gain = (
            parse_float(item.get("base_score"), 0.0)
            - lambda_redundancy * red_total
            - lambda_risk * parse_float(item.get("risk"), 0.0)
        )
        if max_sim > REDUNDANCY_ALERT_THRESHOLD and nearest is not None:
            reason = (
                f"Excluded: redundancy {max_sim:.2f} with {nearest} "
                f"(above {REDUNDANCY_ALERT_THRESHOLD:.2f} threshold)"
            )
        else:
            reason = f"Excluded: marginal gain {gain:.2f} below selected cutoff {cutoff:.2f}"

        entries.append({"id": idea_id, "reason": reason})
        added.add(idea_id)

    return entries


def coverage_check(selected: list[dict[str, object]], taxonomy: dict[str, object]) -> dict[str, object]:
    """Compute coverage counts against taxonomy minimum coverage quotas."""
    quotas = taxonomy.get("quotas") if isinstance(taxonomy.get("quotas"), dict) else {}

    allowed: dict[str, set[str]] = {}
    for dim_out, dim_tax in DIMENSIONS.items():
        classes = taxonomy.get(dim_tax)
        allowed[dim_out] = set(classes.keys()) if isinstance(classes, dict) else set()

    covered = {"method": set(), "data": set(), "contribution": set()}
    for item in selected:
        for dim in ("method", "data", "contribution"):
            labels = as_list(item.get(dim))
            if allowed[dim]:
                labels = [label for label in labels if label in allowed[dim]]
            covered[dim].update(labels)

    method_min = int(quotas.get("min_method_coverage", 0)) if isinstance(quotas.get("min_method_coverage"), int) else 0
    data_min = int(quotas.get("min_data_coverage", 0)) if isinstance(quotas.get("min_data_coverage"), int) else 0
    contribution_min = (
        int(quotas.get("min_contribution_coverage", 0))
        if isinstance(quotas.get("min_contribution_coverage"), int)
        else 0
    )

    passes = (
        len(covered["method"]) >= method_min
        and len(covered["data"]) >= data_min
        and len(covered["contribution"]) >= contribution_min
    )

    return {
        "method_coverage": len(covered["method"]),
        "data_coverage": len(covered["data"]),
        "contribution_coverage": len(covered["contribution"]),
        "method_min": method_min,
        "data_min": data_min,
        "contribution_min": contribution_min,
        "passes": passes,
    }


def item_out(item: dict[str, object]) -> dict[str, object]:
    """Serialize selected candidate to output shape."""
    return {
        "id": str(item["id"]),
        "score": round(parse_float(item.get("score"), 0.0), 6),
        "method": as_list(item.get("method")),
        "data": as_list(item.get("data")),
        "contribution": as_list(item.get("contribution")),
    }


def top_reason(item: dict[str, object]) -> str:
    """Construct rationale text for top-1 bet."""
    mu = parse_float(item.get("mu"), 0.0)
    sigma = parse_float(item.get("sigma"), 0.0)
    risk = parse_float(item.get("risk"), 0.0)
    redundancy_score = parse_float(item.get("redundancy"), 0.0)
    return (
        "Highest marginal gain after uncertainty/risk penalties "
        f"(mu={mu:.2f}, sigma={sigma:.2f}, risk={risk:.1f}, redundancy={redundancy_score:.2f})"
    )


def build_result(
    selected: list[dict[str, object]],
    exclusion_log: list[dict[str, str]],
    coverage: dict[str, object],
    args: argparse.Namespace,
    total_candidates: int,
) -> dict[str, object]:
    """Assemble final output JSON."""
    if selected:
        top_1 = {
            "id": str(selected[0]["id"]),
            "score": round(parse_float(selected[0].get("score"), 0.0), 6),
            "reason": top_reason(selected[0]),
        }
    else:
        top_1 = {"id": "", "score": 0.0, "reason": "No feasible candidate selected"}

    return {
        "metadata": {
            "K": args.K,
            "lambda_uncertainty": args.lambda_uncertainty,
            "lambda_risk": args.lambda_risk,
            "lambda_redundancy": args.lambda_redundancy,
            "total_candidates": total_candidates,
        },
        "portfolio": {
            "top_1_bet": top_1,
            "top_3_variants": [item_out(item) for item in selected[:3]],
            "top_5_diversified": [item_out(item) for item in selected[:5]],
        },
        "exclusion_log": exclusion_log,
        "coverage_check": coverage,
    }


def format_summary(result: dict[str, object]) -> str:
    """Render human-readable summary."""
    portfolio = result.get("portfolio") if isinstance(result, dict) else {}
    portfolio = portfolio if isinstance(portfolio, dict) else {}

    top_1 = portfolio.get("top_1_bet") if isinstance(portfolio.get("top_1_bet"), dict) else {}
    top_3 = portfolio.get("top_3_variants") if isinstance(portfolio.get("top_3_variants"), list) else []
    top_5 = (
        portfolio.get("top_5_diversified")
        if isinstance(portfolio.get("top_5_diversified"), list)
        else []
    )

    coverage = result.get("coverage_check") if isinstance(result.get("coverage_check"), dict) else {}
    exclusion = result.get("exclusion_log") if isinstance(result.get("exclusion_log"), list) else []

    lines = [
        "Portfolio Optimization Summary",
        "=" * 60,
        "Top-1 Dissertation Bet",
        f"- id: {top_1.get('id', '')}",
        f"- score: {parse_float(top_1.get('score'), 0.0):.4f}",
        f"- rationale: {top_1.get('reason', '')}",
        "",
        "Top-3 Variants",
        "rank | id | score | method | data",
    ]

    for idx, item in enumerate(top_3, start=1):
        if not isinstance(item, dict):
            continue
        method = ",".join(as_list(item.get("method"))) or "-"
        data = ",".join(as_list(item.get("data"))) or "-"
        lines.append(f"{idx:>4} | {item.get('id', '')} | {parse_float(item.get('score'), 0.0):.4f} | {method} | {data}")

    lines.extend(["", "Top-5 Diversified", "rank | id | score | method | data"])
    for idx, item in enumerate(top_5, start=1):
        if not isinstance(item, dict):
            continue
        method = ",".join(as_list(item.get("method"))) or "-"
        data = ",".join(as_list(item.get("data"))) or "-"
        lines.append(f"{idx:>4} | {item.get('id', '')} | {parse_float(item.get('score'), 0.0):.4f} | {method} | {data}")

    lines.extend(
        [
            "",
            "Coverage Check",
            f"- method: {coverage.get('method_coverage', 0)} / min {coverage.get('method_min', 0)}",
            f"- data: {coverage.get('data_coverage', 0)} / min {coverage.get('data_min', 0)}",
            f"- contribution: {coverage.get('contribution_coverage', 0)} / min {coverage.get('contribution_min', 0)}",
            f"- passes: {bool(coverage.get('passes', False))}",
            "",
            "Exclusion Reasons (Top Candidates)",
        ]
    )

    for item in exclusion[:10]:
        if isinstance(item, dict):
            lines.append(f"- {item.get('id', '')}: {item.get('reason', '')}")

    return "\n".join(lines)


def build_validation(errors: list[str], rows: int, labels: int, evidence: int) -> dict[str, object]:
    """Build dry-run payload for --validate mode."""
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "metadata": {
            "rankings_count": rows,
            "labels_count": labels,
            "evidence_count": evidence,
        },
    }


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint."""
    args = parse_args(sys.argv[1:] if argv is None else argv)

    try:
        rankings_payload = load_json(Path(args.input))
        taxonomy_payload = load_json(Path(args.taxonomy))
        labels_payload = load_json(Path(args.labels)) if args.labels else None
        evidence_payload = load_json(Path(args.evidence)) if args.evidence else None
    except ValueError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        raise SystemExit(1)

    errors: list[str] = []

    rankings, ranking_errors = normalize_rankings(rankings_payload)
    errors.extend(ranking_errors)

    taxonomy_errors = validate_taxonomy(taxonomy_payload)
    errors.extend(taxonomy_errors)
    taxonomy = taxonomy_payload if isinstance(taxonomy_payload, dict) else {}

    labels_by_id: dict[str, dict[str, list[str]]] = {}
    if labels_payload is not None:
        labels_by_id, label_errors = normalize_labels(labels_payload)
        errors.extend(label_errors)

    evidence_by_id: dict[str, float] = {}
    if evidence_payload is not None:
        evidence_by_id, evidence_errors = normalize_evidence(evidence_payload)
        if not evidence_by_id:
            for warning in evidence_errors:
                sys.stderr.write(f"Warning: {warning}\n")

    if args.K < 1:
        errors.append("-K must be >= 1")
    if args.lambda_uncertainty < 0:
        errors.append("--lambda-uncertainty must be >= 0")
    if args.lambda_risk < 0:
        errors.append("--lambda-risk must be >= 0")
    if args.lambda_redundancy < 0:
        errors.append("--lambda-redundancy must be >= 0")

    validation_payload = build_validation(errors, len(rankings), len(labels_by_id), len(evidence_by_id))
    if args.validate:
        write_json(validation_payload, args.output, args.pretty)
        if args.summary:
            state = "OK" if validation_payload["valid"] else "FAILED"
            sys.stderr.write(
                f"Validation {state}: rankings={len(rankings)}, labels={len(labels_by_id)}, evidence={len(evidence_by_id)}\n"
            )
        if errors:
            raise SystemExit(1)
        return

    if errors:
        sys.stderr.write(f"Validation failed ({len(errors)} errors):\n")
        for error in errors:
            sys.stderr.write(f"  - {error}\n")
        raise SystemExit(1)

    candidates = prepare_candidates(
        rows=rankings,
        taxonomy=taxonomy,
        labels_by_id=labels_by_id,
        evidence_by_id=evidence_by_id,
        lambda_uncertainty=args.lambda_uncertainty,
    )

    global_quota, per_method = resolve_method_quotas(taxonomy)
    selected, quota_log = greedy_select(
        candidates=candidates,
        k=args.K,
        lambda_risk=args.lambda_risk,
        lambda_redundancy=args.lambda_redundancy,
        global_quota=global_quota,
        per_method=per_method,
    )

    exclusion_log = build_exclusion_log(
        candidates=candidates,
        selected=selected,
        quota_log=quota_log,
        lambda_risk=args.lambda_risk,
        lambda_redundancy=args.lambda_redundancy,
    )

    coverage = coverage_check(selected, taxonomy)
    if not bool(coverage.get("passes", False)):
        sys.stderr.write("Warning: selected portfolio does not meet one or more minimum coverage quotas\n")

    result = build_result(
        selected=selected,
        exclusion_log=exclusion_log,
        coverage=coverage,
        args=args,
        total_candidates=len(candidates),
    )

    write_json(result, args.output, args.pretty)
    if args.summary:
        sys.stderr.write(format_summary(result))
        sys.stderr.write("\n")


if __name__ == "__main__":
    main()
