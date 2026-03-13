---
name: convolutional-debate-agent
description: >
  Multi-model reasoning protocol for Claude Code that runs five independent solver drafts
  (across different LLM providers), four adversarial debate reviews, and a reliability-weighted
  aggregation step to select or synthesize the final answer. Invoked via /debate slash command.
platform: claude-code
---

# Convolutional Debate Agent for Claude Code

Reduces single-path reasoning errors by forcing independent candidate generation,
adversarial pressure testing, and deterministic selection. Supports multi-model
execution across Claude, ChatGPT, Gemini, Kimi, and any OpenAI-compatible API.

## When to Use

- Architecture decisions with competing tradeoffs
- Strategic planning under uncertainty
- Complex debugging with multiple hypotheses
- Open-ended analysis where the "right" answer isn't obvious
- Any high-stakes decision where being wrong has meaningful downside

## When NOT to Use

- Simple factual lookups
- Routine code edits
- Tasks with a single obvious correct answer

## Invocation

```
/debate <your question or problem>
```

## Step 0: Model Configuration Prompt

**Before executing the debate**, check whether the user's message already specifies model preferences (e.g., "use budget mode", "all opus", "chatgpt-5.4 for solvers"). If it does, apply those preferences directly and skip this prompt. If it does NOT, present the following using AskUserQuestion:

```
Model configuration for /debate:

PROFILE (choose one, or "custom"):
  1. multi_model  — opus + chatgpt-5.4 + gpt-5.2 + kimi-2.5 + gemini-3.1-pro solvers (default)
  2. balanced     — all opus solvers
  3. max_quality  — same as multi_model, best debaters
  4. cost_optimized — all gemini-3-flash
  5. budget       — zero Claude subagents (chatgpt/gpt/kimi/gemini/glm)
  6. custom       — specify models per role below

REASONING EFFORT (optional — press Enter for defaults):
  Claude (opus):    thinking budget → [16k tokens (default) / 32k / 64k / 128k]
  ChatGPT (5.4/5.2): reasoning_effort → [xhigh (default) / high / medium / low]

CONTEXT WINDOW (optional — press Enter for defaults):
  [default / specify tokens / auto (orchestrator decides per task)]

Enter choice (e.g. "1", "budget", "custom: solvers=opus,opus,chatgpt-5.4,kimi-2.5,gemini-3-pro debaters=opus,gpt-5.2,chatgpt-5.4,opus"):
```

**Parsing the response:**
- If user picks a numbered profile or name → set `active_profile` in model-settings.json for this run
- If user specifies reasoning effort → override `reasoning.max_tokens` for opus and/or `reasoning_effort` for ChatGPT models in the runtime config
- If user specifies context window → apply as `context_length` override; if "auto", choose based on question complexity (short questions → default, long multi-file analysis → max available)
- If user says "custom" → parse their per-role assignments and construct an ad-hoc profile
- If user presses Enter or says "defaults" → use `grade_loop` profile (current active)

## Architecture

The protocol uses a hybrid execution model:
- **Claude models** run via Claude Code's native Task tool (no API key needed)
- **External models** run via `scripts/llm_runner.py` calling their APIs

```
User Question
     |
     v
[Model Config Prompt] — ask user for profile/reasoning/context preferences (skip if already specified)
     |
     v
[Load Config] — read model-settings.json, determine routing
     |
     v
[Qualification] — trivial? --> Direct answer
     |
     v
[Gap Detection] — identify & resolve ambiguities via iterative Q&A
     |
     v
[Domain Classification] — match keywords → benchmark-profiles.json
     |
     v
[Frame Objective]
     |
     v
[5 Solver Agents in Parallel] (configurable per-slot)
  A: First-Principles    B: Code-First       C: Failure-Mode
  D: Clarity             E: Research & Evidence
     |
     v
[Formalizer] — extract 1 claim per candidate (fast, ~30s)
     |
     v
[4 Debaters + Aristotle — ALL IN PARALLEL]  ← zero added latency
  ├── Debater 1: Consistency   (model: domain-specific, e.g. opus for coding)
  ├── Debater 2: Counterexample (model: domain-specific, e.g. GPT-5.2EH for coding)
  ├── Debater 3: Constraint    (model: domain-specific, e.g. GPT-5.3 for coding)
  ├── Debater 4: Evidence      (model: domain-specific, e.g. Gemini for coding)
  └── Aristotle: background proofs (~1-5 claims, 2min timeout each)
     |
     v
[Collect Aristotle results] — whatever finished gets used, rest = inconclusive
     |
     v
[RWEA Scoring] (scripts/rwea_score.py --domain <detected>)
  score = w_base*base + w_pairwise*pairwise - w_risk*risk
        + w_reliability*model_weight + w_formal*formal_score
     |
     v
[Decision: Winner / Hybrid / Insufficient]
     |
     v
[Final Synthesis]
```

