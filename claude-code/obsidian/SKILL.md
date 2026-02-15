---
name: obsidian
description: >
  Obsidian vault automation using the 3-tier hybrid architecture: direct file ops
  for CRUD, Obsidian CLI v1.12 for discovery and graph intelligence, and URIs for
  UI control. Invoked via /obsidian slash command.
platform: claude-code
---

# Obsidian Vault Expert

The definitive skill for managing the Agentic Obsidian vault. Combines direct file
operations (always available) with Obsidian CLI v1.12 (indexed graph queries) for
a system that is both reliable and intelligent.

## When to Use

- Create, read, edit, organize, or delete notes in the vault
- Find orphan notes, dead-end notes, or unresolved links
- Query backlinks, tags, properties, or tasks across the vault
- Run a vault health check or maintenance session
- Create notes from templates (Daily Note, Research Note, Project, etc.)
- Build or update Maps of Content (MOCs)
- Manage plugins (list, install, enable)
- Any question about the vault's structure, content, or graph

## When NOT to Use

- Writing Obsidian plugins (TypeScript/plugin API) — use normal coding
- Content quality review or grammar checking
- Media transcription or lecture slide extraction
- Knowledge graph theory or visualization

## Invocation

```
/obsidian                          # Interactive — asks what you need
/obsidian health                   # Full vault health check
/obsidian orphans                  # Find and fix orphan notes
/obsidian create research "Title"  # Create a research note from template
/obsidian search "query"           # Search vault content
/obsidian backlinks "note path"    # Find what links to a note
/obsidian tags                     # List all tags with counts
/obsidian daily                    # Create or append to today's daily note
/obsidian moc "Topic"              # Create/update a Map of Content
/obsidian plugins                  # List installed plugins
```

## Architecture: The 3-Tier Hybrid Model

```
User: /obsidian [command] [args]
     |
     v
[Tier Selection] — Choose the right tool for the job
     |
     +---> CRUD (create, read, edit, delete, search content)?
     |       → Tier 1: Direct File Ops (Read/Write/Edit/Glob/Grep)
     |       → Always available, zero dependencies, instant
     |
     +---> Discovery (orphans, backlinks, tags, properties, indexed search)?
     |       → Tier 2: Obsidian CLI v1.12
     |       → Pre-check: pgrep -x Obsidian (must be running)
     |       → Binary: /Applications/Obsidian.app/Contents/MacOS/Obsidian
     |       → IMPORTANT: vault=Agentic MUST be first parameter
     |       → Fallback: Tier 1 (slower but functional)
     |
     +---> UI control (open note, trigger search panel)?
             → Tier 3: obsidian:// URI scheme
             → open "obsidian://open?vault=Agentic&file=..."
```

## Vault Details

- **Path**: `/path/to/vault/`
- **PARA folders**: 00 Inbox, 01 Projects, 02 Areas, 03 Resources, 09 Systems, 10 School, 99 Archive
- **Templates** (12): in `09 Systems/Templates/` — Daily Note, Weekly Review, Project, Research Note, Literature Note, Company Research, Job Application, Learning Plan, Networking Log, Quant Prep, Skill Log, Template Index
- **Installed plugins**: terminal, calendar, templater-obsidian
- **CLI version**: 1.12.1

## Domain Knowledge

Deep reference material lives in the spawner skill. Read these files for detailed
patterns, sharp edges, and architectural decisions when needed:

```
~/.spawner/skills/creative/obsidian-cli/
├── skill.yaml           # Core definition, 13 patterns, 13 domains
├── patterns.md          # 11 pattern deep-dives with full examples
├── sharp-edges.yaml     # 15 pitfalls with detection patterns
├── sharp-edges.md       # 15 sharp edges with Why/Detect/Fix/Prevent
├── collaboration.yaml   # Ecosystem, prerequisites, handoffs
├── decisions.md         # 11 architectural decisions with rationale
├── anti-patterns.md     # 9 anti-patterns with bad/good examples
└── validations.yaml     # 16 quality gate checks
```

