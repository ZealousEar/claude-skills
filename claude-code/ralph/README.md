# ralph

Autonomous fresh-context loop with two modes: **idea generation** (dissertation research) and **analytics discovery** (SaaS funnel insights via SQL execution).

## Modes

### Idea Generation (`ralph.sh`)
7-step loop producing dissertation research ideas scored on novelty + feasibility. 20 creative lenses force divergent thinking across iterations.

### Analytics Discovery (`ralph-analytics.sh`)
9-step loop with SQL execution producing data-grounded funnel findings scored on novelty + actionability + evidence. Two LLM calls per iteration: one to generate SQL queries, one to synthesize results into actionable findings. 15 tiered analytical lenses.

## Files

### Core (shared by both modes)
- `SKILL.md` — full workflow definition for both modes
- `scripts/session_manager.py` — LLM calls, session lifecycle, structured output parsing
- `scripts/circuit_breaker.py` — per-model 3-state circuit breaker (closed/open/half-open) with exponential cooldown
- `scripts/model_selector.py` — benchmark-weighted stochastic model selection with exploration/exploitation balance
- `scripts/prompt_builder.py` — prompt assembly with creative lens injection and recency avoidance
- `scripts/exit_evaluator.py` — saturation detection (rolling improvement window) and budget limit checks
- `scripts/memory_indexer.py` — cross-iteration learning with 4-type taxonomy (patterns, decisions, fixes, signs)
- `scripts/benchmark_sync.py` — benchmark data freshness check from the `/llm` skill

### Idea Generation
- `scripts/ralph.sh` — bash orchestrator: 7-step iteration loop
- `scripts/idea_evaluator.py` — novelty/feasibility scoring and Jaccard-similarity deduplication
- `settings/ralph-config.json` — loop limits, exit gates, circuit breaker params, model selection weights
- `settings/presets/idea-generation.json` — dissertation preset: academic domain, quantitative finance
- `references/creative-lenses.yaml` — 20 curated divergence-forcing constraints

### Analytics Discovery
- `scripts/ralph-analytics.sh` — bash orchestrator: 9-step iteration loop with SQL execution
- `scripts/analytics_evaluator.py` — novelty/actionability/evidence scoring and Jaccard deduplication
- `scripts/sql_executor.py` — SQL execution via psql subprocess with timeout and row limits
- `scripts/build_synthesis_prompt.py` — combines original prompt with SQL results for Phase 2
- `scripts/synthesis_pass.py` — post-loop aggregation: groups findings by funnel stage, ranks recommendations
- `settings/analytics-config.json` — extends main config with analytics evaluation and SQL execution settings
- `settings/presets/grapple-analytics.json` — Grapple Law funnel analytics preset
- `references/grapple-lenses.yaml` — 15 tiered analytical lenses (structural, behavioral, exploratory, stretch)
- `references/grapple-schema.md` — PostgreSQL schema reference injected into prompts

### Shared references
- `settings/benchmark-profiles.json` — domain-specific model reliability weights for selection
- `references/architecture.md` — design rationale and failure mode analysis

## How it works

Each iteration runs in a fresh LLM context — no growing conversation, no context window pressure. The bash orchestrator selects a model (weighted by benchmarks with stochastic exploration), builds a prompt injected with a creative lens, calls the model, scores the response, deduplicates against all prior output via Jaccard similarity, and persists everything to disk. A circuit breaker tracks per-model failures and routes around broken models automatically. The loop exits when output quality saturates, the time or iteration budget is exhausted, or all models are circuit-broken.

In analytics mode, each iteration makes **two LLM calls**: the first generates SQL queries based on the analytical lens, which are executed against a live PostgreSQL database. The results are fed back to the model for evidence-grounded synthesis.

Named after the [Ralph Wiggum Loop](https://ghuntley.com/ralph/) pattern by [Geoffrey Huntley](https://github.com/ghuntley/how-to-ralph-wiggum): instead of managing growing context, discard it entirely and restart fresh each iteration. State lives on disk, not in any model's context window.

## Key features

- **Fresh context per iteration** — no context window degradation over hundreds of iterations
- **Multi-model** — rotates across Claude, GPT, Gemini, Kimi, MiniMax via benchmark-weighted stochastic selection
- **Two modes** — idea generation (20 creative lenses) and analytics discovery (15 tiered lenses + SQL)
- **SQL execution** — analytics mode runs queries against live databases and grounds findings in data
- **Saturation exit** — automatically stops when marginal output quality plateaus
- **Circuit breaker** — per-model failure tracking with exponential backoff cooldown
- **Session resume** — pick up where you left off after interruption
- **Cross-iteration memory** — 4-type taxonomy accumulates patterns, decisions, fixes, and warning signs
- **Jaccard deduplication** — prevents near-duplicates from inflating the output bank
- **Post-loop synthesis** — analytics mode aggregates findings by funnel stage and ranks recommendations

## Example invocation

```
# Idea generation
/ralph
/ralph --iterations 20

# Analytics discovery
bash ~/.claude/skills/ralph/scripts/ralph-analytics.sh 15
bash ~/.claude/skills/ralph/scripts/ralph-analytics.sh --resume ralph-analytics-20260226-123456
```

## Setup

Requires the `/llm` skill for model routing and benchmark data, and the `/debate` skill's `benchmark-profiles.json` for domain weights. Python 3.10+. Analytics mode additionally requires `psql` on PATH and a locally accessible PostgreSQL database.

## Acknowledgments

The Ralph Wiggum Loop technique was created by [Geoffrey Huntley](https://ghuntley.com/ralph/) ([how-to-ralph-wiggum](https://github.com/ghuntley/how-to-ralph-wiggum)). All code in this skill is original; the following architectural ideas were studied and reimplemented from scratch:

| Repo | License | Idea Borrowed | How We Adapted It |
|------|---------|--------------|-------------------|
| [frankbria/ralph-claude-code](https://github.com/frankbria/ralph-claude-code) | MIT | 3-state circuit breaker, session persistence | Reimplemented in Python; per-model instead of global; exponential backoff |
| [mikeyobrien/ralph-orchestrator](https://github.com/mikeyobrien/ralph-orchestrator) | MIT | 4-type memory taxonomy (Pattern/Decision/Fix/Context) | Reimplemented in Python; changed "Context" to "Signs" (saturation indicators) |
| [coleam00/ralph-loop-quickstart](https://github.com/coleam00/ralph-loop-quickstart) | -- | Minimal bash loop philosophy | Kept bash as orchestrator; moved logic to standalone Python scripts |
| [snwfdhmp/awesome-ralph](https://github.com/snwfdhmp/awesome-ralph) | -- | "3 Phases, 2 Prompts, 1 Loop" framework | Simplified to single phase, single prompt per iteration |

The circuit breaker pattern originates from Michael Nygard's *Release It!* (2007).
