# /CodexCode — Claude-Orchestrated Parallel Codex Coding Swarm

## Architecture

Claude acts as the **intelligent orchestrator** — analyzing the codebase, decomposing tasks, crafting optimal prompts, and managing N parallel Codex CLI agents that do the heavy coding work.

```
                    ┌─────────────┐
                    │   CLAUDE    │
                    │ Orchestrator│
                    └──────┬──────┘
                           │ decomposes, allocates, monitors
              ┌────────────┼────────────┐────────── ... ──┐
              ▼            ▼            ▼                  ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐     ┌──────────┐
        │ Codex #1 │ │ Codex #2 │ │ Codex #3 │     │ Codex #N │
        │5.3-codex │ │5.3-codex │ │5.3-codex │     │5.3-codex │
        │ worktree │ │ worktree │ │ worktree │     │ worktree │
        └──────────┘ └──────────┘ └──────────┘     └──────────┘
           coding       coding       coding           coding
```

- **Claude decides**: how many agents, what each does, file ownership, dependency ordering
- **Codex agents execute**: autonomous coding via `codex exec` CLI, each in an isolated git worktree
- **Claude synthesizes**: collects structured results, merges worktrees, resolves conflicts, verifies

## Agent Limits

- **Minimum**: N=1 (single focused agent)
- **Maximum**: N=50 (resource-dependent; Claude decides optimal N)
- **Claude chooses N** based on task complexity — the user may suggest but Claude makes the final allocation decision

---

## Skill Directory Structure

```
~/.claude/skills/codex-code/
├── SKILL.md                              # This file — full skill reference
├── settings/
│   ├── swarm-config.json                 # Tunable orchestration parameters
│   └── agent-output-schema.json          # JSON Schema for structured agent output
├── scripts/
│   ├── preflight.sh                      # Pre-launch auth & environment checks
│   ├── parse_jsonl.py                    # JSONL event stream parser
│   ├── aggregate_results.py              # Multi-agent result aggregator
│   └── worktree_manager.sh              # Git worktree create/merge/cleanup
└── references/
    └── codex-cli-reference.md           # Complete Codex CLI flag reference
```

---

## Codex CLI Invocation Reference

### Base Command (v2 — with JSONL + Schema + Worktrees)

```bash
codex exec \
  -m gpt-5.3-codex \
  -c reasoning.effort=xhigh \
  --full-auto \
  --skip-git-repo-check \
  --json \
  -C "<worktree_dir>" \
  --output-schema ~/.claude/skills/codex-code/settings/agent-output-schema.json \
  -o /tmp/codex_swarm_<sid>_<i>_result.txt \
  - < /tmp/codex_swarm_<sid>_<i>_prompt.txt \
  > /tmp/codex_swarm_<sid>_<i>_events.jsonl 2>&1
```

### Flag Reference

| Flag | Value | Purpose |
|------|-------|---------|
| `-m` | `gpt-5.3-codex` | Model — ALWAYS this, no exceptions |
| `-c` | `reasoning.effort=xhigh` | Maximum reasoning depth for highest code quality |
| `--full-auto` | — | Non-interactive autonomous execution |
| `--skip-git-repo-check` | — | Allow operation in any directory |
| `--json` | — | **[GAP 1]** Emit structured JSONL events for real-time parsing |
| `-C` | `<path>` | Set working directory (worktree path for isolated agents) |
| `--output-schema` | `<path>` | **[GAP 2]** Force structured JSON output conforming to schema |
| `-o` | `<path>` | Write final assistant message to file |
| `-` | (stdin) | Read prompt from stdin |
| `-c` | `key=value` | Config overrides (e.g., sandbox, network) |
| `--add-dir` | `<path>` | **[GAP 7]** Grant access to additional directories (repeatable) |
| `-i, --image` | `<path>` | **[GAP 8]** Attach images/screenshots/mockups |

### Network Access (when needed)

If an agent needs network (e.g., installing packages, fetching APIs):
```bash
-c 'sandbox_workspace_write.network_access=true'
```

### Output Capture Strategy (v2)

Three output channels, in priority order:
1. **`-o <result_file>`** — Structured JSON from `--output-schema` (deterministic, parseable)
2. **`> <events_file>`** — JSONL event stream from `--json` (session IDs, tokens, errors, timeline)
3. **Fallback** — If result file is empty, extract final `agent_message` from JSONL events via `parse_jsonl.py`

---

## Git Worktree Isolation [GAP 3]

**Why:** Multiple agents writing to the same directory causes race conditions and conflicts, even with file-ownership assignment. Git worktrees provide OS-level isolation — each agent gets its own full copy of the repo on a temporary branch.

### How It Works

