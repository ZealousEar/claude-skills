from __future__ import annotations

import argparse
import copy
import json
import random
import sys
from collections import Counter
from pathlib import Path

PROVIDER_MAP: dict[str, str] = {
    "opus": "anthropic",
    "gpt-5.3-codex": "openai",
    "gpt-5.2-codex": "openai",
    "gpt-5.2": "openai",
    "gemini-3-pro": "google",
    "kimi-2.5": "moonshot",
}

COST_PER_TIER: dict[str, float] = {
    "cheap": 0.02,
    "mixed": 0.06,
    "best": 0.12,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Swiss-system tournament pairing engine with adaptive judging and field cuts"
    )
    parser.add_argument("--ideas", required=True, help="Path to input ideas JSON")
    parser.add_argument(
        "--rounds", type=int, default=6, help="Number of Swiss rounds (default: 6)"
    )
    parser.add_argument(
        "--field-cuts",
        default="{}",
        help='JSON string like {"after_round_3": 30, "after_round_5": 20}',
    )
    parser.add_argument(
        "--schedule",
        required=True,
        help="Path to judging schedule JSON",
    )
    parser.add_argument(
        "--judge-pool",
        required=True,
        help='Comma-separated judge models, e.g. "opus,gpt-5.3-codex,gemini-3-pro"',
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed for reproducibility"
    )
    parser.add_argument(
        "--output",
        default="-",
        help='Output path for JSON (default: "-" for stdout)',
    )
    parser.add_argument("--pretty", action="store_true", help="Indented JSON output")
    parser.add_argument(
        "--validate", action="store_true", help="Validate inputs without running tournament"
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print human-readable summary instead of JSON output",
    )
    return parser.parse_args(argv)


def load_json_file(path: Path) -> object:
    """Load JSON from path and return parsed object."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"File not found: {path}") from exc
    except OSError as exc:
        raise ValueError(f"Unable to read file: {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def parse_field_cuts(raw: str) -> dict[int, int]:
    """Parse field-cuts JSON string into round->size mapping."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid --field-cuts JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("--field-cuts must be a JSON object")

    parsed: dict[int, int] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not key.startswith("after_round_"):
            raise ValueError(
                f"Invalid field cut key '{key}'. Expected format: after_round_N"
            )
        suffix = key[len("after_round_") :]
        if not suffix.isdigit():
            raise ValueError(
                f"Invalid field cut key '{key}'. N in after_round_N must be an integer"
            )
        if not isinstance(value, int) or value <= 0:
            raise ValueError(
                f"Invalid field cut value for '{key}': expected positive integer"
            )
        parsed[int(suffix)] = value

    return dict(sorted(parsed.items()))


def parse_judge_pool(raw: str) -> list[str]:
    """Parse and validate comma-separated judge pool."""
    models = [m.strip() for m in raw.split(",") if m.strip()]
    if not models:
        raise ValueError("--judge-pool must contain at least one judge model")

    deduped: list[str] = []
    seen: set[str] = set()
    for model in models:
        if model not in seen:
            deduped.append(model)
            seen.add(model)
    return deduped


def provider_for_model(model: str) -> str:
    """Resolve model provider with hardcoded mapping and safe fallback."""
    if model in PROVIDER_MAP:
        return PROVIDER_MAP[model]
    if "-" in model:
        return model.split("-", 1)[0]
    return "unknown"


def parse_schedule(payload: object) -> dict[str, object]:
    """Validate and normalize judging schedule payload."""
    if not isinstance(payload, dict):
        raise ValueError("Schedule must be a JSON object")

    schedule = copy.deepcopy(payload)
    required_sections = ["rounds_1_to_3", "rounds_4_to_5", "round_6_plus"]

    for section in required_sections:
        section_data = schedule.get(section)
        if not isinstance(section_data, dict):
            raise ValueError(f"Schedule missing object section: {section}")
        judges_per_match = section_data.get("judges_per_match")
        model_tier = section_data.get("model_tier")
        if not isinstance(judges_per_match, int) or judges_per_match <= 0:
            raise ValueError(
                f"{section}.judges_per_match must be a positive integer"
            )
        if not isinstance(model_tier, str) or not model_tier.strip():
            raise ValueError(f"{section}.model_tier must be a non-empty string")

    escalation = schedule.get("disagreement_escalation", {})
    if not isinstance(escalation, dict):
        raise ValueError("disagreement_escalation must be an object")
    escalation_enabled = bool(escalation.get("enabled", False))
    max_judges = escalation.get("max_judges", 3)
    if not isinstance(max_judges, int) or max_judges <= 0:
        raise ValueError("disagreement_escalation.max_judges must be positive integer")
    schedule["disagreement_escalation"] = {
        "enabled": escalation_enabled,
        "max_judges": max_judges,
    }

    early_stop = schedule.get("early_stop", {})
    if not isinstance(early_stop, dict):
        raise ValueError("early_stop must be an object")
    unanimous_at = early_stop.get("unanimous_at", 2)
    skip_third_judge = bool(early_stop.get("skip_third_judge", False))
    if not isinstance(unanimous_at, int) or unanimous_at <= 0:
        raise ValueError("early_stop.unanimous_at must be positive integer")
    schedule["early_stop"] = {
        "unanimous_at": unanimous_at,
        "skip_third_judge": skip_third_judge,
    }

    return schedule


