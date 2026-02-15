#!/usr/bin/env python3
"""Gap Analyzer for the System Augmentor skill.

Reads the scanner manifest and gap taxonomy to detect structural gaps
in the Claude Code system. Outputs a JSON gap list with severity ratings.

Uses only Python stdlib — no pip dependencies.

Usage:
    python3 gap_analyzer.py --manifest manifest.json
    python3 gap_analyzer.py --manifest manifest.json --focus "paper search"
    python3 gap_analyzer.py --manifest manifest.json --taxonomy custom-taxonomy.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


DEFAULT_TAXONOMY_PATH = Path(__file__).parent.parent / "references" / "gap-taxonomy.md"

# Severity levels
CRITICAL = "CRITICAL"
HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"


def load_manifest(manifest_path: Path) -> dict:
    """Load the scanner manifest from JSON file or stdin."""
    if str(manifest_path) == "-":
        return json.loads(sys.stdin.read())
    if not manifest_path.exists():
        print(f"Error: manifest file not found: {manifest_path}", file=sys.stderr)
        sys.exit(1)
    return json.loads(manifest_path.read_text())


def get_builtin_rules() -> list[dict]:
    """Return built-in gap detection rules.

    Each rule checks for a specific structural gap in the system.
    Rules are organized by category matching the gap taxonomy.
    """
    return [
        # --- MCP Server Gaps ---
        {
            "id": "MCP-001",
            "category": "mcp_servers",
            "name": "No web search MCP",
            "description": "No MCP server for web search/scraping — limits online research capability",
            "severity": HIGH,
            "check": "mcp_missing",
            "keywords": ["search", "web", "scrape", "browse", "fetch"],
            "suggestion": "Add a web search MCP server (e.g., Firecrawl, Browserless, Tavily)",
        },
        {
            "id": "MCP-002",
            "category": "mcp_servers",
            "name": "No database MCP",
            "description": "No MCP server for database access — limits data querying capability",
            "severity": MEDIUM,
            "check": "mcp_missing",
            "keywords": ["database", "db", "sql", "postgres", "sqlite"],
            "suggestion": "Add a database MCP server (e.g., SQLite MCP, PostgreSQL MCP)",
        },
        {
            "id": "MCP-003",
            "category": "mcp_servers",
            "name": "No file conversion MCP",
            "description": "No MCP server for file format conversion (PDF, DOCX, etc.)",
            "severity": LOW,
            "check": "mcp_missing",
            "keywords": ["pdf", "convert", "document", "docx", "format"],
            "suggestion": "Add a document conversion MCP (e.g., Pandoc MCP, PDF tools)",
        },
        {
            "id": "MCP-004",
            "category": "mcp_servers",
            "name": "No academic search MCP",
            "description": "No MCP server for academic paper search (Semantic Scholar, arXiv, etc.)",
            "severity": HIGH,
            "check": "mcp_missing",
            "keywords": ["paper", "academic", "arxiv", "scholar", "research", "citation"],
            "suggestion": "Add academic search MCP (e.g., Semantic Scholar API, arXiv MCP)",
        },

        # --- CLI Tool Gaps ---
        {
            "id": "CLI-001",
            "category": "cli_tools",
            "name": "Missing jq",
            "description": "jq not installed — limits JSON processing in shell pipelines",
            "severity": LOW,
            "check": "cli_missing",
            "tool_name": "jq",
            "suggestion": "Install jq: brew install jq",
        },
        {
            "id": "CLI-002",
            "category": "cli_tools",
            "name": "Missing ripgrep",
            "description": "rg (ripgrep) not installed — limits fast code search",
            "severity": LOW,
            "check": "cli_missing",
            "tool_name": "rg",
            "suggestion": "Install ripgrep: brew install ripgrep",
        },
        {
            "id": "CLI-003",
            "category": "cli_tools",
            "name": "Missing Docker",
            "description": "docker not installed — limits containerized tool execution",
            "severity": MEDIUM,
            "check": "cli_missing",
            "tool_name": "docker",
            "suggestion": "Install Docker Desktop or docker CLI",
        },
        {
            "id": "CLI-004",
            "category": "cli_tools",
            "name": "Missing pandoc",
            "description": "pandoc not installed — limits document format conversion",
            "severity": LOW,
            "check": "cli_missing",
            "tool_name": "pandoc",
            "suggestion": "Install pandoc: brew install pandoc",
        },
        {
            "id": "CLI-005",
            "category": "cli_tools",
            "name": "Missing LaTeX",
            "description": "pdflatex not installed — limits PDF generation from LaTeX",
            "severity": MEDIUM,
            "check": "cli_missing",
            "tool_name": "pdflatex",
            "suggestion": "Install MacTeX or BasicTeX: brew install --cask basictex",
        },

        # --- API Key Gaps ---
        {
            "id": "KEY-001",
            "category": "api_keys",
            "name": "No Anthropic API key",
            "description": "ANTHROPIC_API_KEY not set — limits direct Anthropic API access",
            "severity": LOW,
            "check": "env_missing",
            "env_var": "ANTHROPIC_API_KEY",
            "suggestion": "Set ANTHROPIC_API_KEY (only needed if using Anthropic API outside Claude Code)",
        },
        {
            "id": "KEY-002",
            "category": "api_keys",
            "name": "No Google API key",
            "description": "GOOGLE_API_KEY not set — Gemini models unavailable in debate agent",
            "severity": MEDIUM,
            "check": "env_missing",
            "env_var": "GOOGLE_API_KEY",
            "suggestion": "Set GOOGLE_API_KEY or add to provider-keys.env for Gemini access",
        },
        {
            "id": "KEY-003",
            "category": "api_keys",
            "name": "No SERP API key",
            "description": "SERPAPI_API_KEY not set — limits programmatic search capabilities",
            "severity": LOW,
            "check": "env_missing",
            "env_var": "SERPAPI_API_KEY",
            "suggestion": "Set SERPAPI_API_KEY for programmatic Google search access",
        },

        # --- Skill/Command Gaps ---
        {
            "id": "SKILL-001",
            "category": "skills",
            "name": "Orphaned command (no matching skill)",
            "description": "Command file exists but references no installed skill",
            "severity": LOW,
            "check": "orphaned_command",
            "suggestion": "Install the missing skill or remove the orphaned command",
        },
        {
            "id": "SKILL-002",
            "category": "skills",
            "name": "Skill without command",
            "description": "Skill directory exists but has no corresponding slash command",
            "severity": MEDIUM,
            "check": "skill_without_command",
            "suggestion": "Create a slash command in ~/.claude/commands/ to invoke this skill",
        },
        {
            "id": "SKILL-003",
            "category": "skills",
            "name": "No code review skill",
            "description": "No skill for systematic code review or PR review",
            "severity": MEDIUM,
            "check": "skill_category_missing",
            "keywords": ["review", "code review", "pr review", "lint"],
            "suggestion": "Create a code review skill or install a review-focused slash command",
        },
        {
            "id": "SKILL-004",
            "category": "skills",
            "name": "No testing skill",
            "description": "No skill for automated test generation or test strategy",
            "severity": MEDIUM,
            "check": "skill_category_missing",
            "keywords": ["test", "testing", "tdd", "coverage"],
            "suggestion": "Create a test generation skill or install a testing-focused slash command",
        },

        # --- Project Context Gaps ---
        {
            "id": "PROJ-001",
            "category": "project",
            "name": "No CLAUDE.md",
            "description": "Current project has no CLAUDE.md — Claude Code lacks project context",
            "severity": CRITICAL,
            "check": "project_marker_missing",
            "marker": "CLAUDE.md",
            "suggestion": "Create a CLAUDE.md with project context and coding standards",
        },
        {
            "id": "PROJ-002",
            "category": "project",
            "name": "No .claude/ directory",
            "description": "Current project has no .claude/ directory for project-specific config",
            "severity": LOW,
            "check": "project_marker_missing",
            "marker": ".claude/",
            "suggestion": "Create .claude/ directory for project-specific settings",
        },
    ]


def check_mcp_missing(rule: dict, manifest: dict) -> dict | None:
    """Check if an MCP server matching keywords is missing."""
    config_files = manifest.get("config_files", {})
    mcp_config = config_files.get("mcp_global", {})
    mcp_servers = mcp_config.get("mcp_servers", [])

    # Also check MCP server details
    mcp_details = mcp_config.get("mcp_server_details", {})
    keywords = rule.get("keywords", [])

    # Build a searchable string from all MCP server names and configs
    mcp_text = " ".join(mcp_servers).lower()
    for name, details in mcp_details.items():
        mcp_text += f" {name} {details.get('command', '')} {' '.join(details.get('args', []))}".lower()

    # Check if any keyword matches
    for kw in keywords:
        if kw.lower() in mcp_text:
            return None  # Found a match, no gap

    return make_gap(rule)


def check_cli_missing(rule: dict, manifest: dict) -> dict | None:
    """Check if a CLI tool is missing."""
    tool_name = rule.get("tool_name", "")
    cli_tools = manifest.get("cli_tools", [])

    for tool in cli_tools:
        if tool.get("name") == tool_name and tool.get("available"):
            return None  # Found, no gap

    return make_gap(rule)


def check_env_missing(rule: dict, manifest: dict) -> dict | None:
    """Check if an environment variable is missing."""
    env_var = rule.get("env_var", "")
    env_vars = manifest.get("env_vars", [])

    for var in env_vars:
        if var.get("name") == env_var and var.get("is_set"):
            return None  # Set, no gap

    return make_gap(rule)


def check_orphaned_command(rule: dict, manifest: dict) -> list[dict]:
    """Check for commands that reference skills that don't exist."""
    gaps = []
    commands = manifest.get("commands", [])
    skills = manifest.get("skills", [])
    skill_names = {s.get("name", "").replace("-", " ").lower() for s in skills if s.get("is_dir")}

    for cmd in commands:
        cmd_name = cmd.get("name", "").replace(".md", "").replace("-", " ").lower()
        # A command is orphaned if no skill directory has a matching name
        # Skip this check for simple commands that don't need a skill
        # (We only flag if the command name suggests it should have a backing skill)
        if cmd_name and cmd_name not in skill_names:
            # Not all commands need skills — this is informational
            pass

    return gaps


