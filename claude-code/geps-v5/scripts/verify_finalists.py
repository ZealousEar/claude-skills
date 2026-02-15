from __future__ import annotations

import argparse
import itertools
import json
import os
import pathlib
import random
import subprocess
import sys
import tempfile

DEFAULT_LLM_RUNNER = pathlib.Path(
    "~/.claude/skills/convolutional-debate-agent/scripts/llm_runner.py"
).expanduser()
DEFAULT_FATAL_FLAW_PROMPT = pathlib.Path(
    "~/.claude/skills/geps-v5/prompts/debater_fatal_flaw_auditor.md"
).expanduser()
DEFAULT_NOVELTY_PROMPT = pathlib.Path(
    "~/.claude/skills/geps-v5/prompts/debater_novelty_judge.md"
).expanduser()
IDENTIFICATION_KEYWORDS = [
    "IV",
    "instrumental variable",
    "diff-in-diff",
    "structural model",
    "calibration",
    "GMM",
    "maximum likelihood",
    "Bayesian estimation",
    "natural experiment",
    "quasi-experimental",
    "event study",
    "propensity score",
]


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Verify finalist ideas via pairwise fatal-flaw auditing, novelty audit, "
            "evidence scoring, and deterministic recommendation."
        )
    )
    parser.add_argument("--ideas", required=True, help="Path to top-K normalized ideas JSON")
    parser.add_argument(
        "--retrieved",
        required=True,
        help="Path to retrieved paper summaries JSON (novelty context)",
    )
    parser.add_argument(
        "--bracket",
        choices=("round_robin", "star"),
        default=None,
        help="Bracket type (default: round_robin for K<=7, else star)",
    )
    parser.add_argument(
        "--verifier-models",
        default="opus,gpt-5.3-codex",
        help="Comma-separated verifier models",
    )
    parser.add_argument(
        "--llm-runner-path",
        default=str(DEFAULT_LLM_RUNNER),
        help="Path to llm_runner.py",
    )
    parser.add_argument(
        "--fatal-flaw-prompt",
        default=str(DEFAULT_FATAL_FLAW_PROMPT),
        help="Path to fatal flaw prompt template",
    )
    parser.add_argument(
        "--novelty-prompt",
        default=str(DEFAULT_NOVELTY_PROMPT),
        help="Path to novelty judge prompt template",
    )
    parser.add_argument(
        "--use-aristotle",
        action="store_true",
        help="Enable Aristotle theorem prover (future feature)",
    )
    parser.add_argument("--output", default="-", help="Output path (default: stdout)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument("--summary", action="store_true", help="Emit human-readable summary")
    return parser.parse_args()


def read_json(path: pathlib.Path) -> object:
    """Load JSON payload from a file."""
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_ideas(raw: object) -> list[dict[str, object]]:
    """Validate and normalize input finalist ideas."""
    if not isinstance(raw, list):
        raise ValueError("--ideas must contain a JSON array")
    ideas: list[dict[str, object]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"ideas[{index}] must be an object")
        idea_id = item.get("id")
        text = item.get("text")
        if not isinstance(idea_id, str) or not idea_id.strip():
            raise ValueError(f"ideas[{index}].id must be a non-empty string")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"ideas[{index}].text must be a non-empty string")
        normalized: dict[str, object] = {
            "id": idea_id.strip(),
            "text": text.strip(),
            "identification": item.get("identification") if isinstance(item.get("identification"), list) else [],
            "data": item.get("data") if isinstance(item.get("data"), dict) else {},
        }
        ideas.append(normalized)
    return ideas


def parse_models(raw: str) -> list[str]:
    """Parse comma-separated model names into a deterministic list."""
    models = [m.strip() for m in raw.split(",") if m.strip()]
    if not models:
        raise ValueError("--verifier-models must include at least one model")
    return models


def infer_provider(model: str) -> str:
    """Infer coarse provider label from a model name."""
    lower = model.lower()
    if "gpt" in lower or "o1" in lower or "o3" in lower or "o4" in lower:
        return "openai"
    if "opus" in lower or "claude" in lower or "anthropic" in lower:
        return "anthropic"
    for sep in ("/", ":", "-"):
        if sep in model:
            prefix = model.split(sep, 1)[0].strip().lower()
            if prefix:
                return prefix
    return lower


