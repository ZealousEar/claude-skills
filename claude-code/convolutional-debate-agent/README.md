# convolutional-debate-agent

Reliability-weighted multi-model debate pipeline for high-stakes or ambiguous reasoning tasks.

## Files

- `SKILL.md` — protocol definition for solver generation, debate, and aggregation.
- `scripts/llm_runner.py`, `scripts/openai_auth.py`, `scripts/rwea_score.py` — model execution, auth handling, and scoring logic.
- `settings/model-settings.json` and `settings/benchmark-profiles.json` — model roster and benchmark/evaluation profiles.
- `references/roles.md`, `references/scoring.md`, `references/rwea-input-template.json` — debate roles, scoring rules, and input schema.
- `api-keys/` — provider key examples and ignore rules for local credential setup.
- `errors.md` — known failure modes and troubleshooting notes.

## How it works

The pipeline generates independent solver drafts from different models to maximize solution diversity. Adversarial reviewers challenge those drafts across multiple debate rounds to expose weak reasoning. A reliability-weighted ensemble stage scores evidence quality and synthesizes a final answer with stronger error resistance than single-pass generation.
