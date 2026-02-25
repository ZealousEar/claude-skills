# Model Prompting Guide

Per-model optimal prompting reference for all LLM models used by the Convolutional Debate Agent.
Machine-readable config: `settings/model-prompting.json`. Auto-applied by `llm_runner.py`.

---

## Claude (Opus 4.6, Sonnet 4.5, Haiku 4.5)

**Sources:**
- https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/overview
- https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-4-best-practices
- https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/use-xml-tags
- https://platform.claude.com/docs/en/build-with-claude/extended-thinking

### Key Findings

- **XML tags strongly recommended** for structuring complex prompts (`<context>`, `<task>`, `<constraints>`). No canonical tag names — use descriptive, consistent names.
- **Conversational system prompts outperform aggressive ones.** Claude 4.6 overtriggers on "CRITICAL: MUST" language. Use "Use this tool when..." not "CRITICAL: You MUST use this tool when..."
- **Explain WHY, not just WHAT.** Provide motivation for constraints rather than demanding compliance.
- **Tell Claude what TO DO, not what NOT to do.** Positive instructions are more effective.
- **Opus 4.6 uses adaptive thinking** (`thinking: {type: "adaptive"}`). No prompt-level CoT needed — the model decides when and how much to think based on query complexity and the `effort` parameter.
- **Thinking sensitivity:** When thinking is disabled, Claude 4.5 is sensitive to the word "think" — use "consider", "evaluate", "believe" instead.
- **Prefilled responses deprecated** on Opus 4.6. Use structured outputs or direct instructions instead.

### Temperature
- Default: 1.0
- Analytical tasks: closer to 0.0
- Creative tasks: closer to 1.0
- Config: `null` (use caller's default — no override needed)

### Format
- **XML-tagged sections + plain prose**
- Use XML for multi-component prompts; plain prose for simple queries
- Match prompt style to desired output style

### Do's
- Use XML tags for structured, multi-part prompts
- Provide context and explain motivation for constraints
- Use examples (multishot) to demonstrate patterns
- Be clear, explicit, and specific

### Don'ts
- Don't use aggressive "CRITICAL: MUST" language (overtriggers on 4.6)
- Don't add "think step by step" — adaptive thinking handles it
- Don't use prefilled responses (deprecated on Opus 4.6)
- Don't over-engineer prompts with unnecessary complexity

---

## GPT (5.3-Codex, 5.2)

**Sources:**
- https://cookbook.openai.com/examples/gpt-5/gpt-5-2_prompting_guide
- https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide/
- https://platform.openai.com/docs/guides/reasoning-best-practices

### Key Findings

- **GPT-5 models do not support the temperature parameter** — they are reasoning models. Temperature is handled internally.
- **Use structured XML specs** like `<instruction_spec>` to improve instruction adherence. XML tags (`<context>`, `<format>`, `<tone>`) are officially recommended.
- **CTCO framework** (Context → Task → Constraints → Output) is the most reliable pattern for preventing hallucinations and generic outputs.
- **Prompt a brief explanation summarizing thought process** at the start of the final answer — improves performance on complex tasks.
- **reasoning_effort=xhigh** handles deep reasoning; no explicit "think step by step" needed.
- **Remove upfront plan requests** from prompts — causes premature stopping on Codex models.
- **By default, GPT-5 API does not format in Markdown.** Must explicitly request markdown if desired.

### Temperature
- Not supported (reasoning model) — `null` in config
- reasoning_effort parameter controls depth instead

### Format
- **CTCO structured sections with XML tags**
- Use `<context_understanding>`, `<format>`, `<tone>` tags
- Plain text with optional headers, bullets ordered by importance

### Do's
- Use CTCO framework for structured prompts
- Use XML spec tags for complex instructions
- Request brief thought-process summaries in final answers
- Use reasoning_effort=xhigh for maximum depth
- Maximize parallel tool calls

### Don'ts
- Don't use temperature parameter (not supported)
- Don't ask for upfront plans or intermediate status (causes stopping on Codex)
- Don't use "think step by step" — reasoning_effort handles it
- Don't use broad try/catch or silent error defaults

---

## Gemini (3 Pro, 3 Flash)

**Sources:**
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/start/gemini-3-prompting-guide
- https://ai.google.dev/gemini-api/docs/prompting-strategies
- https://ai.google.dev/gemini-api/docs/gemini-3

### Key Findings

- **Be concise and direct.** Gemini 3 over-analyzes verbose prompts. Start minimal, add detail only if needed.
- **Place critical constraints LAST** — after data context. Structure: context/data → main task → negative/formatting/quantitative constraints.
- **Use XML tags OR Markdown headings consistently** — both are equally valid, but don't mix within a single prompt.
- **Keep temperature at default 1.0.** Lowering temperature "may lead to unexpected behavior, looping, or degraded performance, particularly with complex mathematical or reasoning tasks."
- **thinkingLevel=HIGH** is the default and maximizes reasoning depth. Use LOW for latency-sensitive queries.
- **Don't use broad negative constraints** like "do not infer" or "do not guess" — causes over-indexing on the constraint and failure on basic logic.
- **Show positive patterns in examples**, not anti-patterns. Examples showing what NOT to do are less effective.

### Temperature
- **Forced to 1.0** — both in Google API and OpenRouter fallback
- Lower values cause looping and degraded reasoning

### Format
- **XML-delimited sections** (preferred) or Markdown headings
- Consistent formatting within a single prompt
- Concise — no unnecessary politeness or fluff

### Do's
- Place critical restrictions at the end of the prompt
- Use personas with clear adherence rules
- Anchor reasoning with "Based on the entire document above..."
- Use few-shot examples (2-5) showing exact expected format
- Steer verbosity explicitly if conversational response needed

### Don'ts
- Don't lower temperature below 1.0
- Don't use open-ended negative constraints ("do not infer")
- Don't over-prompt — prompts safe for Gemini 2.x are overkill for 3
- Don't mix XML and Markdown in the same prompt
- Don't use unnecessary politeness ("please") — treated as fluff

---

## Kimi (2.5)

**Sources:**
- https://huggingface.co/moonshotai/Kimi-K2.5
- https://platform.moonshot.ai/docs/guide/use-kimi-k2-thinking-model
- https://github.com/MoonshotAI/Kimi-K2.5

### Key Findings

- **Temperature: 1.0 for Thinking mode, 0.6 for Instant mode.** top_p: 0.95.
- **Interleaved thinking enabled by default** — model thinks between tool calls and after receiving results.
- **Default system prompt removed** (as of 2026.1.29 changelog) — was causing confusion and unexpected behavior. Provide your own if needed.
- **Standard system instructions work fine** — no special formatting framework required.
- **Thinking mode** accessed via `reasoning_content` field; disable with `thinking: {type: "disabled"}`.

### Temperature
- **1.0** with thinking mode (forced override in config)
- 0.6 for instant mode (not used in debate agent — always thinking)

### Format
- **Plain text** — no special framework needed
- Standard role-based messages (system, user, assistant)

### Do's
- Use temperature=1.0 for thinking mode
- Use instant mode (temp 0.6) only when reasoning isn't needed
- Provide explicit system prompt if needed (no default)
- Interleave thinking with multi-step tool calls

### Don'ts
- Don't rely on default system prompt (it's been removed)
- Don't mix official API and vLLM/SGLang thinking syntax

