#!/usr/bin/env python3
"""Ralph Loop — session lifecycle and LLM call manager.

Handles session initialization, LLM iteration execution, iteration logging,
and session report generation. Delegates model routing to the llm_route module.

CLI:
    --init --session <id> --preset <name> --state-dir <path>
    --run --model <name> --prompt-file <path> --output <path> --iteration <n> --state-dir <path>
    --log-iteration --session <id> --iteration <n> --model <name> --result-file <path> --state-dir <path>
    --report --session <id> --state-dir <path>
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Import llm_route from the LLM skill
_LLM_SCRIPTS = str(Path.home() / ".claude" / "skills" / "llm" / "scripts")
if _LLM_SCRIPTS not in sys.path:
    sys.path.insert(0, _LLM_SCRIPTS)
import llm_route  # noqa: E402

# Paths and defaults
RALPH_DIR = Path.home() / ".claude" / "skills" / "ralph"
CONFIG_PATH = RALPH_DIR / "settings" / "ralph-config.json"
PRESETS_DIR = RALPH_DIR / "settings" / "presets"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TIMEOUT = 600


def load_config() -> dict:
    """Load ralph-config.json."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Ralph config not found: {CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text())


def load_preset(preset_name: str) -> dict:
    """Load a preset JSON file from the presets directory."""
    preset_path = PRESETS_DIR / f"{preset_name}.json"
    if not preset_path.exists():
        available = [p.stem for p in PRESETS_DIR.glob("*.json")]
        raise FileNotFoundError(
            f"Preset '{preset_name}' not found at {preset_path}. "
            f"Available: {', '.join(available) or 'none'}"
        )
    return json.loads(preset_path.read_text())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# --init
# ---------------------------------------------------------------------------
def cmd_init(session_id: str, preset_name: str, state_dir: Path) -> None:
    """Initialize a new session with empty state files."""
    state_dir.mkdir(parents=True, exist_ok=True)
    preset = load_preset(preset_name)  # validate preset exists
    config = load_config()
    loop_cfg = config.get("loop", {})

    _write_json(state_dir / "session.json", {
        "session_id": session_id,
        "preset": preset_name,
        "started_at": time.time(),
        "iteration": 0,
        "status": "running",
        "config_snapshot": {
            "max_iterations": loop_cfg.get("max_iterations", 200),
            "max_runtime_hours": loop_cfg.get("max_runtime_hours", 8),
        },
        "top3_history": [],
    })
    _write_json(state_dir / "ideas-bank.json", {
        "ideas": [],
        "stats": {
            "total": 0, "unique": 0, "duplicates": 0,
            "avg_combined_score": 0.0, "top3_ids": [],
        },
    })
    _write_json(state_dir / "memory.json", {
        "patterns": [], "decisions": [], "fixes": [], "signs": [],
    })
    _write_json(state_dir / "circuit-state.json", {})
    (state_dir / "iterations.jsonl").write_text("")

    print(
        f"Session '{session_id}' initialized.\n"
        f"  Preset : {preset_name}\n"
        f"  Bank   : ideas-bank.json\n"
        f"  State  : {state_dir}\n"
        f"  Files  : session.json, ideas-bank.json, memory.json, "
        f"circuit-state.json, iterations.jsonl"
    )


# ---------------------------------------------------------------------------
# --run
# ---------------------------------------------------------------------------
def cmd_run(
    model_name: str,
    prompt_file: Path,
    output_path: Path,
    iteration: int,
    state_dir: Path,
) -> None:
    """Run a single LLM call and write the result JSON to --output."""
    if not prompt_file.exists():
        _fail(f"Prompt file not found: {prompt_file}")
    prompt = prompt_file.read_text()
    if not prompt.strip():
        _fail(f"Prompt file is empty: {prompt_file}")

    # Read optional system prompt from <prompt-file>.system
    system_file = Path(str(prompt_file) + ".system")
    system: str | None = None
    if system_file.exists():
        system = system_file.read_text().strip() or None

    # LLM call params from config
    config = load_config()
    llm_cfg = config.get("llm_call", {})
    max_tokens = llm_cfg.get("max_tokens", DEFAULT_MAX_TOKENS)
    timeout = llm_cfg.get("timeout", DEFAULT_TIMEOUT)
    sys_max_len = llm_cfg.get("system_prompt_max_length")
    if system and sys_max_len and len(system) > sys_max_len:
        system = system[:sys_max_len]

    # Resolve model via llm_route
    registry = llm_route.load_registry()
    try:
        model_config = llm_route.resolve_model(model_name, registry)
    except ValueError as e:
        _write_result(output_path, model_name, iteration, "", 0.0, False, str(e))
        _fail(str(e))

    # Execute LLM call
    t0 = time.monotonic()
    try:
        response = llm_route.call_model(
            model_config, prompt,
            system=system, max_tokens=max_tokens,
            timeout=timeout, registry=registry,
        )
        duration = time.monotonic() - t0
        _write_result(output_path, model_name, iteration, response, duration, True, None)
        print(
            f"Iteration {iteration} complete. Model: {model_name}, "
            f"Duration: {duration:.1f}s, Response: {len(response)} chars"
        )
    except Exception as e:
        duration = time.monotonic() - t0
        error_msg = f"{type(e).__name__}: {e}"
        _write_result(output_path, model_name, iteration, "", duration, False, error_msg)
        _fail(f"LLM call failed: {error_msg}")


