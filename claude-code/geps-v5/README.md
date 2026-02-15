# geps-v5

Graph-Guided Evolutionary Portfolio Search system for generating and selecting high-performing solver strategies.

## Files

- `SKILL.md` — GEPS v5 execution protocol and stage-by-stage operating guidance.
- `scripts/` — pipeline programs for concept graphing, tournament judging, scoring, calibration, and portfolio optimization.
- `settings/` — JSON configs for taxonomy, literature sources, judging schedule, calibration, and core run parameters.
- `prompts/` — role-specific prompt templates for solvers, debaters, judges, normalizers, and retrieval summarization.
- `references/` — architecture, literature, and formula notes supporting implementation choices.
- `errors.md` — documented pitfalls and recovery patterns.

## How it works

GEPS builds a concept graph from source literature, then proposes a diverse set of candidate solver strategies. Candidates compete in Swiss-style judging rounds and are ranked with Bradley-Terry style scoring and additional calibration checks. The final stage optimizes a portfolio of complementary strategies instead of selecting a single winner.
