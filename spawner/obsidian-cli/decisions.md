# Obsidian CLI & Automation — Design Decisions

Key architectural and design decisions for the obsidian-cli skill. Each decision captures the reasoning behind a specific approach so that future agents and contributors understand not just *what* the skill does, but *why* it does it that way.

---

## Decision 1: Direct File Operations as Primary Interaction Method

**Decision**: Use Claude Code's native file tools (Read, Write, Edit, Glob, Grep) as the primary way to interact with the Obsidian vault. All note creation, modification, search, and organization flows through direct filesystem access.

**Context**: Claude Code runs inside the vault's terminal environment and already has full filesystem access. The Obsidian ecosystem offers multiple programmatic interfaces — a Local REST API plugin, the Advanced URI plugin, external CLI tools like `obsidian-cli`, MCP server integrations, and the Templater plugin's scripting engine. Any of these could serve as the primary interaction method.

**Rationale**: Direct file operations are the only method that requires zero additional dependencies. They are always available regardless of which plugins are installed, they execute instantly without network overhead or plugin boot time, and they require no authentication or configuration. Since Obsidian vault notes are plain Markdown files on disk, every operation an agent needs — creating notes, editing content, searching across files, organizing folders — maps directly to a file operation. This also means the skill works identically on any machine where Claude Code has vault access, with no setup steps.

**Alternatives Considered**:
- **Local REST API plugin**: Provides structured HTTP endpoints for vault operations, but requires the plugin to be installed and Obsidian to be running. Adds a network layer between agent and files. Currently not installed in this vault.
- **Advanced URI plugin**: Enables `obsidian://` URI scheme commands for opening notes, running commands, and triggering actions. Useful for UI automation but requires the plugin and a running Obsidian instance. Currently not installed.
- **External CLI tools** (e.g., `obsidian-cli` npm package): Adds an installation dependency and another abstraction layer over what are ultimately file operations. Introduces version compatibility concerns.
- **MCP server integration**: Promising for structured vault access but requires server configuration, adds latency, and is not yet mature in the Obsidian ecosystem.

**Consequences**:
- Positive: Zero dependencies, instant execution, works offline, works without Obsidian running, portable across machines, leverages Claude Code's strongest capabilities
- Positive: No authentication, no configuration, no plugin version compatibility issues
- Negative: Cannot trigger Obsidian UI actions (open a note in the editor, trigger a plugin command, refresh the graph view)
- Negative: Changes made while Obsidian is open may not reflect immediately in the UI until Obsidian detects the filesystem change (usually within seconds)

---

## Decision 2: Plugin Availability Check Before Use (Graceful Degradation)

**Decision**: Before using any plugin-specific feature, always read `.obsidian/community-plugins.json` to verify the plugin is installed. If a plugin is not available, fall back to a direct file operation equivalent rather than failing silently.

**Context**: The Obsidian plugin ecosystem is rich but fragmented. Useful plugins like Dataview (structured queries), Advanced URI (deep linking), Local REST API (HTTP access), and QuickAdd (quick capture) may or may not be installed in any given vault. An agent skill that assumes plugin availability will break unpredictably across different vaults.

**Rationale**: Silent failures — where a plugin command is issued but nothing happens because the plugin is missing — are far worse than explicit fallbacks. A single check of the community-plugins.json file at the start of an operation tells the agent exactly what is available. The skill can then branch: use the plugin feature if available, or use a direct file operation fallback if not. This check is cheap (one file read) and eliminates an entire class of runtime errors.

**Current vault state**:
- Installed: `terminal`, `calendar`, `templater-obsidian`
- Not installed: `Advanced URI`, `Dataview`, `Local REST API`, `QuickAdd`, `Shell Commands`

**Alternatives Considered**:
- **Assume all plugins are available**: Fast path but breaks immediately on vaults without those plugins. Terrible user experience.
- **Assume no plugins are available**: Safe but misses optimization opportunities. If Dataview is installed, queries are far more powerful than grep-based search.
- **Try-catch approach** (attempt plugin use, catch failure): Adds complexity, and many plugin failures are silent rather than throwing errors, making catch-based detection unreliable.

