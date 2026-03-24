# /ralph — Autonomous Fresh-Context Loop

Ralph is an autonomous multi-model iteration loop that applies the fresh-context pattern to idea generation. Each iteration independently selects a model (weighted by benchmarks), applies a creative divergence lens, calls the LLM, scores and deduplicates the output, and persists everything to disk. The loop self-terminates when output quality saturates or budget limits are hit.

Named after the **Ralph Wiggum Loop** pattern: instead of managing growing context, discard it entirely and restart fresh each iteration. State lives on disk, not in any model's context window.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Usage](#usage)
- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [Creative Lenses](#creative-lenses)
- [Model Pool](#model-pool)
- [Output](#output)
- [State Files](#state-files)
- [Script Reference](#script-reference)
- [Exit Conditions](#exit-conditions)
- [Failure Handling](#failure-handling)
- [Prerequisites](#prerequisites)
- [Design Decisions](#design-decisions)
- [Examples](#examples)
---

## Step 0: Model Configuration Prompt

**Before starting the loop**, check whether the user's message already specifies model preferences (e.g., "use opus only", "exclude kimi", "low reasoning effort"). If it does, apply those preferences directly and skip this prompt. If it does NOT, present the following using AskUserQuestion:

```
Model configuration for /ralph:

MODEL POOL (choose one):
  1. auto-weighted — all available models, weighted by domain benchmarks (default)
  2. opus-only    — every iteration uses opus
  3. custom       — specify which models to include/exclude

Available models: run `python3 ~/.claude/skills/llm/scripts/llm_route.py --list-models` to see what's configured

REASONING EFFORT (optional — press Enter for defaults):
  Claude (opus):      thinking budget → [16k tokens (default) / 32k / 64k / 128k]
  ChatGPT (5.4/5.2):  reasoning_effort → [xhigh (default) / high / medium / low]

CONTEXT WINDOW (optional — press Enter for defaults):
  [default / specify tokens / auto (let model_selector decide per iteration)]

Enter choice (e.g. "1", "opus-only", "custom: include=opus,chatgpt-5.4 effort=high"):
```

**Parsing the response:**
- If "auto-weighted" or "1" → use default `preferred_models` from ralph-config.json
- If "opus-only" → set `preferred_models` to `["opus"]` for this session
- If "custom" → parse include/exclude list, update `preferred_models` and `excluded_models` for this session
- If reasoning effort specified → pass as override to `session_manager.py` calls (e.g., `--thinking-budget 32000` for opus, `--reasoning-effort high` for ChatGPT)
- If context window specified → apply as runtime override; if "auto", let `model_selector.py` choose based on prompt size
- If user presses Enter or says "defaults" → use existing ralph-config.json settings unchanged

---

## Quick Start

```bash
# Run with defaults — idea-generation preset, academic domain, up to 200 iterations
/ralph

# Cap at 10 iterations (good for testing)
/ralph --iterations 10

# Run directly via shell
bash ~/.claude/skills/ralph/scripts/ralph.sh idea-generation 10

# Analytics mode — SaaS funnel discovery with SQL execution
bash ~/.claude/skills/ralph/scripts/ralph-analytics.sh 15
```

The loop will:
1. Select a random model (weighted by academic benchmarks)
2. Build a prompt with a random creative lens
3. Call the model and parse the structured idea
4. Score, deduplicate, and store the idea
5. Repeat until saturation, budget limit, or max iterations

On completion, a session report prints to stdout and all ideas are in `state/<session_id>/ideas-bank.json`.

---

## Usage

### Start a New Session

```bash
# Slash command (via Claude Code)
/ralph
/ralph --iterations 20
/ralph --preset idea-generation --domain academic

# Direct shell invocation
bash ~/.claude/skills/ralph/scripts/ralph.sh <preset> [max_iterations]
bash ~/.claude/skills/ralph/scripts/ralph.sh idea-generation 50
```

**Arguments:**

| Argument | Default | Description |
|----------|---------|-------------|
| `preset` | `idea-generation` | Preset name from `settings/presets/` |
| `max_iterations` | `200` (from config) | Override the maximum iteration count |
| `--resume <id>` | — | Resume a previous session by ID |

### Resume a Previous Session

```bash
bash ~/.claude/skills/ralph/scripts/ralph.sh idea-generation --resume ralph-20260225-230341
```

Resumes from the last completed iteration. All state files are preserved and appended to.

### Sync Benchmarks

```bash
python3 ~/.claude/skills/ralph/scripts/benchmark_sync.py          # sync if stale (>24h)
python3 ~/.claude/skills/ralph/scripts/benchmark_sync.py --force   # force re-fetch
```

Refreshes the benchmark rankings CSV from upstream sources. Runs automatically at session start; this command is for manual refresh.

### View a Session Report

```bash
python3 ~/.claude/skills/ralph/scripts/session_manager.py \
    --report --session <id> --state-dir ~/.claude/skills/ralph/state/<id>
```

Prints iteration stats, model usage breakdown, and top-scored ideas.

---

## How It Works

Each iteration is a **completely independent subprocess pipeline**. No state crosses between iterations via memory — only via JSON files on disk.

```
┌─────────────────────────────────────────────────────────────┐
│                      ralph.sh (bash)                        │
│                                                             │
│  for each iteration:                                        │
│                                                             │
│    [1] model_selector.py   → selects model (stdout)         │
│    [2] prompt_builder.py   → writes prompt + system files   │
│    [3] session_manager.py  → calls LLM, writes result JSON  │
│    [4] idea_evaluator.py   → scores + dedup, updates bank   │
│    [5] memory_indexer.py   → extracts learnings to memory   │
│    [6] circuit_breaker.py  → records success/failure         │
│    [7] exit_evaluator.py   → CONTINUE | SATURATION | LIMIT  │
│                                                             │
│  if exit_evaluator != CONTINUE: break                       │
│                                                             │
│  session_manager.py --report (final summary)                │
└─────────────────────────────────────────────────────────────┘
```

Scripts communicate exclusively through:
- **JSON files on disk** (state directory + temp files)
- **stdout** (single-line outputs: model name, exit decision, eval summary)
- **Exit codes** (0 = success, 1 = error)

This means every script is independently runnable and testable.

---

## Architecture

### Directory Structure

```
~/.claude/skills/ralph/
├── SKILL.md                           # This file
├── scripts/
│   ├── ralph.sh                       # Bash orchestrator — idea generation (7-step)
│   ├── ralph-analytics.sh             # Bash orchestrator — analytics discovery (9-step)
│   ├── session_manager.py             # Session init, LLM calls, logging, reports
│   ├── circuit_breaker.py             # 3-state per-model circuit breaker
│   ├── model_selector.py              # Benchmark-weighted stochastic selection
│   ├── prompt_builder.py              # Prompt assembly + creative lenses
│   ├── exit_evaluator.py              # Saturation detection + budget limits
│   ├── idea_evaluator.py              # Novelty/feasibility scoring + Jaccard dedup
│   ├── memory_indexer.py              # Cross-iteration learning (4-type taxonomy)
│   └── benchmark_sync.py              # Benchmark data freshness check + refresh
├── settings/
│   ├── ralph-config.json              # Main configuration
│   ├── benchmark-profiles.json        # Symlink → debate-agent's domain weights
│   └── presets/
│       └── idea-generation.json       # Default preset
├── references/
│   ├── creative-lenses.yaml           # 20 curated lenses
│   └── architecture.md                # Design rationale document
└── state/                             # Created at runtime, one dir per session
    └── <session_id>/
        ├── session.json
        ├── iterations.jsonl
        ├── ideas-bank.json
        ├── memory.json
        └── circuit-state.json
```

### Infrastructure Reuse

Ralph does not duplicate LLM infrastructure. It imports from sibling skills:

| Dependency | Source | How |
|-----------|--------|-----|
| Model calling | `/llm` skill's `llm_route.py` | `sys.path.insert()` import in `session_manager.py` |
| Prompt wrapping | `/llm` skill's `llm_route.call_model()` | Auto-applies XML/CTCO/plain per model |
| Benchmark data | `/llm` skill's `rankings.csv` | 1,071 models, 32 columns, 5 sources |
| Model registry | `/llm` skill's `model-registry.json` | 11 model configs with routes + reasoning params |
| Domain weights | Debate agent's `benchmark-profiles.json` | Symlinked; 7 domains with per-model weights |
| API keys | Auto-discovered by `llm_route.get_api_key()` | Checks env vars, `.env` files, provider configs |

---

## Configuration

### Main Config: `settings/ralph-config.json`

```json
{
  "loop": {
    "max_iterations": 200,          // Hard cap on iterations
    "max_runtime_hours": 8,         // Wall-clock time limit
    "cooldown_between_iterations_seconds": 5
  },
  "exit_gate": {
    "saturation_window": 10,        // Ideas per comparison window
    "saturation_threshold": 0.15,   // Min improvement to keep going
    "min_unique_ideas": 5,          // Don't check saturation until this many
    "hard_limit_iterations": 200,
    "hard_limit_hours": 8
  },
  "circuit_breaker": {
    "failure_threshold": 3,         // Failures before model is skipped
    "cooldown_seconds": 300,        // Seconds before retry (doubles on re-fail)
    "half_open_max_attempts": 1
  },
  "model_selection": {
    "domain": "academic",           // Domain for benchmark weights
    "exploration_weight": 0.3,      // Recency penalty strength (0=none, 1=max)
    "recency_penalty_window": 5,    // How many recent iterations to penalize
    "excluded_models": ["aristotle", "glm-5"],
    "preferred_models": ["opus", "gemini-3.1-pro", "gpt-5.2", "chatgpt-5.4", "kimi-2.5"]
  },
  "idea_evaluation": {
    "novelty_weight": 0.55,         // Weight for novelty in combined score
    "feasibility_weight": 0.45,     // Weight for feasibility
    "dedup_jaccard_threshold": 0.6, // Similarity threshold for duplicate detection
    "min_key_terms": 5              // Min terms needed for dedup comparison
  },
  "llm_call": {
    "max_tokens": 4096,
    "timeout": 600,                 // 10-minute timeout per LLM call
    "system_prompt_max_length": 8000
  }
}
```

### Presets: `settings/presets/<name>.json`

Presets define the domain, prompt template, and output parsing for a specific use case. The included `idea-generation.json` preset targets quantitative finance dissertation ideas.

**Preset structure:**

| Field | Description |
|-------|-------------|
| `domain` | Academic domain (drives benchmark weight lookup) |
| `subdomain` | Specific subfield |
| `context.dissertation_topic` | Research area description |
| `context.advisor_preferences` | What makes a good idea |
| `context.constraints` | Hard constraints (timeline, data, contribution) |
| `prompt_template.role` | System prompt role definition |
| `prompt_template.task` | User prompt with output JSON schema |
| `prompt_template.creative_lens_instruction` | Template for lens injection (`{lens}` placeholder) |
| `output_parsing.required_fields` | Fields the LLM must return |

**To create a new preset:** Copy `idea-generation.json`, change the domain/topic/constraints, and save as `settings/presets/<your-preset>.json`. Then run with:

```bash
bash ralph.sh your-preset 20
```

---

## Creative Lenses

Each iteration applies one of **20 curated creative lenses** — divergence-forcing constraints that push the model to approach the problem from an unusual angle. Lenses are selected stochastically with recency avoidance (a lens used in the last 5 iterations is deprioritized; if all are exhausted, the least-recently-used is selected).

| # | Lens | Cognitive Shift |
|---|------|----------------|
| 1 | Inversion | Deliberately do the opposite of conventional wisdom |
| 2 | Cross-Pollination | Import technique from an alien field |
| 3 | Failure Mode | Design around an assumption that will break |
| 4 | Scale Shift | Study a phenomenon at a radically different scale |
| 5 | Data-First | Start from an unusual, underexploited data source |
| 6 | Adversarial | Account for intelligent, adaptive counterparties |
| 7 | Radical Simplicity | Find the simplest model that captures 80% |
| 8 | Regime-Aware | Explicitly handle regime changes |
| 9 | Network/Graph | Model the system as a network |
| 10 | Information Asymmetry | Focus on who knows what and when |
| 11 | Temporal Structure | Challenge standard temporal assumptions |
| 12 | Behavioral Finance | Build quantitative models from cognitive biases |
| 13 | Market Microstructure | Focus on mechanics of trade execution |
| 14 | Synthetic Data | Simulation-based inference as primary methodology |
| 15 | Tail Risk | Extreme events from reliability engineering |
| 16 | Multi-Asset | Cross asset class boundaries |
| 17 | Regulatory Arbitrage | Model unintended consequences of regulation |
| 18 | ML Interpretability | Interpretability over prediction accuracy |
| 19 | Climate/ESG | Physical risk pricing, not ESG scoring |
| 20 | DeFi/Decentralized | Apply classical theory to DeFi protocols |

Lenses are defined in `references/creative-lenses.yaml`. To add a new lens, append an entry with `id`, `name`, and `prompt` fields.

---

## Model Pool

Models are selected stochastically, weighted by academic domain benchmark scores from `benchmark-profiles.json`:

| Model | Route | Reasoning | Approximate Weight |
|-------|-------|-----------|-------------------|
| `opus` | Claude CLI | Inherent extended thinking | 0.90 |
| `gemini-3.1-pro` | Google API | `thinkingLevel=HIGH` | 1.00 |
| `gpt-5.2` | Codex CLI | `reasoning_effort=xhigh` | 0.80 |
| `chatgpt-5.4` | Codex CLI | `reasoning_effort=xhigh` | 0.55 |
| `kimi-2.5` | Kimi CLI | `--thinking` | 0.65 |

**Excluded by default:** `aristotle` (theorem prover, not a general LLM), `glm-5` (returns empty responses via OpenRouter).

**Selection algorithm:**
1. Start with preferred models from config
2. Remove excluded models
3. Remove circuit-OPEN models (HALF_OPEN remain eligible)
4. Look up domain weight for each remaining model
5. Apply recency penalty: for each occurrence in last N iterations, multiply weight by `(1 - exploration_weight)`
6. Floor all weights at 1e-6 (no model reaches zero probability)
7. Normalize to sum to 1.0
8. Sample via `random.choices()`

---

## Output

### Ideas Bank: `state/<session_id>/ideas-bank.json`

The primary output. Each idea contains:

```json
{
  "idea_id": "idea-001",
  "source_model": "kimi-2.5",
  "iteration": 1,
  "title": "Higher-Order Contagion in Multi-Asset Derivatives Networks...",
  "research_question": "How do higher-order interdependencies...",
  "abstract": "This dissertation develops a hypergraph framework...",
  "methodology": "Hypergraph theory, stochastic volatility models...",
  "key_mechanisms": ["mechanism1", "mechanism2", "mechanism3"],
  "novelty_claim": "First application of hypergraph spectral theory...",
  "key_references": ["Billio et al. (2012) - ...", "..."],
  "feasibility_notes": "Public OCC data provides...",
  "novelty_score": 0.85,
  "feasibility_score": 0.72,
  "combined_score": 0.79,
  "is_duplicate": false,
  "key_terms": ["hypergraph", "contagion", "derivatives", "..."]
}
```

The `stats` section provides aggregate metrics:

```json
{
  "stats": {
    "total": 50,
    "unique": 43,
    "duplicates": 7,
    "avg_combined_score": 0.76,
    "top3_ids": ["idea-012", "idea-031", "idea-007"]
  }
}
```

### Session Report

Generated automatically at loop completion and available via `--report`:

```
============================================================
  RALPH SESSION REPORT
============================================================
  Session ID   : ralph-20260225-230341
  Preset       : idea-generation
  Status       : running
  Runtime      : 0.10 hours

  ITERATIONS
  ----------------------------------------
  Total        : 3
  Successful   : 3
  Failed       : 0
  Duplicates   : 0
  Avg duration : 121.3s

  IDEAS
  ----------------------------------------
  Total ideas  : 3
  Unique ideas : 3
  Avg score    : 1.000
  Top 3 IDs    : idea-001, idea-002, idea-003

  MODEL USAGE
  ----------------------------------------
  Model                  Calls   Total (s)   Avg (s)
  kimi-2.5                   1        29.7      29.7
  gpt-5.2                    1       254.4     254.4
  sonnet                     1        79.7      79.7

  TOP 5 SCORES
  ----------------------------------------
   Iter  Model              Score  Idea ID
      1  kimi-2.5           1.000  idea-001
      2  gpt-5.2            1.000  idea-002
      3  sonnet             1.000  idea-003
============================================================
```

---

## State Files

All state is stored in `~/.claude/skills/ralph/state/<session_id>/`. Each file serves a specific purpose:

### `session.json` — Session Metadata

```json
{
  "session_id": "ralph-20260225-230341",
  "preset": "idea-generation",
  "started_at": 1772060621.697,
  "iteration": 3,
  "status": "running",
  "config_snapshot": {
    "max_iterations": 200,
    "max_runtime_hours": 8
  }
}
```

### `iterations.jsonl` — Append-Only Iteration Log

One JSON object per line, one line per iteration:

```jsonl
{"iteration": 1, "model": "kimi-2.5", "timestamp": "2026-02-25T23:04:11Z", "duration_seconds": 29.69, "success": true, "idea_id": "idea-001", "combined_score": 1.0, "is_duplicate": false}
{"iteration": 2, "model": "gpt-5.2", "timestamp": "2026-02-25T23:08:31Z", "duration_seconds": 254.38, "success": true, "idea_id": "idea-002", "combined_score": 1.0, "is_duplicate": false}
```

### `memory.json` — Cross-Iteration Learning

Four-type taxonomy inspired by [mikeyobrien/ralph-orchestrator](https://github.com/mikeyobrien/ralph-orchestrator):

```json
{
  "patterns": [],
  "decisions": [
    {"iteration": 1, "model": "kimi-2.5", "type": "model_lens", "detail": "Used kimi-2.5", "timestamp": "..."}
  ],
  "fixes": [],
  "signs": []
}
```

| Category | What Goes In | How It's Used |
|----------|-------------|--------------|
| `patterns` | Periodic summaries (every 5 iterations): model distribution, success rate | Fed back into prompts to reinforce successful approaches |
| `decisions` | Every iteration: which model and lens were chosen | Audit trail; `prompt_builder.py` reads to avoid lens repeats |
| `fixes` | Failed iterations: parse errors, timeouts, model errors | Debugging; not fed into prompts |
| `signs` | Theme repetition detected (>50% mechanism overlap with recent ideas) | Early saturation indicator; fed into prompts |

Capped at 50 entries per category to prevent unbounded growth.

### `circuit-state.json` — Per-Model Circuit Breaker

```json
{
  "kimi-2.5": {
    "state": "CLOSED",
    "failures": 0,
    "cooldown_seconds": 300,
    "opened_at": null,
    "last_failure": null
  }
}
```

---

## Script Reference

### `ralph.sh` — Bash Loop Orchestrator

The main entry point. Calls all Python scripts sequentially per iteration.

```
bash ralph.sh <preset> [max_iterations] [--resume <session_id>]
```

**Exit codes:** `0` = normal exit, `1` = fatal error, `2` = user interrupt (Ctrl-C)

**Behavior:**
- Creates session ID with timestamp: `ralph-YYYYMMDD-HHMMSS`
- Syncs benchmarks at session start (non-fatal if it fails)
- Initializes 5 state files via `session_manager.py --init`
- Runs 7-step iteration loop until exit condition
- Cleans up temp files on exit (prompt, result, eval summary)
- Prints final report and state file paths

### `session_manager.py` — Session Lifecycle + LLM Calls

Four mutually exclusive modes:

```bash
# Initialize a new session (creates 5 state files)
python3 session_manager.py --init --session <id> --preset <name> --state-dir <path>

# Run a single LLM call (reads prompt, writes result JSON)
python3 session_manager.py --run --model <name> --prompt-file <path> \
    --output <path> --iteration <n> --state-dir <path>

# Log an iteration to iterations.jsonl
python3 session_manager.py --log-iteration --session <id> --iteration <n> \
    --model <name> --result-file <path> --state-dir <path>

# Print human-readable session report
python3 session_manager.py --report --session <id> --state-dir <path>
```

### `circuit_breaker.py` — 3-State Per-Model Circuit Breaker

```bash
python3 circuit_breaker.py --check --model <name> --state <path>
# → stdout: CLOSED | OPEN | HALF_OPEN

python3 circuit_breaker.py --cooldown-remaining --model <name> --state <path>
# → stdout: seconds remaining (integer, 0 if not OPEN)

python3 circuit_breaker.py --record-success --model <name> --state <path>
# → stdout: new state

python3 circuit_breaker.py --record-failure "<reason>" --model <name> --state <path>
# → stdout: new state
```

**State machine:**

```
CLOSED ──(3 failures)──→ OPEN ──(cooldown expires)──→ HALF_OPEN
  ↑                                                       │
  └──────────(success)────────────────────────────────────┘
                                                          │
  OPEN ←──────(failure, doubles cooldown, max 3600s)──────┘
```

### `model_selector.py` — Benchmark-Weighted Stochastic Selection

```bash
python3 model_selector.py --config <path> --domain <domain> \
    [--history <path>] [--circuit-state <path>] [--seed <int>] [--debug]
# → stdout: model name (e.g., "opus")
```

Exit 1 if no models are available (all circuit-broken or excluded).

### `prompt_builder.py` — Prompt Assembly + Creative Lenses

```bash
python3 prompt_builder.py --model <name> --preset <name> \
    --memory <path> --ideas-bank <path> --iteration <n> \
    --output <path> --config <path>
# → writes <path> (user prompt) and <path>.system (system prompt)
# → stdout: {"lens_id": "inversion", "lens_name": "Inversion Lens"}
```

**Prompt composition:**
- **System prompt** = role definition + anti-repetition context (previous idea titles/claims) + memory insights (patterns + signs). Truncated at `system_prompt_max_length` (8000 chars).
- **User prompt** = task instruction + creative lens directive.

### `exit_evaluator.py` — Dual-Condition Exit Gate

```bash
python3 exit_evaluator.py --ideas-bank <path> --session <path> --config <path>
# → stdout: "CONTINUE" | "SATURATION: <reason>" | "HARD_LIMIT: <reason>"
```

Always exits 0. The stdout string is the signal.

### `idea_evaluator.py` — Novelty/Feasibility Scoring + Dedup

```bash
python3 idea_evaluator.py --result <path> --ideas-bank <path> --config <path>
# → updates ideas-bank.json
# → stdout: {"idea_id": "idea-007", "title": "...", "combined_score": 0.79,
#            "is_duplicate": false, "novelty_score": 0.85, "feasibility_score": 0.72}
```

**Scoring (heuristic, keyword-based):**
- **Novelty** (0-1): cross-domain bridges, novelty_claim length, key_mechanisms count. Baseline 0.3.
- **Feasibility** (0-1): public data sources, established techniques, feasibility_notes, timeline. Baseline 0.2.
- **Combined**: `novelty_weight * novelty + feasibility_weight * feasibility`
- **Dedup**: Jaccard similarity on key terms from `title + research_question + novelty_claim`. Threshold 0.6.

### `memory_indexer.py` — Cross-Iteration Learning

```bash
python3 memory_indexer.py --result <path> --memory <path>
# → updates memory.json
# → stdout: "memory: +2 entries (1p/3d/1f/0s total)"
```

### `benchmark_sync.py` — Benchmark Data Refresh

```bash
python3 benchmark_sync.py           # sync if stale (>24h)
python3 benchmark_sync.py --force   # force re-fetch
```

Wraps `/llm` skill's `fetch_benchmarks.py`. Always exits 0 (stale data is better than no data).

---

## Exit Conditions

The loop exits when any of these conditions are met:

| Condition | Detection | Exit Reason |
|-----------|-----------|-------------|
| **Score saturation** | `max(recent_window) - max(previous_window) < 0.15` AND `unique_ideas >= 5` | `SATURATION: improvement 0.09 < threshold 0.15` |
| **Iteration limit** | `iteration >= hard_limit_iterations` | `HARD_LIMIT: reached 200 iterations` |
| **Time limit** | `runtime >= hard_limit_hours` | `HARD_LIMIT: exceeded 8 hours runtime` |
| **Max iterations** (CLI) | `iteration >= max_iterations` (CLI arg override) | `MAX_ITERATIONS_REACHED (N)` |
| **All models broken** | `model_selector.py` exits 1 | `ALL_MODELS_BROKEN` |
| **Consecutive failures** | 10 failures in a row | `TOO_MANY_CONSECUTIVE_FAILURES` |
| **User interrupt** | Ctrl-C | Trap cleanup + `INTERRUPTED` message |

**Saturation algorithm:** Compares the maximum `combined_score` in the most recent window of N ideas against the maximum score in the previous window of N ideas (where N = `saturation_window`, default 10). If improvement is below `saturation_threshold` (default 0.15) and at least `min_unique_ideas` (default 5) unique ideas exist, the gate fires. Requires at least `2 * saturation_window` scored ideas before checking.

---

## Failure Handling

The loop is designed to be **resilient to partial failures**. Individual model failures do not kill the session.

| Failure | What Happens |
|---------|-------------|
| **LLM timeout/error** | Circuit breaker records failure. After 3 failures, model is skipped (OPEN). Loop continues with other models. Cooldown expires after 5 min (doubles on re-fail, max 1hr). |
| **Malformed JSON response** | `idea_evaluator.py` records a `parse_failed` entry with zero scores. `memory_indexer.py` logs a fix entry. Loop continues. |
| **All models circuit-broken** | `model_selector.py` exits 1. `ralph.sh` catches this and terminates with a report. |
| **Benchmark sync failure** | Non-fatal. Stale benchmark data is used. Warning printed. |
| **Disk write failure** | Atomic writes (tempfile + rename) prevent corruption. Loop terminates on write error. |
| **API key missing** | `llm_route.get_api_key()` raises ValueError. Circuit breaker opens for that model. |
| **Prompt build failure** | Iteration skipped. Consecutive failure counter incremented. |

All state file writes use **atomic operations** (write to temp file, then `os.replace()`). A crash mid-write cannot corrupt existing state.

---

## Prerequisites

### Required

- **Python 3.10+** (uses `X | Y` union type syntax)
- **`/llm` skill** installed at `~/.claude/skills/llm/` — provides `llm_route.py` for model calling
- **At least one working LLM provider** — API keys auto-discovered by `llm_route.get_api_key()`

### Optional

- **Convolutional debate agent** at `~/.claude/skills/convolutional-debate-agent/` — provides `benchmark-profiles.json` (symlinked). If missing, model selection falls back to uniform weights.
- **Benchmark data** at `~/.claude/skills/llm/benchmarks/rankings.csv` — auto-synced at session start. If missing, sync runs automatically.

### No External Dependencies

All Python scripts use **stdlib only** (no pip install required). The one external import (`llm_route`) is loaded via `sys.path.insert()` at runtime.

---

## Design Decisions

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | LLM infrastructure | `/llm` skill's `llm_route.py` | Newer than debate-agent's `llm_runner.py`; has benchmark CSV, auto-discovers API keys, handles prompting overrides |
| 2 | Prompt wrapping | Delegated to `call_model()` | Already applies XML (Claude/Gemini), CTCO (GPT), plain text (Kimi/MiniMax) per model |
| 3 | Dedup method | Jaccard on key terms | No embeddings/vector DB needed; stdlib-only; conservative but functional for <200 ideas |
| 4 | Model selection | Weighted stochastic | Preserves diversity — different models approach problems differently. Argmax would always pick the same model |
| 5 | Exit gate | Saturation-based | Idea generation has no "done" state; stop when improvement stalls |
| 6 | Memory taxonomy | 4 types (pattern/decision/fix/signs) | Structured retrieval > flat list; each type has a specific feedback role |
| 7 | Script communication | JSON files + exit codes | Every script independently testable; human-readable; zero inter-process coupling |
| 8 | Circuit breaker | Per-model (not global) | One failing model shouldn't stop the entire loop |
| 9 | Creative lenses | 20 curated (not auto-generated) | Auto-generated lenses tend generic or redundant; each curated lens targets a specific cognitive shift |
| 10 | Git checkpointing | None | Ideas are append-only text, not code; nothing to roll back |

Full design rationale with source attribution: `references/architecture.md`

---

## Examples

### Example: 3-Iteration Test Run

```
$ bash ralph.sh idea-generation 3

=== RALPH LOOP — NEW SESSION ralph-20260225-230341 ===
Preset: idea-generation | Domain: academic | Max iterations: 3

[setup] Syncing benchmarks...
benchmarks up-to-date (last synced 2.4h ago) -- 1071 models from 4 sources

=== Starting iteration loop (max 3) ===

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ITERATION 1 / 3
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[1/7] Selecting model... kimi-2.5
[2/7] Building prompt... lens=Network/Graph Lens
[3/7] Calling kimi-2.5... done (29.7s)
[4/7] Evaluating idea... idea-001 | score=1.0
  Title: Higher-Order Contagion in Multi-Asset Derivatives Networks...
[5/7] Updating memory... done
[6/7] Circuit breaker... success for kimi-2.5
[7/7] Exit check... CONTINUE

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ITERATION 2 / 3
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[1/7] Selecting model... gpt-5.2
[2/7] Building prompt... lens=Radical Simplicity Lens
[3/7] Calling gpt-5.2... done (254.4s)
[4/7] Evaluating idea... idea-002 | score=1.0
  Title: Minimum-Information Option Surfaces from Sparse Quotes...
[5/7] Updating memory... done
[6/7] Circuit breaker... success for gpt-5.2
[7/7] Exit check... CONTINUE

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ITERATION 3 / 3
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[1/7] Selecting model... sonnet
[2/7] Building prompt... lens=Regulatory Arbitrage Lens
[3/7] Calling sonnet... done (79.7s)
[4/7] Evaluating idea... idea-003 | score=1.0
  Title: Margin Spirals and Volatility Amplification in OTC Derivatives...
[5/7] Updating memory... done
[6/7] Circuit breaker... success for sonnet
[7/7] Exit check... CONTINUE

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  RALPH LOOP COMPLETE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Exit reason: MAX_ITERATIONS_REACHED (3)
Session: ralph-20260225-230341

[...session report printed...]

Ideas bank: ~/.claude/skills/ralph/state/ralph-20260225-230341/ideas-bank.json
```

### Example: Resume After Interrupt

```bash
# Session was interrupted at iteration 47
bash ralph.sh idea-generation --resume ralph-20260225-230341

=== RALPH LOOP — RESUMING SESSION ralph-20260225-230341 at iteration 47 ===
```

### Example: Check Individual Script

```bash
# Test circuit breaker in isolation
python3 circuit_breaker.py --check --model opus --state /tmp/test-cb.json
# → CLOSED

python3 circuit_breaker.py --record-failure "timeout" --model opus --state /tmp/test-cb.json
python3 circuit_breaker.py --record-failure "timeout" --model opus --state /tmp/test-cb.json
python3 circuit_breaker.py --record-failure "timeout" --model opus --state /tmp/test-cb.json
# → OPEN

python3 circuit_breaker.py --cooldown-remaining --model opus --state /tmp/test-cb.json
# → 298
```

---

## Acknowledgments

The Ralph Wiggum Loop technique was created by **Geoffrey Huntley** ([ghuntley.com/ralph](https://ghuntley.com/ralph/), [how-to-ralph-wiggum](https://github.com/ghuntley/how-to-ralph-wiggum)). The core insight — discard the entire context and restart fresh each iteration, with state persisting to disk — is his.

Architecture derived from a convolutional debate analysis of four community implementations. No code was copied; the following design ideas were adapted:

| Implementation | License | Architectural Idea Borrowed | How We Adapted It |
|---------------|---------|----------------------------|-------------------|
| [frankbria/ralph-claude-code](https://github.com/frankbria/ralph-claude-code) | MIT | 3-state circuit breaker (`lib/circuit_breaker.sh`), session persistence (`lib/response_analyzer.sh`) | Reimplemented in Python; per-model instead of global; exponential backoff cooldown |
| [mikeyobrien/ralph-orchestrator](https://github.com/mikeyobrien/ralph-orchestrator) | MIT | 4-type memory taxonomy (`crates/ralph-core/src/memory.rs`: Pattern/Decision/Fix/Context) | Reimplemented in Python; changed "Context" to "Signs" (early saturation indicators); capped at 50 entries per type |
| [coleam00/ralph-loop-quickstart](https://github.com/coleam00/ralph-loop-quickstart) | — | Minimal bash loop philosophy (`ralph.sh`, ~110 lines) | Kept bash as orchestrator; moved all logic to standalone Python scripts |
| [snwfdhmp/awesome-ralph](https://github.com/snwfdhmp/awesome-ralph) | — | "3 Phases, 2 Prompts, 1 Loop" framework | Simplified to single phase (idea generation), single prompt per iteration |

The circuit breaker pattern itself originates from Michael Nygard's *Release It!* (2007).
