# Claude Code Skills

These are the executable skills -- the ones that actually do things when you invoke them. Each lives in `~/.claude/skills/<name>/` and follows the same structure: a `SKILL.md` that defines behavior, a `scripts/` directory with supporting code, `settings/` for configuration, and `references/` for documentation the skill reads at runtime.

They're invoked as slash commands in Claude Code (e.g., `/prove`, `/debate`, `/research`, `/llm`). When triggered, Claude reads the SKILL.md, loads context from the supporting files, and executes the workflow described.

---

## aristotle-prover

**Purpose:** Translates natural language math problems into formal Lean 4 proofs using Harmonic's Aristotle theorem prover API.

**How it works:** You describe a mathematical statement in plain English (or provide a Lean 4 file with `sorry` stubs), and the skill translates it into an optimal prompt for Aristotle. It submits via the `aristotlelib` Python library, polls for completion, and returns either a verified Lean 4 proof or a counterexample if the statement is false.

**Key features:**
- **Informal mode** -- natural language in, formal proof out
- **Formal mode** -- Lean 4 theorem with `sorry` stubs, Aristotle fills the proofs
- **Hybrid mode** -- Lean theorem + English proof hints for guided proving
- **Counterexample detection** -- when statements are false, returns proof of negation

**Example invocation:**
```
/prove Show that for any convergent sequence {a_n} with limit L,
       the sequence {a_n^2} converges to L^2
```

**File structure:**
```
~/.claude/skills/aristotle-prover/
├── SKILL.md
├── scripts/
│   └── aristotle_submit.py      # API submission + polling
├── settings/
│   └── prompt-templates.json    # Domain-specific prompt templates
└── references/
    ├── lean-patterns.md         # Common Lean 4 translation patterns
    └── prompt-guide.md          # Effective Aristotle prompting
```

**Requirements:** `aristotlelib` (v0.7.0+), `ARISTOTLE_API_KEY` env var, Python 3.10+

---

## codex-code

**Purpose:** Orchestrates parallel Codex CLI agents (running `gpt-5.3-codex`) as a coding swarm, with Claude acting as the intelligent coordinator.

**How it works:** Claude analyzes the codebase, decomposes the task into independent subtasks, and launches N parallel Codex agents -- each in its own isolated git worktree. Every agent gets a targeted prompt with clear file ownership boundaries, works autonomously, and returns structured JSON output. Claude then merges the worktrees, resolves any conflicts, and writes glue code if needed.

**Key features:**
- **5 orchestration strategies:** Parallel Independent (A), Phased (B), Swarm Review (C), Competitive best-of-N (D), Assembly Line (E)
- **Git worktree isolation** -- each agent gets its own full repo copy, no race conditions
- **JSONL event streaming** -- real-time progress via `--json` flag, parsed by `parse_jsonl.py`
- **Structured output schema** -- agents return deterministic JSON (files created, tests run, etc.)
- **Session resume** -- if an agent times out at 80%, resume it instead of relaunching from scratch
- **Wave batching** -- for N>10, launches in configurable waves to avoid resource exhaustion
- **Up to 50 agents** -- Claude decides the optimal N based on task complexity

**Example invocation:**
```
/codex Build a REST API with auth, CRUD endpoints for users and posts,
       comprehensive tests, and API documentation
```

**File structure:**
```
~/.claude/skills/codex-code/
├── SKILL.md
├── settings/
│   ├── swarm-config.json          # Tunable parameters (wave size, timeouts, etc.)
│   └── agent-output-schema.json   # JSON Schema for structured agent output
├── scripts/
│   ├── preflight.sh               # Pre-launch auth & environment checks
│   ├── parse_jsonl.py             # JSONL event stream parser
│   ├── aggregate_results.py       # Multi-agent result aggregator
│   └── worktree_manager.sh        # Git worktree create/merge/cleanup
└── references/
    └── codex-cli-reference.md     # Complete Codex CLI flag reference
```

**Requirements:** Codex CLI (`npm install -g @openai/codex`), authenticated via `codex login`, git

---

## convolutional-debate-agent

**Purpose:** Multi-model adversarial reasoning protocol. Runs 5 independent solver drafts across different LLM providers, 4 adversarial debate rounds, optional formal verification via Aristotle, and reliability-weighted scoring to pick or synthesize the best answer.

**How it works:** The question goes through gap detection (resolving ambiguities upfront), then 5 solver agents generate independent answers from different angles (first-principles, code-first, failure-mode, clarity, research). A formalizer extracts testable claims. Then 4 debaters (standardized as 2 Opus + 2 ChatGPT) pressure-test each candidate simultaneously. RWEA scoring combines base quality, pairwise comparison, risk penalties, model reliability weights, and formal verification results into a final ranking.

