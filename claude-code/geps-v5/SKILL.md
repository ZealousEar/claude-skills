# GEPS v5 — Graph-Guided Evolutionary Portfolio Search

A multi-stage research idea generation and evaluation pipeline that replaces debate-as-core with **search + ranking + calibration**.

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