def choose_verifiers(models: list[str], pair_index: int) -> tuple[tuple[str, str], str | None]:
    """Select two verifier models, preferring different providers."""
    if len(models) == 1:
        return (models[0], models[0]), "Only one verifier model provided; duplicated verifier used"

    valid_pairs: list[tuple[str, str]] = []
    for left, right in itertools.combinations(models, 2):
        if infer_provider(left) != infer_provider(right):
            valid_pairs.append((left, right))

    if valid_pairs:
        return valid_pairs[pair_index % len(valid_pairs)], None

    return (
        (models[0], models[1]),
        "No cross-provider verifier pair available; using first two models",
    )


def determine_bracket(k: int, override: str | None) -> str:
    """Resolve bracket policy."""
    if override:
        return override
    return "round_robin" if k <= 7 else "star"


def generate_round_robin_pairs(k: int) -> list[tuple[int, int]]:
    """Generate all unordered pairings for finalists."""
    return [(i, j) for i, j in itertools.combinations(range(k), 2)]


def generate_star_pairs(k: int, rng: random.Random) -> list[tuple[int, int]]:
    """Generate star bracket pairs: each idea vs rank-1 and two random peers."""
    if k < 2:
        return []

    pairs: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()

    for i in range(k):
        if i == 0:
            opponents = [idx for idx in range(1, k)]
            picks = rng.sample(opponents, min(3, len(opponents)))
        else:
            picks = [0]
            others = [idx for idx in range(k) if idx not in (i, 0)]
            picks.extend(rng.sample(others, min(2, len(others))))

        for j in picks:
            if i == j:
                continue
            pair = (i, j) if i < j else (j, i)
            if pair not in seen:
                seen.add(pair)
                pairs.append(pair)

    return pairs


def render_prompt(template: str, replacements: dict[str, str], fallback: str) -> str:
    """Render prompt with flexible placeholder support."""
    out = template
    replaced_any = False
    for key, value in replacements.items():
        for placeholder in (f"{{{{{key}}}}}", f"{{{key}}}", f"<<{key}>>"):
            if placeholder in out:
                out = out.replace(placeholder, value)
                replaced_any = True
    if not replaced_any:
        out = f"{out.rstrip()}\n\n{fallback.strip()}\n"
    return out


