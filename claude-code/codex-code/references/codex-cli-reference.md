# Codex CLI Quick Reference for CodexCode

## codex exec — Non-Interactive Execution

### Complete Flag Reference

| Flag | Values | Default | Purpose |
|------|--------|---------|---------|
| `PROMPT` or `-` | string / stdin | — | Task instruction |
| `-m, --model` | model ID | config | Override model |
| `-C, --cd` | path | cwd | Set working directory |
| `-o, --output-last-message` | path | — | Write final message to file |
| `--output-schema` | path | — | JSON Schema for structured output |
| `--json` | boolean | false | Emit JSONL event stream to stdout |
| `--color` | always/never/auto | auto | ANSI color control |
| `--full-auto` | boolean | false | Low-friction automation preset |
| `--skip-git-repo-check` | boolean | false | Allow non-git directories |
| `-a, --ask-for-approval` | untrusted/on-failure/on-request/never | — | Approval timing |
| `-s, --sandbox` | read-only/workspace-write/danger-full-access | read-only | Sandbox policy |
| `--add-dir` | path | — | Grant additional directory access (repeatable) |
| `-i, --image` | path[,path...] | — | Attach images (repeatable) |
| `--search` | boolean | false | Enable live web search |
| `-c, --config` | key=value | — | Config override (repeatable) |
| `--dangerously-bypass-approvals-and-sandbox` | boolean | false | YOLO mode |
| `--oss` | boolean | false | Use local Ollama |
| `-p, --profile` | string | — | Config profile from config.toml |

### JSONL Event Types (--json)

| Event | Description |
|-------|-------------|
| `thread.started` | Session begins, contains thread ID |
| `turn.started` | New reasoning cycle begins |
| `turn.completed` | Cycle ends, contains token usage |
| `turn.failed` | Cycle failed, contains error |
| `item.started` | Individual action begins |
| `item.completed` | Action complete (agent_message, command_execution, file_change, web_search) |
| `error` | System-level error |

### Output Capture Patterns

**Structured (recommended for automation):**
```bash
codex exec --json --output-schema schema.json -o result.json - < prompt.txt > events.jsonl 2>&1
```

**Simple (fallback):**
```bash
codex exec -o result.txt - < prompt.txt > stdout.txt 2>&1
```

### Session Resume

```bash
# Resume by session ID
codex exec resume <SESSION_ID> "continue"

# Resume most recent
codex exec resume --last "continue"
```

## 1M Context Window (ChatGPT 5.4)

ChatGPT 5.4 supports 1,050,000 tokens but Codex CLI caps at ~272K by default. To enable the full 1M context:

```bash
# Enable 1M context window
-c model_context_window=1000000

# Set auto-compaction threshold (compact at 900K to preserve headroom)
-c model_auto_compact_token_limit=900000

# Extend stream idle timeout for large-context processing (5 min)
-c stream_idle_timeout_ms=300000
```

**Full command example:**
```bash
codex exec -m chatgpt-5.4 -c reasoning.effort=xhigh \
  -c model_context_window=1000000 \
  -c model_auto_compact_token_limit=900000 \
  -c stream_idle_timeout_ms=300000 \
  --full-auto --skip-git-repo-check \
  - < prompt.txt
```

**Best practices:**
- Accuracy degrades to ~36% beyond 512K tokens — stay under 272K for accuracy-critical work
- Use full 1M for: large codebase analysis, full-repo reads, completeness tasks
- The auto-compact at 900K prevents hitting the hard 1.05M limit unexpectedly
- 5-minute idle timeout prevents premature disconnects during large-context reasoning

## Network & Sandbox Config Overrides

```bash
# Enable network access
-c 'sandbox_workspace_write.network_access=true'

# Set reasoning effort (for gpt-5.2)
-c 'reasoning_effort="high"'
```

## Working Models (ChatGPT Account, verified 2026-02-08)

| Model | Status | Notes |
|-------|--------|-------|
| `chatgpt-5.4` | WORKING | Latest flagship coding model (supersedes gpt-5.3-codex) |
| `gpt-5.3-codex` | WORKING | Previous flagship agentic coding model |
| `gpt-5.2-codex` | WORKING | Advanced coding model |
| `gpt-5.2` | WORKING | General model (use -c reasoning_effort) |
| `gpt-5.1` | WORKING | Great for coding/agentic tasks |
| `gpt-5.1-codex` | WORKING | Long-running agentic coding |
| `gpt-5.1-codex-max` | WORKING | Long-horizon tasks |
| `gpt-5` | WORKING | Reasoning model |

## Prompting Best Practices (from OpenAI Guide)

1. **Autonomy-first**: "Autonomous senior engineer" framing
2. **Action bias**: Deliver working code, not plans
3. **Batch reads**: Maximize parallelism in tool calls
4. **Scope isolation**: Clear file ownership boundaries
5. **Quality standards**: No broad catches, no `as any`, no silent failures
6. **Context injection**: Inline critical code, not just paths
7. **Output spec**: Structured deliverable format

## Git Worktrees for Parallel Agents

```bash
# Create isolated worktree for agent
git worktree add -b <branch> <path> HEAD

# List worktrees
git worktree list

# Remove worktree
git worktree remove <path>

# Prune stale metadata
git worktree prune
```

Sources:
- https://developers.openai.com/codex/cli/reference/
- https://developers.openai.com/codex/noninteractive/
- https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide/
- https://developers.openai.com/codex/skills
