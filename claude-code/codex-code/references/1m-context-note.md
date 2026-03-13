# Codex 1M Context Note

For current ChatGPT-account Codex CLI sessions, use `gpt-5.4` (not `chatgpt-5.4`).

Default Codex metadata still reports roughly `272000` context tokens for `gpt-5.4`, but the CLI/public config supports runtime overrides for larger-context experimental use.

Recommended settings in `~/.codex/config.toml`:

```toml
model = "gpt-5.4"
service_tier = "fast"
model_reasoning_effort = "xhigh"
model_context_window = 1000000
model_auto_compact_token_limit = 900000
stream_idle_timeout_ms = 300000
```

Notes:
- `model_context_window = 1000000` enables the 1M experimental override path.
- `model_auto_compact_token_limit = 900000` keeps some headroom before forced compaction.
- `stream_idle_timeout_ms = 300000` helps avoid premature timeouts on long-context turns.
- For faster but lighter runs, lower reasoning effort to `medium` or `low`.
- Accuracy may degrade substantially at very large contexts; use full 1M mainly for repo-wide analysis/completeness tasks, not precision-critical subtasks.

Verified locally on 2026-03-10.
