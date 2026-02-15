# Anti-Patterns: Obsidian CLI Vault Management

Common mistakes when managing an Obsidian vault programmatically with Claude Code.
Each anti-pattern includes concrete examples of what goes wrong and how to fix it.

---

## 1. Using REST API for Everything

### The Problem

It is tempting to reach for `curl` and the Local REST API plugin because it feels
like the "proper" way to interact with Obsidian programmatically. Developers who
have worked with other tools default to API-first thinking. But when Claude Code
is already running inside the vault as a terminal process, network calls are an
unnecessary detour.

### Why It's Bad

- Adds a hard dependency on the Local REST API plugin (which may not be installed).
- Requires an API key to be configured and available.
- Self-signed certificate issues cause `curl` failures or require `--insecure` flags.
- Network round-trip is slower than a direct filesystem read.
- If Obsidian is closed or the API server is not running, everything breaks.
- Adds complexity for zero benefit when the file is right there on disk.

### Bad Example

```bash
# Reading a note via REST API - unnecessary when running inside the vault
curl -s --insecure \
  -H "Authorization: Bearer abc123" \
  "https://127.0.0.1:27124/vault/01%20Projects/MyProject/notes.md"

# Creating a note via REST API
curl -s --insecure \
  -H "Authorization: Bearer abc123" \
  -H "Content-Type: text/markdown" \
  -X PUT \
  -d "# New Note" \
  "https://127.0.0.1:27124/vault/01%20Projects/MyProject/new-note.md"
```

### Good Example

```python
# Reading a note - just read the file directly
# Use the Read tool on the absolute path
Read("/path/to/vault/01 Projects/MyProject/notes.md")

# Creating a note - just write the file directly
Write("/path/to/vault/01 Projects/MyProject/new-note.md",
      "---\ntags:\n  - project\ndate: 2026-02-12\n---\n# New Note\n")
```

### Key Takeaway

Direct file operations first. REST API only when you specifically need Obsidian-internal
commands (like triggering a plugin action) that cannot be accomplished through the filesystem.

---

## 2. Dumping All Notes in Root/Inbox

### The Problem

When creating notes programmatically, the path of least resistance is to drop
everything into the vault root or `00 Inbox/`. It avoids the question of "where
does this go?" entirely. Agents that quick-capture everything to Inbox replicate
the worst habit of human note-takers: piling things up with the vague intention
of organizing later.

### Why It's Bad

- Defeats the entire purpose of PARA organization.
- `00 Inbox` grows unbounded and becomes a second vault inside the vault.
- Notes never get organized because there is no trigger to move them.
- Finding anything requires search instead of navigation.
- Related notes are scattered instead of grouped by project or area.
- Creates a backlog of "organize Inbox" tasks that never get done.

### Bad Example

```python
# Every note goes to Inbox regardless of type
Write("/path/to/vault/00 Inbox/meeting-notes-2026-02-12.md",
      "---\ntags:\n  - meeting\n---\n# Meeting Notes\n...")

Write("/path/to/vault/00 Inbox/python-decorators.md",
      "---\ntags:\n  - reference\n---\n# Python Decorators\n...")

Write("/path/to/vault/00 Inbox/cs101-lecture-5.md",
      "---\ntags:\n  - school\n---\n# CS101 Lecture 5\n...")

# Result: 00 Inbox has 200+ notes, none organized
```

### Good Example

```python
VAULT = "/path/to/vault"

# Folder decision logic based on note type:
#
#   Is it tied to a specific project with a deadline? → 01 Projects/{project-name}/
#   Is it an ongoing area of responsibility?          → 02 Areas/{area-name}/
#   Is it reference material for future use?          → 03 Resources/{topic}/
#   Is it school-related?                             → 10 School/{course}/
#   Is it a system template or config?                → 09 Systems/
#   Is it a quick capture with no clear home yet?     → 00 Inbox/   (ONLY this case)
#   Is it no longer active?                           → 99 Archive/

# Meeting notes for an active project → 01 Projects
Write(f"{VAULT}/01 Projects/MyProject/meeting-notes-2026-02-12.md",
      "---\ntags:\n  - meeting\n  - project/myproject\ndate: 2026-02-12\ntype: meeting\n---\n# Meeting Notes\n...")

# Reference material → 03 Resources
Write(f"{VAULT}/03 Resources/Programming/Python/python-decorators.md",
      "---\ntags:\n  - reference\n  - python\ndate: 2026-02-12\ntype: reference\n---\n# Python Decorators\n...")

# School content → 10 School
Write(f"{VAULT}/10 School/CS101/cs101-lecture-5.md",
      "---\ntags:\n  - school\n  - cs101\ndate: 2026-02-12\ntype: lecture\n---\n# CS101 Lecture 5\n...")
```

