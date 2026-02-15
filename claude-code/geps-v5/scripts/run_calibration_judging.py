from __future__ import annotations

import argparse
import json
import os
import pathlib
import random
import subprocess
import sys
import time

TIERS = ("high", "mid", "low")
TIER_PAIRS = (("high", "mid"), ("high", "low"), ("mid", "low"))
MAX_SAMPLE_TRIES = 4000
COST_PER_CALL_USD = 23.0 / 225.0


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Calibration judging orchestrator.")
    parser.add_argument("--pack", type=pathlib.Path, required=True)
    parser.add_argument("--judge-pool", type=str, required=True)
    parser.add_argument("--matches-per-tierpair", type=int, default=15)
    parser.add_argument("--min-appearances", type=int, default=3)
    parser.add_argument("--swap-fraction", type=float, default=0.3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--llm-runner-path", type=pathlib.Path, required=True)
    parser.add_argument("--judge-prompt", type=pathlib.Path, required=True)
    parser.add_argument("--judge-script", type=pathlib.Path, required=True)
    parser.add_argument("--calibration-script", type=pathlib.Path, required=True)
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--summary", action="store_true")
    return parser.parse_args()


def read_json(path: pathlib.Path) -> object:
    """Read JSON using json.loads."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"File not found: {path}") from exc
    except OSError as exc:
        raise ValueError(f"Failed reading {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def write_json(path: pathlib.Path, payload: object, pretty: bool) -> None:
    """Write JSON using json.dumps."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2 if pretty else None)
    if pretty:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def parse_judges(raw: str) -> list[str]:
    """Parse and dedupe judge names."""
    judges: list[str] = []
    seen: set[str] = set()
    for token in raw.split(","):
        model = token.strip()
        if model and model not in seen:
            judges.append(model)
            seen.add(model)
    if not judges:
        raise ValueError("--judge-pool must include at least one model")
    return judges


def load_pack(path: pathlib.Path) -> tuple[dict[str, list[dict[str, object]]], dict[str, str]]:
    """Load tiers and validate required paper fields."""
    root = read_json(path)
    if not isinstance(root, dict):
        raise ValueError("Calibration pack root must be a JSON object")
    source = root.get("tiers") if isinstance(root.get("tiers"), dict) else root
    if not isinstance(source, dict):
        raise ValueError("Calibration pack must define tier maps")

    tiers: dict[str, list[dict[str, object]]] = {}
    id_to_tier: dict[str, str] = {}
    for tier in TIERS:
        items = source.get(tier)
        if not isinstance(items, list):
            raise ValueError(f"Missing tier list: {tier}")
        if len(items) < 3:
            raise ValueError(f"Tier '{tier}' must have at least 3 papers")

        papers: list[dict[str, object]] = []
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"Tier '{tier}' entry {idx} must be an object")
            pid = item.get("id")
            title = item.get("title")
            if not isinstance(pid, str) or not pid.strip():
                raise ValueError(f"Tier '{tier}' paper {idx} missing non-empty id")
            if not isinstance(title, str) or not title.strip():
                raise ValueError(f"Tier '{tier}' paper '{pid}' missing non-empty title")
            if pid in id_to_tier:
                raise ValueError(f"Duplicate paper id in pack: {pid}")
            id_to_tier[pid] = tier
            papers.append(item)
        tiers[tier] = papers

    return tiers, id_to_tier


def paper_text(paper: dict[str, object]) -> str:
    """Choose best available summary text."""
    for key in ("summary", "abstract", "text", "paper_summary", "description", "title"):
        value = paper.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def count_appearances(
    sampled: list[tuple[dict[str, object], dict[str, object]]],
    papers_a: list[dict[str, object]],
    papers_b: list[dict[str, object]],
) -> tuple[dict[str, int], dict[str, int]]:
    """Count sampled appearances for both sides."""
    counts_a = {str(p["id"]): 0 for p in papers_a}
    counts_b = {str(p["id"]): 0 for p in papers_b}
    for a, b in sampled:
        counts_a[str(a["id"])] += 1
        counts_b[str(b["id"])] += 1
    return counts_a, counts_b


