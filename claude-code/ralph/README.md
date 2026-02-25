# ralph

Autonomous fresh-context loop for multi-model dissertation idea generation with saturation-based exit.

## Files

- `SKILL.md` — full workflow definition: session management, iteration loop, exit conditions, creative lenses, model selection.
- `scripts/ralph.sh` — bash orchestrator: 7-step iteration loop with session resume and error recovery.
- `scripts/session_manager.py` — LLM calls, session lifecycle, structured output parsing.
- `scripts/circuit_breaker.py` — per-model 3-state circuit breaker (closed/open/half-open) with exponential cooldown.
- `scripts/model_selector.py` — benchmark-weighted stochastic model selection with exploration/exploitation balance.
- `scripts/prompt_builder.py` — prompt assembly with creative lens injection and recency avoidance.
- `scripts/exit_evaluator.py` — saturation detection (rolling improvement window) and budget limit checks.
- `scripts/idea_evaluator.py` — novelty/feasibility scoring and Jaccard-similarity deduplication.
- `scripts/memory_indexer.py` — cross-iteration learning with 4-type taxonomy (patterns, decisions, fixes, signs).
- `scripts/benchmark_sync.py` — benchmark data freshness check from the `/llm` skill.
- `settings/ralph-config.json` — loop limits, exit gates, circuit breaker params, model selection weights.
- `settings/presets/idea-generation.json` — dissertation preset: academic domain, quantitative finance, PhD constraints.
- `settings/benchmark-profiles.json` — domain-specific model reliability weights for selection.
- `references/architecture.md` — design rationale and failure mode analysis.
- `references/creative-lenses.yaml` — 20 curated divergence-forcing constraints.

## How it works

Each iteration runs in a fresh LLM context — no growing conversation, no context window pressure. The bash orchestrator selects a model (weighted by academic benchmarks with stochastic exploration), builds a prompt injected with one of 20 creative lenses (inversion, cross-pollination, failure-mode analysis, scale shift, etc.), calls the model, scores the response for novelty and feasibility, deduplicates against all prior ideas via Jaccard similarity, and persists everything to disk. A circuit breaker tracks per-model failures and routes around broken models automatically. The loop exits when idea quality saturates (rolling improvement drops below threshold), the time or iteration budget is exhausted, or all models are circuit-broken.

Named after the Ralph Wiggum Loop pattern: instead of managing growing context, discard it entirely and restart fresh each iteration. State lives on disk, not in any model's context window.

## Key features

- **Fresh context per iteration** — no context window degradation over hundreds of iterations
- **Multi-model** — rotates across Claude, GPT, Gemini, Kimi, MiniMax via benchmark-weighted stochastic selection
- **20 creative lenses** — divergence-forcing constraints prevent mode collapse across iterations
- **Saturation exit** — automatically stops when marginal idea quality plateaus
- **Circuit breaker** — per-model failure tracking with exponential backoff cooldown
- **Session resume** — pick up where you left off after interruption
- **Cross-iteration memory** — 4-type taxonomy accumulates patterns, decisions, fixes, and warning signs
- **Jaccard deduplication** — prevents near-duplicate ideas from inflating the idea bank

## Example invocation

```
/ralph
/ralph --iterations 20
/ralph --preset idea-generation --domain academic
```

## Setup

Requires the `/llm` skill for model routing and benchmark data, and the `/debate` skill's `benchmark-profiles.json` for domain weights. Python 3.10+.
