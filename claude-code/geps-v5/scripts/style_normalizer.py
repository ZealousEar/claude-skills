#!/usr/bin/env python3
"""Normalize research-idea style into a standard structured template."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ADJECTIVE_BLOCKLIST = [
    "novel",
    "groundbreaking",
    "state-of-the-art",
    "innovative",
    "first-of-its-kind",
    "paradigm-shifting",
    "cutting-edge",
    "unique",
    "unprecedented",
    "transformative",
    "seminal",
    "pioneering",
]

AUTHORITY_PATTERNS = [
    r"(?:as\s+)?suggested\s+by\s+[\w\s,]+(?:\(\d{4}\))?",
    r"JFE-level|RFS-level|top-tier\s+journal\s+worthy",
    r"Dave\s+Cliff\s+(?:says|suggests|recommends)",
    r"(?:JFE|RFS|JF|QJE)\s*(?:-|–)\s*(?:level|grade|tier|worthy)",
]

HEDGING_PATTERNS = [
    r"we\s+believe\s+(?:that\s+)?",
    r"it\s+is\s+hoped\s+(?:that\s+)?",
    r"this\s+could\s+potentially",
]

DEFAULT_LLM_RUNNER_PATH = (
    Path("~/.claude/skills/convolutional-debate-agent/scripts/llm_runner.py").expanduser()
)
DEFAULT_PROMPT_PATH = Path("~/.claude/skills/geps-v5/prompts/normalizer.md").expanduser()

OUTPUT_KEYS = [
    "title",
    "research_question",
    "hypothesis",
    "identification",
    "data",
    "contribution",
    "risk",
    "mvp",
]


def empty_result() -> dict[str, object]:
    """Return the output shape with empty defaults."""
    return {
        "title": "",
        "research_question": "",
        "hypothesis": [],
        "identification": [],
        "data": [],
        "contribution": "",
        "risk": "",
        "mvp": [],
    }


def clean_line(text: str) -> str:
    """Normalize a line fragment by removing bullet prefixes and extra spaces."""
    cleaned = text.strip()
    cleaned = re.sub(r"^[-*+]\s+", "", cleaned)
    cleaned = re.sub(r"^\d+[.)]\s+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" -")


def truncate_words(text: str, max_words: int = 12) -> str:
    """Truncate text to at most max_words words."""
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]).strip()


def cleanup_whitespace(text: str) -> str:
    """Collapse redundant whitespace while preserving paragraph breaks."""
    lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in text.splitlines()]
    normalized = "\n".join(lines)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    normalized = re.sub(r" +([,.;:!?])", r"\1", normalized)
    return normalized.strip()


def strip_persuasive_language(text: str) -> str:
    """Remove persuasive adjectives, authority cues, and hedging fluff."""
    cleaned = text
    for adjective in ADJECTIVE_BLOCKLIST:
        cleaned = re.sub(rf"\b{re.escape(adjective)}\b", "", cleaned, flags=re.IGNORECASE)
    for pattern in AUTHORITY_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    for pattern in HEDGING_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleanup_whitespace(cleaned)


def normalize_section_name(name: str) -> str | None:
    """Map heading/label text to an output key where possible."""
    label = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
    if not label:
        return None
    if label == "title":
        return "title"
    if "research question" in label or label == "question":
        return "research_question"
    if "hypothesis" in label or "mechanism" in label:
        return "hypothesis"
    if "identification" in label:
        return "identification"
    if label.startswith("data") or "data requirement" in label:
        return "data"
    if "contribution" in label:
        return "contribution"
    if "risk" in label:
        return "risk"
    if label.startswith("mvp") or "minimum viable" in label:
        return "mvp"
    return None


def parse_sections(text: str) -> dict[str, list[str]]:
    """Parse markdown-like sections and label-style fields."""
    sections: dict[str, list[str]] = {}
    current: str | None = None

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        heading = re.match(r"^#{1,6}\s*(.+?)\s*$", stripped)
        if heading:
            current = normalize_section_name(heading.group(1))
            if current:
                sections.setdefault(current, [])
            continue

        labeled = re.match(r"^([A-Za-z][A-Za-z0-9 /&()_-]{1,80}):\s*(.*)$", stripped)
        if labeled:
            section_name = normalize_section_name(labeled.group(1))
            if section_name:
                current = section_name
                sections.setdefault(current, [])
                remainder = labeled.group(2).strip()
                if remainder:
                    sections[current].append(remainder)
                continue

        if current is not None:
            sections.setdefault(current, []).append(stripped)

    return sections


def first_heading(text: str) -> str:
    """Return the first markdown heading line, if present."""
    for line in text.splitlines():
        match = re.match(r"^\s*#{1,6}\s*(.+?)\s*$", line)
        if match:
            return clean_line(match.group(1))
    return ""


def first_sentence(text: str) -> str:
    """Return the first sentence-like chunk from text."""
    compact = re.sub(r"\s+", " ", text.strip())
    if not compact:
        return ""
    sentence = re.split(r"(?<=[.!?])\s+", compact, maxsplit=1)[0]
    return clean_line(sentence)


def extract_bullets(lines: list[str], limit: int | None = None) -> list[str]:
    """Extract bullet items from section lines; fallback to non-empty lines."""
    bullets: list[str] = []
    fallback: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        bullet = re.match(r"^[-*+]\s+(.*)$", stripped) or re.match(r"^\d+[.)]\s+(.*)$", stripped)
        if bullet:
            item = clean_line(bullet.group(1))
            if item:
                bullets.append(item)
        else:
            item = clean_line(stripped)
            if item:
                fallback.append(item)
    chosen = bullets if bullets else fallback
    if limit is not None:
        return chosen[:limit]
    return chosen


def extract_single_line(lines: list[str]) -> str:
    """Return the first meaningful line from a section."""
    for line in lines:
        item = clean_line(line)
        if item:
            return item
    return ""


def extract_research_question(text: str, sections: dict[str, list[str]]) -> str:
    """Extract a research question from dedicated section or first '?' line."""
    for line in sections.get("research_question", []):
        cleaned = clean_line(line)
        if "?" in cleaned:
            return cleaned[: cleaned.find("?") + 1]
    if sections.get("research_question"):
        candidate = clean_line(sections["research_question"][0])
        if candidate:
            return candidate if candidate.endswith("?") else f"{candidate}?"

    for raw_line in text.splitlines():
        if "?" not in raw_line:
            continue
        candidate = clean_line(raw_line)
        if ":" in candidate and len(candidate.split(":", 1)[0].split()) <= 4:
            candidate = clean_line(candidate.split(":", 1)[1])
        if candidate:
            return candidate[: candidate.find("?") + 1]
    return ""


def extract_template_fields(text: str) -> dict[str, object]:
    """Best-effort extraction of normalized template fields from text."""
    sections = parse_sections(text)
    result = empty_result()

    title = extract_single_line(sections.get("title", []))
    if not title:
        title = first_heading(text) or first_sentence(text)
    result["title"] = truncate_words(title)

    result["research_question"] = extract_research_question(text, sections)
    result["hypothesis"] = extract_bullets(sections.get("hypothesis", []), limit=3)
    result["identification"] = extract_bullets(sections.get("identification", []), limit=3)
    result["data"] = extract_bullets(sections.get("data", []))
    result["contribution"] = extract_single_line(sections.get("contribution", []))
    result["risk"] = extract_single_line(sections.get("risk", []))
    result["mvp"] = extract_bullets(sections.get("mvp", []), limit=3)
    return result


def fill_prompt_template(prompt_template: str, cleaned_text: str) -> str:
    """Insert cleaned text into prompt template placeholders."""
    if "{raw_idea}" in prompt_template:
        return prompt_template.replace("{raw_idea}", cleaned_text)
    if "{{raw_idea}}" in prompt_template:
        return prompt_template.replace("{{raw_idea}}", cleaned_text)
    return f"{prompt_template.rstrip()}\n\nINPUT:\n{cleaned_text}\n"


def run_llm_normalizer(
    cleaned_text: str,
    llm_runner_path: Path,
    model: str,
    prompt_path: Path,
) -> str:
    """Run llm_runner.py with a filled normalizer prompt and return response text."""
    if not llm_runner_path.exists():
        raise FileNotFoundError(f"LLM runner not found: {llm_runner_path}")
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

    prompt_template = prompt_path.read_text()
    cleaned_tmp_path: Path | None = None
    prompt_tmp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            prefix="normalized-idea-",
            delete=False,
        ) as cleaned_tmp:
            cleaned_tmp.write(cleaned_text)
            cleaned_tmp_path = Path(cleaned_tmp.name)

        prompt = fill_prompt_template(prompt_template, cleaned_tmp_path.read_text())
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".md",
            prefix="normalizer-prompt-",
            delete=False,
        ) as prompt_tmp:
            prompt_tmp.write(prompt)
            prompt_tmp_path = Path(prompt_tmp.name)

        cmd = [
            "python3",
            str(llm_runner_path),
            "--model",
            model,
            "--prompt-file",
            str(prompt_tmp_path),
            "--max-tokens",
            "2000",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(stderr or f"llm_runner exited with {result.returncode}")
        response = result.stdout.strip()
        if not response:
            raise RuntimeError("llm_runner returned an empty response")
        return response
    finally:
        if cleaned_tmp_path is not None:
            cleaned_tmp_path.unlink(missing_ok=True)
        if prompt_tmp_path is not None:
            prompt_tmp_path.unlink(missing_ok=True)


def merge_results(primary: dict[str, object], fallback: dict[str, object]) -> dict[str, object]:
    """Merge parsed LLM result with fallback mechanical result for missing fields."""
    merged = empty_result()
    for key in OUTPUT_KEYS:
        value = primary.get(key)
        if isinstance(value, list):
            merged[key] = value if value else fallback.get(key, [])
        elif isinstance(value, str):
            merged[key] = value if value.strip() else fallback.get(key, "")
        else:
            merged[key] = fallback.get(key, merged[key])
    return merged


def normalize_idea(
    idea_text: str,
    mechanical_only: bool,
    llm_runner_path: Path,
    model: str,
    prompt_path: Path,
) -> dict[str, object]:
    """Normalize one idea, using LLM mode unless mechanical-only is requested."""
    cleaned = strip_persuasive_language(idea_text)
    mechanical_result = extract_template_fields(cleaned)
    if mechanical_only:
        return mechanical_result

    try:
        llm_response = run_llm_normalizer(cleaned, llm_runner_path, model, prompt_path)
        llm_result = extract_template_fields(llm_response)
        return merge_results(llm_result, mechanical_result)
    except Exception as exc:
        print(
            f"Warning: LLM normalization failed ({exc}); falling back to mechanical mode.",
            file=sys.stderr,
        )
        return mechanical_result


def parse_idea_input(raw_input: str) -> tuple[list[str], bool]:
    """Parse stdin/file input as either raw text or JSON array/string."""
    try:
        parsed = json.loads(raw_input)
    except json.JSONDecodeError:
        return [raw_input], False

    if isinstance(parsed, str):
        return [parsed], False
    if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
        return parsed, True
    raise ValueError("JSON input must be a string or an array of strings.")


def read_input_text(input_path: Path | None) -> str:
    """Read input text from file or stdin."""
    if input_path is None:
        return sys.stdin.read()
    return input_path.read_text()


def write_output(data: object, output_path: Path | None, pretty: bool) -> None:
    """Write JSON output to file or stdout."""
    rendered = json.dumps(data, indent=2) if pretty else json.dumps(data)
    if output_path is None:
        sys.stdout.write(f"{rendered}\n")
        return
    output_path.write_text(f"{rendered}\n")


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Strip persuasive language and normalize research ideas into a standard template."
    )
    parser.add_argument("--input", type=Path, help="Input file path. Defaults to stdin.")
    parser.add_argument("--output", type=Path, help="Output file path. Defaults to stdout.")
    parser.add_argument("--mechanical-only", action="store_true", help="Skip LLM calls.")
    parser.add_argument(
        "--llm-runner-path",
        type=Path,
        default=DEFAULT_LLM_RUNNER_PATH,
        help="Path to llm_runner.py.",
    )
    parser.add_argument("--model", default="opus", help="Model name for LLM normalization.")
    parser.add_argument(
        "--prompt-path",
        type=Path,
        default=DEFAULT_PROMPT_PATH,
        help="Path to normalizer prompt template.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    parser.add_argument("--validate", action="store_true", help="Validate input shape and exit.")
    args = parser.parse_args()

    try:
        raw_input = read_input_text(args.input.expanduser() if args.input else None)
        ideas, is_array = parse_idea_input(raw_input)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.validate:
        validation = {
            "valid": True,
            "count": len(ideas),
            "input_type": "array" if is_array else "single",
        }
        write_output(validation, args.output.expanduser() if args.output else None, args.pretty)
        return

    llm_runner_path = args.llm_runner_path.expanduser()
    prompt_path = args.prompt_path.expanduser()
    normalized_items = [
        normalize_idea(
            idea_text=idea,
            mechanical_only=args.mechanical_only,
            llm_runner_path=llm_runner_path,
            model=args.model,
            prompt_path=prompt_path,
        )
        for idea in ideas
    ]
    output: object = normalized_items if is_array else normalized_items[0]
    write_output(output, args.output.expanduser() if args.output else None, args.pretty)


if __name__ == "__main__":
    main()