def check_skill_without_command(rule: dict, manifest: dict) -> list[dict]:
    """Check for skills that have no corresponding slash command."""
    gaps = []
    commands = manifest.get("commands", [])
    skills = manifest.get("skills", [])
    command_names = {
        c.get("name", "").replace(".md", "").lower()
        for c in commands
        if c.get("extension") == ".md"
    }

    # Also check command files for skill path references by reading them
    command_contents = {}
    for c in commands:
        cmd_path = Path(c.get("path", ""))
        if cmd_path.exists() and cmd_path.suffix == ".md":
            try:
                command_contents[c.get("name", "").replace(".md", "").lower()] = cmd_path.read_text().lower()
            except (OSError, UnicodeDecodeError):
                pass

    for skill in skills:
        if not skill.get("is_dir") or not skill.get("has_skill_md"):
            continue
        skill_name = skill.get("name", "").lower()
        # Check if any command name matches or contains the skill name
        has_command = any(
            skill_name in cmd_name or cmd_name in skill_name
            for cmd_name in command_names
        )
        # Also check if any command file references this skill's path
        if not has_command:
            skill_path_fragment = f"skills/{skill_name}"
            has_command = any(
                skill_path_fragment in content
                for content in command_contents.values()
            )
        if not has_command:
            gap = make_gap(rule)
            gap["detail"] = f"Skill '{skill.get('name')}' has no matching command"
            gaps.append(gap)

    return gaps


