from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_PROMPT_TEMPLATE = Path("~/.claude/skills/geps-v5/prompts/judge_pairwise.md").expanduser()
DEFAULT_LLM_RUNNER = Path("~/.claude/skills/convolutional-debate-agent/scripts/llm_runner.py").expanduser()
RETRY_REMINDER = (
    "You must respond with ONLY valid JSON, no other text. "
    "Format: {\"winner\": \"A\"|\"B\", \"confidence\": 0.5-1.0, "
    "\"a_strengths\": \"...\", \"b_strengths\": \"...\", \"rationale\": \"...\"}"
)
PARSE_FAILURE_ERROR = "Could not parse JSON from response after 2 attempts"


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Run pairwise judge evaluation for one match.")
    parser.add_argument("--match-spec", required=True, help="Path to match specification JSON")
    parser.add_argument(
        "--prompt-template",
        default=str(DEFAULT_PROMPT_TEMPLATE),
        help="Path to judge prompt template",
    )
    parser.add_argument(
        "--llm-runner-path",
        default=str(DEFAULT_LLM_RUNNER),
        help="Path to llm_runner.py",
    )
    parser.add_argument("--output", default="-", help="Output path (default: stdout)")
    parser.add_argument("--log-dir", default=None, help="Optional audit log directory")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    return parser.parse_args()


