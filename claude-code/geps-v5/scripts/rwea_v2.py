from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path


ID_CANDIDATE_KEYS = (
    "id",
    "idea_id",
    "ideaId",
    "candidate_id",
    "proposal_id",
)

TEXT_FIELD_KEYS = (
    "text",
    "title",
    "research_question",
    "hypothesis",
    "identification",
    "data",
    "contribution",
    "body",
    "summary",
    "description",
    "abstract",
    "risk",
    "mvp",
)

TAXONOMY_KEYS = (
    "method",
    "data",
    "contribution",
    "taxonomy",
    "labels",
    "tags",
    "themes",
    "classes",
    "method_labels",
    "data_labels",
    "contribution_labels",
)

UNKNOWN_MARKERS = {"", "unknown", "n/a", "na", "tbd", "none"}


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command-line arguments for RWEA v2 scoring."""
    parser = argparse.ArgumentParser(
        description=(
            "Compute RWEA v2 combined scores from BT rankings, evidence, "
            "risk, and optional portfolio redundancy."
        )
    )
    parser.add_argument("--rankings", type=Path, required=True, help="Path to BT rankings JSON")
    parser.add_argument("--evidence", type=Path, help="Path to evidence JSON")
    parser.add_argument("--portfolio", type=Path, help="Path to portfolio state JSON")
    parser.add_argument("--ideas", type=Path, help="Path to full ideas JSON for redundancy")
    parser.add_argument(
        "--lambda-uncertainty",
        dest="lambda_uncertainty",
        type=float,
        default=0.3,
        help="Penalty coefficient for BT uncertainty sigma",
    )
    parser.add_argument(
        "--lambda-evidence",
        dest="lambda_evidence",
        type=float,
        default=0.1,
        help="Bonus coefficient for evidence score",
    )
    parser.add_argument(
        "--lambda-risk",
        dest="lambda_risk",
        type=float,
        default=0.2,
        help="Penalty coefficient for risk score",
    )
    parser.add_argument(
        "--lambda-redundancy",
        dest="lambda_redundancy",
        type=float,
        default=0.4,
        help="Penalty coefficient for redundancy against current portfolio",
    )
    parser.add_argument("--output", default="-", help="Output file path (default: stdout)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument("--validate", action="store_true", help="Validate inputs and exit")
    parser.add_argument("--summary", action="store_true", help="Print a human-readable summary to stderr")
    return parser.parse_args(argv)


def read_json(path: Path) -> object:
    """Read JSON payload from disk."""
    target = path.expanduser()
    if not target.exists():
        raise FileNotFoundError(f"File not found: {target}")
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {target}: {exc}") from exc


def write_output(payload: object, pretty: bool, output_path: str) -> None:
    """Write JSON payload to file or stdout."""
    text = json.dumps(payload, indent=2 if pretty else None, sort_keys=False)
    if output_path == "-":
        sys.stdout.write(text + "\n")
        return
    out = Path(output_path).expanduser()
    out.write_text(text + "\n", encoding="utf-8")


def as_float(value: object, default: float = 0.0) -> float:
    """Convert value to finite float, returning default on failure."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(result):
        return default
    return result


def as_int(value: object, default: int = 0) -> int:
    """Convert value to integer, returning default on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def norm_string(value: object) -> str:
    """Normalize values to lowercase stripped string."""
    if value is None:
        return ""
    return str(value).strip().lower()


def extract_id(entry: dict[str, object], fallback: str = "") -> str:
    """Extract idea identifier from common key variants."""
    for key in ID_CANDIDATE_KEYS:
        raw = entry.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return fallback


def to_string_list(value: object) -> list[str]:
    """Convert scalar/list/dict values into a flattened list of strings."""
    if value is None:
        return []
    if isinstance(value, str):
        val = value.strip()
        return [val] if val else []
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(to_string_list(item))
        return out
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(to_string_list(item))
        return out
    return [str(value)]


def parse_rankings(payload: object) -> tuple[list[dict[str, object]], list[str]]:
    """Parse and validate BT ranking entries."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return [], ["Rankings payload must be a JSON object with 'rankings' array."]
    raw_rankings = payload.get("rankings")
    if not isinstance(raw_rankings, list):
        return [], ["Rankings payload missing 'rankings' array."]

    parsed: list[dict[str, object]] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw_rankings, start=1):
        if not isinstance(item, dict):
            errors.append(f"rankings[{idx}] must be an object")
            continue
        idea_id = extract_id(item)
        if not idea_id:
            errors.append(f"rankings[{idx}] missing id")
            continue
        if idea_id in seen:
            errors.append(f"duplicate ranking id '{idea_id}'")
            continue
        seen.add(idea_id)

        mu = as_float(item.get("mu", item.get("theta", 0.0)))
        sigma = max(0.0, as_float(item.get("sigma", 0.0)))
        bt_rank = as_int(item.get("rank", idx), idx)
        parsed.append(
            {
                "id": idea_id,
                "mu": mu,
                "sigma": sigma,
                "bt_rank": bt_rank,
            }
        )
    return parsed, errors