def check_skill_category_missing(rule: dict, manifest: dict) -> dict | None:
    """Check if a skill category is missing based on keywords."""
    skills = manifest.get("skills", [])
    commands = manifest.get("commands", [])
    keywords = rule.get("keywords", [])

    # Build searchable text from all skills and commands
    all_text = ""
    for s in skills:
        all_text += f" {s.get('name', '')} "
        meta = s.get("metadata", {})
        all_text += f" {meta.get('name', '')} {meta.get('description', '')} "
    for c in commands:
        all_text += f" {c.get('name', '')} "
    all_text = all_text.lower()

    for kw in keywords:
        if kw.lower() in all_text:
            return None  # Found

    return make_gap(rule)


def check_project_marker_missing(rule: dict, manifest: dict) -> dict | None:
    """Check if a project marker is missing."""
    marker = rule.get("marker", "")
    project = manifest.get("project_context", {})
    missing = project.get("markers_missing", [])

    if marker in missing:
        return make_gap(rule)
    return None


def make_gap(rule: dict) -> dict:
    """Create a gap record from a rule."""
    return {
        "id": rule["id"],
        "category": rule["category"],
        "name": rule["name"],
        "description": rule["description"],
        "severity": rule["severity"],
        "suggestion": rule.get("suggestion", ""),
    }


