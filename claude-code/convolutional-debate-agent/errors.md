# Debate Agent Error Log

Persistent log of known errors, root causes, and solutions. Consult before debugging.

---

## Codex CLI — ChatGPT Model Availability (2026-02-08)

**Problem:** Many OpenAI model IDs fail with `"The '<model>' model is not supported when using Codex with a ChatGPT account."` when called via `codex exec`.

**Root cause:** Codex CLI v0.98.0 with a ChatGPT consumer account (not API key) restricts available models. Only models explicitly whitelisted for ChatGPT Codex work.

### Official ChatGPT-account models (source: developers.openai.com/codex/models/)
| Model ID | Notes |
|---|---|
| `chatgpt-5.4` | Most capable agentic coding model (recommended) |
| `gpt-5.2-codex` | Advanced coding model for real-world engineering |
| `gpt-5.1-codex-mini` | Smaller, cost-effective variant |
| `gpt-5.1-codex-max` | Optimized for long-horizon agentic tasks |
| `gpt-5.2` | General agentic model across industries |
| `gpt-5.1` | Great for coding and agentic tasks |
| `gpt-5.1-codex` | Long-running agentic coding (succeeded by Max) |
| `gpt-5-codex` | Tuned for long-running coding tasks (succeeded by 5.1) |
| `gpt-5-codex-mini` | Cost-effective variant (succeeded by 5.1 Mini) |
| `gpt-5` | Reasoning model for coding tasks |

### Verified FAILING models (ChatGPT account + Codex CLI):
| Model ID | Error |
|---|---|
| `gpt-5.2-extra-high` | Not supported with ChatGPT account |
| `gpt-5.2-high` | Not supported with ChatGPT account |
| `gpt-5.2-codex-max` | Not supported with ChatGPT account |
| `gpt-5.2-codex-mini` | Not supported with ChatGPT account |
| `gpt-5.3` (non-codex) | Not supported with ChatGPT account |
| `gpt-5.2-mini` | Not supported with ChatGPT account |
| `o3` | Not supported with ChatGPT account |
| `o4-mini` | Not supported with ChatGPT account |
| `gpt-4.1` | Not supported with ChatGPT account |

### Solution Applied (v4, 2026-02-09):
- Removed all aliases. Models now use direct IDs: `chatgpt-5.4`, `gpt-5.2`
- `gpt-5.2` uses `reasoning_effort=high` via codex CLI (`-c reasoning_effort="high"`)
- "high"/"xhigh" in the interactive Codex CLI are NOT separate models — they're the base `gpt-5.2` model with a reasoning effort parameter
- The model self-reporting "reasoning effort: low" is unreliable — the actual effort is set by the CLI, not the model
- OpenRouter fallback routes still use original model IDs for API-key access

---

## Codex CLI — Output File Sometimes Empty

**Problem:** `codex exec -o <file>` sometimes writes an empty file while stdout contains the response.

**Root cause:** Race condition or model-specific behavior — some models write to stdout directly instead of the -o file.

**Solution:** `llm_runner.py` already handles this — checks output file first, falls back to stdout. No action needed.

---

## Kimi CLI — Model ID Format

**Problem:** Kimi CLI uses format `kimi-code/kimi-for-coding`, not plain model names.

**Solution:** The `kimi-cli` route in model-settings.json correctly maps to `kimi-code/kimi-for-coding`. Verified working (2026-02-08).

---

## Gemini — Temperature Must Be 1.0

**Problem:** Gemini 3 Pro produces degraded output (looping, unexpected behavior) when temperature is set below 1.0.

**Root cause:** Google's Gemini 3 reasoning is optimized for temperature=1.0. Lowering it degrades reasoning quality.

**Solution:** `llm_runner.py` now overrides temperature to 1.0 for Google provider models. The `call_google()` function applies this automatically.

---

## Aristotle — Slow Proofs

**Problem:** Aristotle proofs can take 1-15 minutes, blocking the pipeline.

**Solution:** Step 3.5 runs Aristotle in background (`run_in_background: true`). Claims still running at RWEA time are marked INCONCLUSIVE. This is by design, not an error.

---

## General — Solver JSON Parsing Failures

**Problem:** External models sometimes return malformed JSON (missing code fences, extra text before/after JSON block).

**Solution:** When parsing solver outputs, strip everything before the first `{` and after the last `}`. If JSON still fails, try extracting content between ``` markers first.

---

## Codex CLI — Timeout Cascade in Parallel Batch (2026-02-25)

**Problem:** During a `/debate` run with 30k token budget, Codex CLI timed out at 300s. Claude Code's parallel batch semantics cancelled ALL sibling Bash calls in the same batch. The orchestrator fell back to Task tool (Claude only), so D2 (gpt-5.2) and D3 (chatgpt-5.4) both ran as Opus/Sonnet instead of their intended models — losing multi-model independence.

**Root causes:**
1. CLI timeout default (300s) too low for high token budgets (30k tokens = long generation)
2. No auto-fallback — `RuntimeError` from timeout propagated and killed the call
3. Parallel batch failure propagation — one Bash subprocess timeout cancels all siblings in Claude Code
4. No protocol guidance on error handling or batch isolation

**Solutions applied (v5):**
1. **Increased CLI timeouts:** `DEFAULT_CLI_TIMEOUT = 600` in both `llm_runner.py` and `llm_route.py`. All CLI calls (codex, kimi, claude-cli) now default to 600s instead of 300s.
2. **Auto CLI→API fallback:** When a CLI call fails (timeout, crash, non-zero exit), the runner automatically retries via the model's API fallback route (typically OpenRouter). Does NOT fallback for "not found on PATH" (setup issue). Prints `WARNING: <cli> failed (<error>), falling back to <provider>` to stderr.
3. **Batch isolation in protocol:** `debate.md` Steps 3 and 4 now mandate each external-model Bash call as a **separate Bash invocation** (separate tool call). This prevents cascade cancellation.
4. **Fallback detection:** Step 5 now checks stderr for fallback warnings and notes them in the debate summary.

**Key detail:** The auto-fallback preserves the model family (e.g., chatgpt-5.4 via codex → openai/gpt-5.3 via OpenRouter). The underlying model is the same, just accessed via API instead of CLI.

---

## Codex CLI — Network Errors on Model List Refresh

**Problem:** `ERROR codex_core::models_manager::manager: failed to refresh available models: stream disconnected` appears at startup.

**Root cause:** Transient network issue when Codex tries to fetch the model list from `chatgpt.com/backend-api/codex/models`.

**Solution:** This is non-blocking — Codex still uses its cached model list. The exec command works despite this error. Ignore unless it persists across multiple runs.
