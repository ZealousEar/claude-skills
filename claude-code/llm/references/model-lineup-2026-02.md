# Frontier Model Lineup — February 25, 2026

Reference for benchmark aggregation: which model names are the SAME model vs DIFFERENT models.

## Key Rules

1. **Version bumps are ALWAYS different models** — Opus 4, 4.1, 4.5, 4.6 are four separate models with separate weights
2. **"Thinking" suffix on Arena = same model, different config** — "Claude Opus 4.6 Thinking" is `claude-opus-4-6` with extended thinking enabled
3. **Date suffixes on Arena = snapshots** — "gpt-5.2-chat-latest-20260210" is a dated snapshot
4. **Codex variants are DIFFERENT models** — GPT-5.3-Codex is NOT GPT-5.2 with a different name
5. **"-preview" on Gemini = canonical version** until GA drops the suffix

## Anthropic Claude

| Model | API ID | Released | Status |
|---|---|---|---|
| Opus 4 | `claude-opus-4-20250514` | May 2025 | Superseded |
| Sonnet 4 | `claude-sonnet-4-20250514` | May 2025 | Superseded |
| Opus 4.1 | `claude-opus-4-1-20250805` | Aug 2025 | Superseded |
| Sonnet 4.5 | `claude-sonnet-4-5-20250929` | Sep 2025 | Superseded by 4.6 |
| Haiku 4.5 | `claude-haiku-4-5-20251001` | Oct 2025 | **Current** (smallest) |
| Opus 4.5 | `claude-opus-4-5-*` | Nov 2025 | Superseded |
| **Opus 4.6** | `claude-opus-4-6` | Feb 5, 2026 | **Current flagship** |
| **Sonnet 4.6** | `claude-sonnet-4-6` | Feb 17, 2026 | **Current** (balanced) |

Skipped versions: 4.2, 4.3, 4.4 never existed.
Retired: Sonnet 3.7, Haiku 3.5 — API returns errors.

### Arena naming for Claude
- "Claude Opus 4 (thinking-16k)" → Opus 4.0, NOT 4.6
- "Claude Opus 4 (20250514)" → Opus 4.0
- "Claude Opus 4.6" → Opus 4.6 (our tier 1 "opus")
- "Claude Opus 4.6 Thinking" → Opus 4.6 with extended thinking (same model)

## OpenAI GPT

| Model | API ID | Released | Status |
|---|---|---|---|
| GPT-5 | `gpt-5` | Aug 7, 2025 | Available |
| GPT-5.1 | `gpt-5.1` | Nov 2025 | Available |
| GPT-5.2 | `gpt-5.2` | Dec 11, 2025 | **Current flagship** (general) |
| GPT-5.2-Codex | Codex CLI | Jan 14, 2026 | Available (coding) |
| GPT-5.3-Codex | Codex CLI only | Feb 5, 2026 | Superseded by ChatGPT 5.4 |
| **ChatGPT 5.4** | Codex CLI only | Mar 2026 | **Current flagship** (coding) |

No standalone "GPT-5.3" exists — only GPT-5.3-Codex.
ChatGPT 5.4 replaces GPT-5.3-Codex as the primary coding model.

### Arena naming for GPT
- "gpt-5.2-chat-latest-20260210" → GPT-5.2 dated snapshot
- "o3-2025-04-16" → OpenAI o3 (reasoning model, separate from GPT line)

## Google Gemini

| Model | API ID | Released | Status |
|---|---|---|---|
| Gemini 2.5 Pro | `gemini-2.5-pro` | ~May 2025 | Deprecation path |
| Gemini 2.5 Flash | `gemini-2.5-flash` | ~2025 | Deprecation path |
| **Gemini 3 Pro** | `gemini-3.1-pro-preview` | Nov 18, 2025 | **Current** (reasoning) |
| **Gemini 3 Flash** | `gemini-3-flash-preview` | Jan 7, 2026 | **Current** (fast) |
| **Gemini 3.1 Pro** | `gemini-3.1-pro-preview` | Feb 19, 2026 | **Latest** (77.1% ARC-AGI-2) |

All Gemini 3 models still in "preview" status.

## xAI Grok

| Model | Released | Status |
|---|---|---|
| Grok 4 | Jul 9, 2025 | Superseded |
| Grok 4.1 | Late 2025 | **Current** (API available) |
| Grok 4.20 (Beta) | Mid-Feb 2026 | Preview only (API expected Mar 2026) |

Grok 4.20 is a fundamentally different multi-agent architecture, not a minor bump.

## DeepSeek

| Model | Released | Status |
|---|---|---|
| DeepSeek-V3 | Dec 2024 | Superseded |
| DeepSeek-R1 | Jan 2025 | Superseded by R1-0528 |
| DeepSeek-R1-0528 | May 28, 2025 | Available |
| DeepSeek-V3.1-Terminus | Sep 22, 2025 | Superseded |
| **DeepSeek-V3.2** | Sep 29, 2025 | **Current** |

R2 and V4 have NOT been released as of Feb 25, 2026.

## Other Frontier

| Model | Provider | Released | Status |
|---|---|---|---|
| Qwen3 (family) | Alibaba | Apr 2025 | Superseded |
| **Qwen3.5** (397B MoE) | Alibaba | Feb 16, 2026 | **Current** |
| Llama 4 Scout | Meta | Apr 5, 2025 | Available (10M context) |
| Llama 4 Maverick | Meta | Apr 5, 2025 | Available (1M context) |
| **Kimi K2.5** | Moonshot | Jan 27, 2026 | **Current** (1T params, 256K ctx) |
| **GLM-5** | Zhipu AI | Feb 11, 2026 | **Current** (MIT license) |
| **MiniMax M2.5** | MiniMax | Feb 11, 2026 | **Current** (80.2% SWE-bench) |

## Tier 1 Registry Mapping

Our tier 1 models and what they map to:

| Registry name | Actual model | Arena name (expected) | Epoch name | OpenRouter ID |
|---|---|---|---|---|
| opus | Claude Opus 4.6 | "Claude Opus 4.6" | claude-opus-4-6 | anthropic/claude-opus-4.6 |
| chatgpt-5.4 | ChatGPT 5.4 | N/A (Codex CLI only) | chatgpt-5.4 | openai/chatgpt-5.4 |
| gpt-5.3-codex | GPT-5.3-Codex | N/A (Codex CLI only) | gpt-5.3-codex | openai/gpt-5.3-codex |
| gpt-5.2 | GPT-5.2 | "gpt-5.2-chat-latest" | gpt-5.2-2025-12-11 | openai/gpt-5.2 |
| gemini-3.1-pro | Gemini 3 Pro | "Gemini 3 Pro" | gemini-3.1-pro-preview | google/gemini-3.1-pro-preview |
| gemini-3-flash | Gemini 3 Flash | "Gemini 3 Flash" | gemini-3-flash-preview | google/gemini-3-flash-preview |
| kimi-2.5 | Kimi K2.5 | N/A | kimi-k2.5 | moonshotai/kimi-k2.5 |
| glm-5 | GLM-5 | N/A | glm-5 | z-ai/glm-5 |
| minimax-m2.5 | MiniMax M2.5 | N/A | minimax-m2.5 | minimax/minimax-m2.5 |