**Key features:**
- **Multi-provider** -- uses Claude, ChatGPT (gpt-5.3-codex, gpt-5.2), Gemini 3 Pro, Kimi 2.5
- **5 solver archetypes** -- first-principles, code-first, failure-mode, clarity, research/evidence
- **4 adversarial debaters** -- consistency, counterexample, constraint, evidence
- **Formal verification** -- claims submitted to Aristotle (Lean 4 prover) in parallel with debate
- **Domain-aware scoring** -- RWEA weights shift based on detected domain (coding, math, finance, strategy, etc.)
- **5 routing profiles** -- multi_model, multi_model_full, balanced, cost_optimized, max_quality
- **ChatGPT OAuth** -- login with your ChatGPT account via `openai_auth.py`, no manual API key needed

**Example invocation:**
```
/debate Should we use event sourcing or traditional CRUD for our
       order management system? We have 10K orders/day, need audit
       trail, and the team has no event sourcing experience.
```

**File structure:**
```
~/.claude/skills/convolutional-debate-agent/
├── SKILL.md
├── errors.md                         # Known failures and solutions
├── scripts/
│   ├── rwea_score.py                 # Deterministic RWEA scorer
│   ├── llm_runner.py                 # External LLM API caller
│   └── openai_auth.py                # ChatGPT OAuth device flow
├── settings/
│   ├── model-settings.json           # Provider registry + profiles
│   └── benchmark-profiles.json       # Domain-specific model weights
├── api-keys/
│   ├── provider-keys.env.example     # API key template
│   └── .gitignore
└── references/
    ├── roles.md                      # Solver & debater role definitions
    ├── scoring.md                    # RWEA formula & rules
    └── rwea-input-template.json      # Example scoring payload
```

**Requirements:** At least one external API key (Google, Moonshot, OpenRouter, or Anthropic) for full multi-model. Works in balanced mode with just Claude.

---

## deep-research

**Purpose:** Multi-source deep research pipeline. Takes any combination of YouTube videos, arXiv papers, SSRN papers, PDFs, and web articles, extracts their content in parallel, researches the topic broadly via web search, and synthesizes everything into a comprehensive Obsidian research note.

**How it works:** Phase 0 classifies each input (URL or local path) into a source type using regex patterns for YouTube, arXiv, SSRN, generic PDF, or web article. Phase 1 extracts content from each source in parallel -- YouTube gets transcript via `summarize` CLI plus slide extraction via ffmpeg scene detection, academic papers get converted through Mathpix API with delimiter postprocessing, web articles get fetched via WebFetch. Phase 2 does visual analysis of extracted YouTube slides using Claude's multimodal capabilities. Phase 3 runs broad topic research via WebSearch to find community discussions, GitHub repos, blog posts, and official docs. Phase 4 synthesizes everything into a structured research note following a template (frontmatter, question, key idea, numbered sections, evidence, implications, links). Phase 5 validates Obsidian syntax (math delimiters, Mermaid, frontmatter). Phase 6 writes all output files to the vault.

**Key features:**
- **6 source types** -- YouTube, arXiv, SSRN, PDF (URL), PDF (local), web article
- **Parallel extraction** -- independent sources processed concurrently
- **Multimodal slide analysis** -- YouTube slides read and annotated via Claude vision
- **Mathpix integration** -- academic PDFs converted with math-aware OCR, delimiters auto-fixed for Obsidian
- **SSRN Cloudflare handling** -- cookie-based download with TLS fingerprint fallback guidance
- **Obsidian syntax validation** -- P0-P4 priority rules catch math delimiters, Mermaid issues, frontmatter problems
- **Smart output routing** -- infers vault location from content type, or asks the user

**Example invocation:**
```
/research https://www.youtube.com/watch?v=I7azCAgoUHc
/research https://arxiv.org/abs/2502.07766
/research https://www.youtube.com/watch?v=abc123 https://blog.example.com/post
/research ~/Downloads/paper.pdf --title "Market Microstructure Dynamics"
/research https://arxiv.org/abs/2301.12345 --no-broad-search
```

**File structure:**
```
~/.claude/skills/deep-research/
├── SKILL.md
├── scripts/
│   ├── mathpix_convert.py         # Mathpix API: submit, poll, download, postprocess
│   ├── ssrn_download.py           # SSRN PDF download with Cloudflare bypass
│   └── source_classifier.py       # URL classification + metadata extraction
├── settings/
│   ├── extraction-defaults.json   # Default params per source type
│   ├── research-note-template.md  # Synthesis template + formatting rules
│   └── credentials-paths.json     # Credential file locations
└── references/
    ├── obsidian-syntax-rules.md   # P0-P4 validation rules
    └── source-type-guide.md       # Per-source extraction methods + known issues
```