def _write_result(
    output_path: Path, model: str, iteration: int,
    response: str, duration: float, success: bool, error: str | None,
) -> None:
    """Write result JSON to the output file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({
        "model": model,
        "iteration": iteration,
        "response": response,
        "duration_seconds": round(duration, 2),
        "success": success,
        "error": error,
        "timestamp": _now_iso(),
    }, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# --log-iteration
# ---------------------------------------------------------------------------
def cmd_log_iteration(
    session_id: str, iteration: int, model_name: str,
    result_file: Path, state_dir: Path,
) -> None:
    """Read a result JSON and append a summary line to iterations.jsonl."""
    if not result_file.exists():
        _fail(f"Result file not found: {result_file}")

    result = json.loads(result_file.read_text())
    entry = {
        "iteration": iteration,
        "model": model_name,
        "timestamp": result.get("timestamp", _now_iso()),
        "duration_seconds": result.get("duration_seconds", 0.0),
        "success": result.get("success", False),
        "idea_id": result.get("idea_id", ""),
        "combined_score": result.get("combined_score", 0.0),
        "is_duplicate": result.get("is_duplicate", False),
    }

    with open(state_dir / "iterations.jsonl", "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # Update session.json iteration counter
    session_path = state_dir / "session.json"
    if session_path.exists():
        session = json.loads(session_path.read_text())
        session["iteration"] = iteration
        _write_json(session_path, session)

    print(
        f"Logged iteration {iteration}: model={model_name}, "
        f"success={entry['success']}, score={entry['combined_score']}"
    )


# ---------------------------------------------------------------------------
# --report
# ---------------------------------------------------------------------------
def cmd_report(session_id: str, state_dir: Path) -> None:
    """Print a human-readable session report from state files."""
    session_path = state_dir / "session.json"
    if not session_path.exists():
        _fail(f"Session file not found: {session_path}")

    session = json.loads(session_path.read_text())
    iterations: list[dict] = []
    log_path = state_dir / "iterations.jsonl"
    if log_path.exists():
        for line in log_path.read_text().splitlines():
            if line.strip():
                iterations.append(json.loads(line))

    bank: dict = {}
    bank_path = state_dir / "ideas-bank.json"
    if bank_path.exists():
        bank = json.loads(bank_path.read_text())
    stats = bank.get("stats", {})

    total = len(iterations)
    successful = sum(1 for it in iterations if it.get("success"))
    duplicates = sum(1 for it in iterations if it.get("is_duplicate"))
    started_at = session.get("started_at", 0)
    elapsed_h = (time.time() - started_at) / 3600 if started_at else 0

    # Model usage
    mcounts: dict[str, int] = {}
    mdur: dict[str, float] = {}
    for it in iterations:
        m = it.get("model", "unknown")
        mcounts[m] = mcounts.get(m, 0) + 1
        mdur[m] = mdur.get(m, 0.0) + it.get("duration_seconds", 0.0)

    # Top scores
    scored = sorted(
        [it for it in iterations if it.get("combined_score", 0) > 0],
        key=lambda x: x.get("combined_score", 0), reverse=True,
    )[:5]

    durations = [it.get("duration_seconds", 0) for it in iterations if it.get("success")]
    avg_dur = sum(durations) / len(durations) if durations else 0

    sep = "=" * 60
    print(f"\n{sep}")
    print("  RALPH SESSION REPORT")
    print(sep)
    print(f"  Session ID   : {session.get('session_id', session_id)}")
    print(f"  Preset       : {session.get('preset', '?')}")
    print(f"  Status       : {session.get('status', '?')}")
    print(f"  Runtime      : {elapsed_h:.2f} hours")
    print(f"  State dir    : {state_dir}")
    print(f"\n  ITERATIONS\n  {'-' * 40}")
    print(f"  Total        : {total}")
    print(f"  Successful   : {successful}")
    print(f"  Failed       : {total - successful}")
    print(f"  Duplicates   : {duplicates}")
    print(f"  Avg duration : {avg_dur:.1f}s")
    print(f"\n  IDEAS\n  {'-' * 40}")
    print(f"  Total ideas  : {stats.get('total', 0)}")
    print(f"  Unique ideas : {stats.get('unique', 0)}")
    print(f"  Avg score    : {stats.get('avg_combined_score', 0):.3f}")
    print(f"  Top 3 IDs    : {', '.join(stats.get('top3_ids', [])) or 'none'}")

    if mcounts:
        print(f"\n  MODEL USAGE\n  {'-' * 40}")
        print(f"  {'Model':20s}  {'Calls':>6s}  {'Total (s)':>10s}  {'Avg (s)':>8s}")
        for m in sorted(mcounts, key=lambda x: mcounts[x], reverse=True):
            c = mcounts[m]
            d = mdur.get(m, 0)
            print(f"  {m:20s}  {c:6d}  {d:10.1f}  {d/c:8.1f}")

    if scored:
        print(f"\n  TOP 5 SCORES\n  {'-' * 40}")
        print(f"  {'Iter':>5s}  {'Model':15s}  {'Score':>7s}  {'Idea ID'}")
        for it in scored:
            print(
                f"  {it.get('iteration', 0):5d}  {it.get('model', '?'):15s}  "
                f"{it.get('combined_score', 0):7.3f}  {it.get('idea_id', '')}"
            )

    print(f"\n{sep}\n")


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ralph Loop — session lifecycle and LLM call manager.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --init --session s001 --preset idea-generation --state-dir /tmp/ralph/s001\n"
            "  %(prog)s --run --model opus --prompt-file p.txt --output r.json --iteration 1 --state-dir /tmp/ralph/s001\n"
            "  %(prog)s --log-iteration --session s001 --iteration 1 --model opus --result-file r.json --state-dir /tmp/ralph/s001\n"
            "  %(prog)s --report --session s001 --state-dir /tmp/ralph/s001\n"
        ),
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--init", action="store_true", help="Initialize a new session")
    mode.add_argument("--run", action="store_true", help="Run a single LLM iteration")
    mode.add_argument("--log-iteration", action="store_true", help="Log an iteration result")
    mode.add_argument("--report", action="store_true", help="Generate session report")

    parser.add_argument("--session", help="Session ID")
    parser.add_argument("--state-dir", type=Path, help="Path to session state directory")
    parser.add_argument("--preset", help="Preset name (for --init)")
    parser.add_argument("--model", help="Model name (for --run, --log-iteration)")
    parser.add_argument("--prompt-file", type=Path, help="Prompt text file (for --run)")
    parser.add_argument("--output", type=Path, help="Result JSON output path (for --run)")
    parser.add_argument("--iteration", type=int, help="Iteration number")
    parser.add_argument("--result-file", type=Path, help="Result JSON input (for --log-iteration)")

    args = parser.parse_args()

    try:
        if args.init:
            for req in ("session", "preset", "state_dir"):
                if not getattr(args, req):
                    parser.error(f"--{req.replace('_', '-')} is required for --init")
            cmd_init(args.session, args.preset, args.state_dir)

        elif args.run:
            for req in ("model", "prompt_file", "output", "state_dir"):
                if not getattr(args, req):
                    parser.error(f"--{req.replace('_', '-')} is required for --run")
            if args.iteration is None:
                parser.error("--iteration is required for --run")
            cmd_run(args.model, args.prompt_file, args.output, args.iteration, args.state_dir)

        elif args.log_iteration:
            for req in ("session", "model", "result_file", "state_dir"):
                if not getattr(args, req):
                    parser.error(f"--{req.replace('_', '-')} is required for --log-iteration")
            if args.iteration is None:
                parser.error("--iteration is required for --log-iteration")
            cmd_log_iteration(
                args.session, args.iteration, args.model,
                args.result_file, args.state_dir,
            )

        elif args.report:
            for req in ("session", "state_dir"):
                if not getattr(args, req):
                    parser.error(f"--{req.replace('_', '-')} is required for --report")
            cmd_report(args.session, args.state_dir)

    except FileNotFoundError as e:
        _fail(str(e))
    except json.JSONDecodeError as e:
        _fail(f"Invalid JSON: {e}")
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
