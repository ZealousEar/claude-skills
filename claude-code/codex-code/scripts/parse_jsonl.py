#!/usr/bin/env python3
"""
parse_jsonl.py — Parse Codex CLI JSONL event streams into structured reports.

Reads JSONL output from `codex exec --json` and extracts:
- Agent status (success/failure/timeout)
- Session IDs (for resume)
- File changes
- Error messages
- Token usage
- Execution timeline

Usage:
    python3 parse_jsonl.py --input <jsonl_file> [--pretty] [--summary] [--session-id]
    cat events.jsonl | python3 parse_jsonl.py --stdin [--pretty]
"""

import json
import sys
import argparse
from pathlib import Path


def parse_jsonl_file(filepath: str) -> list[dict]:
    """Parse a JSONL file into a list of event dicts."""
    events = []
    path = Path(filepath)
    if not path.exists():
        return events
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                # Non-JSON lines (progress text, etc.) — skip
                continue
    return events


def parse_jsonl_stdin() -> list[dict]:
    """Parse JSONL from stdin."""
    events = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def extract_report(events: list[dict]) -> dict:
    """Extract a structured report from parsed JSONL events."""
    report = {
        "session_id": None,
        "status": "unknown",
        "turns": 0,
        "turns_completed": 0,
        "turns_failed": 0,
        "items": [],
        "errors": [],
        "file_changes": [],
        "commands_run": [],
        "agent_messages": [],
        "final_message": None,
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0
        },
        "timeline": []
    }

    for event in events:
        etype = event.get("type", "")

        # Thread events
        if etype == "thread.started":
            report["session_id"] = event.get("thread", {}).get("id") or event.get("id")
            report["timeline"].append({"event": "thread.started"})

        # Turn events
        elif etype == "turn.started":
            report["turns"] += 1
            report["timeline"].append({"event": "turn.started", "turn": report["turns"]})

        elif etype == "turn.completed":
            report["turns_completed"] += 1
            usage = event.get("usage", {})
            report["usage"]["input_tokens"] += usage.get("input_tokens", 0)
            report["usage"]["output_tokens"] += usage.get("output_tokens", 0)
            report["usage"]["total_tokens"] += (
                usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            )
            report["timeline"].append({
                "event": "turn.completed",
                "turn": report["turns"],
                "tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            })

        elif etype == "turn.failed":
            report["turns_failed"] += 1
            error_msg = event.get("error", {}).get("message", str(event.get("error", "")))
            report["errors"].append({
                "turn": report["turns"],
                "message": error_msg
            })
            report["timeline"].append({
                "event": "turn.failed",
                "turn": report["turns"],
                "error": error_msg
            })

        # Item events
        elif etype == "item.completed":
            item = event.get("item", {})
            item_type = item.get("type", "")

            if item_type == "agent_message":
                text = item.get("text", "")
                report["agent_messages"].append(text)
                report["final_message"] = text  # Last message wins

            elif item_type == "command_execution":
                cmd = item.get("command", "")
                exit_code = item.get("exit_code", None)
                report["commands_run"].append({
                    "command": cmd,
                    "exit_code": exit_code
                })

            elif item_type == "file_change":
                report["file_changes"].append({
                    "path": item.get("path", ""),
                    "action": item.get("action", "unknown"),
                    "diff_preview": item.get("diff", "")[:200] if item.get("diff") else None
                })

            report["items"].append({
                "type": item_type,
                "id": item.get("id", "")
            })

        # Error events
        elif etype == "error":
            error_msg = event.get("message", str(event))
            report["errors"].append({"message": error_msg})

    # Determine final status
    if report["turns_failed"] > 0 and report["turns_completed"] == 0:
        report["status"] = "failed"
    elif report["turns_failed"] > 0:
        report["status"] = "partial"
    elif report["turns_completed"] > 0:
        report["status"] = "success"
    else:
        report["status"] = "unknown"

    return report


def format_summary(report: dict) -> str:
    """Format a human-readable summary from the report."""
    lines = []
    lines.append(f"Session: {report['session_id'] or 'unknown'}")
    lines.append(f"Status:  {report['status'].upper()}")
    lines.append(f"Turns:   {report['turns_completed']}/{report['turns']} completed"
                 + (f" ({report['turns_failed']} failed)" if report['turns_failed'] else ""))
    lines.append(f"Tokens:  {report['usage']['total_tokens']:,} "
                 f"(in: {report['usage']['input_tokens']:,}, "
                 f"out: {report['usage']['output_tokens']:,})")

    if report["file_changes"]:
        lines.append(f"\nFile changes ({len(report['file_changes'])}):")
        for fc in report["file_changes"]:
            lines.append(f"  {fc['action']:>8}  {fc['path']}")

    if report["commands_run"]:
        lines.append(f"\nCommands run ({len(report['commands_run'])}):")
        for cmd in report["commands_run"][:10]:  # Cap at 10
            status = "OK" if cmd["exit_code"] == 0 else f"EXIT {cmd['exit_code']}"
            lines.append(f"  [{status}] {cmd['command'][:80]}")
        if len(report["commands_run"]) > 10:
            lines.append(f"  ... and {len(report['commands_run']) - 10} more")

    if report["errors"]:
        lines.append(f"\nErrors ({len(report['errors'])}):")
        for err in report["errors"]:
            msg = err.get("message", str(err))[:120]
            lines.append(f"  - {msg}")

    if report["final_message"]:
        preview = report["final_message"][:300]
        lines.append(f"\nFinal message preview:\n  {preview}")
        if len(report["final_message"]) > 300:
            lines.append("  ...")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Parse Codex CLI JSONL events")
    parser.add_argument("--input", "-i", help="Path to JSONL file")
    parser.add_argument("--stdin", action="store_true", help="Read from stdin")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument("--summary", action="store_true", help="Human-readable summary")
    parser.add_argument("--session-id", action="store_true", help="Print only the session ID")
    parser.add_argument("--status", action="store_true", help="Print only the status")
    parser.add_argument("--final-message", action="store_true", help="Print only the final message")
    args = parser.parse_args()

    if args.stdin:
        events = parse_jsonl_stdin()
    elif args.input:
        events = parse_jsonl_file(args.input)
    else:
        parser.error("Provide --input <file> or --stdin")
        return

    report = extract_report(events)

    if args.session_id:
        print(report["session_id"] or "")
    elif args.status:
        print(report["status"])
    elif args.final_message:
        print(report["final_message"] or "")
    elif args.summary:
        print(format_summary(report))
    else:
        indent = 2 if args.pretty else None
        # Strip timeline for compact output unless pretty
        if not args.pretty:
            report.pop("timeline", None)
        print(json.dumps(report, indent=indent))


if __name__ == "__main__":
    main()