def normalize_evidence_entries(payload: object) -> list[tuple[str, dict[str, object]]]:
    """Normalize evidence payload into (id, object) entries."""
    entries: list[tuple[str, dict[str, object]]] = []
    if isinstance(payload, list):
        for idx, item in enumerate(payload):
            if isinstance(item, dict):
                idea_id = extract_id(item, fallback=f"__index_{idx}")
                entries.append((idea_id, item))
        return entries

    if not isinstance(payload, dict):
        return entries

    for key in ("evidence", "scores", "results", "ideas", "items", "finalists"):
        value = payload.get(key)
        if isinstance(value, list):
            for idx, item in enumerate(value):
                if isinstance(item, dict):
                    idea_id = extract_id(item, fallback=f"__index_{idx}")
                    entries.append((idea_id, item))
            return entries

    if all(isinstance(v, dict) for v in payload.values()):
        for key, value in payload.items():
            if isinstance(value, dict):
                entries.append((extract_id(value, fallback=str(key)), value))
        return entries

    if extract_id(payload):
        entries.append((extract_id(payload), payload))
    return entries


def get_gate_pass(entry: dict[str, object], gate_name: str) -> bool | None:
    """Return tri-state gate status (True/False/None) for a gate."""
    gates = entry.get("gates")
    if isinstance(gates, dict):
        gate = gates.get(gate_name)
        if isinstance(gate, dict) and "pass" in gate:
            raw = gate.get("pass")
            if isinstance(raw, bool):
                return raw
            text = norm_string(raw)
            if text in {"pass", "passed", "true", "1", "yes"}:
                return True
            if text in {"fail", "failed", "false", "0", "no"}:
                return False

    candidates = (
        f"{gate_name}_gate",
        f"{gate_name}_status",
        f"{gate_name}_result",
        gate_name,
    )
    for key in candidates:
        if key not in entry:
            continue
        raw = entry.get(key)
        if isinstance(raw, dict) and "pass" in raw:
            val = raw.get("pass")
            if isinstance(val, bool):
                return val
            text = norm_string(val)
        else:
            text = norm_string(raw)
        if text in {"pass", "passed", "true", "1", "yes"}:
            return True
        if text in {"fail", "failed", "false", "0", "no"}:
            return False
    return None


def extract_identification_count(entry: dict[str, object]) -> int:
    """Extract count of identification keywords found."""
    for key in (
        "identification_keywords_found",
        "identification_keyword_count",
        "id_keywords_found",
        "identification_count",
    ):
        if key in entry:
            return max(0, as_int(entry.get(key), 0))

    for key in ("identification_keywords", "id_keywords"):
        if key in entry:
            return len(to_string_list(entry.get(key)))

    gates = entry.get("gates")
    if isinstance(gates, dict):
        ident = gates.get("identifiability")
        if isinstance(ident, dict):
            for key in ("keyword_count", "keywords_found"):
                if key in ident:
                    return max(0, as_int(ident.get(key), 0))
            reason = ident.get("reason")
            if isinstance(reason, str):
                quoted = re.findall(r"'([^']+)'", reason)
                if quoted:
                    return len(quoted)
                return len(re.findall(r"\b[A-Za-z][A-Za-z\- ]{2,}\b", reason))
    return 0