def round_policy(schedule: dict[str, object], round_number: int) -> dict[str, object]:
    """Return schedule policy for a given round number."""
    if round_number <= 3:
        policy = schedule["rounds_1_to_3"]
    elif round_number <= 5:
        policy = schedule["rounds_4_to_5"]
    else:
        policy = schedule["round_6_plus"]

    if not isinstance(policy, dict):
        raise ValueError(f"Invalid round policy for round {round_number}")
    return policy


def validate_ideas(payload: object) -> list[dict[str, str]]:
    """Validate ideas payload and return normalized idea objects."""
    if not isinstance(payload, list):
        raise ValueError("Ideas file must contain a JSON array")

    ideas: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    for idx, idea in enumerate(payload):
        if not isinstance(idea, dict):
            raise ValueError(f"Idea at index {idx} must be an object")
        idea_id = idea.get("id")
        text = idea.get("text")
        if not isinstance(idea_id, str) or not idea_id.strip():
            raise ValueError(f"Idea at index {idx} missing non-empty string 'id'")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Idea '{idea_id}' missing non-empty string 'text'")
        if idea_id in seen_ids:
            raise ValueError(f"Duplicate idea id detected: {idea_id}")

        seen_ids.add(idea_id)
        ideas.append({"id": idea_id, "text": text})

    if len(ideas) < 2:
        raise ValueError("At least 2 ideas are required to run a tournament")

    return ideas


def validate_configuration(
    ideas: list[dict[str, str]],
    rounds: int,
    field_cuts: dict[int, int],
    schedule: dict[str, object],
    judge_pool: list[str],
) -> None:
    """Validate cross-cutting constraints for tournament execution."""
    if rounds <= 0:
        raise ValueError("--rounds must be a positive integer")

    total_ideas = len(ideas)
    for cut_round, cut_size in field_cuts.items():
        if cut_round <= 0:
            raise ValueError("Field cut round must be >= 1")
        if cut_round > rounds:
            raise ValueError(
                f"Field cut after round {cut_round} exceeds total rounds ({rounds})"
            )
        if cut_size <= 0:
            raise ValueError(f"Field cut size must be positive (after round {cut_round})")
        if cut_size > total_ideas:
            raise ValueError(
                f"Field cut size {cut_size} after round {cut_round} exceeds total ideas ({total_ideas})"
            )

    unique_providers = {provider_for_model(model) for model in judge_pool}
    escalation = schedule["disagreement_escalation"]
    if not isinstance(escalation, dict):
        raise ValueError("Invalid disagreement_escalation section")

    max_needed = 0
    for round_number in range(1, rounds + 1):
        policy = round_policy(schedule, round_number)
        base_count = int(policy["judges_per_match"])
        if escalation.get("enabled", False):
            needed = max(base_count, int(escalation["max_judges"]))
        else:
            needed = base_count
        max_needed = max(max_needed, needed)

    if len(unique_providers) < max_needed:
        raise ValueError(
            "Judge pool does not have enough distinct providers for provider-diverse panels: "
            f"need {max_needed}, found {len(unique_providers)}"
        )


def initialize_states(
    ideas: list[dict[str, str]], rng: random.Random
) -> tuple[dict[str, dict[str, object]], dict[str, float], list[str]]:
    """Initialize per-idea state, tie-break scores, and active IDs."""
    states: dict[str, dict[str, object]] = {}
    tie_break: dict[str, float] = {}

    for idea in ideas:
        idea_id = idea["id"]
        states[idea_id] = {
            "id": idea_id,
            "wins": 0,
            "losses": 0,
            "byes": 0,
            "eliminated_after_round": None,
        }
        tie_break[idea_id] = rng.random()

    active_ids = [idea["id"] for idea in ideas]
    return states, tie_break, active_ids


