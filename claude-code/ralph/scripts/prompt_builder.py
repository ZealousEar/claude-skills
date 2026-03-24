#!/usr/bin/env python3
"""Prompt assembly with creative lenses for the Ralph Loop.

Builds the prompt for each iteration by combining:
- The preset's prompt template (role, task, creative_lens_instruction)
- A randomly-selected creative lens (with recency-based exclusion)
- Anti-repetition context from previously generated ideas
- Memory insights (patterns and signs from prior runs)

Usage:
    python prompt_builder.py \
        --model opus --preset idea-generation \
        --memory /path/to/memory.json --ideas-bank /path/to/ideas-bank.json \
        --iteration 7 --output /tmp/prompt.txt --config ralph-config.json
    → writes user prompt to /tmp/prompt.txt
    → writes system prompt to /tmp/prompt.txt.system
    → prints {"lens_id": "...", "lens_name": "..."} to stdout
"""

import argparse
import json
import os
import random
import re
import sys
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("~/.claude/skills/ralph/settings/ralph-config.json").expanduser()


# ---------------------------------------------------------------------------
# Config & file loading
# ---------------------------------------------------------------------------

def load_json(path: str) -> dict:
    """Load a JSON file. Returns {} on missing or invalid."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def load_config(config_path: str) -> dict:
    """Load ralph-config.json."""
    cfg = load_json(config_path)
    if not cfg:
        print(f"ERROR: Cannot load config from {config_path}", file=sys.stderr)
        sys.exit(1)
    return cfg


def load_preset(preset_name: str) -> dict:
    """Load a preset from the presets directory."""
    preset_path = Path(f"~/.claude/skills/ralph/settings/presets/{preset_name}.json").expanduser()
    preset = load_json(str(preset_path))
    if not preset:
        print(f"ERROR: Cannot load preset '{preset_name}' from {preset_path}", file=sys.stderr)
        sys.exit(1)
    if "prompt_template" not in preset:
        print(f"ERROR: Preset '{preset_name}' missing 'prompt_template' section", file=sys.stderr)
        sys.exit(1)
    return preset


# ---------------------------------------------------------------------------
# YAML parser — manual, stdlib-only
# ---------------------------------------------------------------------------

def parse_creative_lenses_yaml(path: str) -> list[dict]:
    """Parse the creative-lenses.yaml file manually.

    Expected format:
        lenses:
          - id: inversion
            name: "Inversion Lens"
            prompt: "Instead of solving..."
          - id: cross_pollination
            ...

    Returns list of dicts with keys: id, name, prompt.
    """
    try:
        with open(path, "r") as f:
            lines = f.readlines()
    except OSError as e:
        print(f"ERROR: Cannot read creative lenses from {path}: {e}", file=sys.stderr)
        sys.exit(1)

    lenses = []
    current: dict | None = None

    for line in lines:
        stripped = line.rstrip("\n")

        # Skip comments and blank lines
        if stripped.lstrip().startswith("#") or not stripped.strip():
            continue

        # New lens entry: "  - id: <value>"
        match_id = re.match(r'^\s+-\s+id:\s*(.+)$', stripped)
        if match_id:
            if current is not None:
                lenses.append(current)
            current = {"id": match_id.group(1).strip(), "name": "", "prompt": ""}
            continue

        # Name field: "    name: <value>"
        match_name = re.match(r'^\s+name:\s*(.+)$', stripped)
        if match_name and current is not None:
            current["name"] = _unquote(match_name.group(1).strip())
            continue

        # Prompt field: "    prompt: <value>"
        match_prompt = re.match(r'^\s+prompt:\s*(.+)$', stripped)
        if match_prompt and current is not None:
            current["prompt"] = _unquote(match_prompt.group(1).strip())
            continue

    # Don't forget the last entry
    if current is not None:
        lenses.append(current)

    if not lenses:
        print(f"ERROR: No lenses found in {path}", file=sys.stderr)
        sys.exit(1)

    return lenses


def _unquote(s: str) -> str:
    """Remove surrounding double quotes and unescape common sequences."""
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
        s = s.replace('\\"', '"')
        s = s.replace("\\n", "\n")
        s = s.replace("\\t", "\t")
        s = s.replace("\\\\", "\\")
    return s


# ---------------------------------------------------------------------------
# Lens selection — recency-aware
# ---------------------------------------------------------------------------

def select_lens(lenses: list[dict], memory: dict, recency_window: int = 5) -> dict:
    """Select a creative lens, avoiding recently used ones.

    Reads memory['decisions'] for entries with type == 'lens_selection'
    to determine which lenses were used in the last `recency_window` iterations.
    """
    # Extract recent lens IDs from memory decisions
    recent_lens_ids: list[str] = []
    decisions = memory.get("decisions", [])
    if isinstance(decisions, list):
        # Collect lens_selection decisions, ordered by iteration (ascending)
        lens_decisions = [
            d for d in decisions
            if isinstance(d, dict) and d.get("type") == "lens_selection"
        ]
        # Sort by iteration if available, take last N
        lens_decisions.sort(key=lambda d: d.get("iteration", 0))
        recent_lens_ids = [
            d["lens_id"]
            for d in lens_decisions[-recency_window:]
            if "lens_id" in d
        ]

    all_ids = {lens["id"] for lens in lenses}
    recent_set = set(recent_lens_ids)

    # Eligible = not used in last recency_window iterations
    eligible = [lens for lens in lenses if lens["id"] not in recent_set]

    if not eligible:
        # All lenses used recently — pick the least-recently-used
        # recent_lens_ids is chronological; find the one used earliest
        lru_id = None
        for rid in recent_lens_ids:
            if rid in all_ids:
                lru_id = rid
                break  # first in chronological order = least recently used
        if lru_id:
            eligible = [lens for lens in lenses if lens["id"] == lru_id]
        else:
            # Fallback: pick any lens
            eligible = lenses

    return random.choice(eligible)


# ---------------------------------------------------------------------------
# Anti-repetition context from ideas bank
# ---------------------------------------------------------------------------

def build_anti_repetition_context(ideas_bank: dict) -> str:
    """Extract titles and novelty claims from existing ideas for anti-repetition."""
    ideas = ideas_bank.get("ideas", [])
    if not ideas:
        return ""

    lines = []
    for i, idea in enumerate(ideas, 1):
        title = idea.get("title", "Untitled")
        novelty = idea.get("novelty_claim", "")
        entry = f"{i}. {title}"
        if novelty:
            entry += f" — {novelty}"
        lines.append(entry)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Memory context extraction
# ---------------------------------------------------------------------------

def build_memory_context(memory: dict) -> str:
    """Extract patterns and signs from memory for context injection."""
    sections = []

    # Patterns
    patterns = memory.get("patterns", [])
    if isinstance(patterns, list) and patterns:
        pattern_lines = []
        for p in patterns:
            if isinstance(p, dict):
                desc = p.get("description", p.get("pattern", str(p)))
            else:
                desc = str(p)
            pattern_lines.append(f"- {desc}")
        if pattern_lines:
            sections.append("Observed patterns from prior iterations:\n" + "\n".join(pattern_lines))

    # Signs (convergence signals, quality signals, etc.)
    signs = memory.get("signs", [])
    if isinstance(signs, list) and signs:
        sign_lines = []
        for s in signs:
            if isinstance(s, dict):
                desc = s.get("description", s.get("sign", str(s)))
            else:
                desc = str(s)
            sign_lines.append(f"- {desc}")
        if sign_lines:
            sections.append("Signals from prior iterations:\n" + "\n".join(sign_lines))

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

def build_literature_context(lit_data: dict) -> str:
    """Format literature gaps data into a prompt section.

    lit_data: parsed JSON from gap_extractor.py --papers-db output.
    """
    sections = []

    # Gap directives with related literature
    gaps = lit_data.get("gaps", [])
    if gaps:
        gap_lines = []
        for g in gaps[:15]:  # Cap to avoid prompt bloat
            line = f"- {g.get('directive', '')}"
            related = g.get("related_literature", [])
            if related:
                line += f" (related: {', '.join(related[:3])})"
            gap_lines.append(line)
        sections.append("Portfolio gap directives:\n" + "\n".join(gap_lines))

    # Literature coverage gaps
    lit_gaps = lit_data.get("literature_gaps", [])
    if lit_gaps:
        lit_lines = []
        for lg in lit_gaps[:10]:
            lit_lines.append(
                f"- {lg['method']} × {lg['domain']}: {lg['paper_count']} papers"
            )
        sections.append(
            "Under-studied method×domain intersections in the literature corpus:\n"
            + "\n".join(lit_lines)
        )

    return "\n\n".join(sections) if sections else ""


def build_system_prompt(
    preset: dict,
    anti_rep_context: str,
    memory_context: str,
    max_length: int,
    literature_context: str = "",
) -> str:
    """Assemble the system prompt from preset role, anti-repetition, memory, and literature."""
    template = preset["prompt_template"]
    parts = [template["role"]]

    # Calculate budget for anti-repetition after accounting for role + memory + literature
    base_len = len(parts[0])
    memory_section = ""
    if memory_context:
        memory_section = f"\n\n## Context from Prior Iterations\n{memory_context}"
    lit_section = ""
    if literature_context:
        lit_section = f"\n\n## Literature-Grounded Gap Directives\n{literature_context}"
    overhead = base_len + len(memory_section) + len(lit_section) + 200  # 200 chars buffer

    if anti_rep_context:
        header = "\n\n## Anti-Repetition — Existing Ideas\nThe following ideas have already been generated. You MUST NOT repeat or closely paraphrase any of them:\n"
        available = max_length - overhead - len(header)
        if available > 0:
            truncated = anti_rep_context
            if len(truncated) > available:
                # Truncate to fit, cutting at a newline boundary
                truncated = truncated[:available]
                last_newline = truncated.rfind("\n")
                if last_newline > 0:
                    truncated = truncated[:last_newline]
                truncated += "\n[... truncated for length]"
            parts.append(header + truncated)
        # else: skip anti-repetition entirely if no room

    if lit_section:
        parts.append(lit_section)

    if memory_section:
        parts.append(memory_section)

    system_prompt = "".join(parts)

    # Final safety truncation
    if len(system_prompt) > max_length:
        system_prompt = system_prompt[:max_length - 20] + "\n[... truncated]"

    return system_prompt


def build_user_prompt(preset: dict, lens: dict, iteration: int) -> str:
    """Assemble the user prompt from preset task, creative lens, and iteration."""
    template = preset["prompt_template"]
    parts = [template["task"]]

    # Insert creative lens
    lens_instruction = template.get("creative_lens_instruction", "")
    if lens_instruction and lens.get("prompt"):
        filled = lens_instruction.replace("{lens}", lens["prompt"])
        parts.append(f"\n\n{filled}")

    # Iteration context
    parts.append(f"\n\nThis is iteration {iteration}.")

    return "".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Prompt assembly with creative lenses for the Ralph Loop."
    )
    p.add_argument("--model", required=True,
                   help="Model name (for logging context)")
    p.add_argument("--preset", required=True,
                   help="Preset name (e.g. idea-generation)")
    p.add_argument("--memory", required=True,
                   help="Path to memory.json")
    p.add_argument("--ideas-bank", required=True,
                   help="Path to ideas-bank.json")
    p.add_argument("--iteration", required=True, type=int,
                   help="Current iteration number")
    p.add_argument("--output", required=True,
                   help="Path to write user prompt (system prompt written to <output>.system)")
    p.add_argument("--config", default=str(DEFAULT_CONFIG_PATH),
                   help="Path to ralph-config.json")
    p.add_argument("--literature-context", default=None,
                   help="Path to pre-computed literature gaps JSON (from gap_extractor.py)")
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # 1. Load config
    config = load_config(args.config)
    max_system_len = config.get("llm_call", {}).get("system_prompt_max_length", 8000)

    # 2. Load preset
    preset = load_preset(args.preset)

    # 3. Load creative lenses
    lenses_path = config.get("paths", {}).get("creative_lenses", "")
    if lenses_path.startswith("~"):
        lenses_path = os.path.expanduser(lenses_path)
    if not lenses_path or not os.path.isfile(lenses_path):
        print(f"ERROR: Creative lenses file not found: {lenses_path}", file=sys.stderr)
        return 1
    lenses = parse_creative_lenses_yaml(lenses_path)

    # 4. Load memory (optional)
    memory: dict = {}
    if args.memory and os.path.isfile(args.memory):
        memory = load_json(args.memory)

    # 5. Select a creative lens
    lens = select_lens(lenses, memory)

    # 6. Load ideas bank — build anti-repetition context
    anti_rep_context = ""
    if args.ideas_bank and os.path.isfile(args.ideas_bank):
        ideas_bank = load_json(args.ideas_bank)
        anti_rep_context = build_anti_repetition_context(ideas_bank)

    # 7. Build memory context (optional)
    memory_context = build_memory_context(memory)

    # 7b. Build literature context (optional)
    literature_context = ""
    lit_path = args.literature_context or os.environ.get("RALPH_LITERATURE_CONTEXT")
    if lit_path and os.path.isfile(lit_path):
        lit_data = load_json(lit_path)
        if lit_data:
            literature_context = build_literature_context(lit_data)

    # 8. Build system prompt
    system_prompt = build_system_prompt(
        preset, anti_rep_context, memory_context, max_system_len,
        literature_context=literature_context,
    )

    # 9. Build user prompt
    user_prompt = build_user_prompt(preset, lens, args.iteration)

    # 10. Write outputs
    output_path = args.output
    system_path = output_path + ".system"

    output_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(output_dir, exist_ok=True)

    try:
        with open(output_path, "w") as f:
            f.write(user_prompt)
        with open(system_path, "w") as f:
            f.write(system_prompt)
    except OSError as e:
        print(f"ERROR: Cannot write output files: {e}", file=sys.stderr)
        return 1

    # 11. Report lens selection to stdout as JSON
    result = {"lens_id": lens["id"], "lens_name": lens["name"]}
    print(json.dumps(result))

    return 0


if __name__ == "__main__":
    sys.exit(main())
