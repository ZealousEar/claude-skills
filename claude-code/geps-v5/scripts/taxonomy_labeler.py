#!/usr/bin/env python3
"""Rule-based multi-label taxonomy classifier for research ideas."""

from __future__ import annotations

import argparse
import json
import re
import sys
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


def read_json_file(path: Path) -> object:
    """Read JSON from file using json.loads."""
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def normalize_ideas(payload: object) -> list[dict[str, object]]:
    """Normalize payload into a list of idea objects."""
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return payload
    raise ValueError("input JSON must be an idea object or an array of idea objects")


def collect_strings(value: object) -> list[str]:
    """Recursively collect strings from nested JSON-like data."""
    if isinstance(value, str):
        return [value]
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


def build_idea_text(idea: dict[str, object]) -> str:
    """Build searchable text from all string fields in an idea."""
    return "\n".join(collect_strings(idea))


def matches_keyword(text: str, text_lower: str, keyword: str) -> bool:
    """Apply keyword rule: <=3 chars uses word boundary, else substring."""
    token = keyword.strip()
    if not token:
        return False
    if len(token) <= 3:
        return re.search(r"\b" + re.escape(token) + r"\b", text, flags=re.IGNORECASE) is not None
    return token.lower() in text_lower


def match_dimension(text: str, classes: dict[str, object]) -> tuple[list[str], dict[str, list[str]]]:
    """Return matched labels and matched keywords for one taxonomy dimension."""
    labels: list[str] = []
    matched_keywords: dict[str, list[str]] = {}
    text_lower = text.lower()

    for category, config in classes.items():
        if not isinstance(config, dict):
            continue
        keywords = config.get("keywords", [])
        if not isinstance(keywords, list):
            continue

        hits: list[str] = []
        seen: set[str] = set()
        for keyword in keywords:
            if not isinstance(keyword, str):
                continue
            if matches_keyword(text, text_lower, keyword):
                dedupe_key = keyword.lower()
                if dedupe_key not in seen:
                    seen.add(dedupe_key)
                    hits.append(keyword)

        if hits:
            labels.append(category)
            matched_keywords[category] = hits

    return labels, matched_keywords


def classify_idea(idea: dict[str, object], taxonomy: dict[str, object], fallback_id: str) -> dict[str, object]:
    """Classify one idea into method/data/contribution labels."""
    idea_id = idea.get("id")
    output_id = idea_id if isinstance(idea_id, str) and idea_id.strip() else fallback_id
    text = build_idea_text(idea)

    result: dict[str, object] = {
        "id": output_id,
        "method": [],
        "data": [],
        "contribution": [],
        "matched_keywords": {"method": {}, "data": {}, "contribution": {}},
    }

    for dim_out, dim_taxonomy in DIMENSIONS.items():
        classes = taxonomy.get(dim_taxonomy, {})
        if not isinstance(classes, dict):
            continue
        labels, hits = match_dimension(text, classes)
        result[dim_out] = labels
        matched = result["matched_keywords"]
        if isinstance(matched, dict):
            matched[dim_out] = hits

    return result


def classify_ideas(ideas: list[dict[str, object]], taxonomy: dict[str, object]) -> list[dict[str, object]]:
    """Classify all ideas."""
    return [
        classify_idea(idea, taxonomy, fallback_id=f"IDEA-{idx:03d}")
        for idx, idea in enumerate(ideas, start=1)
    ]


def validate_taxonomy(taxonomy: object) -> list[str]:
    """Validate taxonomy structure."""
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
            else:
                for i, keyword in enumerate(keywords, start=1):
                    if not isinstance(keyword, str) or not keyword.strip():
                        errors.append(f"{dim}.{category}.keywords[{i}] must be a non-empty string")

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


def validate_ideas(ideas: list[object]) -> list[str]:
    """Validate idea objects."""
    errors: list[str] = []
    if not ideas:
        return ["input must contain at least one idea"]

    for idx, idea in enumerate(ideas, start=1):
        if not isinstance(idea, dict):
            errors.append(f"idea at index {idx} must be an object")
            continue

        idea_id = idea.get("id")
        title = idea.get("title")
        if not isinstance(idea_id, str) or not idea_id.strip():
            errors.append(f"idea at index {idx} missing non-empty string field 'id'")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"idea {idea_id!r} missing non-empty string field 'title'")

        has_text_field = any(
            key not in {"id", "title"} and bool(collect_strings(value))
            for key, value in idea.items()
        )
        if not has_text_field:
            errors.append(
                f"idea {idea_id!r} should include at least one additional text field "
                "(e.g., research_question, hypothesis, data, contribution)"
            )

    return errors