1. **Before launch:** Create N worktrees via `worktree_manager.sh create <sid> <N>`
   - Each agent gets: `/tmp/codex_worktrees/<sid>/agent_<i>/`
   - Each on branch: `codex-swarm-<sid>-agent-<i>`

2. **During execution:** Each agent's `-C` flag points to its worktree, not the main repo

3. **After completion:** Merge each agent's changes back via `worktree_manager.sh merge <sid> <i>`
   - `diff-apply` strategy: Generate patch, apply to main branch (default)
   - `cherry-pick` strategy: Commit in worktree, cherry-pick to main

4. **Cleanup:** `worktree_manager.sh cleanup <sid>` removes all worktrees and temp branches

### When to Skip Worktrees

- **Strategy C (Swarm Review)**: Agents only read, no writes — worktrees unnecessary
- **Non-git directories**: Fall back to direct execution with file-ownership rules
- **User opts out**: If user explicitly asks for direct execution

---

## Pre-Flight Checks [GAP 6]

Before launching ANY agents, run:

```bash
bash ~/.claude/skills/codex-code/scripts/preflight.sh --check-git --verbose
```

This verifies:
1. **Codex CLI installed** and in PATH
2. **Authentication valid** (not expired/missing)
3. **Model available** (`gpt-5.3-codex`)
4. **Git repo status** (for worktree support)
5. **Temp directory writable** with sufficient space

If any check fails, the script exits with a diagnostic message. Claude should fix the issue (guide user through `codex login`, etc.) before proceeding.

---

## JSONL Event Streaming [GAP 1]

The `--json` flag makes Codex emit structured JSONL events to stdout:

```
{"type":"thread.started","thread":{"id":"sess_abc123"}}
{"type":"turn.started"}
{"type":"item.completed","item":{"type":"file_change","path":"src/api.ts","action":"create"}}
{"type":"item.completed","item":{"type":"command_execution","command":"npm test","exit_code":0}}
{"type":"item.completed","item":{"type":"agent_message","text":"Done. Created 3 files..."}}
{"type":"turn.completed","usage":{"input_tokens":24763,"output_tokens":1220}}
```

### Parsing

Use the provided parser script:

```bash
# Full structured report
python3 ~/.claude/skills/codex-code/scripts/parse_jsonl.py --input events.jsonl --pretty

# Just the session ID (for resume)
python3 ~/.claude/skills/codex-code/scripts/parse_jsonl.py --input events.jsonl --session-id

# Just the status
python3 ~/.claude/skills/codex-code/scripts/parse_jsonl.py --input events.jsonl --status

# Human-readable summary
python3 ~/.claude/skills/codex-code/scripts/parse_jsonl.py --input events.jsonl --summary
```

### Benefits over raw stdout

| Aspect | Raw stdout | JSONL events |
|--------|-----------|--------------|
| Status detection | Guess from text | `turn.completed` / `turn.failed` |
| Error extraction | Parse stderr | `error` events with messages |
| Token usage | Not available | `turn.completed.usage` |
| Session ID (for resume) | Not available | `thread.started.thread.id` |
| File changes | Parse text | `item.completed` with `file_change` type |

---

## Structured Output Schema [GAP 2]

The `--output-schema` flag forces agents to return JSON conforming to `settings/agent-output-schema.json`:

```json
{
  "agent_id": 1,
  "status": "success",
  "files_created": ["src/api/auth.ts", "src/api/auth.test.ts"],
  "files_modified": ["src/index.ts"],
  "summary": "Built JWT authentication module with login, logout, and refresh endpoints...",
  "assumptions": ["Using HS256 algorithm for JWT signing"],
  "limitations": ["No rate limiting on login endpoint yet"],
  "tests_run": true,
  "tests_passed": true
}
```

### Benefits over free-text summary

- **Deterministic parsing**: `json.loads()` instead of regex
- **Reliable file tracking**: Exact list of created/modified files
- **Aggregation**: `aggregate_results.py` can merge N agent reports mechanically
- **Validation**: Schema violations caught by Codex before returning

---

## Session Resume [GAP 9]

If an agent times out or partially completes, its session ID is captured from JSONL events. Claude can resume instead of relaunching from scratch:

```bash
# Extract session ID from JSONL
SESSION_ID=$(python3 ~/.claude/skills/codex-code/scripts/parse_jsonl.py \
  --input /tmp/codex_swarm_<sid>_<i>_events.jsonl --session-id)

# Resume the session
codex exec resume "$SESSION_ID" "Continue and finish the task" \
  -m gpt-5.3-codex --full-auto --json \
  -o /tmp/codex_swarm_<sid>_<i>_result.txt \
  > /tmp/codex_swarm_<sid>_<i>_events_resumed.jsonl 2>&1
```