---

## GLM-5

**Sources:**
- https://docs.z.ai/guides/llm/glm-5
- https://docs.z.ai/guides/capabilities/thinking-mode
- https://docs.z.ai/api-reference/llm/chat-completion

### Key Findings

- **Thinking activated by default** in GLM-5. Disable with `thinking: {type: "disabled"}`.
- **Interleaved thinking by default** — model thinks between tool calls for step-by-step reasoning.
- **Temperature default: 1.0**, range [0.0, 1.0]. Documentation recommends choosing only temperature OR top_p for tuning, not both.
- **Preserved thinking recommended** for coding/agent scenarios (`clear_thinking: false`).
- **Must return complete, unmodified reasoning_content** back to the API for reasoning continuity.
- **No specific formatting preference documented** — plain text with standard role-based messages.

### Temperature
- Default: 1.0
- Config: `null` (use caller's default — no forced override needed)

### Format
- **Plain text** — standard instructions
- Strong at agentic + multi-step reasoning

### Do's
- Return complete historical reasoning_content in subsequent messages
- Use preserved thinking for coding/agent workflows
- Disable thinking for lightweight queries (fact-checking, wording edits)

### Don'ts
- Don't reorder or modify reasoning blocks
- Don't discard thinking content when using interleaved thinking with tools
- Don't use both temperature and top_p simultaneously

---

## MiniMax M2.5

**Sources:**
- https://huggingface.co/MiniMaxAI/MiniMax-M2.5
- https://github.com/MiniMax-AI/MiniMax-M2.5
- https://www.minimax.io/news/minimax-m25

### Key Findings

- **Temperature: 1.0, top_p: 0.95, top_k: 40** — official recommended parameters.
- **Extended thinking by default** with interleaved `<think>...</think>` tags that must be preserved in conversation history.
- **RL-trained for efficient task breakdown** — decomposes and plans before writing code.
- **Default system prompt:** "You are a helpful assistant. Your name is MiniMax-M2.5 and is built by MiniMax."
- **No specific formatting framework documented** — plain text with standard instructions.

### Temperature
- **1.0** (forced override in config)

### Format
- **Plain text** — no special framework needed
- Standard system/user/assistant messages

### Do's
- Use recommended parameters (temp=1.0, top_p=0.95, top_k=40)
- Preserve `<think>...</think>` tags in conversation history

### Don'ts
- Don't strip thinking tags from conversation context

---

## Cross-Model Rules

These rules apply universally across all models in the debate agent:

1. **All thinking/reasoning models: no "think step by step"** — the reasoning parameter (reasoning_effort, thinkingLevel, thinking mode) handles it. Prompt-level CoT is redundant and can cause issues.

2. **Prompt formatting by family:**
   - XML tags: Claude + Gemini + GPT
   - CTCO framework: GPT (in addition to XML tags)
   - Plain text: Kimi, GLM-5, MiniMax

3. **Never use temperature 0 with thinking-enabled models** — causes looping/degraded performance on Gemini, and is unsupported on GPT-5.

4. **Position critical constraints at END** for all models — especially important for Gemini, but beneficial universally.

5. **Positive instructions outperform negative ones** across all models — tell the model what to do, not what to avoid.

6. **Preserve reasoning/thinking content** when available (GLM-5, MiniMax, Kimi) — don't strip or modify thinking blocks in multi-turn conversations.