def compute_counts(results: list[dict[str, object]], dimension: str) -> dict[str, int]:
    """Count category matches for one output dimension."""
    counts: dict[str, int] = {}
    for result in results:
        labels = result.get(dimension, [])
        if not isinstance(labels, list):
            continue
        for label in labels:
            if isinstance(label, str):
                counts[label] = counts.get(label, 0) + 1
    return counts


def get_category_quota(taxonomy: dict[str, object], dim_taxonomy: str, config: dict[str, object]) -> int | None:
    """Resolve max quota for category from local or global settings."""
    if isinstance(config.get("max_quota"), int) and config.get("max_quota") >= 0:
        return config.get("max_quota")
    if dim_taxonomy == "method_classes":
        quotas = taxonomy.get("quotas", {})
        if isinstance(quotas, dict) and isinstance(quotas.get("max_per_method_class"), int):
            if quotas.get("max_per_method_class") >= 0:
                return quotas.get("max_per_method_class")
    return None


def format_summary(results: list[dict[str, object]], taxonomy: dict[str, object]) -> str:
    """Build human-readable distribution, quota, and monoculture summary."""
    total = len(results)
    quotas = taxonomy.get("quotas", {})
    if not isinstance(quotas, dict):
        quotas = {}

    lines = ["Taxonomy Labeling Summary", "=" * 60, f"Ideas processed: {total}", ""]
    for dim_out, dim_taxonomy in DIMENSIONS.items():
        classes = taxonomy.get(dim_taxonomy, {})
        if not isinstance(classes, dict):
            continue

        counts = {category: 0 for category in classes}
        counts.update(compute_counts(results, dim_out))

        lines.append(f"{dim_out.capitalize()} distribution:")
        for category, count in counts.items():
            pct = (count / total * 100.0) if total else 0.0
            lines.append(f"  - {category}: {count}/{total} ({pct:.1f}%)")

        coverage = sum(1 for count in counts.values() if count > 0)
        min_required = quotas.get(MIN_COVERAGE_KEYS[dim_out])
        if isinstance(min_required, int):
            status = "OK" if coverage >= min_required else "FAIL"
            lines.append(f"  Coverage: {coverage} categories, minimum {min_required} [{status}]")
        else:
            lines.append(f"  Coverage: {coverage} categories")

        violations: list[str] = []
        for category, config in classes.items():
            if isinstance(config, dict):
                quota = get_category_quota(taxonomy, dim_taxonomy, config)
                if quota is not None and counts.get(category, 0) > quota:
                    violations.append(f"{category} exceeded quota ({counts.get(category, 0)} > {quota})")
        if violations:
            lines.append("  Quota warnings:")
            for warning in violations:
                lines.append(f"    - {warning}")
        else:
            lines.append("  Quota warnings: none")

        monoculture = [
            f"{category} ({count}/{total}, {count / total * 100.0:.1f}%)"
            for category, count in counts.items()
            if total and (count / total) > 0.5
        ]
        if monoculture:
            lines.append("  Monoculture warnings:")
            for warning in monoculture:
                lines.append(f"    - {warning}")
        else:
            lines.append("  Monoculture warnings: none")
        lines.append("")

    return "\n".join(lines).rstrip()


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Rule-based multi-label taxonomy classifier for research ideas."
    )
    parser.add_argument("--input", type=Path, required=True, help="Path to input ideas JSON.")
    parser.add_argument("--taxonomy", type=Path, required=True, help="Path to taxonomy JSON.")
    parser.add_argument("--output", type=Path, help="Path to output JSON file (default: stdout).")
    parser.add_argument("--pretty", action="store_true", help="Print indented JSON.")
    parser.add_argument("--validate", action="store_true", help="Validate input and taxonomy only.")
    parser.add_argument("--summary", action="store_true", help="Print human-readable distribution summary.")
    args = parser.parse_args()

    try:
        ideas_payload = read_json_file(args.input)
        taxonomy_payload = read_json_file(args.taxonomy)
        ideas_raw = normalize_ideas(ideas_payload)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    errors = validate_taxonomy(taxonomy_payload) + validate_ideas(ideas_raw)
    if errors:
        print(f"Validation failed ({len(errors)} errors):", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        sys.exit(1)

    if args.validate:
        print("Input and taxonomy are valid.")
        sys.exit(0)

    ideas = [idea for idea in ideas_raw if isinstance(idea, dict)]
    taxonomy = taxonomy_payload
    results = classify_ideas(ideas, taxonomy)

    output_json = json.dumps(results, indent=2 if args.pretty else None)
    if args.output:
        args.output.expanduser().write_text(f"{output_json}\n", encoding="utf-8")

    if args.summary:
        print(format_summary(results, taxonomy))
    elif not args.output:
        print(output_json)


if __name__ == "__main__":
    main()