def rank_ideas(
    active_ids: list[str],
    states: dict[str, dict[str, object]],
    tie_break: dict[str, float],
) -> list[str]:
    """Rank active ideas by Swiss score (wins desc) and stable tiebreakers."""
    return sorted(
        active_ids,
        key=lambda idea_id: (
            -int(states[idea_id]["wins"]),
            int(states[idea_id]["losses"]),
            tie_break[idea_id],
            idea_id,
        ),
    )


def played_key(idea_a: str, idea_b: str) -> tuple[str, str]:
    """Canonical key for match history lookup."""
    return tuple(sorted((idea_a, idea_b)))


def swiss_pairings(
    ranked_ids: list[str], played_pairs: set[tuple[str, str]]
) -> tuple[list[tuple[str, str]], list[str]]:
    """Create Swiss pairings with basic rematch avoidance and bye handling."""
    pool = ranked_ids[:]
    byes: list[str] = []

    if len(pool) % 2 == 1:
        byes.append(pool.pop())

    pairs: list[tuple[str, str]] = []
    idx = 0
    while idx < len(pool):
        idea_a = pool[idx]
        idea_b = pool[idx + 1]

        if played_key(idea_a, idea_b) in played_pairs:
            swap_idx = -1
            for candidate_idx in range(idx + 2, len(pool)):
                candidate = pool[candidate_idx]
                if played_key(idea_a, candidate) not in played_pairs:
                    swap_idx = candidate_idx
                    break
            if swap_idx != -1:
                pool[idx + 1], pool[swap_idx] = pool[swap_idx], pool[idx + 1]
                idea_b = pool[idx + 1]

        pairs.append((idea_a, idea_b))
        idx += 2

    return pairs, byes


def should_early_stop(
    votes: Counter,
    current_judges: int,
    base_judges: int,
    unanimous_at: int,
    skip_third_judge: bool,
) -> bool:
    """Check early-stop condition for unanimous panels."""
    if not skip_third_judge:
        return False
    if current_judges < unanimous_at:
        return False
    if current_judges >= base_judges:
        return False

    vote_values = list(votes.values())
    if not vote_values:
        return False

    return max(vote_values) == current_judges


def run_match(
    round_number: int,
    match_number: int,
    idea_a: str,
    idea_b: str,
    schedule: dict[str, object],
    judge_pool: list[str],
    rng: random.Random,
) -> tuple[dict[str, object], str, int]:
    """Simulate one match, assign judges, and return winner and judge call count."""
    policy = round_policy(schedule, round_number)
    base_judges = int(policy["judges_per_match"])
    tier = str(policy["model_tier"])

    escalation = schedule["disagreement_escalation"]
    escalation_enabled = bool(escalation.get("enabled", False))
    max_judges = int(escalation.get("max_judges", base_judges))
    if not escalation_enabled:
        max_judges = base_judges
    max_judges = max(max_judges, base_judges)

    early_stop = schedule["early_stop"]
    unanimous_at = int(early_stop.get("unanimous_at", 2))
    skip_third_judge = bool(early_stop.get("skip_third_judge", False))

    match_id = f"R{round_number}-M{match_number:02d}"
    judges: list[dict[str, object]] = []
    used_providers: set[str] = set()
    votes: Counter = Counter()
    pool_order = judge_pool[:]
    rng.shuffle(pool_order)
    pool_index = 0

    while len(judges) < max_judges:
        if len(judges) < base_judges:
            need_another = True
        elif escalation_enabled:
            need_another = votes[idea_a] == votes[idea_b]
        else:
            need_another = False

        if not need_another:
            break

        if should_early_stop(
            votes=votes,
            current_judges=len(judges),
            base_judges=base_judges,
            unanimous_at=unanimous_at,
            skip_third_judge=skip_third_judge,
        ):
            break

        model = ""
        provider = ""
        while pool_index < len(pool_order):
            candidate = pool_order[pool_index]
            pool_index += 1
            candidate_provider = provider_for_model(candidate)
            if candidate_provider in used_providers:
                continue
            model = candidate
            provider = candidate_provider
            break

        if not model:
            raise ValueError(
                "Unable to sample a provider-unique judge for this match. "
                "Increase provider diversity in --judge-pool."
            )

        used_providers.add(provider)

        idea_a_as_a = rng.random() < 0.5
        pos_a = 1 if idea_a_as_a else -1
        pos_b = -1 if idea_a_as_a else 1

        # This script only builds bracket assignments; it does not call external judge models.
        # A seeded pseudo-vote is used internally to advance Swiss standings deterministically.
        pseudo_vote = idea_a if rng.random() < 0.5 else idea_b
        votes[pseudo_vote] += 1

        judge_id = f"{match_id}-J{len(judges) + 1}"
        judges.append(
            {
                "judge_id": judge_id,
                "model": model,
                "provider": provider,
                "pos_a": pos_a,
                "pos_b": pos_b,
                "result": None,
            }
        )

    if votes[idea_a] > votes[idea_b]:
        winner = idea_a
    elif votes[idea_b] > votes[idea_a]:
        winner = idea_b
    else:
        winner = idea_a if rng.random() < 0.5 else idea_b

    match = {
        "match_id": match_id,
        "idea_a": idea_a,
        "idea_b": idea_b,
        "model_tier": tier,
        "judges": judges,
        "winner": winner,
    }
    return match, winner, len(judges)


