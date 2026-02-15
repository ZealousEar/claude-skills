# claude-skills

I keep my Claude Code skills and Spawner knowledge skills here for an agentic Obsidian vault workflow.

## What's in here

```text
.
├── claude-code/
│   ├── aristotle-prover/
│   ├── codex-code/
│   ├── convolutional-debate-agent/
│   ├── geps-v5/
│   ├── obsidian/
│   └── system-augmentor/
└── spawner/
    ├── arxiv-pdf-reader/
    ├── lecture-notes-sync/
    ├── mathpix-pdf-converter/
    ├── media-transcript/
    ├── obsidian-cli/
    ├── obsidian-notes-validator/
    ├── online-research/
    └── ssrn-pdf-reader/
```

## Claude Code Skills (`claude-code/`)

| Skill | What it does |
| --- | --- |
| `aristotle-prover` | Translates math problems into Lean 4 proofs through the Harmonic Aristotle API. |
| `codex-code` | Breaks work into subtasks, runs parallel Codex CLI agents in worktrees, then merges results. |
| `convolutional-debate-agent` | Runs adversarial multi-model debates and aggregates outputs with reliability weighting. |
| `geps-v5` | Uses graph-guided evolutionary search and tournament ranking for portfolio strategy exploration. |
| `obsidian` | Automates vault CRUD, graph queries, and UI control with a 3-tier workflow. |
| `system-augmentor` | Audits capability gaps, researches options, debates candidates, and applies the best upgrade. |

## [Spawner](https://spawner.vibeship.co/mcp-guide) Skills (`spawner/`)

| Skill | What it does |
| --- | --- |
| `arxiv-pdf-reader` | Guidance for downloading and processing arXiv papers. |
| `lecture-notes-sync` | Patterns for syncing lecture recordings with structured notes. |
| `mathpix-pdf-converter` | Mathpix API patterns for PDF-to-Markdown conversion, including batch workflows. |
| `media-transcript` | Patterns for transcribing audio and video content. |
| `obsidian-cli` | Deep Obsidian CLI v1.12 reference with patterns, edge cases, and architecture decisions. |
| `obsidian-notes-validator` | Quality rules for validating notes in an Obsidian vault. |
| `ssrn-pdf-reader` | SSRN download patterns, including Cloudflare bypass gotchas. |
| `online-research` | Web research workflow patterns. |

## How these work

I use two skill systems because they solve different problems. Claude Code skills are executable: each one is a slash-command skill with a `SKILL.md` workflow and optional `scripts/`, `settings/`, and `references/` support files. Spawner skills are not executable; they are YAML plus Markdown knowledge packs that Claude reads as domain context. In practice, I combine them so a Claude Code skill does the actions while a Spawner skill supplies guardrails and known pitfalls.

## Using these

### Claude Code skills

Copy or symlink `claude-code/<skill-name>/` into your Claude Code skills directory.  
Run the skill by name from Claude Code (for example, `/codex-code`).  
The skill's `SKILL.md` defines the execution workflow and any helper files it can use.

### Spawner skills

Load `spawner/<skill-name>/` as a knowledge skill in your Spawner setup.  
Use it as reference context during tasks; these files are guidance, not commands.  
Pair a Spawner skill with a Claude Code skill when you want execution plus domain rules.

Licensed under the MIT License. See `LICENSE`.