## Model Routing

Configured in `settings/model-settings.json`. Seven profiles:

| Profile           | Solver A        | Solver B          | Solver C        | Solver D  | Solver E      | Debaters (fallback)       | Synthesizer    |
|-------------------|-----------------|-------------------|-----------------|-----------|---------------|---------------------------|----------------|
| multi_model       | opus            | chatgpt-5.4    | gpt-5.2         | kimi-2.5  | gemini-3-pro  | opus (static)             | opus           |
| multi_model_full  | opus            | chatgpt-5.4    | gpt-5.2         | kimi-2.5  | gemini-3-pro  | mixed (static)            | opus           |
| balanced          | opus            | opus              | opus            | opus      | opus          | opus (static)             | opus           |
| cost_optimized    | gemini-3-flash  | gemini-3-flash    | gemini-3-flash  | gemini-3-flash | gemini-3-flash | gemini-3-flash (static)  | opus           |
| max_quality       | opus            | chatgpt-5.4    | gpt-5.2         | kimi-2.5  | gemini-3-pro  | mixed (static)            | opus           |
| **budget**        | chatgpt-5.4   | gpt-5.2           | kimi-2.5        | gemini-3-pro | glm-5      | 2×GPT + Kimi + Gemini    | chatgpt-5.4  |

**Standardized debater assignment:** All debaters use exactly **2 Opus + 2 ChatGPT** models to eliminate intelligence gaps between evaluators. When a domain is detected (Step 1.5), the debater assignment from `benchmark-profiles.json` overrides profile defaults, but all domains now use the standardized 2+2 split:

| Domain   | D1 (Consistency)       | D2 (Counterexample)    | D3 (Constraint)        | D4 (Evidence)    |
|----------|------------------------|------------------------|------------------------|------------------|
| coding   | opus                   | gpt-5.2                | chatgpt-5.4          | opus             |
| math     | opus                   | gpt-5.2                | chatgpt-5.4          | opus             |
| finance  | opus                   | gpt-5.2                | chatgpt-5.4          | opus             |
| legal    | opus                   | gpt-5.2                | chatgpt-5.4          | opus             |
| academic | opus                   | gpt-5.2                | chatgpt-5.4          | opus             |
| strategy | gpt-5.2                | opus                   | chatgpt-5.4          | opus             |
| general  | opus                   | gpt-5.2                | chatgpt-5.4          | opus             |

**Budget mode debater assignment:** When the `budget` profile is active, `budget_debater_models` replaces `debater_models` — zero Claude in any slot:

| Domain   | D1 (Consistency)       | D2 (Counterexample)    | D3 (Constraint)        | D4 (Evidence)    |
|----------|------------------------|------------------------|------------------------|------------------|
| coding   | chatgpt-5.4          | gpt-5.2                | kimi-2.5               | gemini-3-pro     |
| math     | gemini-3-pro           | gpt-5.2                | chatgpt-5.4          | kimi-2.5         |
| finance  | gpt-5.2                | chatgpt-5.4          | kimi-2.5               | gemini-3-pro     |
| legal    | gpt-5.2                | chatgpt-5.4          | kimi-2.5               | gemini-3-pro     |
| academic | gpt-5.2                | chatgpt-5.4          | kimi-2.5               | gemini-3-pro     |
| strategy | gpt-5.2                | chatgpt-5.4          | kimi-2.5               | gemini-3-pro     |
| general  | chatgpt-5.4          | gpt-5.2                | kimi-2.5               | gemini-3-pro     |

### Supported Providers