def apply_field_cut(
    round_number: int,
    cut_size: int,
    active_ids: list[str],
    states: dict[str, dict[str, object]],
    tie_break: dict[str, float],
) -> tuple[list[str], list[str]]:
    """Apply a top-N field cut after a round."""
    if cut_size >= len(active_ids):
        return active_ids, []

    ranked = rank_ideas(active_ids, states, tie_break)
    kept = ranked[:cut_size]
    eliminated = ranked[cut_size:]

    for idea_id in eliminated:
        states[idea_id]["eliminated_after_round"] = round_number

    return kept, eliminated


def run_tournament(
    ideas: list[dict[str, str]],
    rounds: int,
    field_cuts: dict[int, int],
    schedule: dict[str, object],
    judge_pool: list[str],
    seed: int,
) -> dict[str, object]:
    """Run full Swiss tournament generation and return output JSON payload."""
    rng = random.Random(seed)
    states, tie_break, active_ids = initialize_states(ideas, rng)

    played_pairs: set[tuple[str, str]] = set()
    rounds_output: list[dict[str, object]] = []

    for round_number in range(1, rounds + 1):
        if len(active_ids) <= 1:
            break

        ranked = rank_ideas(active_ids, states, tie_break)
        pairs, byes = swiss_pairings(ranked, played_pairs)

        round_policy_data = round_policy(schedule, round_number)
        round_entry: dict[str, object] = {
            "round": round_number,
            "field_size": len(active_ids),
            "judges_per_match_target": int(round_policy_data["judges_per_match"]),
            "model_tier": str(round_policy_data["model_tier"]),
            "matches": [],
            "byes": byes,
            "eliminations": [],
            "field_size_after_cut": len(active_ids),
        }

        for bye_id in byes:
            states[bye_id]["wins"] = int(states[bye_id]["wins"]) + 1
            states[bye_id]["byes"] = int(states[bye_id]["byes"]) + 1

        for match_number, (idea_a, idea_b) in enumerate(pairs, start=1):
            match, winner, _judge_calls = run_match(
                round_number=round_number,
                match_number=match_number,
                idea_a=idea_a,
                idea_b=idea_b,
                schedule=schedule,
                judge_pool=judge_pool,
                rng=rng,
            )
            loser = idea_b if winner == idea_a else idea_a

            states[winner]["wins"] = int(states[winner]["wins"]) + 1
            states[loser]["losses"] = int(states[loser]["losses"]) + 1

            played_pairs.add(played_key(idea_a, idea_b))
            round_entry["matches"].append(match)

        if round_number in field_cuts:
            active_ids, eliminated = apply_field_cut(
                round_number=round_number,
                cut_size=field_cuts[round_number],
                active_ids=active_ids,
                states=states,
                tie_break=tie_break,
            )
            round_entry["eliminations"] = eliminated
            round_entry["field_size_after_cut"] = len(active_ids)

        rounds_output.append(round_entry)

    final_order = rank_ideas(list(states.keys()), states, tie_break)
    final_standings: list[dict[str, object]] = []
    for idea_id in final_order:
        state = states[idea_id]
        final_standings.append(
            {
                "id": idea_id,
                "wins": int(state["wins"]),
                "losses": int(state["losses"]),
                "byes": int(state["byes"]),
                "eliminated_after_round": state["eliminated_after_round"],
            }
        )

    metadata_field_cuts = {f"after_round_{k}": v for k, v in field_cuts.items()}
    payload: dict[str, object] = {
        "metadata": {
            "total_ideas": len(ideas),
            "rounds": rounds,
            "seed": seed,
            "judge_pool": judge_pool,
            "field_cuts": metadata_field_cuts,
        },
        "rounds": rounds_output,
        "final_standings": final_standings,
    }
    return payload