def min_appearances_met(
    sampled: list[tuple[dict[str, object], dict[str, object]]],
    papers_a: list[dict[str, object]],
    papers_b: list[dict[str, object]],
    minimum: int,
) -> bool:
    """Return True if every paper appears >= minimum."""
    if minimum <= 0:
        return True
    counts_a, counts_b = count_appearances(sampled, papers_a, papers_b)
    return all(v >= minimum for v in counts_a.values()) and all(v >= minimum for v in counts_b.values())


def greedy_sample(
    all_pairs: list[tuple[dict[str, object], dict[str, object]]],
    papers_a: list[dict[str, object]],
    papers_b: list[dict[str, object]],
    match_count: int,
    min_appearances: int,
    rng: random.Random,
) -> list[tuple[dict[str, object], dict[str, object]]]:
    """Fallback sampler favoring unmet quota papers."""
    remaining = list(all_pairs)
    rng.shuffle(remaining)
    selected: list[tuple[dict[str, object], dict[str, object]]] = []
    counts_a = {str(p["id"]): 0 for p in papers_a}
    counts_b = {str(p["id"]): 0 for p in papers_b}

    while remaining and len(selected) < match_count:
        best_score = -1
        best_idx: list[int] = []
        for i, (a, b) in enumerate(remaining):
            aid = str(a["id"])
            bid = str(b["id"])
            score = 0
            if counts_a[aid] < min_appearances:
                score += min_appearances - counts_a[aid]
            if counts_b[bid] < min_appearances:
                score += min_appearances - counts_b[bid]
            if score > best_score:
                best_score = score
                best_idx = [i]
            elif score == best_score:
                best_idx.append(i)
        pick = rng.choice(best_idx) if best_idx else 0
        a, b = remaining.pop(pick)
        selected.append((a, b))
        counts_a[str(a["id"])] += 1
        counts_b[str(b["id"])] += 1

    return selected


def sample_tier_pairs(
    papers_a: list[dict[str, object]],
    papers_b: list[dict[str, object]],
    match_count: int,
    min_appearances: int,
    rng: random.Random,
) -> list[tuple[dict[str, object], dict[str, object]]]:
    """Sample unique cross-tier pairs with constraints."""
    if match_count <= 0:
        raise ValueError("--matches-per-tierpair must be > 0")
    if min_appearances < 0:
        raise ValueError("--min-appearances must be >= 0")

    max_pairs = len(papers_a) * len(papers_b)
    if match_count > max_pairs:
        raise ValueError(f"Requested {match_count} matches but only {max_pairs} unique pairs exist")
    if min_appearances > len(papers_a) or min_appearances > len(papers_b):
        raise ValueError("--min-appearances too high for unique pair limits")
    if match_count < len(papers_a) * min_appearances:
        raise ValueError("--matches-per-tierpair too low for side A min appearances")
    if match_count < len(papers_b) * min_appearances:
        raise ValueError("--matches-per-tierpair too low for side B min appearances")

    all_pairs = [(a, b) for a in papers_a for b in papers_b]
    for _ in range(MAX_SAMPLE_TRIES):
        sampled = rng.sample(all_pairs, match_count)
        if min_appearances_met(sampled, papers_a, papers_b, min_appearances):
            return sampled

    sampled = greedy_sample(all_pairs, papers_a, papers_b, match_count, min_appearances, rng)
    if min_appearances_met(sampled, papers_a, papers_b, min_appearances):
        return sampled
    raise ValueError("Unable to satisfy min-appearance constraints with requested sampling")


