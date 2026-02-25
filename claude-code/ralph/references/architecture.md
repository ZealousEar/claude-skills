# Ralph Loop Architecture — Design Rationale

> This document captures the architectural decisions for the Ralph skill, derived from a convolutional debate analysis of 4 major Ralph implementations (frankbria, mikeyobrien, coleam00, awesome-ralph) plus community patterns. The Ralph Wiggum Loop technique was created by [Geoffrey Huntley](https://ghuntley.com/ralph/) ([how-to-ralph-wiggum](https://github.com/ghuntley/how-to-ralph-wiggum)).

## Core Insight

The Ralph Loop solves the "malloc/free problem" of LLM context windows. Instead of trying to manage growing context, it **discards the entire context and restarts fresh** each iteration. State persists to disk (JSON/JSONL files), not in the model's context window. This means:

1. Every iteration gets maximum available context for the actual task
2. No context pollution from earlier failed attempts
3. Different models can be used across iterations without migration concerns
4. The loop can run for hundreds of iterations without degradation

## Design Decisions

### 1. LLM Infrastructure: `/llm` Skill (not debate-agent's llm_runner.py)
**Why**: The `/llm` skill's `llm_route.py` is newer, has benchmark CSV integration, auto-discovers API keys from multiple locations, and handles per-model prompting overrides automatically via `apply_prompting_overrides()`. The debate agent's `llm_runner.py` is older and tightly coupled to the debate protocol.

**Implication**: `session_manager.py` imports `llm_route` via `sys.path.insert()`. This is a runtime import, not a package dependency.

### 2. Prompt Wrapping: Delegated to `llm_route.call_model()`
**Why**: `call_model()` (line 645-648) already applies per-model system prompt preambles, temperature overrides, and format preferences (XML for Claude/Gemini, CTCO for GPT, plain for Kimi/MiniMax). Duplicating this logic in `prompt_builder.py` would create drift.

**Implication**: `prompt_builder.py` builds raw content. Model-specific wrapping happens automatically when `session_manager.py` calls `call_model()`.

### 3. Dedup Method: Jaccard on Key Terms (not embeddings)
**Why**: Embedding-based dedup requires a vector DB or external API call, adding latency and complexity. Jaccard on extracted key terms (title + research question + novelty claim) is conservative but functional for the expected output volume (<200 ideas). False negatives (missing duplicates) are acceptable — the human reviews the final bank anyway.

**Implication**: `idea_evaluator.py` uses stdlib-only tokenization with a hardcoded stopword list.

### 4. Model Selection: Weighted Stochastic (not argmax)
**Why**: Argmax would always select the same top-scoring model, eliminating diversity. The value of the Ralph loop comes from **different models approaching the same problem differently**. Stochastic selection with benchmark-based weights means better models are selected more often, but weaker models still contribute occasionally (they sometimes produce the most creative ideas).

**Implication**: `model_selector.py` uses `random.choices()` with weights from `benchmark-profiles.json`. Recency penalty further discourages consecutive same-model selections.

### 5. Exit Gate: Saturation-Based (not dual-condition)
**Why**: The original frankbria dual-condition gate (completion indicators + EXIT_SIGNAL) is designed for coding tasks where "done" is verifiable. For idea generation, there's no "done" — we want to stop when ideas stop improving. Saturation detection (comparing recent window's max score to previous window's max score) naturally detects when the model pool has exhausted its creative capacity for the given prompt structure.

**Implication**: `exit_evaluator.py` compares score windows, not output strings.

### 6. Memory: 4-Type Taxonomy (Pattern/Decision/Fix/Signs)
**Why**: From mikeyobrien's orchestrator. Flat memory (just a list) becomes unsearchable. The taxonomy enables structured retrieval:
- **Patterns**: Feed back into prompts to reinforce successful approaches
- **Decisions**: Audit trail of model/lens choices
- **Fixes**: Error recovery log for debugging
- **Signs**: Early saturation indicators

**Implication**: `memory_indexer.py` classifies each iteration's output into the taxonomy. `prompt_builder.py` reads patterns and signs to build richer prompts.

### 7. Script Communication: JSON Files + Exit Codes (not pipes/sockets)
**Why**: Every script is independently testable. You can run `python3 circuit_breaker.py --check --model opus --state /tmp/test.json` in isolation. JSON files are human-readable and debuggable. Exit codes signal success/failure to the bash orchestrator. No inter-process coupling.

**Implication**: `ralph.sh` is a simple sequential loop that calls scripts via `python3 script.py --args`. Temporary files for prompt/result transfer.

### 8. Circuit Breaker: Per-Model (not global)
**Why**: A global circuit breaker would stop the entire loop when one model fails. Per-model breakers allow the loop to continue with remaining healthy models. If opus times out 3 times, the breaker opens for opus but gemini-3-pro continues.

**Implication**: `circuit-state.json` has one entry per model. `model_selector.py` checks breaker state before including a model in the selection pool.

### 9. Creative Lenses: 20 Curated (not infinite generation)
**Why**: Auto-generated lenses tend toward generic ("think differently") or redundant. The 20 curated lenses each target a specific cognitive shift relevant to quantitative finance research. They're applied stochastically with recency avoidance, ensuring ~20 unique angles before any repeat.

**Implication**: `creative-lenses.yaml` is a static reference file. Adding new lenses is manual and intentional.

### 10. No Git Checkpointing (unlike reference implementations)
**Why**: The original Ralph loop checkpoints to git after each iteration because it modifies code files. This skill generates ideas (text), not code. Ideas are stored in `ideas-bank.json` which is append-only. There's nothing to roll back.

**Implication**: `ralph.sh` does not call git. Session state is the checkpoint.

## Source Implementations

No code was copied from any of these repositories. The following design ideas were studied and reimplemented from scratch:

| Repo | License | Key Architectural Idea | How We Adapted It |
|------|---------|----------------------|-------------------|
| [frankbria/ralph-claude-code](https://github.com/frankbria/ralph-claude-code) | MIT | 3-state circuit breaker (`lib/circuit_breaker.sh`), session persistence via response analyzer | Reimplemented in Python (`circuit_breaker.py`); per-model instead of global; added exponential backoff cooldown (doubles on re-fail, max 3600s) |
| [mikeyobrien/ralph-orchestrator](https://github.com/mikeyobrien/ralph-orchestrator) | MIT | 4-type memory taxonomy (`memory.rs`: Pattern/Decision/Fix/Context), multi-model backend adapters | Reimplemented in Python (`memory_indexer.py`); changed "Context" to "Signs" for early saturation detection; delegated multi-model routing to /llm skill |
| [coleam00/ralph-loop-quickstart](https://github.com/coleam00/ralph-loop-quickstart) | — | Minimal bash loop (`ralph.sh`, ~110 lines, no dependencies beyond `claude` CLI) | Kept bash as outer orchestrator; moved all logic to standalone Python scripts callable independently |
| [snwfdhmp/awesome-ralph](https://github.com/snwfdhmp/awesome-ralph) | — | "3 Phases, 2 Prompts, 1 Loop" framework (Define → Plan → Build) | Simplified to single phase (idea generation), single prompt per iteration |

The circuit breaker pattern itself originates from Michael Nygard, *Release It!* (2007), popularized by [Martin Fowler's writeup](https://martinfowler.com/bliki/CircuitBreaker.html).

## Failure Modes & Mitigations

| Failure | Detection | Mitigation |
|---------|-----------|------------|
| Model timeout | `call_model()` raises RuntimeError | Circuit breaker opens after 3 failures; auto-fallback in llm_route |
| Malformed JSON response | `idea_evaluator.py` parse failure | Records as failed iteration, memory_indexer logs fix entry |
| All models circuit-broken | `model_selector.py` exits 1 | ralph.sh catches and terminates with report |
| Idea saturation | `exit_evaluator.py` detects score plateau | Loop exits cleanly with "SATURATION" reason |
| Disk full | JSON write fails | Atomic writes prevent corruption; loop terminates on write error |
| API key missing | `llm_route.get_api_key()` raises ValueError | Circuit breaker opens for that model's route |