**Consequences**:
- Positive: Skill works on any vault regardless of installed plugins
- Positive: Clear error messages when a requested feature needs a missing plugin
- Positive: Can recommend plugin installation when a user's workflow would benefit from it
- Negative: Every plugin-dependent operation requires a preliminary file read
- Negative: Fallback paths must be maintained alongside plugin-native paths

---

## Decision 3: PARA Structure Enforcement

**Decision**: All notes created by the agent must be placed into the appropriate PARA folder. Notes must never be created in the vault root. The agent must select the correct PARA folder based on note type and content.

**Context**: The vault uses a PARA organizational structure with numbered prefixes:
- `00 Inbox` — unsorted captures, quick notes, items to be processed
- `01 Projects` — active projects with defined outcomes and deadlines
- `02 Areas` — ongoing areas of responsibility (career, health, finance)
- `03 Resources` — reference material, topics of interest, collected knowledge
- `09 Systems` — templates, dashboards, vault configuration
- `10 School` — academic coursework and study material
- `99 Archive` — completed or inactive items

**Rationale**: Agents should be more disciplined than humans, not less. When a human creates a quick note, they might drop it in the vault root and sort it later. An agent has no excuse — it can determine the correct location at creation time. Enforcing PARA placement means every agent-created note is immediately findable in the expected location. This also prevents vault root clutter, which degrades the user experience in the Obsidian file explorer.

**Alternatives Considered**:
- **Default everything to Inbox**: Safe but lazy. Creates an inbox processing burden for the user. Defeats the purpose of having an intelligent agent.
- **Allow vault root placement**: Simpler implementation but leads to organizational drift. Users who set up PARA expect it to be respected.
- **Ask the user every time**: Correct but tedious. The agent should infer the right location from context and only ask when genuinely ambiguous.

**Consequences**:
- Positive: Vault stays organized without user intervention
- Positive: Notes are immediately findable in the expected PARA category
- Positive: Reinforces the user's organizational system rather than undermining it
- Negative: Agent must implement folder selection logic (mapping note types to PARA folders)
- Negative: Edge cases exist where the correct folder is ambiguous (a project resource vs. a general resource)

---

## Decision 4: Frontmatter-First Approach

**Decision**: Every note created by the agent MUST include YAML frontmatter. The minimum required fields are `tags` (list) and `date` (ISO 8601). Additional standard fields include `type`, `status`, `project`, and `source` where applicable.

**Context**: YAML frontmatter is the standard metadata mechanism in Obsidian. It appears between `---` delimiters at the top of a note and stores structured key-value data. Plugins like Dataview, Templater, and the core Search plugin can read and query frontmatter fields. Even without these plugins, frontmatter provides a consistent, machine-readable metadata layer.

**Rationale**: Frontmatter is an investment in future capability. Even though Dataview is not currently installed in this vault, structuring metadata now means zero migration work when it is installed later. Tags enable Obsidian's native tag search. Dates enable chronological sorting and filtering. Type fields enable categorical queries. The cost of adding frontmatter at creation time is minimal (a few lines of YAML), but retrofitting hundreds of notes with frontmatter later is painful.

**Standard frontmatter schema**:
```yaml
---
tags:
  - topic-tag
  - category-tag
date: 2026-02-12
type: note | project | area | resource | literature-note | daily-note
status: active | completed | archived | on-hold
project: "[[Related Project]]"
source: "URL or reference"
---
```

**Alternatives Considered**:
- **No frontmatter, tags inline only**: Simpler but loses structured metadata. Inline `#tags` work but cannot store dates, statuses, or relationships.
- **Frontmatter only when needed**: Reduces verbosity but creates inconsistency. Some notes queryable, others not. Harder to build reliable automations.
- **JSON frontmatter**: Valid in some tools but not standard in Obsidian. YAML is the universal expectation.

**Consequences**:
- Positive: Every note is searchable, queryable, and sortable by metadata
- Positive: Dataview-ready from day one — no migration needed when plugin is installed
- Positive: Consistent structure enables reliable automation and agent workflows
- Negative: Notes are slightly more verbose at the top
- Negative: Agent must determine appropriate metadata values for each note type

---

## Decision 5: Git for Version Control Over Obsidian Sync

**Decision**: Use git for vault version control and synchronization. The vault repository should include a `.gitignore` that excludes `workspace.json`, `.obsidian/workspace.json`, and other ephemeral Obsidian state files.

