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

## Architecture

The protocol uses a hybrid execution model:
- **Claude models** run via Claude Code's native Task tool (no API key needed)
- **External models** run via `scripts/llm_runner.py` calling their APIs

```
User Question
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

Configured in `settings/model-settings.json`. Five profiles:

| Profile           | Solver A | Solver B          | Solver C               | Solver D  | Solver E      | Debaters (fallback) | Synthesizer |
|-------------------|----------|-------------------|------------------------|-----------|---------------|---------------------|-------------|
| multi_model       | opus     | gpt-5.3-codex codex | gpt-5.2 | kimi-2.5  | gemini-3-pro  | sonnet (static)     | opus        |
| multi_model_full  | opus     | gpt-5.3-codex codex | gpt-5.2 | kimi-2.5  | gemini-3-pro  | mixed (static)      | opus        |
| balanced          | opus     | opus              | opus                   | opus      | opus          | sonnet (static)     | opus        |
| cost_optimized    | sonnet   | sonnet            | sonnet                 | sonnet    | sonnet        | haiku (static)      | sonnet      |
| max_quality       | opus     | gpt-5.3-codex codex | gpt-5.2 | kimi-2.5  | gemini-3-pro  | mixed (static)      | opus        |

**Standardized debater assignment:** All debaters use exactly **2 Opus + 2 ChatGPT** models to eliminate intelligence gaps between evaluators. When a domain is detected (Step 1.5), the debater assignment from `benchmark-profiles.json` overrides profile defaults, but all domains now use the standardized 2+2 split:

| Domain   | D1 (Consistency)       | D2 (Counterexample)    | D3 (Constraint)        | D4 (Evidence)    |
|----------|------------------------|------------------------|------------------------|------------------|
| coding   | opus                   | gpt-5.2 | gpt-5.3-codex            | opus             |
| math     | opus                   | gpt-5.2 | gpt-5.3-codex            | opus             |
| finance  | opus                   | gpt-5.2 | gpt-5.3-codex            | opus             |
| legal    | opus                   | gpt-5.2 | gpt-5.3-codex            | opus             |
| academic | opus                   | gpt-5.2 | gpt-5.3-codex            | opus             |
| strategy | gpt-5.2 | opus                   | gpt-5.3-codex            | opus             |
| general  | opus                   | gpt-5.2 | gpt-5.3-codex            | opus             |

### Supported Providers

| Provider   | API Style         | Models Available                          | Env Key           |
|------------|-------------------|-------------------------------------------|--------------------|
| claude-code| Native Task tool  | opus, sonnet, haiku                       | None needed        |
| codex      | Codex CLI         | gpt-5.3-codex, chatgpt-5.2, gpt-5.2 | None (uses `codex login`) |
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

## File Structure

```
~/.claude/commands/debate.md              # Slash command (orchestration)
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

### v4 — 2026-02-08 (Post-Evaluation Overhaul)

**1. Error logging** — Created `errors.md` persistent error log documenting all known failures and solutions. Includes Codex CLI model availability matrix, Gemini temperature quirks, Kimi model ID format, and JSON parsing edge cases.

**2. ChatGPT model fix** — `gpt-5.2-extra-high` is NOT available via Codex CLI with a ChatGPT consumer account. Replaced with `gpt-5.2-codex` (verified working). Verified model availability: `gpt-5.3-codex`, `gpt-5.2-codex`, `gpt-5.2`, `gpt-5`, `gpt-5.1`, `gpt-5.1-codex`, `gpt-5.1-codex-max` all work. Models like `o3`, `o4-mini`, `gpt-4.1` do NOT work with ChatGPT accounts.

**3. Gap-detection questioning** — Added Step 1.1 to `debate.md`. Before proceeding to domain classification, the agent now exhaustively analyzes the prompt for missing constraints, unstated assumptions, ambiguous terms, unclear scope, missing success criteria, and hidden dependencies. Uses iterative AskUserQuestion calls until all gaps are resolved. No fatigue — keeps asking until confident.

**4. Standardized debater models** — All debater assignments across all 7 domains now use exactly **2 Opus + 2 ChatGPT** (gpt-5.3-codex and gpt-5.2-codex via alias). This eliminates intelligence gaps between debaters that occurred when mixing Gemini and Kimi (lower benchmark models) into evaluator roles. Gemini and Kimi remain as solvers where their diverse architectures add value.

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