Read the relevant file when you need deep context on a specific topic.

## Command Reference

### /obsidian health — Full Vault Health Check

The canonical hybrid workflow. Uses CLI for fast discovery, file ops for fixes.

```
Step 1: Pre-flight checks
  - Verify Obsidian is running: pgrep -x Obsidian
  - Verify CLI responds: obsidian vault=Agentic version
  - If CLI unavailable, warn user and fall back to file-ops-only mode

Step 2: Discovery via CLI (Tier 2)
  - obsidian vault=Agentic orphans total        → count orphan notes
  - obsidian vault=Agentic deadends total       → count dead-end notes
  - obsidian vault=Agentic unresolved total     → count unresolved links
  - obsidian vault=Agentic tags all counts      → tag distribution
  - obsidian vault=Agentic tasks all todo total → open task count

Step 3: Structural analysis via file ops (Tier 1)
  - Glob each PARA folder to count notes per folder
  - Grep for notes missing frontmatter (no leading ---)
  - Grep for notes in vault root (should be zero)

Step 4: Report
  - Present findings as a markdown summary
  - Categorize issues by severity (critical, warning, info)
  - Offer to fix issues (add links to orphans, create missing notes, etc.)

Step 5: Fix (if user approves)
  - Use Edit to add [[links]] to orphan notes
  - Use Write to create stub notes for unresolved links
  - Use Edit to add frontmatter to notes missing it
```

### /obsidian orphans — Find and Fix Orphan Notes

```
Step 1: CLI discovery
  obsidian vault=Agentic orphans
  → List of notes with no incoming links

Step 2: For each orphan, analyze with file ops
  - Read the orphan note
  - Identify its topic, tags, and content
  - Search for related notes that should link to it

Step 3: Suggest or apply fixes
  - Add [[links]] in related notes pointing to the orphan
  - Add the orphan to relevant MOCs
  - If the orphan is stale, suggest archiving to 99 Archive/
```

### /obsidian create [type] "Title" — Create Note from Template

```
Supported types:
  research  → Research Note v1.md  → 03 Resources/
  project   → Project v1.md       → 01 Projects/
  daily     → Daily Note v1.md    → 00 Inbox/YYYY-MM-DD.md
  weekly    → Weekly Review v1.md  → 00 Inbox/
  literature → Literature Note v1.md → 03 Resources/
  company   → Company Research v1.md → 03 Resources/
  job       → Job Application v1.md → 01 Projects/
  learning  → Learning Plan v1.md  → 01 Projects/
  networking → Networking Log v1.md → 02 Areas/
  quant     → Quant Prep v1.md    → 10 School/
  skill     → Skill Log v1.md     → 02 Areas/

Step 1: Read the template from 09 Systems/Templates/
Step 2: Substitute Templater variables with actual values
  - <% tp.date.now("YYYY-MM-DD") %> → current date
  - <% tp.file.title %> → the provided title
Step 3: Check for existing file with Glob (prevent overwrite)
Step 4: Write the populated note to the correct PARA folder
Step 5: Optionally open in Obsidian via URI
```

### /obsidian search "query" — Indexed Search

```
Step 1: If CLI available:
  obsidian vault=Agentic search query="[query]" limit=20
  → Fast indexed results in <0.5s

Step 2: If CLI unavailable, fall back:
  Grep: pattern="[query]" path="vault" glob="*.md"
  → Slower but always works
```

### /obsidian backlinks "path" — Backlink Analysis

```
Step 1: CLI query
  obsidian vault=Agentic backlinks path="[path]"
  → All notes linking TO this note

Step 2: Optionally get outgoing links too
  obsidian vault=Agentic links path="[path]"
  → All notes this note links TO

Step 3: Present as a link map
```

### /obsidian tags — Tag Overview