**Context**: Multiple synchronization and version control options exist for Obsidian vaults: Obsidian Sync (paid, official), iCloud/Dropbox/Google Drive (consumer cloud sync), git (developer version control), and Syncthing (peer-to-peer sync). Each has different tradeoffs around history, conflict resolution, cost, and collaboration.

**Rationale**: Git provides capabilities no other sync method offers: full diff history of every change, branching for experimental workflows, conflict detection with merge tools, and free hosting on GitHub/GitLab. For an agent-augmented vault, git history is especially valuable — it provides a complete audit trail of what the agent changed and when, enabling easy rollback of agent actions. The `.gitignore` for `workspace.json` is critical because this file changes on every Obsidian interaction (window size, open tabs, etc.) and would create constant merge noise.

**Critical `.gitignore` entries**:
```
.obsidian/workspace.json
.obsidian/workspace-mobile.json
.trash/
```

**Alternatives Considered**:
- **Obsidian Sync**: Official, seamless, handles conflicts well, but costs $4-8/month, provides no diff history, and cannot be scripted by agents.
- **iCloud/Dropbox sync**: Free tier available, but sync conflicts in Markdown files are destructive (duplicate files, data loss). No version history beyond basic file versions.
- **Syncthing**: Free, peer-to-peer, no cloud dependency, but no version history and conflict resolution creates duplicate files.

**Consequences**:
- Positive: Complete change history with diffs for every commit
- Positive: Free hosting, works with GitHub for backup and collaboration
- Positive: Agent actions are auditable and reversible via git revert
- Positive: Branching enables experimental agent workflows without risk
- Negative: Requires git knowledge for conflict resolution
- Negative: Binary files (images, PDFs) bloat the repository
- Negative: Must remember to commit regularly — unsaved work is unversioned

---

## Decision 6: Claude-Processed Templates Over Templater Automation

**Decision**: Use the template files in `09 Systems/Templates/` as reference documents that Claude reads, interprets, and manually substitutes values into, rather than triggering Templater plugin automation to process them.

**Context**: The vault contains 12 templates:
`Company Research v1.md`, `Daily Note v1.md`, `Job Application v1.md`, `Learning Plan v1.md`, `Literature Note v1.md`, `Networking Log v1.md`, `Project v1.md`, `Quant Prep v1.md`, `Research Note v1.md`, `Skill Log v1.md`, `Template Index v1.md`, `Weekly Review v1.md`

The Templater plugin is installed and uses `<% %>` syntax for dynamic content insertion. However, Templater is designed for interactive use within the Obsidian UI — the user triggers a template, and Templater prompts for inputs and processes the template in-app.

**Rationale**: Claude reading and processing templates directly provides more control and fewer side effects. The agent can read a template file, understand its structure, substitute appropriate values based on context, and write the result as a new note — all without requiring Obsidian to be running or Templater to be active. This approach also lets Claude adapt templates intelligently: adding extra sections when relevant, skipping fields that do not apply, and enriching content beyond simple variable substitution.

**Alternatives Considered**:
- **Trigger Templater via URI or API**: Would require Advanced URI plugin (not installed) and Obsidian running. Introduces dependency on Obsidian state.
- **Use Templater's `<% %>` syntax directly**: Confusing because the syntax would be interpreted as literal text by file write operations, not as Templater commands. Would need Templater to process the file after creation.
- **Create notes without templates**: Loses the consistency that templates provide. Each note would have ad-hoc structure.

**Consequences**:
- Positive: Full control over template processing — Claude can adapt, extend, or simplify
- Positive: No dependency on Obsidian running or Templater plugin state
- Positive: Templates serve as structural reference — the spirit is preserved even if syntax differs
- Negative: Claude must manually replicate Templater's variable substitution logic
- Negative: If Templater templates use complex logic (conditionals, loops), Claude must interpret that intent

---

## Decision 7: Wiki-Links Over Markdown Links for Internal References

**Decision**: Use Obsidian wiki-link syntax `[[Note Name]]` for all internal vault links. Never use standard Markdown link syntax `[text](path/to/note.md)` for links between vault notes.

**Context**: Obsidian supports two internal linking syntaxes:
- Wiki-links: `[[Note Name]]` or `[[Note Name|Display Text]]` or `[[Note Name#Heading]]`
- Markdown links: `[Display Text](path/to/note.md)` or `[Display Text](path/to/note.md#heading)`