**Requirements:** `summarize` CLI (`npm i -g @steipete/summarize`), yt-dlp, ffmpeg, Mathpix API credentials, Python 3.10+. Optional: SSRN cookies (for SSRN papers), tesseract (for slide OCR).

---

## geps-v5

**Purpose:** Graph-Guided Evolutionary Portfolio Search. A 7-stage research idea generation and evaluation pipeline that uses concept graphs, evolutionary operators, and tournament-based ranking to discover portfolio strategies.

**How it works:** Stage A builds a concept graph from a literature corpus and identifies structural holes (unexplored combinations). Stage B generates ideas through 4 channels (graph-explorer, analogy-transfer, exploit-refiner, constraint-injection). Stage C applies 5 mechanical screening gates. Stage D runs a Swiss-system pairwise tournament with Bradley-Terry rating aggregation. Stage E does finalist verification (fatal-flaw audit, novelty audit, evidence scoring). Stage F runs greedy portfolio optimization with taxonomy quotas. Stage G feeds results back via Thompson Sampling to improve future generation.

**Key features:**
- **Literature-driven** -- concept graph built from actual papers, not from the model's training data
- **4 generation channels** -- diverse idea sources reduce mode collapse
- **5 mechanical gates** -- data availability, complexity, identifiability, novelty, ethics (no LLM needed)
- **Swiss-system tournament** -- budget-efficient pairwise comparison with adaptive judging
- **Bradley-Terry aggregation** -- principled rating from pairwise outcomes, with judge calibration
- **14 Python scripts** -- all stdlib, zero pip dependencies
- **Reuses debate infrastructure** -- `llm_runner.py` and `model-settings.json` from the debate skill

**Example invocation:**
```
/geps full                    # Run complete 7-stage pipeline
/geps generate                # Just generate ideas (Stage B)
/geps tournament              # Just run the tournament (Stage D)
/geps calibrate               # Calibrate judges before first tournament
```

**File structure:**
```
~/.claude/skills/geps-v5/
├── SKILL.md
├── errors.md
├── settings/
│   ├── geps-config.json           # Pipeline configuration
│   ├── taxonomy.json              # Strategy taxonomy for quotas
│   ├── calibration-pack.json      # Judge calibration data
│   ├── literature_sources.json    # Literature corpus sources
│   └── judging_schedule.json      # Tournament scheduling
├── scripts/                       # 14 Python scripts (stdlib only)
│   ├── concept_graph.py           # Literature-driven concept graph
│   ├── swiss_tournament.py        # Adaptive Swiss-system tournament
│   ├── bradley_terry.py           # Bradley-Terry rating aggregation
│   ├── portfolio_optimizer.py     # Greedy forward selection
│   ├── failure_ledger.py          # Thompson Sampling feedback
│   └── ...                        # (9 more)
├── prompts/                       # 9 prompt templates for solvers/judges
└── references/
    ├── architecture.md
    ├── rwea_v2_formula.md
    └── literature.md
```

**Requirements:** Python 3.10+ (stdlib only), debate skill's `llm_runner.py` for LLM calls

---

## llm

**Purpose:** Universal LLM router. Routes prompts to any model across all providers with a CLI-first approach for zero-cost routing, auto-discovery of new models, and benchmark tracking from public leaderboards.

**How it works:** The core router (`llm_route.py`) resolves which provider to use for a given model based on a priority hierarchy: CLI tools first (Claude CLI, Codex CLI, Kimi CLI -- all subscription-based, zero marginal cost), then Google GenAI API for Gemini models, then OpenRouter for everything else. It auto-applies per-model prompting overrides (temperature, system preambles) from `settings/prompting-overrides.json`. The discovery script (`discover_models.py`) queries OpenRouter and Google APIs for new models and slots them into a tiered registry. The benchmark fetcher (`fetch_benchmarks.py`) aggregates rankings from Chatbot Arena, Epoch AI, OpenRouter, and Artificial Analysis into a unified CSV that other skills read for model selection decisions.

