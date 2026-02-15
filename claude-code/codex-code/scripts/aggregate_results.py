#!/usr/bin/env python3
"""
aggregate_results.py — Aggregate results from N parallel Codex agents into a unified report.

Reads agent output files (from --output-schema JSON or raw text fallback),
JSONL event logs, and worktree status to produce a comprehensive execution report.

Usage:
    python3 aggregate_results.py --session <sid> [--agents N] [--pretty] [--summary]
    python3 aggregate_results.py --session <sid> --markdown
"""

import json
import sys
import argparse
import os
from pathlib import Path


TEMP_DIR = "/tmp"
FILE_PREFIX = "codex_swarm"


def find_agent_files(session_id: str, agent_num: int) -> dict:
    """Find all output files for a given agent."""
    base = f"{TEMP_DIR}/{FILE_PREFIX}_{session_id}_{agent_num}"
    return {
        "prompt": f"{base}_prompt.txt",
        "result": f"{base}_result.txt",
        "stdout": f"{base}_stdout.txt",
        "jsonl": f"{base}_events.jsonl",
    }


def read_file_safe(path: str) -> str:
    """Read a file, returning empty string if missing or empty."""
    try:
        p = Path(path)
        if p.exists() and p.stat().st_size > 0:
            return p.read_text()
    except Exception:
        pass
    return ""


def parse_structured_result(content: str) -> dict | None:
    """Try to parse a structured JSON result from --output-schema."""
    if not content.strip():
        return None
    try:
        result = json.loads(content.strip())
        if isinstance(result, dict) and "status" in result:
            return result
    except json.JSONDecodeError:
        pass
    # Try to find JSON block in text
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                result = json.loads(line)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                continue
    return None


def parse_jsonl_status(content: str) -> dict:
    """Extract status info from JSONL events."""
    info = {
        "session_id": None,
        "status": "unknown",
        "turns": 0,
        "turns_completed": 0,
        "turns_failed": 0,
        "errors": [],
        "input_tokens": 0,
        "output_tokens": 0,
    }
    if not content.strip():
        return info
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        etype = event.get("type", "")
        if etype == "thread.started":
            info["session_id"] = event.get("thread", {}).get("id") or event.get("id")
        elif etype == "turn.started":
            info["turns"] += 1
        elif etype == "turn.completed":
            info["turns_completed"] += 1
            usage = event.get("usage", {})
            info["input_tokens"] += usage.get("input_tokens", 0)
            info["output_tokens"] += usage.get("output_tokens", 0)
        elif etype == "turn.failed":
            info["turns_failed"] += 1
            info["errors"].append(event.get("error", {}).get("message", str(event.get("error", ""))))
        elif etype == "error":
            info["errors"].append(event.get("message", str(event)))

    if info["turns_failed"] > 0 and info["turns_completed"] == 0:
        info["status"] = "failed"
    elif info["turns_failed"] > 0:
        info["status"] = "partial"
    elif info["turns_completed"] > 0:
        info["status"] = "success"
    return info


def collect_agent_result(session_id: str, agent_num: int) -> dict:
    """Collect and parse results for a single agent."""
    files = find_agent_files(session_id, agent_num)
    result = {
        "agent": agent_num,
        "status": "unknown",
        "files_created": [],
        "files_modified": [],
        "summary": "",
        "errors": [],
        "session_id": None,
        "tokens": {"input": 0, "output": 0, "total": 0},
        "has_output": False,
    }

    # Try structured result first (from --output-schema / -o)
    result_content = read_file_safe(files["result"])
    if result_content:
        result["has_output"] = True
        parsed = parse_structured_result(result_content)
        if parsed:
            result["status"] = parsed.get("status", "success")
            result["files_created"] = parsed.get("files_created", [])
            result["files_modified"] = parsed.get("files_modified", [])
            result["summary"] = parsed.get("summary", "")
            result["assumptions"] = parsed.get("assumptions", [])
            result["limitations"] = parsed.get("limitations", [])
        else:
            # Raw text result
            result["status"] = "success"
            result["summary"] = result_content[:500]

    # Parse JSONL for status and tokens
    jsonl_content = read_file_safe(files["jsonl"])
    if jsonl_content:
        jsonl_info = parse_jsonl_status(jsonl_content)
        result["session_id"] = jsonl_info["session_id"]
        result["tokens"] = {
            "input": jsonl_info["input_tokens"],
            "output": jsonl_info["output_tokens"],
            "total": jsonl_info["input_tokens"] + jsonl_info["output_tokens"],
        }
        if jsonl_info["errors"]:
            result["errors"] = jsonl_info["errors"]
        # JSONL status overrides if result file was empty
        if not result["has_output"]:
            result["status"] = jsonl_info["status"]

    # Fallback to stdout if nothing else
    if not result["has_output"]:
        stdout_content = read_file_safe(files["stdout"])
        if stdout_content:
            result["has_output"] = True
            if not result["summary"]:
                result["summary"] = stdout_content[:500]
            if result["status"] == "unknown":
                result["status"] = "success"  # Got output, assume success
        else:
            result["status"] = "no_output"

    return result


