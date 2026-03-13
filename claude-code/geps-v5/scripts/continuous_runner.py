#!/usr/bin/env python3
"""Continuous pipeline runner for GEPS v5.

Orchestrates the full 7-stage research idea generation and evaluation pipeline
in a loop, with failure recovery, seed rotation, cost tracking, and feedback.

Usage:
    python3 continuous_runner.py \
        --geps-config geps-config.json \
        --runs-dir ./runs/ \
        --max-iterations 100 \
        --sleep-between-runs 30 \
        --stop-on-consecutive-failures 3 \
        --base-seed 42
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPTS_DIR = Path(__file__).resolve().parent
SETTINGS_DIR = SCRIPTS_DIR.parent / "settings"

STAGE_TIMEOUT = 600  # seconds per subprocess call
GENERATION_TIMEOUT = 120  # per-idea LLM generation call
DEFAULT_MAX_ITERATIONS = 100
DEFAULT_SLEEP_BETWEEN = 30
DEFAULT_CONSECUTIVE_FAILURES = 3
DEFAULT_BASE_SEED = 42

# Rough per-call token estimates for cost tracking (input + output tokens)
TOKEN_ESTIMATES = {
    "concept_graph": (0, 0),       # pure computation, no LLM
    "llm_generation": (2000, 1500),
    "style_normalizer": (2000, 1000),
    "taxonomy_labeler": (0, 0),    # rule-based
    "mechanical_gates": (0, 0),    # rule-based
    "swiss_tournament": (0, 0),    # bracket generation only
    "judge_pairwise": (3000, 500),
    "bradley_terry": (0, 0),       # computation only
    "literature_retrieval": (500, 500),
    "verify_finalists": (4000, 1500),
    "portfolio_optimizer": (0, 0), # computation only
    "failure_ledger": (0, 0),      # computation only
}


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


def estimate_cost(model: str, input_tokens: int, output_tokens: int,
                  pricing: dict[str, object]) -> float:
    """Estimate USD cost from token counts and pricing table."""
    models = pricing.get("models", {})
    if not isinstance(models, dict):
        return 0.0
    entry = models.get(model)
    if not isinstance(entry, dict):
        return 0.0
    input_rate = float(entry.get("input_per_1m", 0.0))
    output_rate = float(entry.get("output_per_1m", 0.0))
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


# ---------------------------------------------------------------------------
# Stage functions
# ---------------------------------------------------------------------------

def run_stage_a(run_dir: Path, config: dict, corpus_dir: Path | None,
                papers_json: Path | None) -> tuple[bool, Path | None, float]:
    """Stage A: Build concept graph and extract structural holes."""
    output_path = run_dir / "stage_a_structural_holes.json"
    cmd = ["python3", str(SCRIPTS_DIR / "concept_graph.py"), "--holes", "20",
           "--output", str(output_path), "--pretty"]
    if corpus_dir and corpus_dir.exists():
        cmd.extend(["--corpus-dir", str(corpus_dir)])
    if papers_json and papers_json.exists():
        cmd.extend(["--papers-json", str(papers_json)])
    if not corpus_dir and not papers_json:
        log("Stage A: no corpus sources configured, skipping")
        return True, None, 0.0
    try:
        result = run_subprocess(cmd)
        if result.returncode != 0:
            raise RuntimeError(result.stderr[:500])
        return True, output_path, 0.0
    except Exception as exc:
        log(f"Stage A failed: {exc}")
        return False, None, 0.0


def run_stage_b(run_dir: Path, config: dict, seed: int,
                pricing: dict, channel_weights: dict[str, float] | None
                ) -> tuple[bool, Path | None, float]:
    """Stage B: Generate ideas across channels, normalize, and label."""
    generation = config.get("generation", {})
    channels = generation.get("channels", {})
    ideas_per_channel = int(generation.get("ideas_per_channel", 10))
    llm_runner = resolve_path(config.get("paths", {}).get("llm_runner", ""))
    if not llm_runner.exists():
        log(f"Stage B: llm_runner not found at {llm_runner}")
        return False, None, 0.0

    all_ideas: list[dict] = []
    total_cost = 0.0

    for channel_name, channel_cfg in channels.items():
        if not isinstance(channel_cfg, dict):
            continue
        model = channel_cfg.get("model", "opus")
        weight = float(channel_cfg.get("weight", 0.1))
        if channel_weights and channel_name in channel_weights:
            weight = channel_weights[channel_name]

        n_ideas = max(1, round(ideas_per_channel * weight / 0.15))

        prompt_file = channel_cfg.get("prompt", "")
        prompt_path = SCRIPTS_DIR.parent / "prompts" / prompt_file
        if not prompt_path.exists():
            log(f"Stage B: prompt {prompt_path} not found for channel {channel_name}, skipping")
            continue

        for idea_idx in range(n_ideas):
            idea_seed = seed * 1000 + hash(channel_name) % 1000 + idea_idx
            cmd = [
                "python3", str(llm_runner),
                "--model", model,
                "--prompt-file", str(prompt_path),
                "--max-tokens", "2000",
                "--temperature", "0.9",
            ]
            try:
                result = run_subprocess(cmd, timeout=GENERATION_TIMEOUT)
                if result.returncode != 0:
                    log(f"Stage B: generation failed for {channel_name} idea {idea_idx}: "
                        f"{result.stderr[:200]}")
                    continue
                idea_text = result.stdout.strip()
                if not idea_text:
                    continue
                all_ideas.append({
                    "id": f"{channel_name}-{seed}-{idea_idx:03d}",
                    "channel": channel_name,
                    "text": idea_text,
                    "model": model,
                    "seed": idea_seed,
                })
                in_tok, out_tok = TOKEN_ESTIMATES["llm_generation"]
                total_cost += estimate_cost(model, in_tok, out_tok, pricing)
            except subprocess.TimeoutExpired:
                log(f"Stage B: timeout for {channel_name} idea {idea_idx}")
            except Exception as exc:
                log(f"Stage B: error for {channel_name} idea {idea_idx}: {exc}")

    if not all_ideas:
        log("Stage B: no ideas generated across any channel")
        return False, None, total_cost

    raw_ideas_path = run_dir / "stage_b_raw_ideas.json"
    write_json(raw_ideas_path, all_ideas)

    # Style normalization
    normalized_path = run_dir / "stage_b_normalized.json"
    norm_cmd = [
        "python3", str(SCRIPTS_DIR / "style_normalizer.py"),
        "--input", str(raw_ideas_path),
        "--output", str(normalized_path),
        "--mechanical-only",
        "--pretty",
    ]
    try:
        result = run_subprocess(norm_cmd)
        if result.returncode != 0:
            log(f"Stage B normalization warning: {result.stderr[:300]}")
            normalized_path = raw_ideas_path
    except Exception as exc:
        log(f"Stage B normalization failed: {exc}")
        normalized_path = raw_ideas_path

    # Taxonomy labeling
    taxonomy_path = SETTINGS_DIR / "taxonomy.json"
    labeled_path = run_dir / "stage_b_labeled.json"
    if taxonomy_path.exists():
        label_cmd = [
            "python3", str(SCRIPTS_DIR / "taxonomy_labeler.py"),
            "--input", str(normalized_path),
            "--taxonomy", str(taxonomy_path),
            "--output", str(labeled_path),
            "--pretty",
        ]
        try:
            result = run_subprocess(label_cmd)
            if result.returncode != 0:
                log(f"Stage B labeling warning: {result.stderr[:300]}")
        except Exception as exc:
            log(f"Stage B labeling failed: {exc}")

    return True, normalized_path, total_cost


def run_stage_c(run_dir: Path, ideas_path: Path, config: dict) -> tuple[bool, Path | None, float]:
    """Stage C: Mechanical gates screening."""
    output_path = run_dir / "stage_c_screened.json"
    config_path = run_dir / "_geps_config.json"
    write_json(config_path, config, pretty=False)
    cmd = [
        "python3", str(SCRIPTS_DIR / "mechanical_gates.py"),
        "--input", str(ideas_path),
        "--output", str(output_path),
        "--config", str(config_path),
        "--pretty",
    ]
    try:
        result = run_subprocess(cmd)
        if result.returncode != 0:
            raise RuntimeError(result.stderr[:500])
        # Filter to only passing ideas for downstream stages
        gates_data = load_json(output_path)
        if isinstance(gates_data, list):
            raw_ideas = load_json(ideas_path)
            ideas_by_id = {}
            if isinstance(raw_ideas, list):
                for idea in raw_ideas:
                    if isinstance(idea, dict):
                        ideas_by_id[idea.get("id", "")] = idea
            survivors = []
            for gate_result in gates_data:
                if isinstance(gate_result, dict) and gate_result.get("overall_pass"):
                    idea_id = gate_result.get("id", "")
                    if idea_id in ideas_by_id:
                        survivors.append(ideas_by_id[idea_id])
            survivors_path = run_dir / "stage_c_survivors.json"
            write_json(survivors_path, survivors)
            return True, survivors_path, 0.0
        return True, output_path, 0.0
    except Exception as exc:
        log(f"Stage C failed: {exc}")
        return False, None, 0.0


def run_stage_d(run_dir: Path, ideas_path: Path, config: dict, seed: int,
                pricing: dict) -> tuple[bool, Path | None, float]:
    """Stage D: Swiss tournament + pairwise judging + Bradley-Terry ranking."""
    tournament_cfg = config.get("tournament", {})
    rounds = int(tournament_cfg.get("rounds", 6))
    judge_pool = tournament_cfg.get("judge_pool", [])
    field_cuts = tournament_cfg.get("field_cuts", {})
    schedule_path = SETTINGS_DIR / "judging_schedule.json"

    # Swiss tournament bracket
    bracket_path = run_dir / "stage_d_bracket.json"
    cmd = [
        "python3", str(SCRIPTS_DIR / "swiss_tournament.py"),
        "--ideas", str(ideas_path),
        "--rounds", str(rounds),
        "--schedule", str(schedule_path),
        "--judge-pool", ",".join(judge_pool),
        "--seed", str(seed),
        "--field-cuts", json.dumps(field_cuts),
        "--output", str(bracket_path),
        "--pretty",
    ]
    try:
        result = run_subprocess(cmd)
        if result.returncode != 0:
            raise RuntimeError(f"Swiss tournament: {result.stderr[:500]}")
    except Exception as exc:
        log(f"Stage D (tournament) failed: {exc}")
        return False, None, 0.0

    # Parse bracket for match specs and run pairwise judging
    total_cost = 0.0
    judgments: list[dict] = []
    try:
        bracket_data = load_json(bracket_path)
        if not isinstance(bracket_data, dict):
            raise ValueError("Invalid bracket output")
        rounds_data = bracket_data.get("rounds", [])
        ideas_data = load_json(ideas_path)
        ideas_by_id = {}
        if isinstance(ideas_data, list):
            for idea in ideas_data:
                if isinstance(idea, dict):
                    ideas_by_id[str(idea.get("id", ""))] = idea

        for round_entry in rounds_data:
            if not isinstance(round_entry, dict):
                continue
            for match in round_entry.get("matches", []):
                if not isinstance(match, dict):
                    continue
                for judge_spec in match.get("judges", []):
                    if not isinstance(judge_spec, dict):
                        continue
                    match_spec = {
                        "match_id": match.get("match_id", ""),
                        "idea_a": {
                            "id": match.get("idea_a", ""),
                            "text": ideas_by_id.get(match.get("idea_a", ""), {}).get("text", ""),
                        },
                        "idea_b": {
                            "id": match.get("idea_b", ""),
                            "text": ideas_by_id.get(match.get("idea_b", ""), {}).get("text", ""),
                        },
                        "judge": judge_spec,
                    }
                    spec_path = run_dir / f"match_spec_{judge_spec.get('judge_id', 'x')}.json"
                    write_json(spec_path, match_spec, pretty=False)
                    judgment_path = run_dir / f"judgment_{judge_spec.get('judge_id', 'x')}.json"
                    judge_cmd = [
                        "python3", str(SCRIPTS_DIR / "judge_pairwise.py"),
                        "--match-spec", str(spec_path),
                        "--output", str(judgment_path),
                    ]
                    try:
                        j_result = run_subprocess(judge_cmd)
                        if j_result.returncode == 0 and judgment_path.exists():
                            j_data = load_json(judgment_path)
                            if isinstance(j_data, dict):
                                judgments.append(j_data)
                        model = judge_spec.get("model", "opus")
                        in_tok, out_tok = TOKEN_ESTIMATES["judge_pairwise"]
                        total_cost += estimate_cost(model, in_tok, out_tok, pricing)
                    except Exception as exc:
                        log(f"Stage D judging error ({judge_spec.get('judge_id')}): {exc}")
    except Exception as exc:
        log(f"Stage D (judging) failed: {exc}")
        return False, None, total_cost

    if not judgments:
        log("Stage D: no judgments produced")
        return False, None, total_cost

    judgments_path = run_dir / "stage_d_judgments.json"
    write_json(judgments_path, judgments)

    # Bradley-Terry ranking
    bt_cfg = config.get("bradley_terry", {})
    calibration_path = SETTINGS_DIR / "calibration-pack.json"
    rankings_path = run_dir / "stage_d_rankings.json"
    bt_cmd = [
        "python3", str(SCRIPTS_DIR / "bradley_terry.py"),
        "--input", str(judgments_path),
        "--calibration", str(calibration_path),
        "--iterations", str(int(bt_cfg.get("em_iterations", 100))),
        "--bootstrap", str(int(bt_cfg.get("bootstrap_samples", 200))),
        "--pi-lambda", str(float(bt_cfg.get("pi_lambda", 0.1))),
        "--seed", str(seed),
        "--output", str(rankings_path),
        "--pretty",
    ]
    try:
        result = run_subprocess(bt_cmd)
        if result.returncode != 0:
            raise RuntimeError(f"Bradley-Terry: {result.stderr[:500]}")
        return True, rankings_path, total_cost
    except Exception as exc:
        log(f"Stage D (Bradley-Terry) failed: {exc}")
        return False, None, total_cost


def run_stage_e(run_dir: Path, rankings_path: Path, config: dict,
                pricing: dict) -> tuple[bool, Path | None, float]:
    """Stage E: Literature retrieval + finalist verification."""
    verification_cfg = config.get("verification", {})
    top_k = int(verification_cfg.get("top_k", 5))
    verifier_models = verification_cfg.get("verifier_models", ["opus"])

    # Extract top-K ideas from rankings
    rankings_data = load_json(rankings_path)
    rankings_list = []
    if isinstance(rankings_data, dict):
        rankings_list = rankings_data.get("rankings", [])
    elif isinstance(rankings_data, list):
        rankings_list = rankings_data
    top_ideas = rankings_list[:top_k] if isinstance(rankings_list, list) else []
    if not top_ideas:
        log("Stage E: no ranked ideas to verify")
        return False, None, 0.0

    # Ensure each idea has required fields for verify_finalists
    for idea in top_ideas:
        if isinstance(idea, dict) and "text" not in idea:
            idea["text"] = idea.get("title", idea.get("id", ""))

    finalists_path = run_dir / "stage_e_finalists_input.json"
    write_json(finalists_path, top_ideas)

    # Literature retrieval (API mode with graceful fallback)
    query_text = " ".join(
        str(idea.get("text", idea.get("id", "")))[:200]
        for idea in top_ideas[:3] if isinstance(idea, dict)
    )
    retrieved_path = run_dir / "stage_e_retrieved.json"
    lit_cmd = [
        "python3", str(SCRIPTS_DIR / "literature_retrieval.py"),
        "--query", query_text[:500] if query_text else "research finance",
        "--mode", "api",
        "--top-k", "8",
        "--output", str(retrieved_path),
        "--pretty",
    ]
    total_cost = 0.0
    try:
        result = run_subprocess(lit_cmd)
        if result.returncode != 0:
            log(f"Stage E retrieval warning: {result.stderr[:300]}")
            write_json(retrieved_path, {"query": query_text, "mode": "api",
                                         "results_count": 0, "results": []})
    except Exception as exc:
        log(f"Stage E retrieval failed: {exc}")
        write_json(retrieved_path, {"query": "", "mode": "api",
                                     "results_count": 0, "results": []})

    # Verify finalists
    verification_path = run_dir / "stage_e_verification.json"
    verify_cmd = [
        "python3", str(SCRIPTS_DIR / "verify_finalists.py"),
        "--ideas", str(finalists_path),
        "--retrieved", str(retrieved_path),
        "--verifier-models", ",".join(verifier_models),
        "--output", str(verification_path),
        "--pretty",
    ]
    try:
        result = run_subprocess(verify_cmd, timeout=STAGE_TIMEOUT * 2)
        if result.returncode != 0:
            raise RuntimeError(f"verify_finalists: {result.stderr[:500]}")
        for model in verifier_models:
            in_tok, out_tok = TOKEN_ESTIMATES["verify_finalists"]
            total_cost += estimate_cost(model, in_tok, out_tok, pricing) * top_k
        return True, verification_path, total_cost
    except Exception as exc:
        log(f"Stage E (verification) failed: {exc}")
        return False, None, total_cost


def run_stage_f(run_dir: Path, rankings_path: Path, config: dict) -> tuple[bool, Path | None, float]:
    """Stage F: Portfolio optimization."""
    portfolio_cfg = config.get("portfolio", {})
    taxonomy_path = SETTINGS_DIR / "taxonomy.json"
    evidence_path = run_dir / "stage_e_verification.json"
    output_path = run_dir / "stage_f_portfolio.json"

    cmd = [
        "python3", str(SCRIPTS_DIR / "portfolio_optimizer.py"),
        "--input", str(rankings_path),
        "--taxonomy", str(taxonomy_path),
        "-K", str(int(portfolio_cfg.get("K", 5))),
        "--lambda-uncertainty", str(float(portfolio_cfg.get("lambda_uncertainty", 0.3))),
        "--lambda-risk", str(float(portfolio_cfg.get("lambda_risk", 0.2))),
        "--lambda-redundancy", str(float(portfolio_cfg.get("lambda_redundancy", 0.4))),
        "--output", str(output_path),
        "--pretty",
    ]
    if evidence_path.exists():
        cmd.extend(["--evidence", str(evidence_path)])
    try:
        result = run_subprocess(cmd)
        if result.returncode != 0:
            raise RuntimeError(result.stderr[:500])
        return True, output_path, 0.0
    except Exception as exc:
        log(f"Stage F failed: {exc}")
        return False, None, 0.0


def run_stage_g(run_dir: Path, ideas_path: Path, rankings_path: Path,
                config: dict, seed: int) -> tuple[bool, Path | None, dict[str, float] | None, float]:
    """Stage G: Failure ledger update and channel weight feedback."""
    feedback_cfg = config.get("feedback", {})
    ledger_path = run_dir.parent / "failure_ledger.json"
    output_path = run_dir / "stage_g_feedback.json"

    # Build round input: merge ideas with tournament percentile info
    ideas_data = load_json(ideas_path) if ideas_path.exists() else []
    rankings_data = load_json(rankings_path) if rankings_path.exists() else {}
    rankings_list = []
    if isinstance(rankings_data, dict):
        rankings_list = rankings_data.get("rankings", [])
    elif isinstance(rankings_data, list):
        rankings_list = rankings_data

    rank_map: dict[str, int] = {}
    total_ranked = len(rankings_list) if isinstance(rankings_list, list) else 0
    for idx, entry in enumerate(rankings_list):
        if isinstance(entry, dict):
            rank_map[str(entry.get("id", ""))] = idx + 1

    round_input: list[dict] = []
    if isinstance(ideas_data, list):
        for idea in ideas_data:
            if not isinstance(idea, dict):
                continue
            idea_id = str(idea.get("id", ""))
            rank = rank_map.get(idea_id, total_ranked)
            round_input.append({
                "channel": idea.get("channel", "unknown"),
                "id": idea_id,
                "tournament_rank": rank,
                "total_in_tournament": max(total_ranked, 1),
                "gates_passed": True,
            })

    if not round_input:
        log("Stage G: no ideas to process for feedback")
        return True, None, None, 0.0

    round_input_path = run_dir / "stage_g_round_input.json"
    write_json(round_input_path, round_input)

    cmd = [
        "python3", str(SCRIPTS_DIR / "failure_ledger.py"),
        "--input", str(round_input_path),
        "--ledger", str(ledger_path),
        "--success-quantile", str(float(feedback_cfg.get("success_quantile", 0.5))),
        "--exploration-floor", str(float(feedback_cfg.get("exploration_floor", 0.10))),
        "--seed", str(seed),
        "--output", str(output_path),
        "--pretty",
    ]
    try:
        result = run_subprocess(cmd)
        if result.returncode != 0:
            raise RuntimeError(result.stderr[:500])
        feedback_data = load_json(output_path)
        channel_weights = None
        if isinstance(feedback_data, dict):
            channel_weights = feedback_data.get("channel_weights")
            if not isinstance(channel_weights, dict):
                channel_weights = None
        return True, output_path, channel_weights, 0.0
    except Exception as exc:
        log(f"Stage G failed: {exc}")
        return False, None, None, 0.0


# ---------------------------------------------------------------------------
# Stage retry wrapper
# ---------------------------------------------------------------------------

def run_with_retry(stage_fn, *args, retries: int = 1, **kwargs):
    """Run a stage function with retry on failure."""
    for attempt in range(retries + 1):
        result = stage_fn(*args, **kwargs)
        success = result[0]
        if success:
            return result
        if attempt < retries:
            log(f"Retrying stage (attempt {attempt + 2}/{retries + 1})...")
            time.sleep(2)
    return result


# ---------------------------------------------------------------------------
# Top pick extraction
# ---------------------------------------------------------------------------

def extract_top_pick(portfolio_path: Path | None) -> str | None:
    """Extract the top-1 dissertation bet from portfolio output."""
    if portfolio_path is None or not portfolio_path.exists():
        return None
    try:
        data = load_json(portfolio_path)
        if isinstance(data, dict):
            portfolio = data.get("portfolio", {})
            if isinstance(portfolio, dict):
                top_1 = portfolio.get("top_1_bet", {})
                if isinstance(top_1, dict):
                    return str(top_1.get("id", ""))
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_iteration(iteration: int, run_dir: Path, config: dict, pricing: dict,
                  seed: int, channel_weights: dict[str, float] | None,
                  corpus_dir: Path | None, papers_json: Path | None
                  ) -> tuple[bool, dict, dict[str, float] | None]:
    """Execute one full pipeline iteration. Returns (success, metadata, new_weights)."""
    run_dir.mkdir(parents=True, exist_ok=True)
    stage_results: dict[str, dict] = {}
    total_cost = 0.0
    new_weights = channel_weights

    # Stage A: Concept graph
    log(f"  Stage A: concept graph")
    ok_a, holes_path, cost_a = run_with_retry(
        run_stage_a, run_dir, config, corpus_dir, papers_json)
    stage_results["A"] = {"success": ok_a, "cost": cost_a}
    total_cost += cost_a

    # Stage B: Generation
    log(f"  Stage B: idea generation")
    ok_b, ideas_path, cost_b = run_with_retry(
        run_stage_b, run_dir, config, seed, pricing, channel_weights)
    stage_results["B"] = {"success": ok_b, "cost": cost_b}
    total_cost += cost_b
    if not ok_b or ideas_path is None:
        log("  Pipeline halted: Stage B failed (no ideas generated)")
        metadata = _build_metadata(iteration, seed, stage_results, total_cost, None)
        write_json(run_dir / "metadata.json", metadata)
        return False, metadata, new_weights

    # Stage C: Mechanical gates
    log(f"  Stage C: mechanical gates")
    ok_c, survivors_path, cost_c = run_with_retry(
        run_stage_c, run_dir, ideas_path, config)
    stage_results["C"] = {"success": ok_c, "cost": cost_c}
    total_cost += cost_c
    screened_path = survivors_path if ok_c and survivors_path else ideas_path

    # Check survivor count
    try:
        survivors_data = load_json(screened_path)
        survivor_count = len(survivors_data) if isinstance(survivors_data, list) else 0
    except Exception:
        survivor_count = 0
    if survivor_count < 2:
        log(f"  Pipeline halted: only {survivor_count} ideas survived screening")
        metadata = _build_metadata(iteration, seed, stage_results, total_cost, None)
        write_json(run_dir / "metadata.json", metadata)
        return False, metadata, new_weights

    # Stage D: Tournament + judging + ranking
    log(f"  Stage D: tournament and ranking ({survivor_count} ideas)")
    ok_d, rankings_path, cost_d = run_with_retry(
        run_stage_d, run_dir, screened_path, config, seed, pricing)
    stage_results["D"] = {"success": ok_d, "cost": cost_d}
    total_cost += cost_d
    if not ok_d or rankings_path is None:
        log("  Pipeline halted: Stage D failed (no rankings)")
        metadata = _build_metadata(iteration, seed, stage_results, total_cost, None)
        write_json(run_dir / "metadata.json", metadata)
        return False, metadata, new_weights

    # Stage E: Literature retrieval + verification
    log(f"  Stage E: verification")
    ok_e, verification_path, cost_e = run_with_retry(
        run_stage_e, run_dir, rankings_path, config, pricing)
    stage_results["E"] = {"success": ok_e, "cost": cost_e}
    total_cost += cost_e

    # Stage F: Portfolio optimization
    log(f"  Stage F: portfolio optimization")
    ok_f, portfolio_path, cost_f = run_with_retry(
        run_stage_f, run_dir, rankings_path, config)
    stage_results["F"] = {"success": ok_f, "cost": cost_f}
    total_cost += cost_f

    # Stage G: Feedback / failure ledger
    log(f"  Stage G: failure ledger and channel weights")
    ok_g, feedback_path, updated_weights, cost_g = run_with_retry(
        run_stage_g, run_dir, ideas_path, rankings_path, config, seed)
    stage_results["G"] = {"success": ok_g, "cost": cost_g}
    total_cost += cost_g
    if updated_weights is not None:
        new_weights = updated_weights

    top_pick = extract_top_pick(portfolio_path)
    metadata = _build_metadata(iteration, seed, stage_results, total_cost, top_pick)
    write_json(run_dir / "metadata.json", metadata)

    all_ok = ok_b and ok_d  # B and D are required; others are best-effort
    return all_ok, metadata, new_weights


def _build_metadata(iteration: int, seed: int, stage_results: dict,
                    total_cost: float, top_pick: str | None) -> dict:
    """Build per-run metadata dict."""
    return {
        "iteration": iteration,
        "seed": seed,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "stages": stage_results,
        "total_estimated_cost": round(total_cost, 4),
        "top_portfolio_pick": top_pick,
    }


def write_summary(runs_dir: Path, all_metadata: list[dict]) -> None:
    """Write aggregate summary across all iterations."""
    total_iterations = len(all_metadata)
    successful = sum(1 for m in all_metadata
                     if all(s.get("success", False)
                            for s in m.get("stages", {}).values()
                            if isinstance(s, dict)))
    failed = total_iterations - successful
    total_cost = sum(float(m.get("total_estimated_cost", 0)) for m in all_metadata)

    top_picks: list[str] = []
    for m in all_metadata:
        pick = m.get("top_portfolio_pick")
        if pick:
            top_picks.append(pick)

    # Find most common top pick
    best_pick = None
    if top_picks:
        counts: dict[str, int] = {}
        for pick in top_picks:
            counts[pick] = counts.get(pick, 0) + 1
        best_pick = max(counts, key=lambda k: counts[k])

    summary = {
        "total_iterations": total_iterations,
        "successful_iterations": successful,
        "failed_iterations": failed,
        "total_estimated_cost_usd": round(total_cost, 4),
        "best_portfolio_pick": best_pick,
        "pick_frequency": {pick: top_picks.count(pick) for pick in set(top_picks)} if top_picks else {},
        "iterations": [
            {
                "iteration": m.get("iteration"),
                "seed": m.get("seed"),
                "timestamp": m.get("timestamp"),
                "cost": m.get("total_estimated_cost"),
                "top_pick": m.get("top_portfolio_pick"),
                "stages_ok": [
                    stage for stage, info in m.get("stages", {}).items()
                    if isinstance(info, dict) and info.get("success")
                ],
            }
            for m in all_metadata
        ],
    }
    write_json(runs_dir / "summary.json", summary)
    log(f"Summary written to {runs_dir / 'summary.json'}")
    log(f"  Total: {total_iterations} iterations, {successful} successful, "
        f"{failed} failed, ${total_cost:.2f} estimated cost")
    if best_pick:
        log(f"  Best pick across runs: {best_pick}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="GEPS v5 continuous pipeline runner."
    )
    parser.add_argument(
        "--geps-config", required=True,
        help="Path to geps-config.json",
    )
    parser.add_argument(
        "--runs-dir", default="./runs/",
        help="Directory for run outputs (default: ./runs/)",
    )
    parser.add_argument(
        "--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS,
        help=f"Maximum pipeline iterations (default: {DEFAULT_MAX_ITERATIONS})",
    )
    parser.add_argument(
        "--sleep-between-runs", type=int, default=DEFAULT_SLEEP_BETWEEN,
        help=f"Seconds to sleep between iterations (default: {DEFAULT_SLEEP_BETWEEN})",
    )
    parser.add_argument(
        "--stop-on-consecutive-failures", type=int, default=DEFAULT_CONSECUTIVE_FAILURES,
        help=f"Stop after N consecutive failed iterations (default: {DEFAULT_CONSECUTIVE_FAILURES})",
    )
    parser.add_argument(
        "--base-seed", type=int, default=DEFAULT_BASE_SEED,
        help=f"Base random seed; iteration seed = base + iteration (default: {DEFAULT_BASE_SEED})",
    )
    parser.add_argument(
        "--corpus-dir", type=str, default=None,
        help="Optional corpus directory for Stage A concept graph",
    )
    parser.add_argument(
        "--papers-json", type=str, default=None,
        help="Optional papers JSON file for Stage A concept graph",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate config and exit without running pipeline",
    )
    return parser.parse_args()


def main() -> None:
    """Main entry point."""
    args = parse_args()

    # Load config and pricing
    config_path = resolve_path(args.geps_config)
    if not config_path.exists():
        log(f"Config not found: {config_path}")
        sys.exit(1)
    config = load_json(config_path)
    if not isinstance(config, dict):
        log("Config must be a JSON object")
        sys.exit(1)

    pricing_path = SETTINGS_DIR / "model_pricing.json"
    pricing = {}
    if pricing_path.exists():
        pricing_data = load_json(pricing_path)
        if isinstance(pricing_data, dict):
            pricing = pricing_data

    runs_dir = Path(args.runs_dir).resolve()
    runs_dir.mkdir(parents=True, exist_ok=True)

    corpus_dir = resolve_path(args.corpus_dir) if args.corpus_dir else None
    papers_json = resolve_path(args.papers_json) if args.papers_json else None

    log(f"GEPS v5 Continuous Runner")
    log(f"  Config: {config_path}")
    log(f"  Runs dir: {runs_dir}")
    log(f"  Max iterations: {args.max_iterations}")
    log(f"  Base seed: {args.base_seed}")
    log(f"  Channels: {list(config.get('generation', {}).get('channels', {}).keys())}")

    if args.dry_run:
        log("Dry run: config validated successfully")
        sys.exit(0)

    # Main loop
    all_metadata: list[dict] = []
    consecutive_failures = 0
    channel_weights: dict[str, float] | None = None

    for iteration in range(args.max_iterations):
        seed = args.base_seed + iteration
        timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        run_dir = runs_dir / f"run_{timestamp}_iter{iteration:04d}"

        log(f"=== Iteration {iteration} (seed={seed}) ===")

        try:
            success, metadata, channel_weights = run_iteration(
                iteration=iteration,
                run_dir=run_dir,
                config=config,
                pricing=pricing,
                seed=seed,
                channel_weights=channel_weights,
                corpus_dir=corpus_dir,
                papers_json=papers_json,
            )
        except Exception as exc:
            log(f"Iteration {iteration} crashed: {exc}")
            success = False
            metadata = _build_metadata(iteration, seed, {}, 0.0, None)

        all_metadata.append(metadata)

        if success:
            consecutive_failures = 0
            log(f"  Iteration {iteration} completed successfully "
                f"(cost=${metadata.get('total_estimated_cost', 0):.2f}, "
                f"pick={metadata.get('top_portfolio_pick', 'none')})")
        else:
            consecutive_failures += 1
            log(f"  Iteration {iteration} failed "
                f"({consecutive_failures}/{args.stop_on_consecutive_failures} consecutive)")
            if consecutive_failures >= args.stop_on_consecutive_failures:
                log(f"Stopping: {consecutive_failures} consecutive failures reached limit")
                break

        # Sleep between runs (skip after last iteration)
        if iteration < args.max_iterations - 1:
            log(f"  Sleeping {args.sleep_between_runs}s before next iteration...")
            time.sleep(args.sleep_between_runs)

    # Write aggregate summary
    write_summary(runs_dir, all_metadata)


if __name__ == "__main__":
    main()
