# Provider Setup Guide

Authentication and setup instructions for each LLM provider supported by `/llm`.

## CLI Providers (Zero Cost — Subscription-Based)

### Claude CLI (Anthropic)

**Models**: opus, sonnet, haiku
**Install**: `npm install -g @anthropic-ai/claude-code`
**Auth**: `claude login` (opens browser for Anthropic account)
**Verify**: `claude -p "Hello" --model sonnet --no-session-persistence`
**No API key needed** — uses your Claude subscription.

### Codex CLI (OpenAI)

**Models**: gpt-5.3-codex, gpt-5.2
**Install**: `npm install -g @openai/codex`
**Auth**: `codex login` (uses ChatGPT account)
**Verify**: `codex exec -m gpt-5.2 --full-auto --skip-git-repo-check <<< "Say hello"`
**No API key needed** — uses your ChatGPT Plus/Pro subscription.

### Kimi CLI (Moonshot)

**Models**: kimi-2.5
**Install**: `npm install -g kimi-cli`
**Auth**: `kimi login` (opens browser for Kimi account)
**Verify**: `kimi --quiet -m kimi-code/kimi-for-coding -p "Hello"`
**No API key needed** — uses your Kimi subscription.

## API Providers

### Google Generative AI API

**Models**: gemini-3-pro, gemini-3-flash
**Env var**: `GOOGLE_API_KEY`
**Get key**: https://aistudio.google.com/apikey
**Features**: thinkingLevel (HIGH/MEDIUM/LOW), Google Search grounding
**Quirks**:
- Gemini 3 models are optimized for temperature=1.0; lower values degrade reasoning
- Thinking is enabled via `thinkingConfig.thinkingLevel`, NOT via the reasoning param
- Grounding adds Google Search citations but increases latency
- Free tier: 1,000 req/min for Flash, 60 req/min for Pro

### OpenRouter

**Models**: glm-5, minimax-m2.5, + 300+ others
**Env var**: `OPENROUTER_API_KEY`
**Get key**: https://openrouter.ai/keys
**Features**: OpenAI-compatible API, reasoning param for thinking models
**Quirks**:
- No auth needed for model listing (`GET /api/v1/models`)
- `reasoning` param maps to provider-native thinking: `{"effort": "high"}` for GPT/Gemini, `{"max_tokens": 16000}` for Claude
- Some models have per-token costs; check pricing at https://openrouter.ai/models

### Anthropic API (Direct)

**Models**: All Claude models
**Env var**: `ANTHROPIC_API_KEY`
**Get key**: https://console.anthropic.com/settings/keys
**Quirks**:
- Uses Messages API v1 (not Completions)
- Requires `anthropic-version: 2023-06-01` header
- Generally prefer Claude CLI over direct API (CLI is subscription-based, API is per-token)

### Moonshot API (Direct)

**Models**: kimi-2.5, moonshot-v1-*
**Env var**: `MOONSHOT_API_KEY`
**Get key**: https://platform.moonshot.cn/console/api-keys
**Quirks**:
- OpenAI-compatible API
- Generally prefer Kimi CLI over direct API (CLI is subscription-based)

### Artificial Analysis

**Data**: Intelligence Index, speed metrics (TPS/TTFT), evaluation scores
**Env var**: `ARTIFICIAL_ANALYSIS_API_KEY`
**Get key**: https://artificialanalysis.ai/api-access-preview (create account)
**Rate limit**: 1,000 req/day free tier
**Attribution**: Required — cite Artificial Analysis when displaying their data
**Quirks**:
- Intelligence Index is a composite of 10 evaluations (0-100 scale)
- 95% confidence interval < ±1% on the index
- Speed metrics (TPS, TTFT) are measured independently, not self-reported
- Model names use display format ("Claude Opus 4.6", "GPT-5.3") — alias mapping handles this

## Credential Resolution Order

When `/llm` needs an API key, it checks in this order:

1. **Environment variable** (e.g., `GOOGLE_API_KEY` in your shell)
2. **Debate agent's provider-keys.env** at `~/.claude/skills/convolutional-debate-agent/api-keys/provider-keys.env`
3. **Error** with setup instructions pointing to this file

To add a key, either:
```bash
# Option A: Export in your shell profile
export GOOGLE_API_KEY="your-key-here"

# Option B: Add to the shared keys file
echo 'GOOGLE_API_KEY=your-key-here' >> ~/.claude/skills/convolutional-debate-agent/api-keys/provider-keys.env
```

## Verifying Setup

```bash
# Check which CLIs are available
python3 ~/.claude/skills/llm/scripts/discover_models.py

# Test each provider
python3 ~/.claude/skills/llm/scripts/llm_route.py --model opus --prompt "Say hello"         # Claude CLI
python3 ~/.claude/skills/llm/scripts/llm_route.py --model gpt-5.2 --prompt "Say hello"      # Codex CLI
python3 ~/.claude/skills/llm/scripts/llm_route.py --model gemini-3-flash --prompt "Say hello" # Google API
python3 ~/.claude/skills/llm/scripts/llm_route.py --model glm-5 --prompt "Say hello"        # OpenRouter
```