### Key Takeaway

`00 Inbox` is for quick capture only. When an agent creates a note, it should file
it in the correct PARA folder immediately -- agents have no excuse for "I'll organize
it later."

---

## 3. Creating Notes Without Frontmatter

### The Problem

Writing a Markdown file with just content and no YAML frontmatter block. It works
as a note -- Obsidian will render it fine -- so it feels harmless. But a note without
frontmatter is invisible to every automated system in the vault.

### Why It's Bad

- Breaks Dataview queries (current and future) that filter by metadata.
- No tags means the note is invisible to tag-based navigation.
- No date means you cannot sort or filter chronologically.
- No type field means automated processing cannot categorize the note.
- Inconsistent with the rest of the vault, creating second-class notes.
- Retroactively adding frontmatter to hundreds of notes is painful.

### Bad Example

```markdown
# Project Status Update

The project is on track. We completed the authentication module
and started work on the dashboard.

## Next Steps
- Finish dashboard layout
- Add API integration
- Write tests
```

### Good Example

Minimal frontmatter (absolute minimum for every note):

```markdown
---
tags:
  - project
  - status-update
date: 2026-02-12
type: status-update
---

# Project Status Update

The project is on track. We completed the authentication module
and started work on the dashboard.

## Next Steps
- Finish dashboard layout
- Add API integration
- Write tests
```

Comprehensive frontmatter (for important or structured notes):

```markdown
---
tags:
  - project
  - status-update
  - project/myproject
date: 2026-02-12
type: status-update
project: MyProject
status: active
created: 2026-02-12T10:30:00
modified: 2026-02-12T10:30:00
aliases:
  - MyProject Status Feb 12
related:
  - "[[MyProject Overview]]"
  - "[[Sprint Planning 2026-02-10]]"
---

# Project Status Update

The project is on track. We completed the authentication module
and started work on the dashboard.

## Next Steps
- [ ] Finish dashboard layout
- [ ] Add API integration
- [ ] Write tests
```

### Key Takeaway

Every note gets frontmatter. No exceptions. At minimum: `tags`, `date`, and `type`.

---

## 4. Manual Link Lists Instead of Dataview

### The Problem

Manually maintaining lists of `[[links]]` to related notes -- for example, a project
index page that lists every meeting note, or an area page that lists every resource.
These lists are created once and immediately start going stale.

### Why It's Bad

- The list goes stale the moment a new note is created without updating the index.
- Manual maintenance is error-prone: typos in link names, forgotten entries, dead links.
- Duplicate effort: the note already has metadata that could be queried.
- Does not scale: a project with 50 notes means a 50-line manual list to maintain.
- If someone else (or another agent) creates a note, they may not know to update the index.

### Bad Example

```markdown
# MyProject Index

## Meeting Notes
- [[Meeting 2026-01-15]]
- [[Meeting 2026-01-22]]
- [[Meeting 2026-01-29]]
- [[Meeting 2026-02-05]]
<!-- Someone forgets to add Meeting 2026-02-12 here -->

## Design Documents
- [[Architecture Overview]]
- [[API Design]]
- [[Database Schema]]
<!-- New doc "Auth Flow" was created but never added here -->
```

### Good Example

Since Dataview is not currently installed, use a two-layer strategy:
write Dataview-ready frontmatter so queries will work when the plugin is added,
AND provide static tables that can be regenerated by an agent.