def load_json_object(path: Path) -> dict[str, object]:
    """Load a JSON object from disk."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def require_string(obj: dict[str, object], key: str, ctx: str) -> str:
    """Return a required non-empty string field."""
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{ctx}.{key} must be a non-empty string")
    return value


def require_object(obj: dict[str, object], key: str, ctx: str) -> dict[str, object]:
    """Return a required object field."""
    value = obj.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{ctx}.{key} must be an object")
    return value


def require_pos(obj: dict[str, object], key: str, ctx: str) -> int:
    """Return a required position field in {-1, 1}."""
    value = obj.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value not in (-1, 1):
        raise ValueError(f"{ctx}.{key} must be -1 or 1")
    return value


def normalize_match_spec(spec: dict[str, object]) -> dict[str, object]:
    """Validate match spec shape and return normalized fields."""
    idea_a = require_object(spec, "idea_a", "match_spec")
    idea_b = require_object(spec, "idea_b", "match_spec")
    judge = require_object(spec, "judge", "match_spec")

    match_id = require_string(spec, "match_id", "match_spec")
    idea_a_id = require_string(idea_a, "id", "match_spec.idea_a")
    idea_b_id = require_string(idea_b, "id", "match_spec.idea_b")
    idea_a_text = require_string(idea_a, "text", "match_spec.idea_a")
    idea_b_text = require_string(idea_b, "text", "match_spec.idea_b")

    judge_id = require_string(judge, "judge_id", "match_spec.judge")
    model = require_string(judge, "model", "match_spec.judge")
    pos_a = require_pos(judge, "pos_a", "match_spec.judge")
    pos_b = require_pos(judge, "pos_b", "match_spec.judge")
    if pos_a != -pos_b:
        raise ValueError("match_spec.judge.pos_a and pos_b must be opposite signs")

    return {
        "match_id": match_id,
        "idea_a_id": idea_a_id,
        "idea_b_id": idea_b_id,
        "idea_a_text": idea_a_text,
        "idea_b_text": idea_b_text,
        "judge_id": judge_id,
        "model": model,
        "pos_a": pos_a,
    }


def fill_prompt(template: str, idea_a_text: str, idea_b_text: str, pos_a: int) -> str:
    """Fill prompt template with position-aware A/B presentation."""
    if "{idea_a}" not in template or "{idea_b}" not in template:
        raise ValueError("Prompt template must include {idea_a} and {idea_b}")

    shown_a = idea_a_text if pos_a == 1 else idea_b_text
    shown_b = idea_b_text if pos_a == 1 else idea_a_text

    content = template.replace("{idea_a}", "__PAIRWISE_IDEA_A__")
    content = content.replace("{idea_b}", "__PAIRWISE_IDEA_B__")
    content = content.replace("__PAIRWISE_IDEA_A__", shown_a)
    content = content.replace("__PAIRWISE_IDEA_B__", shown_b)
    return content


def stable_prompt_hash(text: str) -> str:
    """Compute deterministic FNV-1a 64-bit hash (hex) for prompt audit."""
    value = 1469598103934665603
    for byte in text.encode("utf-8"):
        value ^= byte
        value = (value * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"


def run_llm_runner(llm_runner_path: Path, model: str, prompt_text: str) -> tuple[int, str, str]:
    """Call llm_runner.py and return subprocess (returncode, stdout, stderr)."""
    temp_prompt: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".md", delete=False
        ) as handle:
            handle.write(prompt_text)
            temp_prompt = handle.name

        cmd = [
            "python3",
            str(llm_runner_path),
            "--model",
            model,
            "--prompt-file",
            temp_prompt,
            "--max-tokens",
            "4096",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        return proc.returncode, proc.stdout, proc.stderr
    finally:
        if temp_prompt and os.path.exists(temp_prompt):
            try:
                os.unlink(temp_prompt)
            except OSError:
                pass


def extract_fenced_json(raw: str) -> list[str]:
    """Extract candidate blocks from markdown fences, including ```json``` blocks."""
    blocks: list[str] = []
    cursor = 0
    while True:
        start = raw.find("```", cursor)
        if start == -1:
            break
        header_end = raw.find("\n", start + 3)
        if header_end == -1:
            break
        info = raw[start + 3 : header_end].strip().lower()
        end = raw.find("```", header_end + 1)
        if end == -1:
            break
        body = raw[header_end + 1 : end].strip()
        if body and (not info or "json" in info):
            blocks.append(body)
        cursor = end + 3
    return blocks


def extract_braced_json(raw: str) -> str | None:
    """Extract broad { ... } candidate from first '{' to last '}' if available."""
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return raw[start : end + 1].strip()


def validate_result(payload: object) -> dict[str, object]:
    """Validate parsed judge payload fields and normalize confidence to float."""
    if not isinstance(payload, dict):
        raise ValueError("Parsed payload must be a JSON object")

    winner = payload.get("winner")
    confidence = payload.get("confidence")
    a_strengths = payload.get("a_strengths")
    b_strengths = payload.get("b_strengths")
    rationale = payload.get("rationale")

    if winner not in ("A", "B"):
        raise ValueError("winner must be 'A' or 'B'")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("confidence must be numeric")

    confidence_value = float(confidence)
    if confidence_value != confidence_value or confidence_value < 0.5 or confidence_value > 1.0:
        raise ValueError("confidence must be between 0.5 and 1.0")
    if not isinstance(a_strengths, str):
        raise ValueError("a_strengths must be string")
    if not isinstance(b_strengths, str):
        raise ValueError("b_strengths must be string")
    if not isinstance(rationale, str):
        raise ValueError("rationale must be string")

    return {
        "winner": winner,
        "confidence": confidence_value,
        "a_strengths": a_strengths,
        "b_strengths": b_strengths,
        "rationale": rationale,
    }


def parse_response(raw_response: str) -> dict[str, object]:
    """Strictly parse JSON from direct response, fenced blocks, or braced segment."""
    candidates: list[str] = []
    stripped = raw_response.strip()
    if stripped:
        candidates.append(stripped)
    candidates.extend(extract_fenced_json(raw_response))
    braced = extract_braced_json(raw_response)
    if braced:
        candidates.append(braced)

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        try:
            return validate_result(parsed)
        except ValueError:
            continue

    raise ValueError("Could not parse valid JSON judgment payload")


def map_winner_ids(pos_a: int, winner_label: str, idea_a_id: str, idea_b_id: str) -> tuple[str, str]:
    """Map winner label A/B back to original idea IDs."""
    if pos_a == 1:
        if winner_label == "A":
            return idea_a_id, idea_b_id
        return idea_b_id, idea_a_id

    if winner_label == "A":
        return idea_b_id, idea_a_id
    return idea_a_id, idea_b_id


def format_attempt_log(attempt: int, returncode: int, stdout: str, stderr: str) -> str:
    """Format one attempt's raw output for audit logging."""
    parts: list[str] = [f"[attempt {attempt}]"]
    if stdout.strip():
        parts.append(stdout.strip())
    if stderr.strip():
        parts.append(f"[stderr]\n{stderr.strip()}")
    if returncode != 0:
        parts.append(f"[returncode]\n{returncode}")
    return "\n\n".join(parts)


def run_with_retry(llm_runner_path: Path, model: str, base_prompt: str) -> tuple[dict[str, object] | None, str, str]:
    """Run LLM once, then retry once with strict JSON reminder if needed."""
    prompts = [base_prompt, base_prompt + "\n\n" + RETRY_REMINDER]
    logs: list[str] = []

    for idx, prompt in enumerate(prompts, start=1):
        returncode, stdout, stderr = run_llm_runner(llm_runner_path, model, prompt)
        logs.append(format_attempt_log(idx, returncode, stdout, stderr))

        if returncode != 0:
            continue
        try:
            parsed = parse_response(stdout)
        except ValueError:
            continue

        return parsed, ("ok" if idx == 1 else "retry_ok"), "\n\n".join(logs)

    return None, "failed", "\n\n".join(logs)