| Provider   | API Style         | Models Available                          | Env Key           |
|------------|-------------------|-------------------------------------------|--------------------|
| claude-code| Native Task tool  | opus                                      | None needed        |
| codex      | Codex CLI         | chatgpt-5.4, chatgpt-5.2, gpt-5.2 | None (uses `codex login`) |
| google     | Generative AI API | gemini-3-pro                              | GOOGLE_API_KEY     |
| moonshot   | OpenAI-compatible | kimi-2.5                                  | MOONSHOT_API_KEY   |
| openrouter | OpenAI-compatible | all models (fallback route)               | OPENROUTER_API_KEY |
| anthropic  | Messages API      | claude-api                                | ANTHROPIC_API_KEY  |
| aristotle  | aristotlelib SDK  | aristotle (Lean 4 theorem prover)         | ARISTOTLE_API_KEY  |

## Setup for External Models

### OpenAI (ChatGPT) — OAuth Login (Recommended)

Authenticate with your ChatGPT account directly, just like Codex CLI. No manual API key needed:

```bash
python3 ~/.claude/skills/convolutional-debate-agent/scripts/openai_auth.py login
```

This opens your browser, you log in with your ChatGPT account, and the script obtains an API key automatically. The key is stored locally at `api-keys/openai-oauth.json` (permissions 0600, gitignored).

Other auth commands:
```bash
python3 scripts/openai_auth.py status    # Check if logged in
python3 scripts/openai_auth.py refresh   # Refresh tokens (auto-refreshes every 8 days)
python3 scripts/openai_auth.py logout    # Clear stored tokens
python3 scripts/openai_auth.py token     # Print API key to stdout (for scripting)
```

### Other Providers — API Keys

For Google, Moonshot, and Anthropic, use API keys:

1. Copy the template:
   ```
   cp api-keys/provider-keys.env.example api-keys/provider-keys.env
   ```
2. Fill in your API keys for the providers you want to use
3. Set `active_profile` in `settings/model-settings.json` to the desired profile

### Auth Priority (OpenAI)

When resolving the OpenAI API key, the system checks in order:
1. OAuth token store (`api-keys/openai-oauth.json`) — from `openai_auth.py login`
2. Environment variable `OPENAI_API_KEY`
3. Env file `api-keys/provider-keys.env`

The first source that provides a key wins.

## RWEA Scoring

### Domain-Aware Formula

```
score(c) = w_base*base + w_pairwise*pairwise - w_risk*risk + w_reliability*model_weight(c) + w_formal*formal_score(c)
```

- `base(c) = mean(support + evidence)` — range [0, 4]
- `risk(c) = mean(major_risks + 2*critical_fail)` — range [0, 4]
- `pairwise(c) = wins(c) / (num_candidates - 1)` — range [0, 1]
- `model_weight(c)` — benchmark reliability for the model that generated candidate c, per domain — range [0, 1]
- `formal_score(c)` — Aristotle verification: (proved - disproved) / total_claims — range [-1, 1]

All five weights (w_base, w_pairwise, w_risk, w_reliability, w_formal) are **domain-specific** — they shift based on the classified domain to emphasize what matters most (e.g., math raises w_base, w_reliability, and w_formal; strategy raises w_pairwise and w_risk).

Benchmark profiles and domain-specific weights are in `settings/benchmark-profiles.json` (source: Vals.ai, Feb 2026).

### Elimination & Decision Rules

- **Elimination**: candidate eliminated if 2+ debaters flag `critical_fail = 1`
- **Winner**: highest score among non-eliminated candidates
- **Hybrid**: top-two gap < 0.40 triggers synthesis from both
- **Insufficient**: top score < 1.20 or all eliminated triggers follow-up questions

### Refreshing Benchmark Weights