```markdown
# MyProject Index

## Meeting Notes

<!-- AUTOGENERATED: Regenerate by scanning 01 Projects/MyProject/ for type: meeting -->
<!-- Dataview query (for when plugin is installed):
```dataview
TABLE date, status
FROM "01 Projects/MyProject"
WHERE type = "meeting"
SORT date DESC
```
-->

| Note | Date |
|------|------|
| [[Meeting 2026-02-12]] | 2026-02-12 |
| [[Meeting 2026-02-05]] | 2026-02-05 |
| [[Meeting 2026-01-29]] | 2026-01-29 |
| [[Meeting 2026-01-22]] | 2026-01-22 |
| [[Meeting 2026-01-15]] | 2026-01-15 |

<!-- END AUTOGENERATED -->

## Design Documents

<!-- AUTOGENERATED: Regenerate by scanning 01 Projects/MyProject/ for type: design -->

| Note | Status |
|------|--------|
| [[Architecture Overview]] | complete |
| [[API Design]] | in-progress |
| [[Database Schema]] | complete |
| [[Auth Flow]] | draft |

<!-- END AUTOGENERATED -->
```

The regeneration pattern using Claude Code:

```python
# Agent can regenerate the table by scanning the directory
Glob("01 Projects/MyProject/**/*.md")
# Then read each file's frontmatter, filter by type, and rebuild the table
# This is run on-demand rather than maintained manually
```

### Key Takeaway

Structure data for automation, even if the automation tool is not installed yet.
Use Dataview-ready frontmatter and autogenerated static tables as a bridge.

---

## 5. Hardcoded Vault Paths

### The Problem

Embedding the full absolute path to the vault in every file operation, command,
or script. It works on this machine, right now, but it is brittle and verbose.

### Why It's Bad

- Breaks instantly if the vault is moved, renamed, or synced to another machine.
- Clutters every command with a long path string.
- Makes scripts and patterns non-portable.
- If the path contains spaces (as this vault does), quoting errors cause subtle bugs.
- Multiple hardcoded paths mean multiple places to update if anything changes.

### Bad Example

```python
# Hardcoded paths scattered throughout
Read("/path/to/vault/01 Projects/MyProject/notes.md")
Glob("/path/to/vault/01 Projects/**/*.md")
Write("/path/to/vault/01 Projects/MyProject/new.md", content)

# Even worse: inconsistent path styles
Read("/path/to/vault/01 Projects/MyProject/notes.md")
Read("~/Code/Agentic Obsidian Vault/Agentic/01 Projects/MyProject/other.md")
# These may resolve differently depending on the tool
```

### Good Example

```python
# Detect vault root by finding the .obsidian directory
# The vault root is the directory that contains .obsidian/
Glob("**/.obsidian")
# Result: /path/to/vault/.obsidian
# → Vault root: /path/to/vault

# Define vault root once, use relative references everywhere
VAULT = "/path/to/vault"

# All operations use the vault root variable
Read(f"{VAULT}/01 Projects/MyProject/notes.md")
Glob(f"{VAULT}/01 Projects/**/*.md")
Write(f"{VAULT}/01 Projects/MyProject/new.md", content)

# If working in a skill or reusable pattern, detect dynamically:
import os

def find_vault_root(start_path="."):
    """Walk up from start_path until we find a .obsidian directory."""
    current = os.path.abspath(start_path)
    while current != os.path.dirname(current):  # stop at filesystem root
        if os.path.isdir(os.path.join(current, ".obsidian")):
            return current
        current = os.path.dirname(current)
    return None

VAULT = find_vault_root()
```

### Key Takeaway

Detect vault root dynamically from the `.obsidian/` directory. Define it once, reference
it everywhere. Never scatter raw absolute paths across operations.

---

## 6. Overwriting Notes Without Checking Existence

### The Problem

Using `Write` to create a note without first checking whether a file already exists
at that path. If the note exists, `Write` silently replaces all of its content.
There is no undo, no version history, and no warning.

### Why It's Bad

- Destroys existing content permanently.
- Loses manual edits, links, and metadata that the user added.
- No built-in version history in Obsidian (unlike a database).
- The user may not notice the loss until much later.
- Particularly dangerous with common filenames like `index.md` or `README.md`.

### Bad Example

```python
VAULT = "/path/to/vault"

# Dangerous: blindly writes without checking
Write(f"{VAULT}/01 Projects/MyProject/status.md",
      "---\ntags:\n  - status\ndate: 2026-02-12\n---\n# Status\nAll good.\n")
# If status.md already existed with 6 months of history, it is now gone.
```

### Good Example