```
obsidian vault=Agentic tags all counts sort=count
→ All tags sorted by frequency
```

### /obsidian daily — Daily Note

```
Step 1: Determine today's date
Step 2: Check if daily note exists: Glob "00 Inbox/YYYY-MM-DD.md"
Step 3a: If exists, read it and offer to append
Step 3b: If not, create from Daily Note v1.md template
Step 4: Optionally open in Obsidian
```

### /obsidian moc "Topic" — Map of Content

```
Step 1: Search for notes related to the topic
  - CLI: obsidian vault=Agentic search query="[topic]"
  - Grep: pattern="[topic]" glob="**/*.md"
  - Check existing tags: obsidian vault=Agentic tags all

Step 2: Read matched notes to categorize them

Step 3: Create or update the MOC note
  - Location: 03 Resources/MOC - [Topic].md
  - Frontmatter: type: moc, tags: [moc, topic-tag]
  - Organize links by subcategory
  - Add Dataview query in HTML comment (for future use)
```

### /obsidian plugins — Plugin Management

```
obsidian vault=Agentic plugins enabled filter=community versions
→ List of installed community plugins with versions

To install a new plugin:
  obsidian vault=Agentic plugin:install id=[plugin-id] enable
```

## CLI Quick Reference

All commands use this base invocation:
```
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic [command]
```

| Command | Purpose |
|---------|---------|
| `version` | Check CLI version |
| `search query="term" limit=N` | Indexed full-text search |
| `orphans [total]` | Notes with no incoming links |
| `deadends [total]` | Notes with no outgoing links |
| `unresolved [total] [counts] [verbose]` | Broken [[links]] |
| `tags all [counts] [sort=count]` | All tags in vault |
| `properties all [total] [counts]` | All frontmatter properties |
| `backlinks path="path"` | What links TO this note |
| `links path="path"` | What this note links TO |
| `file path="path"` | File metadata (size, dates, words) |
| `tasks all [todo] [done] [total]` | Task overview |
| `plugins enabled [filter=community] [versions]` | Plugin list |
| `plugin:install id=ID [enable]` | Install a plugin |
| `create name="N" path="P" [template="T"]` | Create note |
| `daily:append content="text"` | Append to daily note |
| `template:read name="T" [resolve] [title="T"]` | Read template |

## Critical Rules

1. **vault=Agentic is ALWAYS first** — immediately after the binary path, before any command
2. **Check before write** — always Glob before Write to prevent overwriting existing notes
3. **Frontmatter is mandatory** — every note gets `tags`, `date`, `type` at minimum
4. **PARA placement** — never create notes in vault root; file to the correct folder
5. **CLI pre-check** — verify Obsidian is running before CLI commands; fall back to file ops
6. **Use `all` for vault-wide** — `tasks`, `tags`, `properties` need `all` flag or `file=` parameter
7. **No raw Templater syntax** — substitute `<% %>` variables before writing; wrap in code blocks if documenting
8. **Wiki-links over markdown links** — use `[[Note Name]]` for all internal links

## PARA Folder Selection

| Content Type | Folder |
|-------------|--------|
| Active project with deadline | `01 Projects/` |
| Ongoing area of responsibility | `02 Areas/` |
| Reference material, topic | `03 Resources/` |
| Academic, coursework | `10 School/` |
| Quick capture, unsorted | `00 Inbox/` |
| Templates, dashboards, config | `09 Systems/` |
| Completed, inactive | `99 Archive/` |

## Performance Benchmarks

| Operation | CLI v1.12 | File Ops | CLI Speedup |
|-----------|-----------|----------|-------------|
| Orphan detection | 0.26s | 15.6s | 60x |
| Search | 0.32s | 1.6s | 5x |
| Backlinks | ~0.1s | Impossible* | -- |
| Tag aggregation | ~0.2s | ~3s | 15x |

*Backlink queries via file ops require scanning every file for `[[target]]`, missing aliases.