def apply_swaps(
    sampled: list[tuple[dict[str, object], dict[str, object]]],
    swap_fraction: float,
    rng: random.Random,
) -> list[tuple[dict[str, object], dict[str, object]]]:
    """Swap A/B order for a fraction of sampled matches."""
    if not 0.0 <= swap_fraction <= 1.0:
        raise ValueError("--swap-fraction must be between 0 and 1")
    swap_count = int(round(len(sampled) * swap_fraction))
    swap_count = max(0, min(len(sampled), swap_count))
    swap_idx = set(rng.sample(range(len(sampled)), swap_count)) if swap_count else set()
    return [(b, a) if i in swap_idx else (a, b) for i, (a, b) in enumerate(sampled)]


def build_match_specs(
    tiers: dict[str, list[dict[str, object]]],
    judges: list[str],
    matches_per_tierpair: int,
    min_appearances: int,
    swap_fraction: float,
    rng: random.Random,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Build sampled base matches and per-judge match specs."""
    base_matches: list[dict[str, object]] = []
    counter = 1
    for tier_a, tier_b in TIER_PAIRS:
        sampled = sample_tier_pairs(tiers[tier_a], tiers[tier_b], matches_per_tierpair, min_appearances, rng)
        for paper_a, paper_b in apply_swaps(sampled, swap_fraction, rng):
            base_matches.append(
                {
                    "base_match_id": f"CAL-{counter:03d}",
                    "tier_pair": f"{tier_a}-{tier_b}",
                    "paper_a": paper_a,
                    "paper_b": paper_b,
                }
            )
            counter += 1

    specs: list[dict[str, object]] = []
    for base in base_matches:
        base_id = str(base["base_match_id"])
        paper_a = base["paper_a"]
        paper_b = base["paper_b"]
        if not isinstance(paper_a, dict) or not isinstance(paper_b, dict):
            raise ValueError("Invalid sampled paper payload")
        for model in judges:
            match_id = f"{base_id}-{model}"
            specs.append(
                {
                    "match_id": match_id,
                    "idea_a": {"id": str(paper_a["id"]), "text": paper_text(paper_a)},
                    "idea_b": {"id": str(paper_b["id"]), "text": paper_text(paper_b)},
                    "judge": {"judge_id": f"{match_id}-J1", "model": model, "pos_a": 1, "pos_b": -1},
                    "tier_pair": base["tier_pair"],
                }
            )
    return base_matches, specs


def safe_name(text: str) -> str:
    """Convert arbitrary string to safe filename token."""
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in text)


def build_judge_command(
    spec_file: pathlib.Path,
    out_file: pathlib.Path,
    judge_script: pathlib.Path,
    judge_prompt: pathlib.Path,
    llm_runner: pathlib.Path,
) -> list[str]:
    """Create judge_pairwise subprocess command."""
    return [
        sys.executable,
        str(judge_script),
        "--match-spec",
        str(spec_file),
        "--prompt-template",
        str(judge_prompt),
        "--llm-runner-path",
        str(llm_runner),
        "--output",
        str(out_file),
    ]


def enrich_result(result: dict[str, object], spec: dict[str, object], id_to_tier: dict[str, str]) -> dict[str, object]:
    """Attach tier metadata and judge model fields."""
    out = dict(result)
    idea_a = spec.get("idea_a")
    idea_b = spec.get("idea_b")
    judge = spec.get("judge")
    if not isinstance(idea_a, dict) or not isinstance(idea_b, dict) or not isinstance(judge, dict):
        raise ValueError("Invalid match spec for enrichment")

    a_id = str(idea_a.get("id", ""))
    b_id = str(idea_b.get("id", ""))
    paper_a = dict(out["paper_a"]) if isinstance(out.get("paper_a"), dict) else {}
    paper_b = dict(out["paper_b"]) if isinstance(out.get("paper_b"), dict) else {}
    paper_a.setdefault("id", a_id)
    paper_b.setdefault("id", b_id)
    paper_a["tier"] = id_to_tier.get(a_id, "unknown")
    paper_b["tier"] = id_to_tier.get(b_id, "unknown")

    out["paper_a"] = paper_a
    out["paper_b"] = paper_b
    out.setdefault("match_id", spec.get("match_id"))
    out["judge_model"] = str(judge.get("model", ""))
    out["tier_pair"] = spec.get("tier_pair")
    return out


def human_summary(report: dict[str, object]) -> str:
    """Render human-readable run summary."""
    lines = [
        "Calibration orchestration summary",
        f"  Base matches: {report.get('base_matches_total', 0)}",
        f"  Judge calls planned: {report.get('judge_calls_total', 0)}",
        f"  Judge calls executed: {report.get('judge_calls_executed', 0)}",
        f"  Existing reused: {report.get('judge_calls_skipped_existing', 0)}",
        f"  Successful results: {report.get('successful_results', 0)}",
        f"  Failed calls: {report.get('failed_calls', 0)}",
    ]
    if report.get("results_file"):
        lines.append(f"  Results file: {report.get('results_file')}")
    if report.get("weights_file"):
        lines.append(f"  Weights file: {report.get('weights_file')}")
    calibration = report.get("calibration")
    if isinstance(calibration, dict) and calibration.get("message"):
        lines.append(f"  Calibration note: {calibration.get('message')}")
    failures = report.get("failures")
    if isinstance(failures, list) and failures:
        lines.append("  Failure samples:")
        for item in failures[:5]:
            if isinstance(item, dict):
                lines.append(f"    - {item.get('match_id', 'unknown')}: {item.get('error', 'unknown')} ")
    return "\n".join(lines)


def main() -> None:
    """CLI entrypoint."""
    args = parse_args()
    try:
        judges = parse_judges(args.judge_pool)
        pack_path = args.pack.expanduser()
        output_dir = args.output_dir.expanduser()
        judge_script = args.judge_script.expanduser()
        judge_prompt = args.judge_prompt.expanduser()
        llm_runner = args.llm_runner_path.expanduser()
        calibration_script = args.calibration_script.expanduser()

        tiers, id_to_tier = load_pack(pack_path)
        rng = random.Random(args.seed)
        base_matches, specs = build_match_specs(
            tiers,
            judges,
            args.matches_per_tierpair,
            args.min_appearances,
            args.swap_fraction,
            rng,
        )

        total_matches = len(base_matches)
        total_calls = len(specs)
        cost_estimate = int(round(total_calls * COST_PER_CALL_USD))
        print("Calibration will run:", file=sys.stderr)
        print(f"  {total_matches} matches × {len(judges)} judges = {total_calls} total LLM calls", file=sys.stderr)
        print(f"  Estimated cost: ~${cost_estimate} (one-time, reusable)", file=sys.stderr)

        judge_dir = output_dir / "judge_results"
        temp_dir = output_dir / "_tmp_specs"
        if not args.dry_run:
            judge_dir.mkdir(parents=True, exist_ok=True)
            temp_dir.mkdir(parents=True, exist_ok=True)

        aggregated: list[dict[str, object]] = []
        failures: list[dict[str, object]] = []
        planned: list[dict[str, object]] = []
        executed_calls = 0
        skipped_existing = 0

        for spec in specs:
            match_id = str(spec["match_id"])
            out_file = judge_dir / f"{safe_name(match_id)}.json"

            if args.skip_existing and out_file.exists():
                skipped_existing += 1
                if args.dry_run:
                    planned.append({"match_id": match_id, "action": "skip-existing", "output": str(out_file)})
                try:
                    old = read_json(out_file)
                    if not isinstance(old, dict):
                        raise ValueError("existing result is not a JSON object")
                    aggregated.append(enrich_result(old, spec, id_to_tier))
                except Exception as exc:
                    failures.append({"match_id": match_id, "error": f"Failed loading existing result: {exc}"})
                continue

            if args.dry_run:
                spec_file = temp_dir / f"spec-{safe_name(match_id)}.json"
                planned.append(
                    {
                        "match_id": match_id,
                        "action": "run",
                        "output": str(out_file),
                        "command": build_judge_command(spec_file, out_file, judge_script, judge_prompt, llm_runner),
                        "match_spec": spec,
                    }
                )
                continue

            executed_calls += 1
            stamp = f"{os.getpid()}-{int(time.time() * 1000)}-{rng.randint(1000, 9999)}"
            spec_file = temp_dir / f"spec-{safe_name(match_id)}-{stamp}.json"
            write_json(spec_file, spec, pretty=True)

            proc = subprocess.run(
                build_judge_command(spec_file, out_file, judge_script, judge_prompt, llm_runner),
                capture_output=True,
                text=True,
            )
            try:
                if spec_file.exists():
                    spec_file.unlink()
            except OSError:
                pass

            if proc.returncode != 0:
                msg = (proc.stderr or proc.stdout or f"judge script exited with code {proc.returncode}").strip()
                failures.append({"match_id": match_id, "error": msg, "returncode": proc.returncode})
                continue
            if not out_file.exists():
                failures.append({"match_id": match_id, "error": f"Judge output missing: {out_file}"})
                continue

            try:
                result = read_json(out_file)
                if not isinstance(result, dict):
                    raise ValueError("judge output is not a JSON object")
                aggregated.append(enrich_result(result, spec, id_to_tier))
            except Exception as exc:
                failures.append({"match_id": match_id, "error": f"Failed loading judge output: {exc}"})

        results_file = output_dir / "calibration_results.json"
        weights_file = output_dir / "calibration_weights.json"
        calibration_report: dict[str, object] = {"attempted": False, "success": False, "message": "dry-run"}

        if not args.dry_run:
            write_json(results_file, aggregated, pretty=args.pretty)
            if calibration_script.exists():
                cal_cmd = [
                    sys.executable,
                    str(calibration_script),
                    "--pack",
                    str(pack_path),
                    "--results",
                    str(results_file),
                    "--output",
                    str(weights_file),
                    "--pretty",
                ]
                cal = subprocess.run(cal_cmd, capture_output=True, text=True)
                if cal.returncode == 0 and weights_file.exists():
                    calibration_report = {"attempted": True, "success": True, "message": "calibration weights generated"}
                else:
                    msg = (cal.stderr or cal.stdout or f"calibration script exited with code {cal.returncode}").strip()
                    calibration_report = {"attempted": True, "success": False, "message": msg}
            else:
                calibration_report = {
                    "attempted": False,
                    "success": False,
                    "message": f"calibration script not found: {calibration_script}",
                }

        report: dict[str, object] = {
            "ok": len(failures) == 0,
            "dry_run": bool(args.dry_run),
            "seed": args.seed,
            "base_matches_total": total_matches,
            "judge_pool_size": len(judges),
            "judge_calls_total": total_calls,
            "judge_calls_executed": executed_calls,
            "judge_calls_skipped_existing": skipped_existing,
            "successful_results": len(aggregated),
            "failed_calls": len(failures),
            "cost_estimate_usd": cost_estimate,
            "results_file": None if args.dry_run else str(results_file),
            "weights_file": None if args.dry_run else (str(weights_file) if weights_file.exists() else None),
            "calibration": calibration_report,
            "failures": failures,
        }

        if args.dry_run:
            report["planned_calls"] = planned
            report["planned_match_specs"] = [
                entry["match_spec"]
                for entry in planned
                if isinstance(entry, dict) and entry.get("action") == "run" and "match_spec" in entry
            ]

        if args.summary:
            print(human_summary(report))
        else:
            print(json.dumps(report, indent=2 if args.pretty else None))

        if failures:
            sys.exit(2)

    except Exception as exc:
        err = {"ok": False, "error": str(exc)}
        if args.summary:
            print(f"Error: {exc}", file=sys.stderr)
        else:
            print(json.dumps(err, indent=2 if args.pretty else None), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