def data_component_score(entry: dict[str, object]) -> float:
    """Compute data evidence component according to accessibility/source signals."""
    data_pass = get_gate_pass(entry, "data")
    if data_pass is False:
        return 0.0

    access_candidates: list[str] = []
    for key in ("data_access", "access", "dataset_access", "source_access"):
        if key in entry:
            access_candidates.extend(to_string_list(entry.get(key)))
    data_obj = entry.get("data")
    if isinstance(data_obj, dict):
        access_candidates.extend(to_string_list(data_obj.get("access")))
        access_candidates.extend(to_string_list(data_obj.get("availability")))
        sources = to_string_list(data_obj.get("sources"))
    else:
        sources = []

    if not sources and "sources" in entry:
        sources = to_string_list(entry.get("sources"))
    sources_lower = [s.strip().lower() for s in sources if s.strip()]
    named_sources = [s for s in sources_lower if s not in UNKNOWN_MARKERS and len(s) >= 3]

    access_text = " ".join(access_candidates).strip().lower()
    if any(word in access_text for word in ("unknown", "tbd", "n/a")):
        return 0.0
    if any(word in access_text for word in ("free", "public", "open", "available")) and named_sources:
        return 1.0
    if "accessible" in access_text or "available" in access_text:
        return 0.5
    if data_pass and named_sources:
        return 0.5
    return 0.0


def compute_evidence_score(entry: dict[str, object]) -> float:
    """Compute E_i = (novelty + identification + data) / 3."""
    novelty_pass = get_gate_pass(entry, "novelty")
    e_novelty = 1.0 if novelty_pass else 0.0
    e_identification = 1.0 if extract_identification_count(entry) >= 2 else 0.0
    e_data = data_component_score(entry)
    return (e_novelty + e_identification + e_data) / 3.0


def extract_risk_score(entry: dict[str, object]) -> int:
    """Extract risk score (gate failure count) from evidence entry."""
    for key in ("R", "risk", "risk_score", "gate_failures", "failure_count"):
        if key in entry:
            raw = entry.get(key)
            if isinstance(raw, list):
                return len(raw)
            return max(0, as_int(raw, 0))

    failed = entry.get("failed_gates")
    if isinstance(failed, list):
        return len(failed)

    gates = entry.get("gates")
    if isinstance(gates, dict):
        count = 0
        for gate in gates.values():
            if not isinstance(gate, dict):
                continue
            status = gate.get("pass")
            if isinstance(status, bool):
                if not status:
                    count += 1
                continue
            lowered = norm_string(status)
            if lowered in {"fail", "failed", "false", "0", "no"}:
                count += 1
        return count
    return 0


def parse_evidence(payload: object) -> tuple[dict[str, dict[str, float | int]], list[str]]:
    """Parse evidence payload into map keyed by idea id."""
    errors: list[str] = []
    evidence_map: dict[str, dict[str, float | int]] = {}
    for idea_id, entry in normalize_evidence_entries(payload):
        if not isinstance(entry, dict):
            continue
        normalized_id = idea_id.strip()
        if not normalized_id or normalized_id.startswith("__index_"):
            fallback = extract_id(entry)
            if not fallback:
                continue
            normalized_id = fallback
        score = compute_evidence_score(entry)
        risk = extract_risk_score(entry)
        evidence_map[normalized_id] = {"E": score, "R": risk}

    if not evidence_map:
        errors.append("Evidence payload did not contain any identifiable idea entries.")
    return evidence_map, errors


def parse_portfolio(payload: object) -> tuple[list[str], list[str]]:
    """Parse portfolio payload as an idea-id list."""
    errors: list[str] = []
    ids: list[str] = []

    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, str) and item.strip():
                ids.append(item.strip())
            elif isinstance(item, dict):
                idea_id = extract_id(item)
                if idea_id:
                    ids.append(idea_id)
        return ids, errors

    if isinstance(payload, dict):
        for key in ("portfolio", "idea_ids", "selected_ids", "ids", "ideas"):
            value = payload.get(key)
            if isinstance(value, list):
                parsed, _ = parse_portfolio(value)
                return parsed, errors
        if extract_id(payload):
            return [extract_id(payload)], errors
        errors.append("Portfolio object missing array field (portfolio/idea_ids/selected_ids/ids/ideas).")
        return [], errors

    errors.append("Portfolio JSON must be an array or object.")
    return [], errors