The model weights in `settings/benchmark-profiles.json` are derived from [Vals.ai](https://vals.ai) benchmarks (scraped Feb 2026). To refresh when models update:

1. Fetch fresh benchmarks via `/llm`:
   ```bash
   python3 ~/.claude/skills/llm/scripts/fetch_benchmarks.py --list --top 20
   ```
2. Compare key metrics (GPQA, Arena Elo, SWE-bench, AIME, MMLU Pro) against the weights in `benchmark-profiles.json`
3. Update `models.<model_name>.weight` and `benchmarks` fields for any models with significant changes
4. Update `budget_debater_models` D1 assignments if the strongest non-Claude model changed for a domain

The `/llm` skill's `benchmarks/rankings.csv` aggregates data from Chatbot Arena, Epoch AI, OpenRouter, and Artificial Analysis with BetterBench quality tiers.

## Output Persistence

Every debate run saves all raw outputs to a timestamped scratchpad directory:
```
~/.claude/debates/<YYYY-MM-DD_HHMMSS>/
  solver_A_opus_output.txt       # Raw solver A response
  solver_B_codex_output.txt      # Raw solver B response
  solver_C_gpt52_output.txt      # Raw solver C response
  solver_D_kimi_output.txt       # Raw solver D response
  solver_E_gemini_output.txt     # Raw solver E response
  debater_1_output.txt           # Raw debater 1 response (with justifications)
  debater_2_output.txt           # Raw debater 2 response
  debater_3_output.txt           # Raw debater 3 response
  debater_4_output.txt           # Raw debater 4 response (with pairwise reasoning)
  rwea_payload.json              # RWEA scoring input
  rwea_result.txt                # RWEA scoring output
```

This ensures debate evidence survives context compaction and can be reviewed across sessions. When the grade-loop skill invokes `/debate`, it uses `report/grade-loop-state/scratchpad/` as the scratchpad directory instead, with iteration-numbered filenames (e.g., `solver_A_opus_output_iter19.txt`).

## File Structure

```
~/.claude/commands/debate.md              # Slash command (orchestration)
~/.claude/debates/                         # Timestamped debate output archives
~/.claude/skills/convolutional-debate-agent/
  SKILL.md                                 # This file
  errors.md                                # Persistent error log with solutions
  scripts/
    rwea_score.py                          # Deterministic RWEA scorer
    llm_runner.py                          # External LLM API caller
    openai_auth.py                         # ChatGPT OAuth device flow login
  settings/
    model-settings.json                    # Provider registry + profiles + formal verification config
    benchmark-profiles.json                # Domain-specific model weights + RWEA overrides (Vals.ai)
  api-keys/
    provider-keys.env.example              # API key template
    provider-keys.env                      # Your actual keys (gitignored)
    openai-oauth.json                      # ChatGPT OAuth tokens (gitignored)
    .gitignore
  references/
    roles.md                               # Solver & debater role definitions
    scoring.md                             # RWEA formula & rules
    rwea-input-template.json               # Example scoring payload

~/.claude/skills/aristotle-prover/         # Formal theorem prover (used in Step 3.5)
  SKILL.md                                 # Aristotle skill docs
  scripts/
    aristotle_submit.py                    # API submission + polling script
  settings/
    prompt-templates.json                  # Domain-specific formalization templates
  references/
    prompt-guide.md                        # How to write effective Aristotle prompts
```

## Changelog

### v6 — 2026-03-05 (Output Persistence)

**1. Solver output persistence** — After all 5 solvers complete, raw responses are saved to `<scratchpad>/solver_<X>_<model>_output.txt`. Previously only prompts were saved; actual model outputs were lost on context compaction.

**2. Debater output persistence** — After all 4 debaters complete, raw responses (including justifications and pairwise reasoning) are saved to `<scratchpad>/debater_<N>_output.txt`.

**3. RWEA result persistence** — RWEA scorer output (scores, eliminations, decisions) saved to `<scratchpad>/rwea_result.txt`. Previously only the input payload was saved.

**4. Timestamped scratchpad** — Standalone `/debate` runs create `~/.claude/debates/<YYYY-MM-DD_HHMMSS>/` for all artifacts. Grade-loop overrides to `report/grade-loop-state/scratchpad/` with iteration-numbered filenames.

**Trigger:** 19 grade-loop iterations lost detailed solver analyses and debater justifications to context compaction. The summary in score-history.json preserved numbers but not the reasoning behind them, making it impossible to trace why specific feedback was given.

### v5 — 2026-02-25 (CLI Timeout Cascade Fix + Budget Mode)

**1. CLI timeout increase** — `DEFAULT_CLI_TIMEOUT` raised from 300s to 600s in both `llm_runner.py` and `llm_route.py`. Codex, Kimi, and Claude CLI calls all default to 600s. A `--timeout` CLI flag is now available on both scripts for explicit control.

**2. Auto CLI→API fallback** — When a CLI call fails (timeout, crash, non-zero exit, empty response), the runner automatically retries via the model's API fallback route (e.g., OpenRouter). Skips fallback for "not found on PATH" (setup issue, not transient). Prints `WARNING` to stderr so the orchestrator can detect and report it. New helpers: `_find_fallback_route()` and `_call_api_route()` in both Python files.

**3. Protocol batch isolation** — `debate.md` Steps 3 and 4 now mandate each external-model Bash call as a **separate Bash invocation** (separate tool call). This prevents Claude Code's parallel batch cancellation from cascading one CLI timeout to all sibling calls.

**4. Fallback detection in scoring** — Step 5 now checks stderr for fallback warnings and notes any CLI→API fallbacks in the debate summary, so the user knows which models ran via non-primary routes.

**5. Budget mode** — New `budget` profile: zero Claude subagents. All solver/debater/synthesizer/formalizer calls route via Codex CLI, Kimi CLI, Google API, or OpenRouter. The only Claude instance is the main orchestrator. Domain-specific `budget_debater_models` added to all 7 domains in benchmark-profiles.json. Formalizer falls back to `budget_formalizer_model` (chatgpt-5.4). Debate summary shows "Mode: budget (no Claude subagents)" when active.

**Trigger:** Codex CLI timed out at 300s during a 30k-token debate run, cascading to cancel all sibling Bash calls. See `errors.md` for full incident details.

### v4 — 2026-02-08 (Post-Evaluation Overhaul)

**1. Error logging** — Created `errors.md` persistent error log documenting all known failures and solutions. Includes Codex CLI model availability matrix, Gemini temperature quirks, Kimi model ID format, and JSON parsing edge cases.

**2. ChatGPT model fix** — `gpt-5.2-extra-high` is NOT available via Codex CLI with a ChatGPT consumer account. Replaced with `gpt-5.2-codex` (verified working). Verified model availability: `chatgpt-5.4`, `gpt-5.2-codex`, `gpt-5.2`, `gpt-5`, `gpt-5.1`, `gpt-5.1-codex`, `gpt-5.1-codex-max` all work. Models like `o3`, `o4-mini`, `gpt-4.1` do NOT work with ChatGPT accounts.

**3. Gap-detection questioning** — Added Step 1.1 to `debate.md`. Before proceeding to domain classification, the agent now exhaustively analyzes the prompt for missing constraints, unstated assumptions, ambiguous terms, unclear scope, missing success criteria, and hidden dependencies. Uses iterative AskUserQuestion calls until all gaps are resolved. No fatigue — keeps asking until confident.

**4. Standardized debater models** — All debater assignments across all 7 domains now use exactly **2 Opus + 2 ChatGPT** (chatgpt-5.4 and gpt-5.2-codex via alias). This eliminates intelligence gaps between debaters that occurred when mixing Gemini and Kimi (lower benchmark models) into evaluator roles. Gemini and Kimi remain as solvers where their diverse architectures add value.

**5. Gemini prompting optimization** — Applied Google's Gemini 3 prompting best practices:
   - Forced `temperature=1.0` for all Google API calls in `llm_runner.py` (Gemini degrades below 1.0)
   - Updated all Gemini guidance strings to use XML-style section tags (`<analysis>`, `<evidence>`, etc.)
   - Added explicit "provide DETAILED reasoning" instruction (Gemini defaults to concise)
   - Added "Based on the entire problem context above..." anchoring for multi-document synthesis
   - Source: [Google Gemini 3 Prompting Guide](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/start/gemini-3-prompting-guide)

**6. Complete output display** — Added mandatory Step 7 to `debate.md`. The complete debate output (answer, reasoning, scores, error margins, raw score table) MUST be displayed to the user as a single consolidated block before the skill exits. No more truncated or missing final outputs.

**7. System evaluation** — This changelog documents all changes. Key remaining limitations:
   - `gpt-5.2` alias now maps to `gpt-5.2-codex`, which may have slightly different behavior
   - Aristotle formal verification still subject to 2-minute timeouts per claim
   - Gemini prompting improvements are heuristic — need live A/B testing to confirm impact
   - Gap detection adds latency to the start of each debate (but prevents wasted compute on ambiguous prompts)