### When to Resume vs. Relaunch

| Situation | Action |
|-----------|--------|
| Agent timed out at 80%+ | **Resume** — let it finish |
| Agent timed out at <30% | **Relaunch** with narrower scope |
| Agent errored mid-execution | **Diagnose** error, then resume or relaunch |
| Agent produced wrong output | **Relaunch** with corrected prompt |

---

## Image/Screenshot Input [GAP 8]

For UI/design tasks, attach mockups or screenshots to agent prompts:

```bash
codex exec -m gpt-5.3-codex --full-auto \
  -i /path/to/mockup.png \
  -i /path/to/screenshot.jpg \
  - < prompt.txt > events.jsonl 2>&1
```

### When to Use

- User provides UI mockups or wireframes
- Task involves matching an existing design
- Debugging visual issues (attach screenshot of the bug)
- Implementing from a Figma export

Claude should check if the user's request involves visual assets and proactively attach them.

---

## Cross-Directory Access [GAP 7]

When agents need files outside their working directory (monorepo shared libs, config dirs):

```bash
codex exec -m gpt-5.3-codex --full-auto \
  --add-dir /path/to/shared/libs \
  --add-dir /path/to/common/types \
  -C /path/to/agent/worktree \
  - < prompt.txt
```

### When to Use

- Monorepo with shared packages
- Agent needs to read types/interfaces from another package
- Cross-project dependencies
- Shared configuration files

**Prefer `--add-dir` over `--sandbox danger-full-access`** — it grants targeted access while maintaining sandbox safety.

---

## Configuration [GAP 4]

All tunable parameters are in `settings/swarm-config.json`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `model` | `gpt-5.3-codex` | Primary model |
| `model_fallback` | `gpt-5.2-codex` | Fallback if primary unavailable |
| `limits.max_agents` | 50 | Maximum agents per session |
| `limits.wave_size` | 10 | Agents per parallel wave |
| `limits.wave_completion_threshold` | 0.5 | % of wave done before next wave |
| `limits.default_timeout_ms` | 600000 | 10 minute default timeout |
| `limits.extended_timeout_ms` | 900000 | 15 minute extended timeout |
| `limits.max_retries_per_agent` | 2 | Max retries for failed agents |
| `sandbox.default_policy` | `workspace-write` | Default sandbox level |
| `sandbox.network_access` | false | Default network access |
| `sandbox.use_worktrees` | true | Enable git worktree isolation |
| `output.use_json_events` | true | Enable JSONL event streaming |
| `output.use_output_schema` | true | Enable structured output schema |
| `preflight.check_auth` | true | Check auth before launch |
| `session.enable_resume` | true | Enable session resume on timeout |

---

## Codex Prompting Best Practices (Research-Backed)

These rules are derived from the official OpenAI Codex Prompting Guide and must be followed when crafting agent prompts.

### 1. Autonomy-First Framing
Each agent prompt must establish the agent as an autonomous senior engineer:
> "You are an autonomous senior engineer. Gather context, plan, implement, test, and refine without waiting for additional prompts. Persist until the task is fully handled end-to-end. Deliver working code, not just a plan."

### 2. Scope Isolation
Each agent must have crystal-clear boundaries:
- Exactly which files it owns (may create/modify)
- Which files are READ-ONLY context
- What it must NOT touch
- Expected deliverables

### 3. Action Bias Over Analysis
Prompts must discourage analysis-only responses:
> "Default to implementation with reasonable assumptions. Do NOT end with clarifying questions — make your best judgment and deliver working code."

### 4. Parallelization Within Agents
Tell agents to batch their own reads:
> "Maximize parallelism in your tool calls. Read all needed files in a single batch, not one by one."

### 5. Code Quality Standards
Embed quality requirements:
> "Write production-quality code. No broad try/catch blocks, no `as any` casts, no silent error swallowing. Reuse existing helpers. Cover all relevant surfaces for consistency."

### 6. Context Injection
For each agent, Claude should:
- Read the relevant source files BEFORE crafting the prompt
- Inline critical file contents directly into the prompt (not just paths)
- Include dependency information (package.json, imports, types)
- Provide architectural context (how this piece fits the whole)

### 7. Output Specification
Each prompt must tell the agent to conform to the output schema:
> "When finished, your final message MUST be valid JSON conforming to the output schema. Include: agent_id, status, files_created, files_modified, summary, assumptions, and limitations."

---

## Orchestration Strategies

Claude should select the appropriate strategy based on task type:

### Strategy A: Parallel Independent (most common)
N agents work on completely independent subtasks.
- Each agent in its own worktree
- No file overlap, no dependencies
- All launch simultaneously
- Merge all worktrees after completion