**Key features:**
- **CLI-first routing** -- Claude, GPT, and Kimi go through subscription CLIs (free), not paid APIs
- **3-tier model registry** -- tier 1 curated (11 models), tier 2 auto-discovered notable, tier 3 everything else
- **Auto-discovery** -- finds new models from OpenRouter and Google APIs, never overwrites curated entries
- **Benchmark aggregation** -- unified `rankings.csv` from 4 public leaderboards with BetterBench quality tiers
- **Per-model prompting** -- auto-applies optimal temperature and system prompt format per model family
- **Provider override** -- `--route openrouter` forces any model through a specific provider
- **JSON output** -- `--json` for programmatic consumption by other skills
- **Shared credentials** -- falls back to the debate agent's `provider-keys.env` if env vars aren't set

**Example invocation:**
```
/llm --model gpt-5.3-codex --prompt "Write a binary search in Rust"
/llm --model gemini-3-pro --prompt "Explain transformer attention" --json
/llm --list-models
```

**File structure:**
```
~/.claude/skills/llm/
├── SKILL.md
├── scripts/
│   ├── llm_route.py                 # Core router (provider calls + CLI)
│   ├── discover_models.py           # Auto-discovery from OpenRouter/Google
│   └── fetch_benchmarks.py          # Benchmark aggregation from 4 sources
├── settings/
│   ├── model-registry.json          # All known models + routes + tiers
│   ├── routing-rules.json           # Regex patterns for auto-routing
│   ├── prompting-overrides.json     # Per-model temperature + system preambles
│   └── benchmark-quality.json       # BetterBench quality metadata
├── benchmarks/
│   ├── rankings.csv                 # Unified rankings (THE file other skills read)
│   └── _meta.json                   # Fetch timestamps and source status
└── references/
    ├── provider-setup.md            # Auth setup per provider
    ├── betterbench-notes.md         # BetterBench methodology notes
    └── model-lineup-2026-02.md      # Current model landscape
```

**Requirements:** Python 3.10+. At least one CLI tool (`claude`, `codex`, or `kimi`) or API key (`GOOGLE_API_KEY`, `OPENROUTER_API_KEY`).

---

## obsidian

**Purpose:** Full vault automation for an Obsidian knowledge base. The single skill for creating, reading, editing, organizing, and analyzing notes in the vault.

