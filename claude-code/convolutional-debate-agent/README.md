# convolutional-debate-agent

Reliability-weighted multi-model debate pipeline for high-stakes or ambiguous reasoning tasks.

## Files

- `SKILL.md` — protocol definition for solver generation, debate, and aggregation.
- `scripts/llm_runner.py` — unified model execution with auto CLI→API fallback and per-model prompting overrides.
- `scripts/openai_auth.py` — ChatGPT OAuth device flow login for Codex CLI.
- `scripts/rwea_score.py` — deterministic RWEA scoring with domain-specific weights.
- `settings/model-settings.json` — model roster, provider routing, and 7 execution profiles.
- `settings/benchmark-profiles.json` — domain-specific model reliability weights and RWEA overrides (Vals.ai).
- `settings/model-prompting.json` — per-model temperature, system prompt preambles/suffixes.
- `references/roles.md`, `references/scoring.md`, `references/rwea-input-template.json` — debate roles, scoring rules, and input schema.
- `references/model-prompting-guide.md` — deep reference for model-specific prompting best practices.
- `api-keys/` — provider key examples and ignore rules for local credential setup.
- `errors.md` — known failure modes and troubleshooting notes.

## How it works

The pipeline generates independent solver drafts from different models to maximize solution diversity. Adversarial reviewers challenge those drafts across multiple debate rounds to expose weak reasoning. A reliability-weighted ensemble stage scores evidence quality and synthesizes a final answer with stronger error resistance than single-pass generation.

## Execution Profiles

| Profile | Description |
|---------|-------------|
| `cli_primary` | CLI-first: Claude/GPT/Kimi via native CLIs, Gemini via Google API, GLM-5/MiniMax via OpenRouter |
| `multi_model` | Maximum diversity — each solver is a different provider |
| `balanced` | All Claude via native CLI/Task tool |
| `cost_optimized` | Cheapest — Sonnet solvers, Haiku debaters |
| `max_quality` | Best from each provider |
| `budget` | Zero Claude subagents — all calls via Codex/Kimi CLI or OpenRouter API |

## Key Features (v5)

- **Auto CLI→API fallback** — CLI timeouts/crashes auto-retry via OpenRouter. Zero manual intervention.
- **600s CLI timeout** — prevents premature timeout on high-token-budget runs.
- **Batch isolation** — each external-model Bash call is a separate invocation to prevent cascade cancellation.
- **Per-model prompting** — temperature, system preambles, and suffixes auto-applied per model via `model-prompting.json`.
- **Budget mode** — zero Claude subagent costs. All reasoning via Codex CLI, Kimi CLI, Google API, or OpenRouter.
- **Domain-aware scoring** — 7 domains (coding, math, finance, legal, academic, strategy, general) with benchmark-derived weights.
- **Formal verification** — Aristotle theorem prover runs in parallel with debaters for zero added latency.