def normalize_ideas(payload: object) -> tuple[dict[str, dict[str, object]], list[str]]:
    """Normalize ideas payload to map of id -> object."""
    errors: list[str] = []
    records: list[dict[str, object]] = []

    if isinstance(payload, list):
        records = [x for x in payload if isinstance(x, dict)]
    elif isinstance(payload, dict):
        for key in ("ideas", "records", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                records = [x for x in value if isinstance(x, dict)]
                break
        if not records and extract_id(payload):
            records = [payload]
    else:
        return {}, ["Ideas JSON must be an array or object."]

    idea_map: dict[str, dict[str, object]] = {}
    for idx, idea in enumerate(records, start=1):
        idea_id = extract_id(idea, fallback=f"__index_{idx}")
        if idea_id.startswith("__index_"):
            continue
        idea_map[idea_id] = idea
    if not idea_map:
        errors.append("Ideas payload did not contain any identifiable idea IDs.")
    return idea_map, errors


def collect_text(value: object) -> list[str]:
    """Collect textual fields recursively for text-vector construction."""
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(collect_text(item))
        return out
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(collect_text(item))
        return out
    return []


def build_idea_text(idea: dict[str, object]) -> str:
    """Build merged text for one idea."""
    parts: list[str] = []
    for key in TEXT_FIELD_KEYS:
        if key in idea:
            parts.extend(collect_text(idea.get(key)))
    if not parts:
        parts = collect_text(idea)
    return " ".join(parts)


def collect_taxonomy_labels(idea: dict[str, object]) -> set[str]:
    """Extract taxonomy-like labels from idea fields."""
    labels: set[str] = set()
    for key in TAXONOMY_KEYS:
        if key not in idea:
            continue
        for token in to_string_list(idea.get(key)):
            label = token.strip().lower()
            if label:
                labels.add(label)
    return labels


def tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase alphanumeric terms."""
    return re.findall(r"[a-z0-9]+", text.lower())


def tfidf_vectors(texts: dict[str, str]) -> dict[str, dict[str, float]]:
    """Compute TF-IDF vectors keyed by idea id."""
    token_map: dict[str, list[str]] = {idea_id: tokenize(text) for idea_id, text in texts.items()}
    doc_freq: Counter[str] = Counter()
    for tokens in token_map.values():
        doc_freq.update(set(tokens))

    total_docs = max(1, len(token_map))
    vectors: dict[str, dict[str, float]] = {}
    for idea_id, tokens in token_map.items():
        if not tokens:
            vectors[idea_id] = {}
            continue
        counts = Counter(tokens)
        denom = float(len(tokens))
        vec: dict[str, float] = {}
        for term, count in counts.items():
            tf = count / denom
            idf = math.log((1.0 + total_docs) / (1.0 + doc_freq[term])) + 1.0
            vec[term] = tf * idf
        vectors[idea_id] = vec
    return vectors


def cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """Compute cosine similarity between sparse vectors."""
    if not vec_a or not vec_b:
        return 0.0
    if len(vec_a) > len(vec_b):
        vec_a, vec_b = vec_b, vec_a
    dot = 0.0
    for term, val in vec_a.items():
        dot += val * vec_b.get(term, 0.0)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def taxonomy_overlap(labels_a: set[str], labels_b: set[str]) -> float:
    """Compute Jaccard overlap between taxonomy label sets."""
    if not labels_a or not labels_b:
        return 0.0
    union = labels_a | labels_b
    if not union:
        return 0.0
    return len(labels_a & labels_b) / len(union)


def compute_redundancy(
    candidate_id: str,
    portfolio_ids: list[str],
    vectors: dict[str, dict[str, float]],
    label_map: dict[str, set[str]],
) -> float:
    """Compute red(i, S) as max(cosine + taxonomy_overlap) vs portfolio ideas."""
    best = 0.0
    vec_i = vectors.get(candidate_id, {})
    labels_i = label_map.get(candidate_id, set())
    for portfolio_id in portfolio_ids:
        if portfolio_id == candidate_id:
            continue
        sim = cosine_similarity(vec_i, vectors.get(portfolio_id, {}))
        tax = taxonomy_overlap(labels_i, label_map.get(portfolio_id, set()))
        best = max(best, sim + tax)
    return best


def build_summary(payload: dict[str, object]) -> str:
    """Build human-readable summary output."""
    metadata = payload.get("metadata", {})
    scores = payload.get("scores", [])
    if not isinstance(metadata, dict) or not isinstance(scores, list):
        return "No summary available."

    lines = ["RWEA v2 Summary", "=" * 60]
    lines.append(f"Total ideas: {metadata.get('total_ideas', 0)}")
    lines.append(
        "Lambdas: "
        f"uncertainty={metadata.get('lambda_uncertainty')}, "
        f"evidence={metadata.get('lambda_evidence')}, "
        f"risk={metadata.get('lambda_risk')}, "
        f"redundancy={metadata.get('lambda_redundancy')}"
    )
    lines.append("")
    lines.append("Top 10 ideas:")
    for idx, row in enumerate(scores[:10], start=1):
        if not isinstance(row, dict):
            continue
        comp = row.get("components", {})
        if not isinstance(comp, dict):
            comp = {}
        lines.append(
            f"{idx:2d}. {row.get('id')} | RWEA2={as_float(row.get('rwea2')):.4f} | "
            f"mu={as_float(row.get('mu')):.4f}, sigma={as_float(row.get('sigma')):.4f}, "
            f"E={as_float(row.get('E')):.4f}, R={as_float(row.get('R')):.2f}, "
            f"red={as_float(row.get('redundancy')):.4f}"
        )
        lines.append(
            "    components: "
            f"unc={as_float(comp.get('uncertainty_penalty')):.4f}, "
            f"ev={as_float(comp.get('evidence_bonus')):.4f}, "
            f"risk={as_float(comp.get('risk_penalty')):.4f}, "
            f"red={as_float(comp.get('redundancy_penalty')):.4f}"
        )

    if bool(metadata.get("has_evidence")):
        e_values = [as_float(row.get("E")) for row in scores if isinstance(row, dict)]
        if e_values:
            avg = sum(e_values) / len(e_values)
            lines.append("")
            lines.append("Evidence distribution:")
            lines.append(
                f"min={min(e_values):.4f}, max={max(e_values):.4f}, avg={avg:.4f}, count={len(e_values)}"
            )
            buckets = {"0.0": 0, "(0,0.33]": 0, "(0.33,0.66]": 0, "(0.66,1.0]": 0}
            for value in e_values:
                if value <= 0.0:
                    buckets["0.0"] += 1
                elif value <= 1.0 / 3.0:
                    buckets["(0,0.33]"] += 1
                elif value <= 2.0 / 3.0:
                    buckets["(0.33,0.66]"] += 1
                else:
                    buckets["(0.66,1.0]"] += 1
            lines.append(
                "buckets: "
                + ", ".join(f"{name}={count}" for name, count in buckets.items())
            )

    if bool(metadata.get("has_portfolio")):
        reds = [as_float(row.get("redundancy")) for row in scores if isinstance(row, dict)]
        if reds:
            avg_red = sum(reds) / len(reds)
            lines.append("")
            lines.append("Redundancy statistics:")
            lines.append(
                f"min={min(reds):.4f}, max={max(reds):.4f}, avg={avg_red:.4f}, count={len(reds)}"
            )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> tuple[dict[str, object], list[str], list[str]]:
    """Execute scoring pipeline; returns payload, errors, warnings."""
    errors: list[str] = []
    warnings: list[str] = []

    rankings_payload = read_json(args.rankings)
    rankings, ranking_errors = parse_rankings(rankings_payload)
    errors.extend(ranking_errors)

    evidence_map: dict[str, dict[str, float | int]] = {}
    if args.evidence is not None:
        evidence_payload = read_json(args.evidence)
        parsed_evidence, evidence_errors = parse_evidence(evidence_payload)
        evidence_map = parsed_evidence
        errors.extend(evidence_errors)

    portfolio_ids: list[str] = []
    if args.portfolio is not None:
        portfolio_payload = read_json(args.portfolio)
        portfolio_ids, portfolio_errors = parse_portfolio(portfolio_payload)
        errors.extend(portfolio_errors)
        if not portfolio_ids:
            warnings.append("Portfolio provided but no valid idea IDs were found.")

    idea_map: dict[str, dict[str, object]] = {}
    if args.ideas is not None:
        ideas_payload = read_json(args.ideas)
        idea_map, idea_errors = normalize_ideas(ideas_payload)
        errors.extend(idea_errors)
    elif portfolio_ids:
        warnings.append("Portfolio provided without --ideas; redundancy defaults to 0.")

    vectors: dict[str, dict[str, float]] = {}
    label_map: dict[str, set[str]] = {}
    if portfolio_ids and idea_map:
        texts: dict[str, str] = {idea_id: build_idea_text(idea) for idea_id, idea in idea_map.items()}
        vectors = tfidf_vectors(texts)
        label_map = {idea_id: collect_taxonomy_labels(idea) for idea_id, idea in idea_map.items()}

    if args.validate:
        return (
            {
                "valid": len(errors) == 0,
                "errors": errors,
                "warnings": warnings,
                "metadata": {
                    "total_rankings": len(rankings),
                    "evidence_entries": len(evidence_map),
                    "portfolio_size": len(portfolio_ids),
                    "idea_records": len(idea_map),
                },
            },
            errors,
            warnings,
        )

    if errors:
        return ({}, errors, warnings)

    scored: list[dict[str, object]] = []
    for row in rankings:
        idea_id = str(row["id"])
        mu = as_float(row["mu"])
        sigma = as_float(row["sigma"])
        evidence = evidence_map.get(idea_id, {})
        e_i = as_float(evidence.get("E", 0.0))
        r_i = as_int(evidence.get("R", 0), 0)
        red = 0.0
        if portfolio_ids and vectors:
            red = compute_redundancy(idea_id, portfolio_ids, vectors, label_map)

        uncertainty_penalty = -args.lambda_uncertainty * sigma
        evidence_bonus = args.lambda_evidence * e_i
        risk_penalty = -args.lambda_risk * r_i
        redundancy_penalty = -args.lambda_redundancy * red
        rwea2 = mu + uncertainty_penalty + evidence_bonus + risk_penalty + redundancy_penalty

        scored.append(
            {
                "id": idea_id,
                "rwea2": rwea2,
                "mu": mu,
                "sigma": sigma,
                "E": e_i,
                "R": r_i,
                "redundancy": red,
                "components": {
                    "mu_i": mu,
                    "uncertainty_penalty": uncertainty_penalty,
                    "evidence_bonus": evidence_bonus,
                    "risk_penalty": risk_penalty,
                    "redundancy_penalty": redundancy_penalty,
                },
                "bt_rank": as_int(row.get("bt_rank", 0), 0),
            }
        )

    scored.sort(key=lambda x: (-as_float(x.get("rwea2")), as_int(x.get("bt_rank"), 10**9), str(x.get("id"))))

    payload: dict[str, object] = {
        "metadata": {
            "lambda_uncertainty": args.lambda_uncertainty,
            "lambda_evidence": args.lambda_evidence,
            "lambda_risk": args.lambda_risk,
            "lambda_redundancy": args.lambda_redundancy,
            "total_ideas": len(scored),
            "has_evidence": bool(args.evidence),
            "has_portfolio": bool(portfolio_ids),
        },
        "scores": scored,
    }
    return payload, errors, warnings


def main(argv: list[str] | None = None) -> None:
    """Program entry point."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        payload, errors, _warnings = run(args)
    except (FileNotFoundError, ValueError) as exc:
        sys.stderr.write(str(exc) + "\n")
        raise SystemExit(1)

    if args.validate:
        if args.summary:
            sys.stderr.write(build_summary({"metadata": payload.get("metadata", {}), "scores": []}) + "\n")
        write_output(payload, args.pretty, args.output)
        return

    if errors:
        error_payload = {"valid": False, "errors": errors}
        write_output(error_payload, args.pretty, args.output)
        raise SystemExit(1)

    if args.summary:
        sys.stderr.write(build_summary(payload) + "\n")

    write_output(payload, args.pretty, args.output)


if __name__ == "__main__":
    main()