def now_timestamp() -> str:
    """Return local timestamp in YYYY-MM-DDTHH:MM:SS format."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def failure_output(
    match_id: str,
    judge_id: str,
    model: str,
    pos: int | None,
    error: str,
    raw_response: str,
) -> dict[str, object]:
    """Create standard fail-loud output payload."""
    return {
        "match_id": match_id,
        "judge_id": judge_id,
        "model": model,
        "winner": None,
        "loser": None,
        "confidence": None,
        "pos": pos,
        "parse_status": "failed",
        "error": error,
        "raw_response_preview": raw_response[:200],
    }


def write_json_output(payload: dict[str, object], output_target: str, pretty: bool) -> None:
    """Write JSON output to stdout or file."""
    text = json.dumps(payload, indent=2 if pretty else None)
    if output_target == "-":
        sys.stdout.write(text + "\n")
        return

    output_path = Path(output_target).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text + "\n", encoding="utf-8")


def write_audit_log(
    log_dir: Path,
    match_id: str,
    judge_id: str,
    model: str,
    prompt_hash: str,
    raw_response: str,
    parsed_result: dict[str, object] | None,
    parse_status: str,
    winner_id: str | None,
) -> None:
    """Write per-judgment audit record to <log-dir>/<match_id>_<judge_id>.json."""
    log_dir.mkdir(parents=True, exist_ok=True)
    name = f"{match_id}_{judge_id}".replace(os.sep, "_")
    log_path = log_dir / f"{name}.json"
    payload = {
        "match_id": match_id,
        "judge_id": judge_id,
        "model": model,
        "prompt_hash": prompt_hash,
        "raw_response": raw_response,
        "parsed_result": parsed_result,
        "parse_status": parse_status,
        "winner_id": winner_id,
        "timestamp": now_timestamp(),
    }
    log_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    """Entrypoint for pairwise judgment execution."""
    args = parse_args()

    match_id = "unknown"
    judge_id = "unknown"
    model = "unknown"
    pos: int | None = None
    prompt_hash = ""
    raw_response = ""
    parsed_result: dict[str, object] | None = None
    parse_status = "failed"
    winner_id: str | None = None

    try:
        spec = load_json_object(Path(args.match_spec).expanduser())
        normalized = normalize_match_spec(spec)

        match_id = str(normalized["match_id"])
        judge_id = str(normalized["judge_id"])
        model = str(normalized["model"])
        pos = int(normalized["pos_a"])
        idea_a_id = str(normalized["idea_a_id"])
        idea_b_id = str(normalized["idea_b_id"])
        idea_a_text = str(normalized["idea_a_text"])
        idea_b_text = str(normalized["idea_b_text"])

        template = Path(args.prompt_template).expanduser().read_text(encoding="utf-8")
        prompt = fill_prompt(template, idea_a_text, idea_b_text, pos)
        prompt_hash = stable_prompt_hash(prompt)

        parsed_result, parse_status, raw_response = run_with_retry(
            Path(args.llm_runner_path).expanduser(),
            model,
            prompt,
        )

        if parsed_result is None:
            output = failure_output(
                match_id,
                judge_id,
                model,
                pos,
                PARSE_FAILURE_ERROR,
                raw_response,
            )
            exit_code = 1
        else:
            winner_id, loser_id = map_winner_ids(
                pos,
                str(parsed_result["winner"]),
                idea_a_id,
                idea_b_id,
            )
            output = {
                "match_id": match_id,
                "judge_id": judge_id,
                "model": model,
                "winner": winner_id,
                "loser": loser_id,
                "confidence": parsed_result["confidence"],
                "pos": pos,
                "a_strengths": parsed_result["a_strengths"],
                "b_strengths": parsed_result["b_strengths"],
                "rationale": parsed_result["rationale"],
                "parse_status": parse_status,
            }
            exit_code = 0

    except Exception as exc:
        output = failure_output(match_id, judge_id, model, pos, str(exc), raw_response)
        parsed_result = None
        parse_status = "failed"
        winner_id = None
        exit_code = 1

    if args.log_dir:
        try:
            write_audit_log(
                Path(args.log_dir).expanduser(),
                match_id,
                judge_id,
                model,
                prompt_hash,
                raw_response,
                parsed_result,
                parse_status,
                winner_id,
            )
        except Exception as exc:
            sys.stderr.write(f"Warning: failed to write audit log: {exc}\n")

    write_json_output(output, args.output, args.pretty)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
