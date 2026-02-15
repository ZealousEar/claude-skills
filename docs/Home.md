# Claude Skills Collection

A collection of 14 custom AI agent skills built for two complementary systems: **Claude Code** (executable slash-command workflows) and **Spawner** (YAML+MD domain knowledge packs). These aren't toy examples -- they're production skills I use daily for formal theorem proving, multi-model debates, portfolio research, vault automation, academic paper processing, and more.

## What's Here

**6 Claude Code skills** -- executable workflows invoked via slash commands (`/prove`, `/debate`, `/geps`, etc.). Each one has a `SKILL.md`, supporting scripts, config files, and reference docs. They do things: call APIs, orchestrate agents, manipulate files, run tournaments.

**8 Spawner skills** -- domain knowledge packs that Claude reads as reference context. They don't execute anything themselves. Instead, they encode expertise about what works, what breaks, and how tools fit together. Think of them as the institutional memory that prevents you from making the same mistake twice.

## Quick Navigation

- [Claude Code Skills](Claude-Code-Skills.md) -- Deep dive on the 6 executable skills
- [Spawner Skills](Spawner-Skills.md) -- Deep dive on the 8 knowledge packs
- [Architecture](Architecture.md) -- How the two systems work together
- [Getting Started](Getting-Started.md) -- Installation and usage guide

## All 14 Skills at a Glance

### Claude Code Skills (Executable)

| Skill | Slash Command | What It Does |
|-------|--------------|--------------|
| **aristotle-prover** | `/prove` | Translates math into Lean 4 formal proofs via Harmonic API |
| **codex-code** | `/codex` | Orchestrates parallel Codex CLI agents as a coding swarm |
| **convolutional-debate-agent** | `/debate` | 5 solver drafts, 4 adversarial reviews, reliability-weighted scoring |
| **geps-v5** | `/geps` | Graph-guided evolutionary search for portfolio strategies |
| **obsidian** | `/obsidian` | 3-tier vault automation (file ops + CLI + URIs) |
| **system-augmentor** | `/improve` | Self-improvement agent that audits gaps and installs solutions |

### Spawner Skills (Knowledge Packs)

| Skill | Category | What It Knows |
|-------|----------|---------------|
| **arxiv-pdf-reader** | Academic | Fetching and converting arXiv papers via Mathpix API |
| **lecture-notes-sync** | Academic | Synthesizing slides + transcripts into study notes |
| **mathpix-pdf-converter** | Academic | PDF/EPUB/DOCX to markdown with math preservation |
| **media-transcript** | Content | YouTube/PDF transcript extraction via summarize CLI |
| **obsidian-cli** | Vault | Full Obsidian vault automation patterns and anti-patterns |
| **obsidian-notes-validator** | Quality | Note validation: Mermaid, TikZ, frontmatter, wiki-links |
| **online-research** | Research | Systematic web research with SIFT verification |
| **ssrn-pdf-reader** | Academic | SSRN paper fetching with Cloudflare cookie handling |

## Navigation

- [Claude Code Skills](Claude-Code-Skills.md) | [Spawner Skills](Spawner-Skills.md) | [Architecture](Architecture.md) | [Getting Started](Getting-Started.md)