def summarize_tournament(payload: dict[str, object]) -> str:
    """Create human-readable tournament summary."""
    rounds_data = payload.get("rounds", [])
    if not isinstance(rounds_data, list):
        return "No round data available."

    lines: list[str] = []
    lines.append("Swiss Tournament Summary")
    lines.append("=" * 24)

    total_matches = 0
    total_judge_calls = 0
    total_cost = 0.0

    for entry in rounds_data:
        if not isinstance(entry, dict):
            continue
        round_number = int(entry.get("round", 0))
        field_size = int(entry.get("field_size", 0))
        field_after_cut = int(entry.get("field_size_after_cut", field_size))
        matches = entry.get("matches", [])
        byes = entry.get("byes", [])
        tier = str(entry.get("model_tier", "mixed"))

        if not isinstance(matches, list):
            matches = []
        if not isinstance(byes, list):
            byes = []

        round_judge_calls = 0
        for match in matches:
            if not isinstance(match, dict):
                continue
            judges = match.get("judges", [])
            if isinstance(judges, list):
                round_judge_calls += len(judges)

        cost_per_call = COST_PER_TIER.get(tier, COST_PER_TIER["mixed"])
        round_cost = round_judge_calls * cost_per_call

        total_matches += len(matches)
        total_judge_calls += round_judge_calls
        total_cost += round_cost

        lines.append(
            f"Round {round_number}: field={field_size}->{field_after_cut}, matches={len(matches)}, "
            f"byes={len(byes)}, judge_calls={round_judge_calls}, tier={tier}, "
            f"est_cost=${round_cost:.2f}"
        )

    lines.append("-" * 24)
    lines.append(
        f"Totals: matches={total_matches}, judge_calls={total_judge_calls}, "
        f"estimated_cost=${total_cost:.2f}"
    )

    if total_matches > 0:
        avg_calls = total_judge_calls / max(1, total_matches)
        lines.append(f"Average judges per match: {avg_calls:.2f}")

    metadata = payload.get("metadata", {})
    if isinstance(metadata, dict):
        total_ideas = metadata.get("total_ideas")
        rounds = metadata.get("rounds")
        lines.append(f"Configured ideas={total_ideas}, rounds={rounds}")

    return "\n".join(lines)


def emit_text(text: str, output_path: str) -> None:
    """Write plain text to stdout or file."""
    if output_path == "-":
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
        return

    path = Path(output_path)
    path.write_text(text + ("" if text.endswith("\n") else "\n"), encoding="utf-8")


def emit_json(payload: dict[str, object], output_path: str, pretty: bool) -> None:
    """Write JSON payload to stdout or file."""
    if pretty:
        text = json.dumps(payload, indent=2, ensure_ascii=False)
    else:
        text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    emit_text(text, output_path)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    args = parse_args(argv)

    ideas_payload = load_json_file(Path(args.ideas))
    schedule_payload = load_json_file(Path(args.schedule))

    ideas = validate_ideas(ideas_payload)
    field_cuts = parse_field_cuts(args.field_cuts)
    schedule = parse_schedule(schedule_payload)
    judge_pool = parse_judge_pool(args.judge_pool)

    validate_configuration(
        ideas=ideas,
        rounds=args.rounds,
        field_cuts=field_cuts,
        schedule=schedule,
        judge_pool=judge_pool,
    )

    if args.validate:
        validation_payload = {
            "valid": True,
            "metadata": {
                "total_ideas": len(ideas),
                "rounds": args.rounds,
                "judge_pool_size": len(judge_pool),
                "field_cuts": {f"after_round_{k}": v for k, v in field_cuts.items()},
            },
        }
        if args.summary:
            summary = (
                "Validation successful\n"
                f"ideas={len(ideas)} rounds={args.rounds} "
                f"judge_pool={len(judge_pool)} field_cuts={len(field_cuts)}"
            )
            emit_text(summary, args.output)
        else:
            emit_json(validation_payload, args.output, args.pretty)
        return 0

    payload = run_tournament(
        ideas=ideas,
        rounds=args.rounds,
        field_cuts=field_cuts,
        schedule=schedule,
        judge_pool=judge_pool,
        seed=args.seed,
    )

    if args.summary:
        emit_text(summarize_tournament(payload), args.output)
    else:
        emit_json(payload, args.output, args.pretty)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        raise SystemExit(2)