**How it works:** Uses a 3-tier architecture. Tier 1 (direct file operations via Read/Write/Edit/Glob/Grep) handles all CRUD -- always available, zero dependencies. Tier 2 (Obsidian CLI v1.12) handles discovery and graph intelligence -- orphan detection in 0.26s vs 15.6s, indexed search, backlinks, tags. Tier 3 (obsidian:// URI scheme) handles UI control -- opening notes, triggering searches. Falls back gracefully when higher tiers are unavailable.

**Key features:**
- **15+ commands** -- health check, orphan detection, note creation from 12 templates, search, backlinks, tags, MOC generation, plugin management, daily notes
- **PARA method enforcement** -- notes always filed to the correct folder (Projects, Areas, Resources, Archive, etc.)
- **Template instantiation** -- reads Templater templates, substitutes variables, writes populated notes
- **Vault health checks** -- combines CLI discovery with file-ops analysis for a full structural report
- **60x speedup** -- CLI v1.12 indexed queries vs grep-based alternatives for orphans and backlinks
- **Paired with Spawner skill** -- reads `obsidian-cli` Spawner skill for deep pattern/anti-pattern reference

**Example invocation:**
```
/obsidian health              # Full vault health check
/obsidian create research "Volatility Surface Calibration"
/obsidian orphans             # Find and fix orphan notes
/obsidian daily               # Create or append to today's daily note
/obsidian moc "Machine Learning"  # Build a Map of Content
```

**File structure:**
```
~/.claude/skills/obsidian/
├── SKILL.md
└── references/
    └── cli-cheatsheet.md     # CLI v1.12 command reference
```

**Requirements:** Obsidian vault on local filesystem. Obsidian 1.12+ running for Tier 2 commands.

---

## ralph

**Purpose:** Autonomous fresh-context loop for multi-model dissertation idea generation. Runs hundreds of independent LLM iterations, each in a clean context, with automatic saturation detection to know when to stop.

**How it works:** Each iteration discards the previous context entirely -- state lives on disk, not in any model's memory. The bash orchestrator (`ralph.sh`) picks a model weighted by academic benchmarks with stochastic exploration, builds a prompt injected with one of 20 creative divergence lenses (inversion, cross-pollination, failure-mode analysis, scale shift, etc.), calls the model, scores the response for novelty and feasibility, deduplicates against all prior ideas via Jaccard similarity, updates a cross-iteration memory taxonomy, and records circuit breaker state. The loop self-terminates when idea quality saturates, the budget is exhausted, or all models are circuit-broken.

Named after the Ralph Wiggum Loop pattern: instead of managing growing context, throw it away and start fresh.

**Key features:**
- **Fresh context per iteration** -- no context window degradation over hundreds of iterations
- **Multi-model rotation** -- Claude, GPT, Gemini, Kimi, MiniMax via benchmark-weighted stochastic selection
- **20 creative lenses** -- divergence-forcing constraints prevent mode collapse (inversion, cross-pollination, failure mode, scale shift, data-first, adversarial, regime-aware, etc.)
- **Saturation exit** -- automatically stops when rolling marginal idea quality plateaus below threshold
- **Per-model circuit breaker** -- 3-state (closed/open/half-open) with exponential backoff cooldown
- **Session resume** -- pick up where you left off after interruption
- **Cross-iteration memory** -- 4-type taxonomy (patterns, decisions, fixes, warning signs) accumulates across iterations
- **Jaccard deduplication** -- prevents near-duplicate ideas from inflating the idea bank

**Example invocation:**
```
/ralph
/ralph --iterations 20
/ralph --preset idea-generation --domain academic
```

**File structure:**
```
~/.claude/skills/ralph/
├── SKILL.md
├── scripts/
│   ├── ralph.sh                 # Bash orchestrator (7-step iteration loop)
│   ├── session_manager.py       # LLM calls + session lifecycle
│   ├── circuit_breaker.py       # Per-model 3-state circuit breaker
│   ├── model_selector.py        # Benchmark-weighted stochastic selection
│   ├── prompt_builder.py        # Prompt assembly + 20 creative lenses
│   ├── exit_evaluator.py        # Saturation detection + budget limits
│   ├── idea_evaluator.py        # Novelty/feasibility scoring + dedup
│   ├── memory_indexer.py        # Cross-iteration learning (4-type taxonomy)
│   └── benchmark_sync.py        # Benchmark data freshness check
├── settings/
│   ├── ralph-config.json        # Loop limits, exit gates, circuit breaker params
│   ├── benchmark-profiles.json  # Domain-specific model reliability weights
│   └── presets/
│       └── idea-generation.json # Dissertation preset (academic, quant finance)
└── references/
    ├── architecture.md          # Design rationale + failure modes
    └── creative-lenses.yaml     # 20 curated divergence lenses
```

**Requirements:** `/llm` skill (model routing + benchmarks), `/debate` skill's `benchmark-profiles.json` (domain weights), Python 3.10+

---

## system-augmentor

**Purpose:** Self-improvement agent. Audits your Claude Code system for capability gaps, researches solutions online, evaluates candidates via the debate protocol, and implements the winner.

**How it works:** Phase 1 runs a deep system audit -- `system_scanner.py` inventories the filesystem (skills, MCP servers, CLI tools, configs), `gap_analyzer.py` detects structural gaps, and Claude applies reasoning to find capability-level gaps. Phase 2 researches solutions via WebSearch/WebFetch using query templates. Phase 3 evaluates competing solutions through the full `/debate` protocol (5 solvers, 4 debaters, RWEA scoring). Phase 4 implements the winner with safety checks (idempotent, no secrets in files, user consent at every step).

**Key features:**
- **4-phase pipeline** -- audit, research, debate, implement -- with user consent gates between each
- **Calls /debate internally** -- non-trivial choices get the full adversarial evaluation treatment
- **Filesystem inventory** -- scans skills, commands, MCP servers, settings, tools
- **Gap taxonomy** -- classifies gaps by type and severity
- **Safety-first** -- never writes API keys, always checks existence before creating, reversible installs

**Example invocation:**
```
/improve                      # Full system audit
/improve web scraping         # Focused audit on web scraping capability
/improve paper search         # Focused audit on academic paper access
```

**File structure:**
```
~/.claude/skills/system-augmentor/
├── SKILL.md
├── scripts/
│   ├── system_scanner.py         # Filesystem inventory scanner
│   └── gap_analyzer.py           # Structural gap detector
├── settings/
│   ├── scan-targets.json         # Configurable scan paths
│   └── search-templates.json     # WebSearch query patterns
└── references/
    ├── gap-taxonomy.md           # Gap classification schema
    └── debate-question-template.md  # Template for /debate questions
```

**Requirements:** WebSearch/WebFetch for research phase. `/debate` skill for evaluation phase (optional -- skipped for trivial fixes).

---

## Navigation

- [Home](Home.md) -- Back to overview
- [Spawner Skills](Spawner-Skills.md) -- The knowledge pack counterparts
- [Architecture](Architecture.md) -- How Claude Code and Spawner skills work together
- [Getting Started](Getting-Started.md) -- Installation guide