```python
VAULT = "/path/to/vault"
target = f"{VAULT}/01 Projects/MyProject/status.md"

# Step 1: Check if the file exists
result = Glob(f"{VAULT}/01 Projects/MyProject/status.md")

if result:
    # File exists → READ it first, then EDIT specific sections
    content = Read(target)

    # Update only the section that needs changing
    Edit(target,
         old_string="## Current Status\nIn progress",
         new_string="## Current Status\nComplete as of 2026-02-12")
else:
    # File does not exist → safe to create with Write
    Write(target,
          "---\ntags:\n  - status\n  - project/myproject\ndate: 2026-02-12\ntype: status\n---\n\n# Status\n\n## Current Status\nComplete as of 2026-02-12\n")
```

For appending content to an existing note:

```python
VAULT = "/path/to/vault"
target = f"{VAULT}/01 Projects/MyProject/log.md"

# Read existing content
existing = Read(target)

# Find the insertion point and use Edit to add content
Edit(target,
     old_string="## Log Entries",
     new_string="## Log Entries\n\n### 2026-02-12\n- Completed authentication module\n- Started dashboard work")
```

### Key Takeaway

Check before write. Use `Glob` to test existence, `Read` to inspect content, `Edit` to
modify existing notes, and `Write` only for genuinely new files.

---

## 7. Mixing Tools Inconsistently

### The Problem

Using the REST API for one operation, direct file reads for the next, a CLI tool for
the third, and `curl` to Obsidian Actions for the fourth -- all in the same workflow
with no consistent rationale for which tool is used when.

### Why It's Bad

- Each tool has different failure modes, making debugging harder.
- Unnecessary dependencies: if one tool is unavailable, the whole workflow may break.
- Inconsistent behavior: REST API may return different content than raw file read
  (e.g., processed vs raw Markdown).
- Harder for other agents or future sessions to understand and maintain.
- More surface area for bugs: each tool has its own quoting, encoding, and error handling.

### Bad Example

```python
VAULT = "/path/to/vault"

# Operation 1: Read via REST API
Bash("curl -s --insecure -H 'Authorization: Bearer abc' https://127.0.0.1:27124/vault/01%20Projects/status.md")

# Operation 2: Write via direct file operation
Write(f"{VAULT}/01 Projects/MyProject/new-note.md", content)

# Operation 3: Search via grep
Bash("grep -r 'TODO' '/path/to/vault/01 Projects/'")

# Operation 4: List files via REST API
Bash("curl -s --insecure -H 'Authorization: Bearer abc' https://127.0.0.1:27124/vault/")

# No rationale for why different tools are used for similar operations
```

### Good Example

Follow a clear tool selection hierarchy:

```
┌─────────────────────────────────────────────────────┐
│              Tool Selection Decision Tree             │
├─────────────────────────────────────────────────────┤
│                                                       │
│  Can I do this with direct file operations?           │
│  (Read, Write, Edit, Glob, Grep)                     │
│     │                                                 │
│     ├── YES → Use direct file operations (DEFAULT)    │
│     │                                                 │
│     └── NO → Do I need Obsidian-internal features?    │
│              (plugin commands, graph data, sync)       │
│                │                                      │
│                ├── YES → Is the required plugin        │
│                │         installed and running?        │
│                │            │                          │
│                │            ├── YES → Use plugin API   │
│                │            └── NO → Fallback to       │
│                │                     file ops + warn   │
│                │                                      │
│                └── NO → Use Bash for shell-level ops  │
│                         (git, file permissions, etc)  │
│                                                       │
└─────────────────────────────────────────────────────┘
```

```python
VAULT = "/path/to/vault"

# ALL operations use direct file ops -- consistent and dependency-free

# Read a note
Read(f"{VAULT}/01 Projects/MyProject/status.md")

# Create a note
Write(f"{VAULT}/01 Projects/MyProject/new-note.md", content)

# Search for content
Grep("TODO", path=f"{VAULT}/01 Projects/")

# List files
Glob(f"{VAULT}/01 Projects/**/*.md")

# The only time we use Bash is for operations that genuinely require the shell
Bash("git -C '{VAULT}' log --oneline -5")  # git operations
Bash("wc -l '{VAULT}/01 Projects/MyProject/'*.md")  # bulk file stats
```

### Key Takeaway

Be consistent. Default to direct file operations for everything. Escalate to plugin
APIs or shell commands only when direct file ops genuinely cannot do the job.

---

