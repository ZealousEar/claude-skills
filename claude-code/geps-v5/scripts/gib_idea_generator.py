#!/usr/bin/env python3
"""Generate research ideas from a single model on a single topic for GIB."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SKILL_DIR = Path.home() / ".claude" / "skills" / "geps-v5"
DEFAULT_LLM_RUNNER = (
    Path.home() / ".claude" / "skills" / "convolutional-debate-agent"
    / "scripts" / "llm_runner.py"
)
DEFAULT_MODEL_SETTINGS = (
    Path.home() / ".claude" / "skills" / "convolutional-debate-agent"
    / "settings" / "model-settings.json"
)
DEFAULT_PROMPT_TEMPLATE = SKILL_DIR / "prompts" / "gib_generate.md"
DEFAULT_TOPICS = SKILL_DIR / "settings" / "gib-topics.json"

# ---------------------------------------------------------------------------
# Diversity seed hints — rotated for each idea
# ---------------------------------------------------------------------------

SEED_HINTS = [
    "Focus on cross-sectional variation across firms or industries.",
    "Consider a natural experiment or regulatory shock as identification.",
    "Use high-frequency or intraday data for sharper identification.",
    "Explore a behavioral channel or investor heterogeneity mechanism.",
    "Consider an international or cross-country comparison design.",
    "Use a difference-in-differences design with staggered treatment adoption.",
    "Focus on a machine learning method applied to a classical finance question.",
    "Consider network effects or contagion mechanisms between market participants.",
]

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
# Topic loading
# ---------------------------------------------------------------------------


def load_topic(topics_path: Path, topic_id: str) -> dict:
    """Load gib-topics.json and return the topic dict matching topic_id."""
    topics_data = load_json(topics_path)
    topics = topics_data if isinstance(topics_data, list) else topics_data.get("topics", [])
    for topic in topics:
        if topic.get("id") == topic_id:
            return topic
    available = [t.get("id", "?") for t in topics]
    raise ValueError(
        f"Topic '{topic_id}' not found in {topics_path}. "
        f"Available: {', '.join(available)}"
    )


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def build_prompt(template_text: str, topic_prompt: str, seed_hint: str) -> str:
    """Replace {topic} and {seed_hint} placeholders in the template."""
    prompt = template_text.replace("{topic}", topic_prompt)
    prompt = prompt.replace("{seed_hint}", seed_hint)
    return prompt


# ---------------------------------------------------------------------------
# LLM invocation
# ---------------------------------------------------------------------------


def call_llm(
    runner_path: Path,
    settings_path: Path,
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
    timeout: int = 300,
) -> str:
    """Call llm_runner.py via subprocess and return the response text."""
    cmd = [
        "python3", str(runner_path),
        "--model", model,
        "--prompt", prompt,
        "--temperature", str(temperature),
        "--max-tokens", str(max_tokens),
        "--settings", str(settings_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"llm_runner failed for {model}: {result.stderr[:500]}")
    response = result.stdout.strip()
    if not response:
        raise RuntimeError(f"llm_runner returned empty response for {model}")
    return response


# ---------------------------------------------------------------------------
# Idea generation
# ---------------------------------------------------------------------------


def generate_ideas(args: argparse.Namespace) -> list[dict]:
    """Main generation loop: produce args.count ideas from a single model/topic."""
    topics_path = Path(args.topic_file)
    template_path = Path(args.prompt_template)

    topic = load_topic(topics_path, args.topic_id)
    topic_prompt = topic.get("prompt", topic.get("description", ""))
    if not topic_prompt:
        raise ValueError(f"Topic '{args.topic_id}' has no 'prompt' or 'description' field.")

    template_text = template_path.read_text(encoding="utf-8")
    runner_path = Path(args.llm_runner_path)
    settings_path = Path(args.settings)

    ideas: list[dict] = []

    for i in range(args.count):
        seed_hint = SEED_HINTS[i % len(SEED_HINTS)]
        prompt = build_prompt(template_text, topic_prompt, seed_hint)

        log(f"Generating idea {i+1}/{args.count} (model={args.model}, topic={args.topic_id})")
        try:
            raw_text = call_llm(
                runner_path, settings_path, args.model,
                prompt, args.temperature, args.max_tokens,
            )
            idea = {
                "id": f"{args.model}_{args.topic_id}_{i:02d}",
                "model": args.model,
                "topic_id": args.topic_id,
                "raw_text": raw_text,
                "seed_hint": seed_hint,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            ideas.append(idea)
            log(f"  Idea {i+1} generated ({len(raw_text)} chars)")
        except Exception as e:
            log(f"  WARNING: idea {i+1} failed: {e}")
            continue

    return ideas


# ---------------------------------------------------------------------------
# Validation mode
# ---------------------------------------------------------------------------


def validate_inputs(args: argparse.Namespace) -> bool:
    """Check that all required files exist and topic ID is valid. Returns True if ok."""
    ok = True

    topics_path = Path(args.topic_file)
    template_path = Path(args.prompt_template)
    runner_path = Path(args.llm_runner_path)
    settings_path = Path(args.settings)

    # Check topic file
    if not topics_path.exists():
        log(f"FAIL: topic file not found: {topics_path}")
        ok = False
    else:
        log(f"  OK: topic file: {topics_path}")
        # Check topic ID
        try:
            topic = load_topic(topics_path, args.topic_id)
            log(f"  OK: topic '{args.topic_id}' found: {topic.get('title', topic.get('id', '?'))}")
        except ValueError as e:
            log(f"FAIL: {e}")
            ok = False

    # Check template
    if not template_path.exists():
        log(f"FAIL: prompt template not found: {template_path}")
        ok = False
    else:
        log(f"  OK: prompt template: {template_path}")

    # Check runner
    if not runner_path.exists():
        log(f"FAIL: llm_runner not found: {runner_path}")
        ok = False
    else:
        log(f"  OK: llm_runner: {runner_path}")

    # Check settings
    if not settings_path.exists():
        log(f"FAIL: model settings not found: {settings_path}")
        ok = False
    else:
        log(f"  OK: model settings: {settings_path}")

    if ok:
        log("Validation PASSED — all inputs exist and are valid.")
    else:
        log("Validation FAILED — see errors above.")

    return ok


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate research ideas from one model on one topic for GIB."
    )
    parser.add_argument("--model", required=True, help="Model name (e.g., 'opus', 'glm-5')")
    parser.add_argument("--topic-file", default=str(DEFAULT_TOPICS), help="Path to gib-topics.json")
    parser.add_argument("--topic-id", required=True, help="Topic ID to generate for")
    parser.add_argument("--count", type=int, default=3, help="Number of ideas to generate (default: 3)")
    parser.add_argument("--prompt-template", default=str(DEFAULT_PROMPT_TEMPLATE), help="Path to gib_generate.md")
    parser.add_argument("--llm-runner-path", default=str(DEFAULT_LLM_RUNNER), help="Path to llm_runner.py")
    parser.add_argument("--settings", default=str(DEFAULT_MODEL_SETTINGS), help="Path to model-settings.json")
    parser.add_argument("--output", default="-", help="Output path (default: stdout)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument("--temperature", type=float, default=0.9, help="Generation temperature")
    parser.add_argument("--max-tokens", type=int, default=4096, help="Max generation tokens")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument("--validate", action="store_true", help="Validate inputs only, no generation")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Validation-only mode
    if args.validate:
        log("=== GIB Idea Generator — Validation Mode ===")
        ok = validate_inputs(args)
        sys.exit(0 if ok else 1)

    # Generation mode
    log(f"=== GIB Idea Generator ===")
    log(f"Model: {args.model}")
    log(f"Topic: {args.topic_id}")
    log(f"Count: {args.count}")
    log(f"Temperature: {args.temperature}")
    log(f"Seed: {args.seed}")

    ideas = generate_ideas(args)

    # Build output envelope
    output = {
        "metadata": {
            "model": args.model,
            "topic_id": args.topic_id,
            "requested_count": args.count,
            "generated_count": len(ideas),
            "temperature": args.temperature,
            "seed": args.seed,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "ideas": ideas,
    }

    # Write output
    indent = 2 if args.pretty else None
    json_str = json.dumps(output, indent=indent) + "\n"

    if args.output == "-":
        sys.stdout.write(json_str)
    else:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json_str, encoding="utf-8")
        log(f"Output written to {out_path}")

    log(f"Done: {len(ideas)}/{args.count} ideas generated.")


if __name__ == "__main__":
    main()
