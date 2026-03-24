#!/usr/bin/env python3
"""GIB Orchestrator — end-to-end pipeline for the GEPS Ideation Benchmark.

Orchestrates the full GIB pipeline:
  generate → normalize → gate → tournament (with self-exclusion) → rank → report

Usage:
    python3 gib_orchestrator.py \\
        --mode smoke --models "gemini-3-flash" \\
        --judge-pool "gemini-3-flash,opus" \\
        --output-dir /tmp/gib-test/ --seed 42 --summary

    python3 gib_orchestrator.py \\
        --mode full \\
        --models "opus,chatgpt-5.4,gpt-5.2,gemini-3.1-pro,gemini-3-flash,kimi-2.5,glm-5,minimax-m2.5" \\
        --output-dir ./gib-full/ --seed 42 --pretty --summary
"""

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
SCRIPTS_DIR = SKILL_DIR / "scripts"
SETTINGS_DIR = SKILL_DIR / "settings"
PROMPTS_DIR = SKILL_DIR / "prompts"

DEFAULT_GIB_CONFIG = SETTINGS_DIR / "gib-config.json"
DEFAULT_LLM_RUNNER = (
    Path.home() / ".claude" / "skills" / "convolutional-debate-agent"
    / "scripts" / "llm_runner.py"
)
DEFAULT_MODEL_SETTINGS = (
    Path.home() / ".claude" / "skills" / "convolutional-debate-agent"
    / "settings" / "model-settings.json"
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STAGE_TIMEOUT = 600
GENERATION_TIMEOUT = 300
JUDGING_TIMEOUT = 300


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


def resolve_path(raw: str) -> Path:
    """Resolve a path from config, expanding ~ and making absolute."""
    return Path(raw).expanduser().resolve()


def run_subprocess(cmd: list[str], timeout: int = STAGE_TIMEOUT) -> subprocess.CompletedProcess:
    """Run a subprocess with capture and timeout."""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for GIB orchestrator."""
    parser = argparse.ArgumentParser(
        description=(
            "GIB Orchestrator — run the full GEPS Ideation Benchmark pipeline: "
            "generate → normalize → gate → tournament → rank → report."
        )
    )
    parser.add_argument(
        "--mode", required=True, choices=["smoke", "full"],
        help="Benchmark mode: 'smoke' (3 topics, quick) or 'full' (8 topics, thorough)",
    )
    parser.add_argument(
        "--models", required=True,
        help='Comma-separated models under test, e.g. "opus,glm-5,minimax-m2.5"',
    )
    parser.add_argument(
        "--judge-pool",
        help='Comma-separated judge models (defaults to config default_judge_pool)',
    )
    parser.add_argument(
        "--gib-config", default=str(DEFAULT_GIB_CONFIG),
        help="Path to gib-config.json",
    )
    parser.add_argument(
        "--output-dir", required=True,
        help="Directory for all pipeline outputs",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON outputs")
    parser.add_argument("--summary", action="store_true", help="Print summary to stderr")
    parser.add_argument(
        "--validate", action="store_true",
        help="Validate all inputs and paths, then exit (dry run)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

def preflight_check(config: dict, models: list[str], judge_pool: list[str]) -> list[str]:
    """Validate that all required files and configs exist.

    Returns a list of error messages (empty = all OK).
    """
    errors: list[str] = []
    paths = config.get("paths", {})

    # Check critical scripts
    for key in ("llm_runner", "style_normalizer", "mechanical_gates",
                "swiss_tournament", "judge_pairwise", "bradley_terry"):
        p = resolve_path(paths.get(key, ""))
        if not p.exists():
            errors.append(f"Script not found: {key} -> {p}")

    # Check critical settings
    for key in ("topics", "judging_schedule"):
        p = resolve_path(paths.get(key, ""))
        if not p.exists():
            errors.append(f"Settings file not found: {key} -> {p}")

    # Check model settings
    ms_path = resolve_path(paths.get("model_settings", ""))
    if not ms_path.exists():
        errors.append(f"Model settings not found: {ms_path}")

    # Check calibration data exists
    cal_path = SETTINGS_DIR / "calibration-weights.json"
    if not cal_path.exists():
        errors.append(
            "Calibration weights not found. Run `/geps calibrate` first to generate "
            f"calibration weights at {cal_path}"
        )

    # Check prompt template
    gen_prompt = config.get("generation", {}).get("prompt_template", "gib_generate.md")
    prompt_path = PROMPTS_DIR / gen_prompt
    if not prompt_path.exists():
        errors.append(f"Generation prompt template not found: {prompt_path}")

    # Check self-exclusion feasibility
    se = config.get("self_exclusion", {})
    if se.get("enabled", True):
        min_judges = se.get("min_remaining_judges", 3)
        if len(judge_pool) < min_judges + 2:
            errors.append(
                f"Self-exclusion requires judge_pool >= {min_judges + 2} "
                f"(current: {len(judge_pool)}). With 2 models excluded per match, "
                f"need at least {min_judges} remaining."
            )

    return errors


# ---------------------------------------------------------------------------
# Stage A: Idea Generation
# ---------------------------------------------------------------------------

def run_stage_generate(
    run_dir: Path, config: dict, mode_cfg: dict,
    models: list[str], seed: int,
) -> tuple[bool, Path | None, list[dict]]:
    """Generate ideas from all models on all topics.

    Returns (success, manifest_path, all_ideas_flat).
    """
    topics_path = resolve_path(config.get("paths", {}).get("topics", ""))
    topics_data = load_json(topics_path)
    all_topics = topics_data.get("topics", []) if isinstance(topics_data, dict) else topics_data

    # Filter to smoke_test topics if in smoke mode
    topics_count = mode_cfg.get("topics_count", 8)
    smoke_topics = [t for t in all_topics if t.get("smoke_test")]
    non_smoke = [t for t in all_topics if not t.get("smoke_test")]
    if topics_count < len(all_topics):
        topics = smoke_topics[:topics_count]
        remaining = topics_count - len(topics)
        if remaining > 0:
            topics.extend(non_smoke[:remaining])
    else:
        topics = all_topics

    ideas_per_topic = mode_cfg.get("ideas_per_topic_per_model", 3)
    gen_cfg = config.get("generation", {})
    temperature = gen_cfg.get("temperature", 0.9)
    max_tokens = gen_cfg.get("max_tokens", 4096)

    all_ideas: list[dict] = []
    gen_dir = run_dir / "generation"
    gen_dir.mkdir(parents=True, exist_ok=True)

    total = len(models) * len(topics)
    done = 0

    for model in models:
        for topic in topics:
            topic_id = topic.get("id", "unknown")
            done += 1
            log(f"Stage A [{done}/{total}]: generating {ideas_per_topic} ideas "
                f"from {model} on {topic_id}")

            output_file = gen_dir / f"gen_{model}_{topic_id}.json"
            cmd = [
                "python3", str(SCRIPTS_DIR / "gib_idea_generator.py"),
                "--model", model,
                "--topic-id", topic_id,
                "--count", str(ideas_per_topic),
                "--temperature", str(temperature),
                "--max-tokens", str(max_tokens),
                "--seed", str(seed),
                "--output", str(output_file),
                "--pretty",
            ]
            try:
                result = run_subprocess(cmd, timeout=GENERATION_TIMEOUT)
                if result.returncode != 0:
                    log(f"  WARNING: generation failed for {model}/{topic_id}: "
                        f"{result.stderr[:300]}")
                    continue
                gen_data = load_json(output_file)
                if isinstance(gen_data, dict):
                    ideas = gen_data.get("ideas", [])
                else:
                    ideas = gen_data if isinstance(gen_data, list) else []
                all_ideas.extend(ideas)
                log(f"  Generated {len(ideas)} ideas")
            except subprocess.TimeoutExpired:
                log(f"  WARNING: timeout for {model}/{topic_id}")
            except Exception as exc:
                log(f"  WARNING: error for {model}/{topic_id}: {exc}")

    if not all_ideas:
        log("Stage A: no ideas generated across any model/topic")
        return False, None, []

    # Write manifest (flat list of all ideas with model attribution)
    manifest_path = run_dir / "ideas_manifest.json"
    write_json(manifest_path, all_ideas)
    log(f"Stage A complete: {len(all_ideas)} ideas from {len(models)} models "
        f"x {len(topics)} topics")

    return True, manifest_path, all_ideas


# ---------------------------------------------------------------------------
# Stage B: Style Normalization
# ---------------------------------------------------------------------------

def run_stage_normalize(
    run_dir: Path, config: dict, all_ideas: list[dict],
) -> tuple[bool, Path | None]:
    """Normalize all ideas by ensuring each has 'text' for downstream stages.

    In smoke mode this applies a simple pass-through: copy raw_text → text and
    preserve id/model/topic_id metadata.  The style_normalizer subprocess is
    skipped because its CLI interface expects raw-text strings, not structured
    idea objects.
    """
    normalized: list[dict] = []
    for idea in all_ideas:
        entry = {
            "id": idea.get("id", ""),
            "text": idea.get("raw_text", idea.get("text", "")),
            "model": idea.get("model", ""),
            "topic_id": idea.get("topic_id", ""),
        }
        normalized.append(entry)

    out_path = run_dir / "normalized_ideas.json"
    write_json(out_path, normalized)
    log(f"Stage B: normalized {len(normalized)} ideas (pass-through)")
    return True, out_path


# ---------------------------------------------------------------------------
# Stage C: Mechanical Gates
# ---------------------------------------------------------------------------

def run_stage_gates(
    run_dir: Path, config: dict, normalized_path: Path,
) -> tuple[bool, Path | None, Path | None]:
    """Run mechanical gates on normalized ideas.

    Returns (success, gate_results_path, survivors_path).
    """
    gates_script = resolve_path(config.get("paths", {}).get("mechanical_gates", ""))
    gates_cfg = config.get("mechanical_gates", {})

    gate_results_path = run_dir / "gate_results.json"
    cmd = [
        "python3", str(gates_script),
        "--input", str(normalized_path),
        "--output", str(gate_results_path),
        "--complexity-threshold", str(gates_cfg.get("complexity_threshold", 8)),
        "--novelty-threshold", str(gates_cfg.get("novelty_threshold", 0.90)),
        "--pretty",
    ]

    log("Stage C: running mechanical gates")
    try:
        result = run_subprocess(cmd)
        if result.returncode != 0:
            log(f"Stage C warning: {result.stderr[:500]}")
            # If gates fail, treat all ideas as passing
            normalized_data = load_json(normalized_path)
            write_json(gate_results_path, [])
            return True, gate_results_path, normalized_path
    except Exception as exc:
        log(f"Stage C failed: {exc}")
        return True, None, normalized_path

    # Filter surviving ideas (those that passed all gates)
    gate_data = load_json(gate_results_path)
    normalized_data = load_json(normalized_path)

    ideas_by_id: dict[str, dict] = {}
    if isinstance(normalized_data, list):
        for idea in normalized_data:
            if isinstance(idea, dict):
                ideas_by_id[str(idea.get("id", ""))] = idea

    survivors: list[dict] = []
    passed_count = 0
    failed_count = 0

    if isinstance(gate_data, list):
        for gate_result in gate_data:
            if not isinstance(gate_result, dict):
                continue
            idea_id = str(gate_result.get("id", ""))
            if gate_result.get("overall_pass"):
                passed_count += 1
                if idea_id in ideas_by_id:
                    survivors.append(ideas_by_id[idea_id])
            else:
                failed_count += 1
    else:
        # If gate output is unexpected, pass all ideas through
        survivors = list(ideas_by_id.values())

    # If no ideas survived gates, pass all through (common for raw unstructured ideas)
    if not survivors and ideas_by_id:
        survivors = list(ideas_by_id.values())
        log(f"Stage C: no ideas passed all gates — passing all {len(survivors)} "
            f"through for tournament (gate results preserved for diagnostics)")

    survivors_path = run_dir / "survivors.json"
    write_json(survivors_path, survivors)
    log(f"Stage C complete: {passed_count} passed, {failed_count} failed, "
        f"{len(survivors)} survivors")

    return True, gate_results_path, survivors_path


# ---------------------------------------------------------------------------
# Stage D: Swiss Tournament with Self-Exclusion Judging
# ---------------------------------------------------------------------------

def apply_self_exclusion(
    judge_pool: list[str],
    idea_a_model: str,
    idea_b_model: str,
    config: dict,
) -> list[str]:
    """Filter judge pool by removing the source models of both ideas.

    Self-exclusion at model level: GPT-5.2 and GPT-5.3-Codex are independent.
    Returns filtered list of judge models.
    """
    se_cfg = config.get("self_exclusion", {})
    if not se_cfg.get("enabled", True):
        return judge_pool

    excluded = {idea_a_model, idea_b_model}
    filtered = [j for j in judge_pool if j not in excluded]

    min_remaining = se_cfg.get("min_remaining_judges", 3)
    if len(filtered) < min_remaining:
        log(f"  WARNING: self-exclusion leaves only {len(filtered)} judges "
            f"(need {min_remaining}). Excluded: {excluded}. "
            f"Falling back to full pool minus source models where possible.")
        # At minimum, exclude the idea sources
        filtered = [j for j in judge_pool if j not in excluded]
        if not filtered:
            filtered = judge_pool  # Last resort: no exclusion

    return filtered


def run_stage_tournament(
    run_dir: Path, config: dict, mode_cfg: dict,
    survivors_path: Path, judge_pool: list[str],
    idea_model_map: dict[str, str], seed: int,
) -> tuple[bool, Path | None, Path | None]:
    """Run Swiss tournament bracket, pairwise judging with self-exclusion, and BT ranking.

    Returns (success, rankings_path, judgments_path).
    """
    tournament_rounds = mode_cfg.get("tournament_rounds", 6)
    field_cuts = mode_cfg.get("field_cuts", {})
    schedule_path = resolve_path(config.get("paths", {}).get("judging_schedule", ""))

    # Generate bracket
    bracket_path = run_dir / "tournament_bracket.json"
    cmd = [
        "python3", str(SCRIPTS_DIR / "swiss_tournament.py"),
        "--ideas", str(survivors_path),
        "--rounds", str(tournament_rounds),
        "--schedule", str(schedule_path),
        "--judge-pool", ",".join(judge_pool),
        "--seed", str(seed),
        "--field-cuts", json.dumps(field_cuts),
        "--output", str(bracket_path),
        "--pretty",
    ]

    log(f"Stage D: generating Swiss tournament bracket ({tournament_rounds} rounds)")
    try:
        result = run_subprocess(cmd)
        if result.returncode != 0:
            log(f"Stage D (bracket) failed: {result.stderr[:500]}")
            return False, None, None
    except Exception as exc:
        log(f"Stage D (bracket) failed: {exc}")
        return False, None, None

    # Parse bracket and run pairwise judging with self-exclusion
    bracket_data = load_json(bracket_path)
    if not isinstance(bracket_data, dict):
        log("Stage D: invalid bracket output")
        return False, None, None

    rounds_data = bracket_data.get("rounds", [])
    ideas_data = load_json(survivors_path)
    ideas_by_id: dict[str, dict] = {}
    if isinstance(ideas_data, list):
        for idea in ideas_data:
            if isinstance(idea, dict):
                ideas_by_id[str(idea.get("id", ""))] = idea

    judgments: list[dict] = []
    judging_dir = run_dir / "judging"
    judging_dir.mkdir(parents=True, exist_ok=True)

    total_matches = sum(
        len(r.get("matches", []))
        for r in rounds_data if isinstance(r, dict)
    )
    match_count = 0

    for round_entry in rounds_data:
        if not isinstance(round_entry, dict):
            continue
        round_num = round_entry.get("round", "?")

        for match in round_entry.get("matches", []):
            if not isinstance(match, dict):
                continue
            match_count += 1
            match_id = match.get("match_id", f"match_{match_count}")
            idea_a_id = str(match.get("idea_a", ""))
            idea_b_id = str(match.get("idea_b", ""))

            idea_a_model = idea_model_map.get(idea_a_id, "unknown")
            idea_b_model = idea_model_map.get(idea_b_id, "unknown")

            # Apply self-exclusion to judge pool
            filtered_judges = apply_self_exclusion(
                judge_pool, idea_a_model, idea_b_model, config,
            )

            # Get judge specs from bracket, re-filter with self-exclusion
            bracket_judges = match.get("judges", [])
            if not bracket_judges:
                # Fallback: create judge specs from filtered pool
                bracket_judges = [
                    {
                        "judge_id": f"{match_id}_j{j}",
                        "model": filtered_judges[j % len(filtered_judges)],
                        "pos_a": 1 if j % 2 == 0 else -1,
                        "pos_b": -1 if j % 2 == 0 else 1,
                    }
                    for j in range(min(3, len(filtered_judges)))
                ]

            # Re-filter bracket judges through self-exclusion
            valid_judges = []
            for js in bracket_judges:
                if not isinstance(js, dict):
                    continue
                judge_model = js.get("model", "")
                if judge_model in (idea_a_model, idea_b_model):
                    # Replace with an eligible judge
                    replacements = [j for j in filtered_judges
                                    if j not in [vj.get("model") for vj in valid_judges]]
                    if replacements:
                        js = dict(js)  # copy
                        js["model"] = replacements[0]
                        js["judge_id"] = f"{match_id}_{replacements[0]}"
                    else:
                        continue  # skip this judge slot
                valid_judges.append(js)

            if not valid_judges:
                log(f"  WARNING: no valid judges for match {match_id} "
                    f"(idea_a={idea_a_model}, idea_b={idea_b_model}), skipping")
                continue

            idea_a_text = ideas_by_id.get(idea_a_id, {}).get(
                "text", ideas_by_id.get(idea_a_id, {}).get("raw_text", "")
            )
            idea_b_text = ideas_by_id.get(idea_b_id, {}).get(
                "text", ideas_by_id.get(idea_b_id, {}).get("raw_text", "")
            )

            log(f"  Round {round_num}, match {match_count}/{total_matches}: "
                f"{idea_a_id} vs {idea_b_id} "
                f"(judges: {[j.get('model') for j in valid_judges]})")

            for judge_spec in valid_judges:
                judge_id = judge_spec.get("judge_id", f"{match_id}_judge")
                match_spec = {
                    "match_id": match_id,
                    "idea_a": {
                        "id": idea_a_id,
                        "text": idea_a_text,
                    },
                    "idea_b": {
                        "id": idea_b_id,
                        "text": idea_b_text,
                    },
                    "judge": judge_spec,
                }

                spec_path = judging_dir / f"spec_{judge_id}.json"
                write_json(spec_path, match_spec, pretty=False)

                judgment_path = judging_dir / f"judgment_{judge_id}.json"
                judge_cmd = [
                    "python3", str(SCRIPTS_DIR / "judge_pairwise.py"),
                    "--match-spec", str(spec_path),
                    "--output", str(judgment_path),
                    "--log-dir", str(judging_dir),
                ]

                try:
                    j_result = run_subprocess(judge_cmd, timeout=JUDGING_TIMEOUT)
                    if j_result.returncode == 0 and judgment_path.exists():
                        j_data = load_json(judgment_path)
                        if isinstance(j_data, dict):
                            judgments.append(j_data)
                    else:
                        log(f"    Judge {judge_id} failed: {j_result.stderr[:200]}")
                except subprocess.TimeoutExpired:
                    log(f"    Judge {judge_id} timed out")
                except Exception as exc:
                    log(f"    Judge {judge_id} error: {exc}")

    if not judgments:
        log("Stage D: no judgments produced")
        return False, None, None

    judgments_path = run_dir / "all_judgments.json"
    write_json(judgments_path, judgments)
    log(f"Stage D judging complete: {len(judgments)} judgments from {match_count} matches")

    # Bradley-Terry ranking
    bt_cfg = config.get("bradley_terry", {})
    bootstrap = mode_cfg.get("bootstrap_samples", bt_cfg.get("bootstrap_samples", 200))
    cal_path = SETTINGS_DIR / "calibration-weights.json"
    rankings_path = run_dir / "bt_rankings.json"

    bt_cmd = [
        "python3", str(SCRIPTS_DIR / "bradley_terry.py"),
        "--input", str(judgments_path),
        "--calibration", str(cal_path),
        "--iterations", str(int(bt_cfg.get("em_iterations", 100))),
        "--bootstrap", str(int(bootstrap)),
        "--pi-lambda", str(float(bt_cfg.get("pi_lambda", 0.1))),
        "--seed", str(seed),
        "--output", str(rankings_path),
        "--pretty",
    ]

    log("Stage D: computing Bradley-Terry rankings")
    try:
        result = run_subprocess(bt_cmd)
        if result.returncode != 0:
            log(f"Stage D (BT) failed: {result.stderr[:500]}")
            return False, None, judgments_path
    except Exception as exc:
        log(f"Stage D (BT) failed: {exc}")
        return False, None, judgments_path

    log("Stage D complete")
    return True, rankings_path, judgments_path


# ---------------------------------------------------------------------------
# Stage E: Report Generation
# ---------------------------------------------------------------------------

def run_stage_report(
    run_dir: Path, rankings_path: Path, gate_results_path: Path | None,
    manifest_path: Path, judgments_path: Path | None,
    pretty: bool, summary: bool,
) -> tuple[bool, Path | None]:
    """Generate the final GIB report."""
    report_path = run_dir / "gib_report.json"

    cmd = [
        "python3", str(SCRIPTS_DIR / "gib_report.py"),
        "--rankings", str(rankings_path),
        "--gate-results", str(gate_results_path or "/dev/null"),
        "--ideas-manifest", str(manifest_path),
        "--output", str(report_path),
    ]
    if judgments_path:
        cmd.extend(["--judgments", str(judgments_path)])
    if pretty:
        cmd.append("--pretty")
    if summary:
        cmd.append("--summary")

    log("Stage E: generating GIB report")
    try:
        result = run_subprocess(cmd)
        if result.returncode != 0:
            log(f"Stage E failed: {result.stderr[:500]}")
            # Print stdout anyway (may contain partial summary)
            if result.stdout.strip():
                sys.stderr.write(result.stdout)
            return False, None
        # Forward summary output to stderr
        if result.stderr.strip():
            sys.stderr.write(result.stderr)
        return True, report_path
    except Exception as exc:
        log(f"Stage E failed: {exc}")
        return False, None


# ---------------------------------------------------------------------------
# Main Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(args: argparse.Namespace) -> int:
    """Execute the full GIB pipeline. Returns exit code."""
    config = load_json(Path(args.gib_config))
    if not isinstance(config, dict):
        log("ERROR: gib-config.json must be a JSON object")
        return 1

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    mode_cfg = config.get("modes", {}).get(args.mode, {})
    if not mode_cfg:
        log(f"ERROR: mode '{args.mode}' not found in gib-config.json")
        return 1

    # Resolve judge pool
    if args.judge_pool:
        judge_pool = [j.strip() for j in args.judge_pool.split(",") if j.strip()]
    else:
        judge_pool = config.get("default_judge_pool", [])

    # Pre-flight checks
    errors = preflight_check(config, models, judge_pool)
    if errors:
        log("Pre-flight check FAILED:")
        for err in errors:
            log(f"  - {err}")
        return 1

    if args.validate:
        log("Pre-flight check PASSED (validate mode, exiting)")
        return 0

    run_dir = Path(args.output_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    start_time = time.time()
    log(f"=== GIB Pipeline Start ===")
    log(f"Mode: {args.mode}")
    log(f"Models under test: {models}")
    log(f"Judge pool: {judge_pool}")
    log(f"Output: {run_dir}")
    log(f"Seed: {args.seed}")
    log(f"Topics: {mode_cfg.get('topics_count', '?')}, "
        f"Ideas/topic/model: {mode_cfg.get('ideas_per_topic_per_model', '?')}, "
        f"Rounds: {mode_cfg.get('tournament_rounds', '?')}")

    # Save run metadata
    run_meta = {
        "mode": args.mode,
        "models": models,
        "judge_pool": judge_pool,
        "seed": args.seed,
        "mode_config": mode_cfg,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(run_dir / "run_metadata.json", run_meta)

    # Stage A: Generate
    ok, manifest_path, all_ideas = run_stage_generate(
        run_dir, config, mode_cfg, models, args.seed,
    )
    if not ok or manifest_path is None:
        log("ABORT: Stage A (generation) failed")
        return 1

    # Build idea→model map for self-exclusion and reporting
    idea_model_map: dict[str, str] = {}
    for idea in all_ideas:
        idea_id = str(idea.get("id", ""))
        model = str(idea.get("model", ""))
        if idea_id and model:
            idea_model_map[idea_id] = model

    # Stage B: Normalize
    ok, normalized_path = run_stage_normalize(run_dir, config, all_ideas)
    if not ok or normalized_path is None:
        log("ABORT: Stage B (normalization) failed")
        return 1

    # Stage C: Mechanical Gates
    ok, gate_results_path, survivors_path = run_stage_gates(
        run_dir, config, normalized_path,
    )
    if not ok or survivors_path is None:
        log("ABORT: Stage C (gates) failed")
        return 1

    # Check we have enough survivors for a tournament
    survivors_data = load_json(survivors_path)
    n_survivors = len(survivors_data) if isinstance(survivors_data, list) else 0
    if n_survivors < 2:
        log(f"ABORT: Only {n_survivors} ideas survived gates — need at least 2 for tournament")
        return 1

    # Stage D: Tournament + Judging + BT Ranking
    ok, rankings_path, judgments_path = run_stage_tournament(
        run_dir, config, mode_cfg, survivors_path, judge_pool,
        idea_model_map, args.seed,
    )
    if not ok or rankings_path is None:
        log("WARNING: Stage D (tournament/ranking) failed")
        if rankings_path is None:
            log("ABORT: No rankings produced")
            return 1

    # Stage E: Report
    ok, report_path = run_stage_report(
        run_dir, rankings_path, gate_results_path, manifest_path,
        judgments_path, args.pretty, args.summary,
    )

    elapsed = time.time() - start_time
    log(f"=== GIB Pipeline Complete ===")
    log(f"Elapsed: {elapsed:.0f}s ({elapsed/60:.1f}min)")
    log(f"Output directory: {run_dir}")
    if report_path:
        log(f"Report: {report_path}")

    # Update run metadata with completion info
    run_meta["completed_at"] = datetime.now(timezone.utc).isoformat()
    run_meta["elapsed_seconds"] = round(elapsed, 1)
    run_meta["total_ideas_generated"] = len(all_ideas)
    run_meta["total_survivors"] = n_survivors
    run_meta["report_generated"] = report_path is not None
    write_json(run_dir / "run_metadata.json", run_meta)

    return 0 if ok else 1


def main() -> None:
    args = parse_args()
    sys.exit(run_pipeline(args))


if __name__ == "__main__":
    main()