def run_llm(llm_runner_path: pathlib.Path, model: str, prompt: str, max_tokens: int = 1500) -> tuple[bool, str, str]:
    """Invoke llm_runner.py and return (success, stdout, error_message)."""
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".md", delete=False) as handle:
            handle.write(prompt)
            temp_path = handle.name

        cmd = [
            "python3",
            str(llm_runner_path),
            "--model",
            model,
            "--prompt-file",
            temp_path,
            "--max-tokens",
            str(max_tokens),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        if proc.returncode != 0:
            msg = stderr or stdout or f"llm_runner exited with code {proc.returncode}"
            return False, stdout, msg
        if not stdout:
            return False, stdout, "llm_runner produced empty stdout"
        return True, stdout, ""
    except OSError as exc:
        return False, "", f"Failed to invoke llm_runner: {exc}"
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def normalize_gate(value: str) -> str:
    """Normalize novelty gate labels into PASS/FAIL/UNKNOWN."""
    upper = value.upper()
    pass_pos = upper.find("PASS")
    fail_pos = upper.find("FAIL")
    if pass_pos == -1 and fail_pos == -1:
        return "UNKNOWN"
    if pass_pos != -1 and fail_pos == -1:
        return "PASS"
    if fail_pos != -1 and pass_pos == -1:
        return "FAIL"
    return "PASS" if pass_pos < fail_pos else "FAIL"


def tokenize_words(text: str) -> list[str]:
    """Tokenize alphanumeric words for lightweight parsing."""
    tokens: list[str] = []
    buf: list[str] = []
    for ch in text:
        if ch.isalnum() or ch == "_":
            buf.append(ch)
        else:
            if buf:
                tokens.append("".join(buf))
                buf = []
    if buf:
        tokens.append("".join(buf))
    return tokens


def parse_sections(text: str, keys: list[str]) -> dict[str, str]:
    """Parse a free-form LLM response into keyed sections."""
    keyset = {key.upper(): key for key in keys}
    out: dict[str, list[str]] = {key: [] for key in keys}
    current: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        stripped = line.strip("*`#>- ")
        upper = stripped.upper()
        matched = None
        remainder = ""

        for upper_key, original_key in keyset.items():
            if upper == upper_key:
                matched = original_key
                remainder = ""
                break
            if upper.startswith(upper_key):
                tail = stripped[len(original_key) :].lstrip()
                if not tail or tail[0] in (":", "=", "-"):
                    matched = original_key
                    remainder = tail[1:].lstrip() if tail and tail[0] in (":", "=", "-") else ""
                    break

        if matched is not None:
            current = matched
            if remainder:
                out[current].append(remainder)
            continue

        if current is not None and line:
            out[current].append(line)

    return {key: "\n".join(lines).strip() for key, lines in out.items()}


def parse_commit_label(commit_text: str) -> str | None:
    """Parse COMMIT section and return "A"/"B" when possible."""
    if not commit_text.strip():
        return None
    tokens = [token.upper() for token in tokenize_words(commit_text)]
    has_a = "A" in tokens or "IDEA_A" in tokens
    has_b = "B" in tokens or "IDEA_B" in tokens
    if has_a and not has_b:
        return "A"
    if has_b and not has_a:
        return "B"

    upper = commit_text.upper().strip()
    if upper.startswith("A"):
        return "A"
    if upper.startswith("B"):
        return "B"
    return None


def count_list_items(raw: str) -> int:
    """Approximate the number of listed flaws in a section."""
    if not raw.strip():
        return 0

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    cleaned: list[str] = []
    for line in lines:
        current = line
        for prefix in ("- ", "* ", "+ ", "• "):
            if current.startswith(prefix):
                current = current[len(prefix) :].strip()
        if len(current) >= 2 and current[0].isdigit() and current[1] in (".", ")", ":", "-"):
            current = current[2:].strip()
        if current:
            cleaned.append(current)

    if len(cleaned) <= 1:
        single = cleaned[0] if cleaned else ""
        if ";" in single:
            parts = [p.strip() for p in single.split(";") if p.strip()]
            if len(parts) > 1:
                return len(parts)
        count = 0
        for marker in ("1.", "2.", "3.", "1)", "2)", "3)"):
            if marker in single:
                count += 1
        if count > 1:
            return count

    return len(cleaned)


def safe_flaw_key(idea_id: str) -> str:
    """Create stable JSON key for per-idea flaw counts."""
    chars = []
    for ch in idea_id.lower():
        if ch.isalnum():
            chars.append(ch)
        else:
            chars.append("_")
    return "".join(chars).strip("_") + "_flaws"


def parse_fatal_audit(raw: str, presented: dict[str, str]) -> dict[str, object]:
    """Parse fatal flaw audit response and map back to true idea IDs."""
    keys = ["COMMIT", "A_FATAL", "B_FATAL", "A_REPAIRS", "B_REPAIRS", "WHY_WINNER"]
    sections = parse_sections(raw, keys)

    commit_label = parse_commit_label(sections.get("COMMIT", ""))
    winner = presented.get(commit_label, "UNKNOWN") if commit_label else "UNKNOWN"

    a_flaws = count_list_items(sections.get("A_FATAL", ""))
    b_flaws = count_list_items(sections.get("B_FATAL", ""))

    flaws_by_id = {
        presented["A"]: a_flaws,
        presented["B"]: b_flaws,
    }

    return {
        "winner": winner,
        "a_flaws": a_flaws,
        "b_flaws": b_flaws,
        "flaws_by_id": flaws_by_id,
        "sections": sections,
    }


def format_retrieved_context(retrieved: object) -> str:
    """Serialize retrieval payload for novelty prompt context."""
    return json.dumps(retrieved, ensure_ascii=False, indent=2)


def build_novelty_result(idea_id: str, raw: str) -> dict[str, object]:
    """Parse novelty audit response into normalized structure."""
    keys = ["NOVELTY_CLASS", "EVIDENCE", "NOVELTY_GATE"]
    sections = parse_sections(raw, keys)
    novelty_class = sections.get("NOVELTY_CLASS", "").strip() or "UNKNOWN"
    evidence = sections.get("EVIDENCE", "").strip()
    gate = normalize_gate(sections.get("NOVELTY_GATE", ""))
    if gate == "UNKNOWN":
        gate = normalize_gate(raw)

    return {
        "id": idea_id,
        "novelty_class": novelty_class,
        "evidence": evidence,
        "novelty_gate": gate,
    }


def compute_identification_score(idea_text: str) -> float:
    """Compute binary identification score from keyword hits in idea text."""
    lower = idea_text.lower()
    hits = 0
    for keyword in IDENTIFICATION_KEYWORDS:
        if keyword.lower() in lower:
            hits += 1
    return 1.0 if hits >= 2 else 0.0


def compute_data_score(idea: dict[str, object]) -> float:
    """Compute data score from data.access tiers."""
    data = idea.get("data")
    if not isinstance(data, dict):
        return 0.0
    access = str(data.get("access", "unknown")).strip().lower()
    if access in ("available", "free"):
        return 1.0
    if access in ("apply", "low"):
        return 0.5
    return 0.0


def compute_evidence_scores(
    ideas: list[dict[str, object]], novelty_results: list[dict[str, object]]
) -> tuple[list[dict[str, object]], dict[str, float]]:
    """Compute e_novelty, e_identification, e_data, and aggregate E per idea."""
    novelty_by_id = {str(item["id"]): str(item.get("novelty_gate", "UNKNOWN")) for item in novelty_results}

    evidence: list[dict[str, object]] = []
    score_map: dict[str, float] = {}
    for idea in ideas:
        idea_id = str(idea["id"])
        novelty_gate = novelty_by_id.get(idea_id, "UNKNOWN")
        if novelty_gate == "PASS":
            e_novelty = 1.0
        elif novelty_gate == "FAIL":
            e_novelty = 0.0
        else:
            e_novelty = 0.5

        e_identification = compute_identification_score(str(idea["text"]))
        e_data = compute_data_score(idea)
        aggregate = (e_novelty + e_identification + e_data) / 3.0
        aggregate = round(aggregate, 4)

        row = {
            "id": idea_id,
            "e_novelty": e_novelty,
            "e_identification": e_identification,
            "e_data": e_data,
            "E": aggregate,
        }
        evidence.append(row)
        score_map[idea_id] = aggregate

    return evidence, score_map


def build_summary_rows(
    ideas: list[dict[str, object]],
    fatal_flaws: dict[str, int],
    wins: dict[str, int],
    losses: dict[str, int],
    novelty_results: list[dict[str, object]],
    e_scores: dict[str, float],
) -> list[dict[str, object]]:
    """Build sortable finalist summary rows."""
    novelty_gate_by_id = {str(item["id"]): str(item.get("novelty_gate", "UNKNOWN")) for item in novelty_results}

    rows: list[dict[str, object]] = []
    for idea in ideas:
        idea_id = str(idea["id"])
        w = wins.get(idea_id, 0)
        l = losses.get(idea_id, 0)
        played = w + l
        win_rate = (w / played) if played > 0 else 0.0
        rows.append(
            {
                "id": idea_id,
                "fatal_flaw_count": fatal_flaws.get(idea_id, 0),
                "pairwise_wins": w,
                "pairwise_losses": l,
                "win_rate": win_rate,
                "novelty_gate": novelty_gate_by_id.get(idea_id, "UNKNOWN"),
                "E": e_scores.get(idea_id, 0.0),
            }
        )

    rows.sort(
        key=lambda row: (
            int(row["fatal_flaw_count"]),
            -float(row["win_rate"]),
            0 if row["novelty_gate"] == "PASS" else 1,
            -float(row["E"]),
            str(row["id"]),
        )
    )
    return rows


def build_recommendation(finalist_rows: list[dict[str, object]], ideas: list[dict[str, object]]) -> dict[str, object]:
    """Produce deterministic dissertation recommendation and rationale."""
    if not finalist_rows:
        return {
            "dissertation_bet": None,
            "reason": "No finalist ideas available after verification",
            "runner_up": None,
            "caution": "Insufficient evidence for recommendation",
        }

    by_id = {str(item["id"]): item for item in ideas}
    eligible = [
        row
        for row in finalist_rows
        if int(row["fatal_flaw_count"]) <= 1 and str(row["novelty_gate"]) == "PASS"
    ]
    chosen = eligible[0] if eligible else finalist_rows[0]

    runner_up = finalist_rows[1]["id"] if len(finalist_rows) > 1 else None
    rec_id = str(chosen["id"])
    record = f"{chosen['pairwise_wins']}-{chosen['pairwise_losses']}"
    reason = (
        f"Fewest fatal flaws ({chosen['fatal_flaw_count']}), pairwise record {record}, "
        f"novelty {chosen['novelty_gate']}, E={chosen['E']}"
    )

    caution = "No runner-up available"
    if runner_up:
        caution = f"Consider {runner_up} as backup if {rec_id}'s data access proves difficult"

    rec_idea = by_id.get(rec_id, {})
    data = rec_idea.get("data") if isinstance(rec_idea, dict) else {}
    access = data.get("access") if isinstance(data, dict) else None
    if isinstance(access, str) and access.strip().lower() in ("apply", "low", "unknown"):
        caution = f"Primary pick uses data access='{access.strip()}'; keep {runner_up or 'a backup'} ready"

    return {
        "dissertation_bet": rec_id,
        "reason": reason,
        "runner_up": runner_up,
        "caution": caution,
    }


def render_summary(
    metadata: dict[str, object],
    finalist_rows: list[dict[str, object]],
    recommendation: dict[str, object],
    errors: list[str],
) -> str:
    """Render human-readable summary table and recommendation."""
    lines: list[str] = []
    lines.append("Finalist Verification Summary")
    lines.append(
        f"K={metadata['K']} | bracket={metadata['bracket']} | total_pairs={metadata['total_pairs']} | "
        f"verifiers={','.join(metadata['verifier_models'])}"
    )
    lines.append("")
    lines.append("ID | fatal_flaws | wins | losses | novelty | E")
    lines.append("---|---:|---:|---:|---|---:")
    for row in finalist_rows:
        lines.append(
            f"{row['id']} | {row['fatal_flaw_count']} | {row['pairwise_wins']} | "
            f"{row['pairwise_losses']} | {row['novelty_gate']} | {row['E']}"
        )

    lines.append("")
    lines.append("Recommendation")
    lines.append(f"- dissertation_bet: {recommendation.get('dissertation_bet')}")
    lines.append(f"- runner_up: {recommendation.get('runner_up')}")
    lines.append(f"- reason: {recommendation.get('reason')}")
    lines.append(f"- caution: {recommendation.get('caution')}")

    if errors:
        lines.append("")
        lines.append("Errors")
        for err in errors:
            lines.append(f"- {err}")

    return "\n".join(lines)


def main() -> None:
    """Run finalist verification pipeline."""
    args = parse_args()

    ideas_path = pathlib.Path(args.ideas).expanduser()
    retrieved_path = pathlib.Path(args.retrieved).expanduser()
    llm_runner_path = pathlib.Path(args.llm_runner_path).expanduser()
    fatal_prompt_path = pathlib.Path(args.fatal_flaw_prompt).expanduser()
    novelty_prompt_path = pathlib.Path(args.novelty_prompt).expanduser()

    raw_ideas = read_json(ideas_path)
    ideas = normalize_ideas(raw_ideas)
    retrieved_payload = read_json(retrieved_path)

    fatal_template = fatal_prompt_path.read_text(encoding="utf-8")
    novelty_template = novelty_prompt_path.read_text(encoding="utf-8")

    models = parse_models(args.verifier_models)
    errors: list[str] = []
    if args.use_aristotle:
        errors.append("--use-aristotle requested, but Aristotle integration is not implemented yet")

    rng = random.Random(20260209)
    bracket = determine_bracket(len(ideas), args.bracket)
    if bracket == "round_robin":
        pairs = generate_round_robin_pairs(len(ideas))
    else:
        pairs = generate_star_pairs(len(ideas), rng)

    fatal_counts = {str(idea["id"]): 0 for idea in ideas}
    wins = {str(idea["id"]): 0 for idea in ideas}
    losses = {str(idea["id"]): 0 for idea in ideas}

    pairwise_results: list[dict[str, object]] = []

    for pair_index, (left_index, right_index) in enumerate(pairs):
        left = ideas[left_index]
        right = ideas[right_index]
        left_id = str(left["id"])
        right_id = str(right["id"])

        verifier_pair, pair_warning = choose_verifiers(models, pair_index)
        if pair_warning:
            errors.append(f"Pair {left_id} vs {right_id}: {pair_warning}")

        pair_result: dict[str, object] = {"pair": [left_id, right_id]}
        vote_count = {left_id: 0, right_id: 0}

        for verifier_index, model in enumerate(verifier_pair, start=1):
            flip = rng.random() < 0.5
            if not flip:
                shown_a_id = left_id
                shown_b_id = right_id
                shown_a_text = str(left["text"])
                shown_b_text = str(right["text"])
            else:
                shown_a_id = right_id
                shown_b_id = left_id
                shown_a_text = str(right["text"])
                shown_b_text = str(left["text"])

            prompt = render_prompt(
                fatal_template,
                {
                    "idea_a": shown_a_text,
                    "idea_b": shown_b_text,
                },
                fallback=(
                    "IDEA_A:\n"
                    f"{shown_a_text}\n\n"
                    "IDEA_B:\n"
                    f"{shown_b_text}"
                ),
            )

            ok, stdout, err = run_llm(llm_runner_path, model, prompt, max_tokens=1500)
            left_key = safe_flaw_key(left_id)
            right_key = safe_flaw_key(right_id)
            verifier_key = f"verifier_{verifier_index}"

            if not ok:
                errors.append(f"Fatal flaw audit failed ({left_id} vs {right_id}, {model}): {err}")
                pair_result[verifier_key] = {
                    "model": model,
                    "winner": "UNKNOWN",
                    left_key: 0,
                    right_key: 0,
                    "error": err,
                }
                continue

            parsed = parse_fatal_audit(stdout, {"A": shown_a_id, "B": shown_b_id})
            winner = str(parsed["winner"])
            flaws_by_id = parsed["flaws_by_id"] if isinstance(parsed.get("flaws_by_id"), dict) else {}
            left_flaws = int(flaws_by_id.get(left_id, 0))
            right_flaws = int(flaws_by_id.get(right_id, 0))

            fatal_counts[left_id] += left_flaws
            fatal_counts[right_id] += right_flaws
            if winner in vote_count:
                vote_count[winner] += 1

            pair_result[verifier_key] = {
                "model": model,
                "winner": winner,
                left_key: left_flaws,
                right_key: right_flaws,
            }

        if vote_count[left_id] > vote_count[right_id]:
            wins[left_id] += 1
            losses[right_id] += 1
        elif vote_count[right_id] > vote_count[left_id]:
            wins[right_id] += 1
            losses[left_id] += 1

        pairwise_results.append(pair_result)

    novelty_results: list[dict[str, object]] = []
    novelty_model = models[0]
    retrieved_context = format_retrieved_context(retrieved_payload)

    for idea in ideas:
        idea_id = str(idea["id"])
        idea_text = str(idea["text"])
        prompt = render_prompt(
            novelty_template,
            {
                "idea": idea_text,
                "retrieved_summaries": retrieved_context,
            },
            fallback=(
                "FINALIST_IDEA:\n"
                f"{idea_text}\n\n"
                "RETRIEVED_SUMMARIES:\n"
                f"{retrieved_context}"
            ),
        )

        ok, stdout, err = run_llm(llm_runner_path, novelty_model, prompt, max_tokens=1500)
        if not ok:
            errors.append(f"Novelty audit failed ({idea_id}, {novelty_model}): {err}")
            novelty_results.append(
                {
                    "id": idea_id,
                    "novelty_class": "UNKNOWN",
                    "evidence": "",
                    "novelty_gate": "UNKNOWN",
                }
            )
            continue

        novelty_results.append(build_novelty_result(idea_id, stdout))

    evidence_scores, e_score_map = compute_evidence_scores(ideas, novelty_results)
    finalist_summary = build_summary_rows(
        ideas,
        fatal_counts,
        wins,
        losses,
        novelty_results,
        e_score_map,
    )
    recommendation = build_recommendation(finalist_summary, ideas)

    output_payload: dict[str, object] = {
        "metadata": {
            "K": len(ideas),
            "bracket": bracket,
            "total_pairs": len(pairs),
            "verifier_models": models,
        },
        "pairwise_results": pairwise_results,
        "novelty_results": novelty_results,
        "evidence_scores": evidence_scores,
        "finalist_summary": [
            {
                "id": row["id"],
                "fatal_flaw_count": row["fatal_flaw_count"],
                "pairwise_wins": row["pairwise_wins"],
                "pairwise_losses": row["pairwise_losses"],
                "novelty_gate": row["novelty_gate"],
                "E": row["E"],
            }
            for row in finalist_summary
        ],
        "recommendation": recommendation,
        "errors": errors,
    }

    json_text = json.dumps(
        output_payload,
        ensure_ascii=False,
        indent=2 if args.pretty else None,
    )

    if args.output != "-":
        out_path = pathlib.Path(args.output).expanduser()
        out_path.write_text(json_text + "\n", encoding="utf-8")

    if args.summary:
        summary_text = render_summary(output_payload["metadata"], finalist_summary, recommendation, errors)
        print(summary_text)
        if args.output == "-":
            return

    if args.output == "-":
        print(json_text)


if __name__ == "__main__":
    main()
