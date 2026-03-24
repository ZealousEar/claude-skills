# GEPS v5 — Graph-Guided Evolutionary Portfolio Search

A multi-stage research idea generation and evaluation pipeline that replaces debate-as-core with **search + ranking + calibration**.

## Step 0: Model Configuration Prompt

**Before executing the pipeline**, check whether the user's message already specifies model preferences (e.g., "budget mode", "opus for generators, gemini for judges"). If it does, apply those preferences directly and skip this prompt. If it does NOT, present the following using AskUserQuestion:

```
Model configuration for /geps:

GENERATOR MODELS (Stage B — idea generation, 4 channels):
  1. all available — opus, chatgpt-5.4, gpt-5.2, gemini-3.1-pro, kimi-2.5, glm-5, minimax-m2.5 (default)
  2. top-tier only — opus, chatgpt-5.4, gemini-3.1-pro
  3. custom — specify which models to use

JUDGE POOL (Stage D — pairwise tournament):
  Default: opus, chatgpt-5.4, gpt-5.2, gemini-3.1-pro, kimi-2.5, glm-5, minimax-m2.5
  (enter custom list to override, or press Enter for default)

REASONING EFFORT (optional — press Enter for defaults):
  Claude (opus):      thinking budget → [16k tokens (default) / 32k / 64k / 128k]
  ChatGPT (5.4/5.2):  reasoning_effort → [xhigh (default) / high / medium / low]

CONTEXT WINDOW (optional — press Enter for defaults):
  [default / specify tokens / auto (orchestrator decides based on corpus size)]

Enter choice (e.g. "1", "top-tier judges=opus,gemini-3.1-pro,chatgpt-5.4", "custom: generators=opus,kimi-2.5"):
```

**Parsing the response:**
- If "all available" or "1" → use `all_models` from gib-config.json
- If "top-tier only" → filter to opus, chatgpt-5.4, gemini-3.1-pro
- If "custom" → parse model lists for generators and/or judges
- If judge pool specified → override `default_judge_pool` in gib-config.json for this run
- If reasoning effort specified → pass overrides to `llm_runner.py` calls
- If context window specified → apply as runtime override; if "auto", scale based on literature corpus size
- If user presses Enter or says "defaults" → use existing gib-config.json and model-settings.json

---

## Architecture

7-stage pipeline:
- **Stage A**: Build concept graph from literature corpus; identify structural holes
- **Stage B**: Multi-channel idea generation (graph-explorer, analogy-transfer, exploit-refiner, constraint-injection)
- **Stage C**: Mechanical screening gates (data, complexity, identifiability, novelty, ethics)
- **Stage D**: Swiss-system pairwise tournament with Bradley-Terry aggregation
- **Stage E**: Finalist verification (pairwise fatal-flaw audit + novelty audit + evidence scoring)
- **Stage F**: Portfolio optimization (greedy forward selection with taxonomy quotas)
- **Stage G**: Feedback loop (Thompson Sampling channel weights from failure ledger)

## Invocation

```
/geps full              # Run complete pipeline
/geps generate          # Stage B only
/geps screen            # Stage C only
/geps calibrate         # Run judge calibration (required before first tournament)
/geps tournament        # Stage D only
/geps verify            # Stage E only
/geps portfolio         # Stage F only
/geps feedback          # Stage G only
```

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| LLM runner | Reuse debate skill's `llm_runner.py` | No duplication; standalone CLI tool |
| Embeddings | TF-IDF + Jaccard (stdlib) | No pip deps |
| BT estimation | MAP via MM algorithm; rho_j fixed from calibration | Scale identifiability |
| Tournament | FIDE Swiss + adaptive judging | Budget-safe; deterministic with --seed |
| Portfolio | Greedy forward selection | Pure Python; no submodularity guarantee |
| Concept graph | Literature corpus as primary source | Avoids amplifying existing idea bias |
| Judge diversity | No same-provider duplicates per match | Decorrelation is paramount |

## Dependencies

- Python 3.10+ (stdlib only — no pip packages)
- `~/.claude/skills/convolutional-debate-agent/scripts/llm_runner.py` for LLM calls
- `~/.claude/skills/convolutional-debate-agent/settings/model-settings.json` for model routing

## Scripts (14 total)

### Wave 1 — Foundational
| Script | Purpose |
|--------|---------|
| `concept_graph.py` | Literature-driven concept graph + structural holes |
| `style_normalizer.py` | Strip persuasion + standardize template |
| `mechanical_gates.py` | 5 hard gates (no LLM) |
| `taxonomy_labeler.py` | Rule-based multi-label taxonomy |
| `literature_retrieval.py` | 3-mode retrieval with caching |

### Wave 2 — Evaluation Core
| Script | Purpose |
|--------|---------|
| `swiss_tournament.py` | Adaptive judging + field reduction |
| `judge_pairwise.py` | Strict JSON parse, fail-loud |
| `bradley_terry.py` | Fixed rho_j, sum-zero theta, L2-reg pi |
| `calibration.py` | Judge accuracy + bias estimation |
| `run_calibration_judging.py` | Calibration orchestrator |

### Wave 3 — Aggregation & Feedback
| Script | Purpose |
|--------|---------|
| `portfolio_optimizer.py` | Greedy selection + taxonomy quotas |
| `failure_ledger.py` | Bernoulli Thompson Sampling |
| `rwea_v2.py` | Combined RWEA2 scoring formula |
| `verify_finalists.py` | Round-robin pairwise + novelty + evidence |

## File Layout

```
~/.claude/skills/geps-v5/
├── SKILL.md
├── errors.md
├── settings/
│   ├── geps-config.json
│   ├── taxonomy.json
│   ├── calibration-pack.json
│   ├── literature_sources.json
│   └── judging_schedule.json
├── scripts/          (14 Python scripts)
├── prompts/          (9 prompt templates)
└── references/       (architecture docs)
```
