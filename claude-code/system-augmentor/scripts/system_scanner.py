#!/usr/bin/env python3
"""System Scanner for the System Augmentor skill.

Walks the Claude Code filesystem to inventory all installed capabilities:
skills, commands, MCP servers, CLI tools, API keys, agent specs, and project configs.
Outputs a JSON manifest to stdout.

Uses only Python stdlib — no pip dependencies.

Usage:
    python3 system_scanner.py --output-json
    python3 system_scanner.py --output-json --focus "web scraping"
    python3 system_scanner.py --output-json --scan-config custom-targets.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


DEFAULT_SCAN_CONFIG = Path(__file__).parent.parent / "settings" / "scan-targets.json"


def load_scan_config(config_path: Path) -> dict:
    """Load scan target configuration."""
    if not config_path.exists():
        return get_default_config()
    return json.loads(config_path.read_text())


def get_default_config() -> dict:
    """Return built-in default scan targets."""
    home = str(Path.home())
    return {
        "claude_dirs": {
            "skills": f"{home}/.claude/skills",
            "commands": f"{home}/.claude/commands",
            "settings": f"{home}/.claude",
        },
        "config_files": {
            "mcp_global": f"{home}/.claude/mcp.json",
            "settings_global": f"{home}/.claude/settings.json",
            "settings_local": f"{home}/.claude/settings.local.json",
        },
        "cli_tools": [
            "python3", "node", "npm", "npx", "git", "gh", "docker",
            "codex", "kimi", "curl", "jq", "rg", "fzf", "fd",
            "sqlite3", "psql", "redis-cli",
            "latex", "pdflatex", "pandoc",
            "ffmpeg", "magick", "convert",
        ],
        "env_vars": [
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY",
            "MOONSHOT_API_KEY", "GROQ_API_KEY", "TOGETHER_API_KEY",
            "HUGGING_FACE_HUB_TOKEN", "REPLICATE_API_TOKEN",
            "GITHUB_TOKEN", "GH_TOKEN",
            "AWS_ACCESS_KEY_ID", "GOOGLE_APPLICATION_CREDENTIALS",
            "SERPAPI_API_KEY", "BROWSERLESS_API_KEY",
        ],
        "project_markers": [
            "CLAUDE.md", ".claude/", "package.json", "pyproject.toml",
            "requirements.txt", "Cargo.toml", "go.mod",
        ],
    }


def scan_directory(dir_path: str, item_type: str) -> list[dict]:
    """Scan a directory and return discovered items."""
    results = []
    path = Path(dir_path).expanduser()
    if not path.exists() or not path.is_dir():
        return results

    for entry in sorted(path.iterdir()):
        if entry.name.startswith("."):
            continue
        item = {
            "name": entry.name,
            "type": item_type,
            "path": str(entry),
            "is_dir": entry.is_dir(),
        }
        if entry.is_file():
            item["size_bytes"] = entry.stat().st_size
            item["extension"] = entry.suffix
        elif entry.is_dir():
            # Count files in subdirectory
            try:
                item["file_count"] = sum(
                    1 for f in entry.rglob("*") if f.is_file() and not f.name.startswith(".")
                )
            except PermissionError:
                item["file_count"] = -1
            # Check for SKILL.md or other metadata
            skill_md = entry / "SKILL.md"
            if skill_md.exists():
                item["has_skill_md"] = True
                # Extract name/description from YAML frontmatter
                item["metadata"] = extract_frontmatter(skill_md)
        results.append(item)
    return results


def extract_frontmatter(filepath: Path) -> dict:
    """Extract YAML frontmatter fields from a markdown file."""
    meta = {}
    try:
        text = filepath.read_text()
    except (OSError, UnicodeDecodeError):
        return meta

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return meta

    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if key and value:
                meta[key] = value
    return meta


def scan_config_file(filepath: str) -> dict | None:
    """Read and summarize a JSON config file."""
    path = Path(filepath).expanduser()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        result = {
            "path": str(path),
            "exists": True,
            "top_level_keys": list(data.keys()),
        }
        # Extract specific useful info per config type
        if "mcpServers" in data:
            result["mcp_servers"] = list(data["mcpServers"].keys())
            result["mcp_server_details"] = {}
            for name, cfg in data["mcpServers"].items():
                result["mcp_server_details"][name] = {
                    "command": cfg.get("command", ""),
                    "args": cfg.get("args", []),
                }
        if "permissions" in data:
            perms = data["permissions"]
            result["permission_mode"] = perms.get("defaultMode", "unknown")
            result["allowed_tools"] = perms.get("allow", [])
        if "enabledPlugins" in data:
            result["plugins"] = list(data["enabledPlugins"].keys())
        return result
    except (json.JSONDecodeError, OSError):
        return {"path": str(path), "exists": True, "error": "failed to parse"}


def scan_cli_tools(tool_list: list[str]) -> list[dict]:
    """Check which CLI tools are available on PATH."""
    results = []
    for tool in tool_list:
        location = shutil.which(tool)
        results.append({
            "name": tool,
            "available": location is not None,
            "path": location,
        })
    return results


def scan_env_vars(var_list: list[str]) -> list[dict]:
    """Check which environment variables are set (existence only, not values)."""
    results = []
    for var in var_list:
        results.append({
            "name": var,
            "is_set": var in os.environ,
        })
    return results


def scan_project_context(cwd: str, markers: list[str]) -> dict:
    """Scan current working directory for project context."""
    path = Path(cwd)
    result = {
        "cwd": str(path),
        "exists": path.exists(),
        "markers_found": [],
        "markers_missing": [],
    }
    if not path.exists():
        return result

    for marker in markers:
        target = path / marker
        if target.exists():
            result["markers_found"].append(marker)
        else:
            result["markers_missing"].append(marker)

    # Check for agent specs in Metaresearch/agents/
    agents_dir = path / "Metaresearch" / "agents"
    if agents_dir.exists() and agents_dir.is_dir():
        result["agent_specs"] = [
            f.name for f in sorted(agents_dir.iterdir())
            if f.is_file() and f.suffix == ".md"
        ]

    return result


def scan_api_key_stores() -> list[dict]:
    """Scan for API key storage locations (existence only, never read values)."""
    results = []
    home = Path.home()

    key_stores = [
        ("debate-agent-env", home / ".claude/skills/convolutional-debate-agent/api-keys/provider-keys.env"),
        ("debate-agent-oauth", home / ".claude/skills/convolutional-debate-agent/api-keys/openai-oauth.json"),
        ("global-env", home / ".env"),
        ("project-env", Path.cwd() / ".env"),
    ]

    for name, path in key_stores:
        results.append({
            "name": name,
            "path": str(path),
            "exists": path.exists(),
        })

    return results


def apply_focus_filter(manifest: dict, focus: str) -> dict:
    """Filter manifest to items relevant to the focus keyword."""
    focus_lower = focus.lower()
    filtered = {}

    for key, value in manifest.items():
        if isinstance(value, list):
            filtered_list = []
            for item in value:
                if isinstance(item, dict):
                    # Check if focus keyword appears in any string value
                    item_str = json.dumps(item).lower()
                    if focus_lower in item_str:
                        filtered_list.append(item)
                elif isinstance(item, str) and focus_lower in item.lower():
                    filtered_list.append(item)
            if filtered_list:
                filtered[key] = filtered_list
            else:
                filtered[key] = value  # Keep all if no matches (don't hide context)
        elif isinstance(value, dict):
            item_str = json.dumps(value).lower()
            if focus_lower in item_str:
                filtered[key] = value
            else:
                filtered[key] = value  # Keep for context
        else:
            filtered[key] = value

    filtered["_focus"] = focus
    return filtered


def run_scan(scan_config: dict, focus: str | None = None) -> dict:
    """Execute the full system scan and return the manifest."""
    manifest = {
        "_scanner_version": "1.0.0",
        "_scan_source": "system-augmentor",
    }

    # 1. Scan skills directory
    skills_dir = scan_config.get("claude_dirs", {}).get("skills", "")
    if skills_dir:
        manifest["skills"] = scan_directory(skills_dir, "skill")

    # 2. Scan commands directory
    commands_dir = scan_config.get("claude_dirs", {}).get("commands", "")
    if commands_dir:
        manifest["commands"] = scan_directory(commands_dir, "command")

    # 3. Scan config files
    config_files = scan_config.get("config_files", {})
    manifest["config_files"] = {}
    for label, filepath in config_files.items():
        result = scan_config_file(filepath)
        if result:
            manifest["config_files"][label] = result

    # 4. Scan CLI tools
    cli_tools = scan_config.get("cli_tools", [])
    manifest["cli_tools"] = scan_cli_tools(cli_tools)

    # 5. Scan env vars
    env_vars = scan_config.get("env_vars", [])
    manifest["env_vars"] = scan_env_vars(env_vars)

    # 6. Scan project context
    manifest["project_context"] = scan_project_context(
        os.getcwd(),
        scan_config.get("project_markers", []),
    )

    # 7. Scan API key stores
    manifest["api_key_stores"] = scan_api_key_stores()

    # Apply focus filter if specified
    if focus:
        manifest = apply_focus_filter(manifest, focus)

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan Claude Code system to inventory capabilities."
    )
    parser.add_argument(
        "--output-json",
        action="store_true",
        help="Output manifest as JSON (required)",
    )
    parser.add_argument(
        "--focus",
        type=str,
        default=None,
        help="Filter results to items matching this keyword",
    )
    parser.add_argument(
        "--scan-config",
        type=Path,
        default=DEFAULT_SCAN_CONFIG,
        help="Path to scan-targets.json config file",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output",
    )
    args = parser.parse_args()

    if not args.output_json:
        parser.error("--output-json is required")

    scan_config = load_scan_config(args.scan_config)
    manifest = run_scan(scan_config, focus=args.focus)

    indent = 2 if args.pretty else None
    print(json.dumps(manifest, indent=indent))


if __name__ == "__main__":
    main()