def aggregate(session_id: str, agent_count: int) -> dict:
    """Aggregate results from all agents."""
    report = {
        "session_id": session_id,
        "agent_count": agent_count,
        "agents": [],
        "totals": {
            "success": 0,
            "partial": 0,
            "failed": 0,
            "no_output": 0,
            "unknown": 0,
            "files_created": 0,
            "files_modified": 0,
            "total_tokens": 0,
        }
    }

    for i in range(1, agent_count + 1):
        agent_result = collect_agent_result(session_id, i)
        report["agents"].append(agent_result)

        # Tally
        status = agent_result["status"]
        if status in report["totals"]:
            report["totals"][status] += 1
        else:
            report["totals"]["unknown"] += 1
        report["totals"]["files_created"] += len(agent_result.get("files_created", []))
        report["totals"]["files_modified"] += len(agent_result.get("files_modified", []))
        report["totals"]["total_tokens"] += agent_result["tokens"]["total"]

    return report


def format_markdown(report: dict) -> str:
    """Format the report as Markdown for display."""
    lines = []
    sid = report["session_id"]
    n = report["agent_count"]
    totals = report["totals"]

    lines.append("=" * 63)
    lines.append("              CODEXCODE SWARM — EXECUTION REPORT")
    lines.append("=" * 63)
    lines.append("")
    lines.append(f"Model: gpt-5.3-codex")
    lines.append(f"Agents: {n}")
    lines.append(f"Session: {sid}")
    lines.append("")

    for agent in report["agents"]:
        i = agent["agent"]
        status = agent["status"].upper()
        lines.append("-" * 63)
        lines.append(f"AGENT {i}")
        lines.append(f"Status: {status}")
        if agent.get("files_created"):
            lines.append(f"Files created: {', '.join(agent['files_created'])}")
        if agent.get("files_modified"):
            lines.append(f"Files modified: {', '.join(agent['files_modified'])}")
        if agent.get("session_id"):
            lines.append(f"Session ID: {agent['session_id']}")
        tokens = agent["tokens"]
        if tokens["total"] > 0:
            lines.append(f"Tokens: {tokens['total']:,} (in: {tokens['input']:,}, out: {tokens['output']:,})")
        lines.append("-" * 63)
        if agent.get("summary"):
            lines.append(agent["summary"][:300])
        if agent.get("errors"):
            lines.append(f"\nErrors:")
            for err in agent["errors"]:
                lines.append(f"  - {err[:120]}")
        lines.append("")

    lines.append("=" * 63)
    lines.append("SUMMARY")
    lines.append(f"  Completed:  {totals['success']}/{n}")
    lines.append(f"  Partial:    {totals['partial']}/{n}")
    lines.append(f"  Failed:     {totals['failed']}/{n}")
    lines.append(f"  No output:  {totals['no_output']}/{n}")
    lines.append(f"")
    lines.append(f"  Files created:  {totals['files_created']}")
    lines.append(f"  Files modified: {totals['files_modified']}")
    lines.append(f"  Total tokens:   {totals['total_tokens']:,}")
    lines.append("=" * 63)

    return "\n".join(lines)


def format_summary(report: dict) -> str:
    """Brief one-line summary."""
    t = report["totals"]
    n = report["agent_count"]
    return (f"Session {report['session_id']}: "
            f"{t['success']}/{n} success, {t['partial']}/{n} partial, "
            f"{t['failed']}/{n} failed | "
            f"{t['files_created']} created, {t['files_modified']} modified | "
            f"{t['total_tokens']:,} tokens")


def main():
    parser = argparse.ArgumentParser(description="Aggregate Codex swarm results")
    parser.add_argument("--session", "-s", required=True, help="Session ID")
    parser.add_argument("--agents", "-n", type=int, default=0,
                        help="Number of agents (auto-detect if 0)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    parser.add_argument("--summary", action="store_true", help="One-line summary")
    parser.add_argument("--markdown", action="store_true", help="Markdown report")
    args = parser.parse_args()

    # Auto-detect agent count
    agent_count = args.agents
    if agent_count <= 0:
        # Count prompt files
        prefix = f"{TEMP_DIR}/{FILE_PREFIX}_{args.session}_"
        for i in range(1, 100):
            prompt_path = f"{prefix}{i}_prompt.txt"
            if not Path(prompt_path).exists():
                agent_count = i - 1
                break
        if agent_count <= 0:
            print("ERROR: No agent files found. Specify --agents N.", file=sys.stderr)
            sys.exit(1)

    report = aggregate(args.session, agent_count)

    if args.summary:
        print(format_summary(report))
    elif args.markdown:
        print(format_markdown(report))
    else:
        indent = 2 if args.pretty else None
        print(json.dumps(report, indent=indent))


if __name__ == "__main__":
    main()
