# codex-code

Parallel Codex CLI swarm orchestration for decomposing and implementing coding tasks across multiple agents.

## Files

- `SKILL.md` — orchestrator workflow, decomposition rules, and merge strategy.
- `scripts/preflight.sh`, `scripts/worktree_manager.sh` — environment checks and per-agent git worktree setup.
- `scripts/parse_jsonl.py`, `scripts/aggregate_results.py` — parse structured agent output and combine final results.
- `settings/swarm-config.json` and `settings/agent-output-schema.json` — run configuration and required output contract.
- `references/codex-cli-reference.md` — command/reference notes for Codex CLI behavior.

## How it works

Claude first analyzes the incoming task and splits it into independent subtasks. The orchestrator creates isolated git worktrees, launches multiple Codex agents in parallel, and enforces a shared JSON schema for outputs. Results are parsed and aggregated, then the best changes are merged back into a final combined implementation.