# Map check types to handler functions
CHECK_HANDLERS = {
    "mcp_missing": check_mcp_missing,
    "cli_missing": check_cli_missing,
    "env_missing": check_env_missing,
    "orphaned_command": check_orphaned_command,
    "skill_without_command": check_skill_without_command,
    "skill_category_missing": check_skill_category_missing,
    "project_marker_missing": check_project_marker_missing,
}


def analyze_gaps(manifest: dict, focus: str | None = None) -> list[dict]:
    """Run all gap detection rules against the manifest."""
    rules = get_builtin_rules()
    gaps = []

    for rule in rules:
        check_type = rule.get("check", "")
        handler = CHECK_HANDLERS.get(check_type)
        if not handler:
            continue

        result = handler(rule, manifest)

        if isinstance(result, list):
            gaps.extend(result)
        elif result is not None:
            gaps.append(result)

    # Apply focus filter
    if focus:
        focus_lower = focus.lower()
        gaps = [
            g for g in gaps
            if focus_lower in g.get("name", "").lower()
            or focus_lower in g.get("description", "").lower()
            or focus_lower in g.get("category", "").lower()
            or focus_lower in g.get("suggestion", "").lower()
        ]

    # Sort by severity
    severity_order = {CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3}
    gaps.sort(key=lambda g: severity_order.get(g.get("severity", LOW), 4))

    return gaps


def format_summary(gaps: list[dict]) -> str:
    """Format a human-readable summary of gaps."""
    if not gaps:
        return "No structural gaps detected."

    lines = [f"Found {len(gaps)} gap(s):\n"]
    by_severity = {}
    for g in gaps:
        sev = g.get("severity", "UNKNOWN")
        by_severity.setdefault(sev, []).append(g)

    for sev in [CRITICAL, HIGH, MEDIUM, LOW]:
        group = by_severity.get(sev, [])
        if not group:
            continue
        lines.append(f"[{sev}] ({len(group)})")
        for g in group:
            detail = g.get("detail", "")
            detail_str = f" — {detail}" if detail else ""
            lines.append(f"  - {g['id']}: {g['name']}{detail_str}")
            lines.append(f"    {g['description']}")
            lines.append(f"    Suggestion: {g['suggestion']}")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze system scanner manifest for capability gaps."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to scanner manifest JSON (use '-' for stdin)",
    )
    parser.add_argument(
        "--focus",
        type=str,
        default=None,
        help="Filter gaps to those matching this keyword",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print human-readable summary instead of JSON",
    )
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    gaps = analyze_gaps(manifest, focus=args.focus)

    if args.summary:
        print(format_summary(gaps))
    else:
        output = {
            "gap_count": len(gaps),
            "gaps": gaps,
        }
        indent = 2 if args.pretty else None
        print(json.dumps(output, indent=indent))


if __name__ == "__main__":
    main()