Both resolve to the same notes, but they behave differently in the Obsidian ecosystem.

**Rationale**: Wiki-links are the Obsidian-native convention and provide three critical advantages. First, they automatically update when a linked note is renamed — Obsidian tracks wiki-links and rewrites them on rename, but does not do this for Markdown links. Second, wiki-links appear in the Graph View and Backlinks panel, making the vault's knowledge graph visible and navigable. Third, wiki-links are simpler to write (no path needed, just the note name) which reduces errors. Since this skill targets Obsidian specifically, optimizing for Obsidian's conventions over generic Markdown portability is the right tradeoff.

**Alternatives Considered**:
- **Markdown links**: More portable to other tools (GitHub, Hugo, Jekyll) but lose Obsidian-specific features. Require full relative paths which are fragile if files move.
- **Mixed approach** (wiki-links for internal, Markdown for external): Reasonable but introduces cognitive overhead about which syntax to use when. Better to have one rule: wiki-links inside the vault, Markdown links for external URLs.

**Consequences**:
- Positive: Links auto-update on note rename — no broken links from reorganization
- Positive: Full integration with Graph View, Backlinks, and Outgoing Links panels
- Positive: Simpler syntax — just `[[Note Name]]` with no path management
- Negative: Not portable — wiki-links render as literal text in non-Obsidian Markdown viewers
- Negative: Note name collisions across folders can cause ambiguous links (mitigated by unique naming)

---

## Decision 8: Dataview-Compatible Frontmatter Even Without Dataview Installed

**Decision**: Structure all frontmatter fields to be compatible with Dataview query syntax, including using consistent field names, proper YAML types (lists for tags, strings for dates, inline links for relationships), even though Dataview is not currently installed.

**Context**: Dataview is the most powerful query and data aggregation plugin in the Obsidian ecosystem. It enables SQL-like queries across vault notes using frontmatter and inline fields. While not currently installed in this vault, it is one of the most commonly installed community plugins and likely to be added in the future.

**Rationale**: The cost of Dataview-compatible frontmatter is near zero — it is just well-structured YAML. The cost of retrofitting hundreds of notes with inconsistent metadata to work with Dataview is significant. By committing to a consistent schema now, the vault is immediately ready for Dataview the moment it is installed. This is a classic "pave the road before the traffic comes" decision.

**Standard fields optimized for Dataview**:
- `tags`: YAML list (not inline `#tags`) — Dataview reads both but YAML lists are cleaner
- `date`: ISO 8601 string (`2026-02-12`) — Dataview parses this as a date type for sorting
- `type`: Lowercase string — enables `WHERE type = "project"` queries
- `status`: Lowercase string from controlled vocabulary — enables `WHERE status = "active"` filters
- `project`: Wiki-link in quotes (`"[[Project Name]]"`) — Dataview resolves this as a link type
- `source`: URL string — enables source tracking and bibliography generation

**Alternatives Considered**:
- **Minimal frontmatter, add Dataview fields later**: Lower upfront cost but creates a migration problem. Notes created before and after Dataview installation would have different schemas.
- **Use Dataview inline fields** (`field:: value`): More flexible but mixes metadata into note body. YAML frontmatter is cleaner and supported by more tools.
- **Wait for Dataview installation to decide schema**: Reactive approach that guarantees inconsistency in existing notes.

**Consequences**:
- Positive: Zero migration effort when Dataview is installed
- Positive: Consistent metadata schema across all notes from day one
- Positive: Enables powerful grep-based queries even without Dataview (structured YAML is easy to parse)
- Negative: Some frontmatter fields may feel over-specified for simple notes
- Negative: Schema must be maintained and documented for consistency

---

## Decision 9: Agent Dashboard for Activity Visibility and Auditability

**Decision**: Maintain a dedicated Agent Dashboard note at `09 Systems/Agent Dashboard.md` that logs all significant agent actions — notes created, notes modified, searches performed, organizational changes made.

**Context**: AI agents operating in a personal knowledge vault raise legitimate concerns about visibility and control. When an agent creates, modifies, or moves notes, the user needs to know what happened, when, and why. Without an audit trail, agent actions are invisible and potentially surprising — the user might discover unexpected changes days later with no way to understand or reverse them.