## 8. Assuming Plugins Are Installed

### The Problem

Writing Dataview queries, using Advanced URI schemes, calling the REST API, or invoking
QuickAdd macros without first checking whether those plugins are actually installed
and enabled. The agent assumes a fully-loaded Obsidian setup and writes code that
silently fails or produces broken notes.

### Why It's Bad

- Dataview code blocks render as raw text if Dataview is not installed.
- Advanced URI links (`obsidian://advanced-uri?...`) do nothing without the plugin.
- REST API calls fail with connection refused if Local REST API is not running.
- The user sees broken formatting and has no idea why.
- Silent failures are worse than loud errors: the agent thinks it succeeded.

### Bad Example

```python
VAULT = "/path/to/vault"

# Assumes Dataview is installed -- it is NOT
Write(f"{VAULT}/01 Projects/MyProject/index.md", """---
tags:
  - index
---
# Project Index

## All Meeting Notes
```dataview
TABLE date, status
FROM "01 Projects/MyProject"
WHERE type = "meeting"
SORT date DESC
```

## Open Tasks
```dataview
TASK
FROM "01 Projects/MyProject"
WHERE !completed
```
""")
# Result: User sees raw ```dataview blocks as code fences. Nothing is rendered.

# Assumes Advanced URI is installed -- it is NOT
Write(f"{VAULT}/00 Inbox/quick-link.md", """
Open the dashboard: [Click here](obsidian://advanced-uri?vault=Agentic&filepath=dashboard)
""")
# Result: Link does nothing when clicked.

# Assumes REST API is running -- it is NOT
Bash("curl -s --insecure -H 'Authorization: Bearer abc' https://127.0.0.1:27124/vault/")
# Result: Connection refused. Agent may not handle this error.
```

### Good Example

```python
VAULT = "/path/to/vault"

# Step 1: ALWAYS check which plugins are installed
plugins_file = f"{VAULT}/.obsidian/community-plugins.json"
installed_plugins = Read(plugins_file)
# Returns: ["terminal", "calendar", "templater-obsidian"]

# Step 2: Branch behavior based on what is available
def has_plugin(name, installed):
    """Check if a plugin is in the installed list."""
    return name in installed

# Example: Building an index page
if has_plugin("dataview", installed_plugins):
    # Dataview IS installed → use live queries
    index_content = """## Meeting Notes
```dataview
TABLE date, status
FROM "01 Projects/MyProject"
WHERE type = "meeting"
SORT date DESC
```"""
else:
    # Dataview is NOT installed → use static table with regeneration markers
    # Scan the directory and build the table manually
    meetings = Glob(f"{VAULT}/01 Projects/MyProject/*.md")
    # Read frontmatter from each, filter for type: meeting, build table
    index_content = """## Meeting Notes

<!-- AUTOGENERATED: Run vault index rebuild to update -->
<!-- Dataview-ready: Install dataview plugin to make this dynamic -->
<!-- ```dataview
TABLE date, status
FROM "01 Projects/MyProject"
WHERE type = "meeting"
SORT date DESC
``` -->

| Note | Date | Status |
|------|------|--------|
| [[Meeting 2026-02-12]] | 2026-02-12 | complete |
| [[Meeting 2026-02-05]] | 2026-02-05 | complete |

<!-- END AUTOGENERATED -->"""

# Example: Creating links
if has_plugin("advanced-uri", installed_plugins):
    link = "[Open dashboard](obsidian://advanced-uri?vault=Agentic&filepath=dashboard)"
else:
    # Fallback to standard Obsidian wiki link
    link = "[[dashboard|Open dashboard]]"
```

Currently installed plugins and their implications:

```
INSTALLED:
  terminal           → Claude Code is running here. No action needed.
  calendar           → Daily notes integration available.
  templater-obsidian → Can use Templater templates for note creation.

NOT INSTALLED (do NOT assume these exist):
  dataview           → No live queries. Use static tables.
  advanced-uri       → No advanced URI schemes. Use wiki links.
  local-rest-api     → No REST API. Use direct file ops.
  quickadd           → No macros. Use direct file operations.
  shell-commands     → No shell command triggers. Use Bash tool.