### Strategy B: Parallel + Sequential Phases
Some tasks have phases where later agents depend on earlier ones.
- Phase 1: Launch independent agents in worktrees
- Wait for Phase 1 completion, merge results
- Phase 2: Launch dependent agents with merged codebase
- Example: 3 agents build microservices → 1 agent writes integration tests

### Strategy C: Swarm Review
Multiple agents review/analyze the same codebase from different angles.
- All agents read the same files (read-only)
- **No worktrees needed** — agents don't modify files
- Each produces analysis via structured output schema
- Claude synthesizes into unified report

### Strategy D: Competitive (best-of-N)
Multiple agents solve the same problem independently.
- Each agent in its own worktree
- Claude compares structured outputs and picks the best
- Only the winning worktree gets merged

### Strategy E: Assembly Line
Agents work on sequential pipeline stages in parallel batches.
- Batch 1: Foundation agents in worktrees (types, schemas, configs)
- Merge Batch 1, create new worktrees from merged state
- Batch 2: Core logic agents
- Merge, repeat for Batch 3, 4...

---

## File Ownership Rules

Even with worktree isolation, clear ownership prevents logical conflicts:

1. **Before launching**, Claude maps out which files each agent will create/modify
2. **Worktrees provide OS isolation**, but ownership prevents semantic conflicts (two agents building incompatible interfaces)
3. **New files** are fine — each agent can create its own new files freely
4. **Shared reads** are fine — worktrees start as copies of the same repo

---

## Error Recovery

Claude handles errors intelligently, not mechanically:

| Situation | Claude's Response |
|-----------|-------------------|
| Agent times out | Parse JSONL for progress; **resume session** if >50% done, relaunch with narrower scope if <30% |
| Agent produces empty output | Check JSONL events for `turn.failed`; diagnose (auth? model? sandbox?); retry |
| Agent writes broken code | Read structured output; identify the bug; launch fix-up agent in same worktree |
| File conflict on merge | Present both patches, ask user to choose, or synthesize |
| N agents > system resources | Batch in waves per `swarm-config.json` settings |
| `codex: command not found` | Tell user to install: `npm install -g @openai/codex` |
| Auth failure | Detected by `preflight.sh`; guide user through `codex login` |
| Schema validation failure | Agent didn't conform to output schema; fall back to JSONL parsing |

---

## Result Aggregation

After all agents complete, use the aggregator script:

```bash
# Full JSON report
python3 ~/.claude/skills/codex-code/scripts/aggregate_results.py \
  --session <sid> --agents <N> --pretty

# Markdown report for display
python3 ~/.claude/skills/codex-code/scripts/aggregate_results.py \
  --session <sid> --agents <N> --markdown

# One-line summary
python3 ~/.claude/skills/codex-code/scripts/aggregate_results.py \
  --session <sid> --agents <N> --summary
```

---

## Integration with Claude's Native Tools

Claude uses its FULL toolset alongside the Codex swarm:

| Claude Tool | Usage in CodexCode |
|-------------|-------------------|
| **Read/Glob/Grep** | Pre-launch codebase analysis to inform task decomposition |
| **Bash (background)** | Launch and monitor Codex agents |
| **Bash (scripts)** | Run preflight, parse_jsonl, aggregate_results, worktree_manager |
| **TaskOutput** | Wait for agent completion |
| **Read** | Collect structured agent outputs |
| **Edit/Write** | Post-merge integration, conflict resolution, glue code |
| **Bash (git)** | Worktree management, `git diff`, `git status` |
| **AskUserQuestion** | Clarify task scope, confirm risky allocations |
| **TaskCreate/TaskUpdate** | Track multi-phase orchestrations |

---

## Batching Large Swarms

For N > 10 agents, launch in waves to avoid resource exhaustion:

- **Wave size**: From `swarm-config.json` (default: 10)
- **Wave gap**: Wait for >= threshold % of wave to complete before launching next
- **Priority ordering**: Launch most critical / least dependent agents first
- Claude tracks which wave each agent belongs to

---

## Post-Execution Integration

After all agents complete, Claude:

1. **Parses JSONL events** for each agent via `parse_jsonl.py`
2. **Reads structured results** from output schema JSON files
3. **Aggregates** via `aggregate_results.py --markdown`
4. **Merges worktrees** back to main branch via `worktree_manager.sh merge`
5. **Checks for merge conflicts** — presents both versions if conflicts arise
6. **Runs integration checks** — imports resolve, types match, no circular deps
7. **Writes glue code** if needed — wiring independently-built components
8. **Reports results** in the structured execution report
9. **Cleans up** worktrees and temp files
10. **Offers next steps** — run tests, review specific files, launch follow-up agents