**Rationale**: An Agent Dashboard provides a single point of visibility into all agent activity. It serves three purposes: (1) transparency — the user can see exactly what the agent did in each session, (2) auditability — actions are logged with timestamps and rationale, enabling review, and (3) recoverability — if an agent makes an unwanted change, the dashboard shows what to revert. Placing the dashboard in `09 Systems/` follows the PARA convention for vault infrastructure notes.

**Dashboard structure**:
```markdown
# Agent Dashboard
## Recent Activity
| Date | Action | Note | Details |
|------|--------|------|---------|
| 2026-02-12 | Created | [[New Note]] | Created from Research Note template |
| 2026-02-12 | Modified | [[Existing Note]] | Added literature references |

## Session Log
### 2026-02-12
- Created 3 notes in 01 Projects/
- Updated frontmatter on 5 notes in 03 Resources/
- Moved 2 notes from 00 Inbox to 03 Resources/
```

**Alternatives Considered**:
- **Git history only**: Provides a complete record but requires git literacy to read. Not visible from within Obsidian.
- **Inline comments in modified notes**: Clutters note content. Agent metadata mixed with user content is confusing.
- **No audit trail**: Simplest but irresponsible. Users lose trust in agents they cannot oversee.
- **Separate log file outside vault**: Not visible in Obsidian. Defeats the purpose of in-vault visibility.

**Consequences**:
- Positive: Complete visibility into agent actions from within Obsidian
- Positive: Enables user review and selective rollback of agent changes
- Positive: Builds trust through transparency
- Negative: Dashboard must be updated on every significant agent action (maintenance overhead)
- Negative: Dashboard can grow large over time — needs periodic archival or summarization

---

## Decision 10: Tool Selection Hierarchy for Vault Operations

**Decision**: When multiple tools can accomplish the same vault operation, select the tool using this priority order:
1. **Direct file operations** (Read/Write/Edit/Glob/Grep) — default choice
2. **URI scheme** (`obsidian://`) — when UI action is required (opening a note, triggering a command)
3. **REST API** (Local REST API plugin) — when structured data exchange is needed
4. **External CLI** (npm packages, shell tools) — when batch operations exceed file tool capabilities
5. **MCP integration** — when cross-application coordination is needed

**Context**: The Obsidian ecosystem offers multiple overlapping tools for vault operations. A note can be created via file write, REST API POST, URI scheme, CLI command, or MCP tool call. Without a clear selection hierarchy, tool choice becomes arbitrary, leading to inconsistent behavior, unnecessary dependencies, and unpredictable failure modes.

**Rationale**: The hierarchy is ordered by dependency count and reliability. Direct file operations have zero dependencies — they work everywhere, always, instantly. Each subsequent level adds a dependency: URI scheme requires Obsidian running, REST API requires a plugin and Obsidian running, external CLI requires installation, MCP requires server configuration. By defaulting to the lowest-dependency option and only escalating when a specific capability is needed, the skill remains maximally portable and minimally fragile.

**When to escalate**:
- Escalate to **URI scheme** when: you need to open a note in the Obsidian editor, navigate to a specific heading, or trigger a core command (like opening the daily note)
- Escalate to **REST API** when: you need to query Obsidian's internal state (active file, open tabs), perform operations that require Obsidian's rendering engine, or need structured JSON responses
- Escalate to **External CLI** when: batch operations on hundreds of notes exceed what sequential file operations can handle efficiently
- Escalate to **MCP** when: the operation involves coordination between Obsidian and another application (e.g., syncing tasks with a project management tool)

**Alternatives Considered**:
- **Always use REST API when available**: Provides a consistent interface but adds unnecessary network overhead for simple file operations and fails when Obsidian is closed.
- **Always use the most powerful tool**: MCP or REST API first — overpowered for simple operations, adds latency, increases failure surface.
- **Let the agent choose freely**: No hierarchy means inconsistent tool selection across sessions, making behavior harder to predict and debug.

**Consequences**:
- Positive: Predictable tool selection — users and developers know which tool will be used for each operation type
- Positive: Minimal dependency surface — most operations use zero-dependency file operations
- Positive: Graceful degradation — if a higher-level tool is unavailable, the skill falls back naturally
- Negative: May underutilize specialized tools that offer richer functionality
- Negative: Escalation rules add decision complexity to each operation

---