```

### Key Takeaway

Read `.obsidian/community-plugins.json` before using any plugin-dependent feature.
Always have a fallback path for when the plugin is not installed. Currently only
`terminal`, `calendar`, and `templater-obsidian` are available.

---

## 9. Using Grep for Graph Queries When CLI Has Native Support

### The Problem

Building complex grep, ripgrep, or bash pipelines to answer graph-level questions about the vault — finding orphan notes, detecting broken links, counting backlinks, aggregating tags — when the Obsidian CLI v1.12 provides native indexed commands for all of these operations.

### Why It's Bad

- **Performance**: CLI orphan detection takes 0.26s. The equivalent grep pipeline takes 15.6s — a 60x slowdown.
- **Complexity**: The grep approach requires ~200 tokens of complex bash scripting. The CLI uses ~100 tokens of a single command.
- **Accuracy**: Grep-based backlink detection misses aliases, display-text links (`[[target|display]]`), and cannot distinguish resolved from unresolved links. The CLI uses Obsidian's internal index which handles all edge cases.
- **Impossibility**: Some queries (backlinks to a specific note, dead-end notes) require inverse lookups that are O(n^2) with grep but O(1) against the index.
- **Fragility**: Grep-based solutions break on edge cases — tags with special characters, links in code blocks, varied frontmatter formatting.

### Bad Example

```bash
# Detecting orphans via grep — slow, fragile, complex
all_files=$(find "/path/to/vault" \
  -name "*.md" -not -path "*/.obsidian/*" -not -path "*/.trash/*")
for file in $all_files; do
  basename=$(basename "$file" .md)
  if ! grep -rl "\[\[$basename\]\]" \
    "/path/to/vault" \
    --include="*.md" >/dev/null 2>&1; then
    echo "Orphan: $file"
  fi
done
# Takes 15.6 seconds, misses aliased links, breaks on special characters

# Aggregating tags via grep — manual parsing, fragile
grep -rh "^tags:" "/path/to/vault" \
  --include="*.md" -A 10 | \
  grep "^  - " | sed 's/^  - //' | sort | uniq -c | sort -rn
# Misses inline tags, breaks on varied YAML formatting

# Finding backlinks via grep — misses aliases
grep -rl "\[\[Machine Learning Basics\]\]" \
  "/path/to/vault" \
  --include="*.md"
# Misses: [[Machine Learning Basics|ML]], [[Machine Learning Basics#section]]
```

### Good Example

```bash
# Detecting orphans — 60x faster, accurate
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic orphans
# 0.26 seconds, handles all link types including aliases

# With count
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic orphans total

# Aggregating tags — native, sorted
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic tags all counts sort=count
# Instant, includes inline tags, correct counts

# Finding backlinks — complete results
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic backlinks path="03 Resources/Machine Learning Basics.md"
# Returns ALL linking notes, including aliased and heading links

# Dead-end notes (no outgoing links)
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic deadends

# Unresolved links
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic unresolved

# Properties overview
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic properties all counts sort=count
```

### When Grep IS Still Appropriate

- **Content search within notes**: Grep is fine for finding text patterns in note bodies
- **Frontmatter field queries**: `Grep: pattern="status: active"` is appropriate for filtering notes
- **Obsidian not running**: When CLI is unavailable, grep is the fallback
- **CRUD operations**: Direct file ops remain primary for all content manipulation

### Key Takeaway

For CRUD operations, use direct file ops. For discovery and graph intelligence queries (orphans, backlinks, tags, dead-ends, unresolved links), use the Obsidian CLI. Never build complex grep pipelines for questions the CLI answers natively in under a second.

---

## Summary: Quick Reference

| # | Anti-Pattern | Default To Instead |
|---|---|---|
| 1 | REST API for everything | Direct file ops (Read/Write/Edit) |
| 2 | Dumping notes in Inbox | File to correct PARA folder immediately |
| 3 | Notes without frontmatter | Always add tags, date, type frontmatter |
| 4 | Manual link lists | Dataview-ready frontmatter + static tables |
| 5 | Hardcoded vault paths | Detect vault root, use variable |
| 6 | Overwriting without checking | Glob → Read → Edit existing or Write new |
| 7 | Mixing tools inconsistently | Direct file ops by default, escalate when needed |
| 8 | Assuming plugins exist | Check community-plugins.json, always have fallback |
| 9 | Grep for graph queries | Obsidian CLI for orphans, backlinks, tags, search |