## Decision 11: Hybrid Architecture — Direct File Ops for CRUD + Obsidian CLI for Discovery

**Decision**: Adopt a 3-tier hybrid architecture for vault operations: Direct file ops (Tier 1) for all CRUD and content editing, Obsidian CLI v1.12 (Tier 2) for discovery, graph intelligence, and metadata queries, and obsidian:// URIs (Tier 3) for UI control. This replaces the previous 5-tier hierarchy that treated CLI tools and MCP servers as separate lower-priority tiers.

**Context**: Obsidian v1.12 ships with a native CLI accessible at `/Applications/Obsidian.app/Contents/MacOS/Obsidian`. This CLI provides indexed search, native orphan detection, backlink queries, tag/property aggregation, and plugin management — all through single commands that leverage Obsidian's internal in-memory index. Benchmark testing on this vault revealed dramatic performance differences between CLI and file-based alternatives.

**Benchmark Data**:

| Operation | CLI v1.12 | File Ops (Grep/Bash) | Speedup |
|-----------|-----------|---------------------|---------|
| Orphan detection | 0.26s / ~100 tokens | 15.6s / ~200 tokens | 60x |
| Indexed search | 0.32s | 1.6s (ripgrep) | 5x |
| Backlink query | ~0.1s | Impossible* | — |
| Tag aggregation | ~0.2s | ~3s (YAML parsing) | 15x |
| Property listing | ~0.2s | ~3s (YAML parsing) | 15x |

*Backlink queries require knowing which files link TO a target, which requires a full vault scan with file ops.

**Rationale**: Direct file ops remain the fastest and most reliable method for CRUD operations — they work offline, have zero dependencies, and are the core strength of Claude Code running inside the vault. However, they fundamentally cannot access Obsidian's internal index, graph data, or plugin system. The CLI bridges this gap by exposing indexed data through simple commands.

The hybrid approach provides:
- File ops for content manipulation: zero dependencies, offline capable, instant
- CLI for discovery and intelligence: leverages Obsidian's index for 10-60x speedup
- URIs for UI control: opens notes, triggers searches in the Obsidian interface

This is analogous to a database where you use the filesystem for raw data access but the query engine for indexed lookups.

**The 3-Tier Model**:

```
Tier 1: Direct File Ops (Read/Write/Edit/Glob/Grep)
  → CRUD, content editing, bulk writes
  → Always available, offline, zero dependencies

Tier 2: Obsidian CLI v1.12 (/Applications/Obsidian.app/Contents/MacOS/Obsidian)
  → Discovery: search, orphans, deadends, unresolved links
  → Graph intelligence: backlinks, outgoing links, file metadata
  → Metadata queries: tags, properties, tasks
  → Vault management: plugins, daily notes, templates
  → Requires Obsidian 1.12+ running, <1s indexed responses

Tier 3: obsidian:// URIs
  → UI control: open notes, trigger searches, invoke commands
  → Requires Obsidian running
```

**Alternatives Considered**:
- **CLI-only approach**: Would add an Obsidian-running dependency for basic CRUD operations that work perfectly with file ops. Creates unnecessary fragility for the most common operations.
- **File-ops-only approach** (previous architecture): Worked but was 10-60x slower for graph queries and completely unable to access backlinks, orphans, or plugin data. This approach left significant capability on the table.
- **REST API approach**: Requires installing the Local REST API plugin, managing authentication, dealing with self-signed certificates, and provides less capability coverage than the native CLI. The CLI is built into Obsidian itself with no additional installation.
- **MCP server approach**: Adds protocol overhead, requires server configuration, and the available MCP servers have less mature vault coverage than the native CLI.

**Consequences**:
- Positive: 10-60x faster discovery operations via indexed queries
- Positive: Access to graph intelligence (backlinks, orphans, dead-ends) that is impossible with file ops alone
- Positive: Plugin management without manual file manipulation of .obsidian/plugins/
- Positive: File ops remain primary for CRUD — no new dependency for the most common operations
- Positive: Single binary, no installation required — the CLI is the Obsidian app itself
- Negative: CLI commands require Obsidian to be running (must gracefully fall back to file ops)
- Negative: `vault=` parameter ordering is a footgun (must be first parameter after binary)
- Negative: Some commands require `all` flag for vault-wide scope, which is not obvious
