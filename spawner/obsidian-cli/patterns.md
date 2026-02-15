# Obsidian CLI & Automation — Patterns

Deep-dive documentation for all obsidian-cli patterns with full working examples.

---

## 1. vault-file-crud — Direct File Operations

### Description

Claude Code runs inside the vault directory. This means Read, Write, Edit, Glob, and
Grep tools operate directly on vault files with zero configuration, no plugins, and no
API keys. This is the primary and most reliable method for all vault operations.

### When to Use

Always. Direct file operations are the default approach for every vault interaction.
They require nothing beyond the tools Claude Code already has. Use other patterns only
when you specifically need Obsidian UI control, structured API responses, or cross-tool
integration.

### Core Operations

#### Create a Note

Check if the file exists first, then write with full frontmatter.

```
# Step 1: Check for existing file
Glob: "03 Resources/Machine Learning Basics.md"

# Step 2: Write the note (only if it does not exist)
Write to: /path/to/vault/03 Resources/Machine Learning Basics.md
```

Full note content with frontmatter:

```markdown
---
title: Machine Learning Basics
date: 2026-02-12
type: resource
status: active
tags:
  - machine-learning
  - ai
  - fundamentals
source: ""
aliases:
  - ML Basics
---

# Machine Learning Basics

## Overview

Machine learning is a subset of artificial intelligence that enables systems
to learn and improve from experience without being explicitly programmed.

## Key Concepts

- **Supervised Learning** — Training with labeled data
- **Unsupervised Learning** — Finding patterns in unlabeled data
- **Reinforcement Learning** — Learning through reward signals

## Related

- [[Deep Learning Fundamentals]]
- [[Neural Network Architectures]]
```

#### Read a Note

```
Read: /path/to/vault/03 Resources/Machine Learning Basics.md
```

For large files, use offset and limit:

```
Read: /path/to/vault/01 Projects/Thesis.md
  offset: 50
  limit: 100
```

#### Update a Note (Precise Edit)

Use Edit with old_string/new_string for surgical changes. This preserves the rest
of the file exactly as it is.

```
Edit: /path/to/vault/03 Resources/Machine Learning Basics.md
  old_string: "status: active"
  new_string: "status: complete"
```

Add a new section to an existing note:

```
Edit: /path/to/vault/03 Resources/Machine Learning Basics.md
  old_string: "## Related"
  new_string: "## Applications\n\n- Natural language processing\n- Computer vision\n- Recommendation systems\n\n## Related"
```

#### Delete a Note

Always confirm with the user before deleting. Move to trash or archive instead when
possible.

```bash
# Move to archive instead of deleting
mv "/path/to/vault/03 Resources/Old Note.md" \
   "/path/to/vault/99 Archive/Old Note.md"
```

If the user explicitly requests deletion:

```bash
rm "/path/to/vault/03 Resources/Old Note.md"
```

#### List Notes

```
# All notes in a PARA folder
Glob: "01 Projects/*.md"

# All notes recursively
Glob: "01 Projects/**/*.md"

# All templates
Glob: "09 Systems/Templates/*.md"

# All markdown files in vault
Glob: "**/*.md"

# Notes matching a name pattern
Glob: "**/Machine Learning*.md"
```

#### Search Content

```
# Find notes containing a keyword
Grep: pattern="machine learning" path="/path/to/vault"

# Find notes with a specific tag in frontmatter
Grep: pattern="tags:.*research" glob="**/*.md"

# Find all wiki-links to a specific note
Grep: pattern="\[\[Machine Learning Basics\]\]"

# Find TODO items across vault
Grep: pattern="- \[ \]" output_mode="content"

# Find notes by frontmatter status
Grep: pattern="^status: active" glob="01 Projects/*.md" output_mode="files_with_matches"
```

### Creating a Research Note from Template (Full Example)

This is a complete workflow: read the template, substitute variables, write the note.

```
# Step 1: Read the template
Read: /path/to/vault/09 Systems/Templates/Research Note v1.md

# Step 2: Write the new note with substituted values
Write to: /path/to/vault/03 Resources/Transformer Architecture Research.md
```

Resulting note:

```markdown
---
title: Transformer Architecture Research
date: 2026-02-12
type: research
status: draft
tags:
  - transformers
  - deep-learning
  - attention-mechanism
source: "Vaswani et al. 2017 - Attention Is All You Need"
aliases:
  - Transformer Research
---

# Transformer Architecture Research

## Research Question

How do transformer architectures achieve state-of-the-art performance
through self-attention mechanisms?

## Key Findings

- Self-attention replaces recurrence entirely
- Multi-head attention enables parallel computation
- Positional encoding preserves sequence information

## Methodology

Analysis of the original transformer paper and subsequent improvements
including BERT, GPT, and T5 architectures.

## Notes

-

## References

- Vaswani, A., et al. (2017). Attention Is All You Need.
- Devlin, J., et al. (2019). BERT: Pre-training of Deep Bidirectional Transformers.

## Related

- [[Deep Learning Fundamentals]]
- [[Neural Network Architectures]]
```

### Tips

- **Always Glob before Write** — Check if a file exists before creating it to avoid
  accidental overwrites.
- **Use Edit for updates, not Write** — Write replaces the entire file. Edit modifies
  only the targeted string, preserving everything else.
- **Absolute paths** — Always use the full vault path:
  `/path/to/vault/...`
- **Frontmatter is mandatory** — Every note should start with YAML frontmatter between
  `---` delimiters. This enables future Dataview queries and consistent metadata.
- **PARA placement** — Choose the correct folder:
  - `00 Inbox/` — Quick captures, unsorted notes
  - `01 Projects/` — Active projects with deadlines
  - `02 Areas/` — Ongoing responsibilities (career, health, finance)
  - `03 Resources/` — Reference material, research, learning
  - `10 School/` — Academic content
  - `09 Systems/` — Templates, dashboards, system notes
  - `99 Archive/` — Completed or inactive items

---

## 2. obsidian-uri-commands — URI Scheme

### Description

Obsidian registers a custom URI scheme (`obsidian://`) that enables external
applications to trigger actions inside the running Obsidian application. URIs can
open notes, create new notes, search, and navigate the vault. On macOS, these are
invoked with the `open` command.

### When to Use

- When you need to open a note in the Obsidian GUI for the user to view
- When you need to trigger Obsidian-native actions (search panel, graph view)
- When you need the user to see something in the Obsidian interface
- NOT for creating/editing notes programmatically (use direct file ops instead)

### URI Actions

#### Open an Existing Note

```bash
# Open a note by file path (spaces must be %20-encoded)
open "obsidian://open?vault=Agentic&file=03%20Resources%2FMachine%20Learning%20Basics"

# Note: file path is relative to vault root, without .md extension
```

#### Create a New Note

```bash
# Create and open a new note with content
open "obsidian://new?vault=Agentic&file=00%20Inbox%2FQuick%20Capture&content=---%0Atitle%3A%20Quick%20Capture%0Adate%3A%202026-02-12%0A---%0A%0A%23%20Quick%20Capture%0A%0AContent%20here"

# Overwrite if exists (default is false, which appends)
open "obsidian://new?vault=Agentic&file=00%20Inbox%2FQuick%20Capture&content=New%20content&overwrite=true"

# Append to existing note
open "obsidian://new?vault=Agentic&file=00%20Inbox%2FQuick%20Capture&content=%0A-%20New%20item&append=true"
```

#### Search the Vault

```bash
# Open Obsidian search with a query
open "obsidian://search?vault=Agentic&query=machine%20learning"
```

#### Advanced URI Plugin (If Installed)

The Advanced URI plugin extends the URI scheme significantly. It is NOT currently
installed in this vault, but if added:

```bash
# Write data to a specific heading
open "obsidian://advanced-uri?vault=Agentic&filepath=03%20Resources%2FNote.md&heading=Notes&data=New%20content%20under%20heading"

# Write to frontmatter
open "obsidian://advanced-uri?vault=Agentic&filepath=03%20Resources%2FNote.md&frontmatterkey=status&data=complete"

# Open daily note
open "obsidian://advanced-uri?vault=Agentic&daily=true"

# Execute a command by ID
open "obsidian://advanced-uri?vault=Agentic&commandid=graph%3Aopen"
```

### URL Encoding Reference

Characters that must be encoded in URIs:

| Character | Encoded |
|-----------|---------|
| Space     | `%20`   |
| `/`       | `%2F`   |
| `:`       | `%3A`   |
| `#`       | `%23`   |
| `?`       | `%3F`   |
| `&`       | `%26`   |
| `=`       | `%3D`   |
| Newline   | `%0A`   |

### Helper: Encode and Open

```bash
# Python one-liner to properly encode and open
python3 -c "
import urllib.parse, subprocess
vault = 'Agentic'
filepath = '03 Resources/Machine Learning Basics'
encoded = urllib.parse.quote(filepath, safe='')
subprocess.run(['open', f'obsidian://open?vault={vault}&file={encoded}'])
"
```

### Tips

- **URI scheme requires Obsidian to be running** — If Obsidian is not open, the URI
  will launch it first, which may cause a delay.
- **No .md extension** — The `file` parameter takes the path without the `.md`
  extension.
- **Content length limits** — URIs have practical length limits (~2000 chars). For
  notes with substantial content, create the file directly and then open it with a
  URI.
- **Prefer direct file ops for content** — Use URIs only to control the Obsidian UI.
  Create and modify note content with Write/Edit, then optionally open the result
  with a URI.

---

## 3. rest-api-vault-ops — Local REST API

### Description

The `obsidian-local-rest-api` community plugin exposes a REST API on
`https://127.0.0.1:27124` that provides CRUD operations, search, and more through
standard HTTP requests. It uses a self-signed TLS certificate and requires an API
key for authentication.

### When to Use

- When you need structured JSON responses from vault operations
- When integrating with external tools that speak HTTP
- When building automated pipelines that require API-style interaction
- NOT needed for basic file operations (direct file ops are simpler and faster)

### Prerequisites Check

**Always verify the plugin is installed before attempting API calls.**

```
# Check if the REST API plugin is installed
Grep: pattern="obsidian-local-rest-api"
  path="/path/to/vault/.obsidian/community-plugins.json"
```

If the plugin is not found in community-plugins.json, it is not installed. Fall back
to direct file operations (Pattern 1).

### API Reference

All requests require:
- `--insecure` or `-k` flag (self-signed certificate)
- `Authorization: Bearer YOUR_API_KEY` header
- Base URL: `https://127.0.0.1:27124`

#### List All Files

```bash
curl -k -H "Authorization: Bearer YOUR_API_KEY" \
  "https://127.0.0.1:27124/vault/"
```

Response:
```json
{
  "files": [
    "00 Inbox/Quick Note.md",
    "01 Projects/Thesis.md",
    "03 Resources/Machine Learning Basics.md"
  ]
}
```

#### Read a File

```bash
# Get raw markdown content
curl -k -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Accept: text/markdown" \
  "https://127.0.0.1:27124/vault/03%20Resources/Machine%20Learning%20Basics.md"
```

#### Create or Update a File

```bash
curl -k -X PUT \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: text/markdown" \
  -d '---
title: New Note
date: 2026-02-12
type: note
status: draft
tags:
  - example
---

# New Note

Content goes here.' \
  "https://127.0.0.1:27124/vault/00%20Inbox/New%20Note.md"
```

#### Append to a File

```bash
curl -k -X POST \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: text/markdown" \
  -d '
- New bullet point added via API' \
  "https://127.0.0.1:27124/vault/00%20Inbox/New%20Note.md"
```

#### Delete a File

```bash
curl -k -X DELETE \
  -H "Authorization: Bearer YOUR_API_KEY" \
  "https://127.0.0.1:27124/vault/00%20Inbox/Temporary%20Note.md"
```

#### Search

```bash
# Simple text search
curl -k -X POST \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "machine learning"}' \
  "https://127.0.0.1:27124/search/simple/"
```

Response:
```json
[
  {
    "filename": "03 Resources/Machine Learning Basics.md",
    "score": 12.5,
    "matches": [
      {
        "match": {
          "start": 45,
          "end": 62
        },
        "context": "...fundamentals of machine learning applied to..."
      }
    ]
  }
]
```

### Fallback Strategy

Since the REST API plugin is NOT currently installed in this vault, always implement
a fallback:

```
# Pseudocode for graceful fallback
1. Check community-plugins.json for "obsidian-local-rest-api"
2. If present:
   a. Attempt curl to https://127.0.0.1:27124/ with --connect-timeout 2
   b. If successful, use API
   c. If connection refused, warn user that plugin may not be running
3. If not present:
   a. Use direct file operations (Pattern 1)
   b. Inform user that REST API plugin is available if they want structured access
```

### Tips

- **Self-signed cert** — Always use `-k` / `--insecure` with curl. The plugin
  generates a self-signed certificate.
- **API key location** — The API key is found in Obsidian Settings > Local REST API.
  Do not hardcode it; ask the user or read from a config file.
- **URL encoding** — Spaces in paths must be `%20`-encoded.
- **Plugin must be running** — Obsidian must be open with the plugin enabled.
- **Direct file ops are simpler** — Since Claude Code is inside the vault, direct
  Read/Write/Edit is almost always preferable to HTTP requests.

---

## 4. mcp-obsidian-bridge — MCP Server Integration

### Description

Model Context Protocol (MCP) servers provide a standardized interface for AI tools
to interact with Obsidian vaults. Several community MCP servers exist, each offering
different capabilities. Since Claude Code already runs inside the vault, MCP adds
value primarily for cross-tool integration and when Obsidian-specific operations
(like triggering commands or accessing plugin data) are needed.

### When to Use

- Cross-application workflows where Obsidian operations must be chained with other
  MCP-enabled tools
- When you need access to Obsidian-specific plugin functionality not available through
  direct file operations
- When building integrations that should work across different AI tools
- NOT needed for basic vault CRUD (use direct file ops)

### Available MCP Servers

#### 1. mcp-obsidian (REST API-based)

Requires the Local REST API plugin. Wraps the REST API in MCP protocol.

Configuration in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "obsidian": {
      "command": "npx",
      "args": ["-y", "mcp-obsidian"],
      "env": {
        "OBSIDIAN_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

Available tools:
- `list_files_in_vault` — List all files
- `read_file` — Read note content
- `write_file` — Create or overwrite a note
- `search_vault` — Full-text search
- `get_tags` — List all tags used in vault

#### 2. obsidian-claude-code-mcp (WebSocket-based)

Connects directly to Obsidian via WebSocket (requires its companion Obsidian plugin).

```json
{
  "mcpServers": {
    "obsidian-ws": {
      "command": "npx",
      "args": ["-y", "obsidian-claude-code-mcp"],
      "env": {
        "OBSIDIAN_WS_PORT": "28080"
      }
    }
  }
}
```

Available tools:
- `read_note` — Read file content
- `write_note` — Write file content
- `list_notes` — List vault files
- `search` — Search vault
- `execute_command` — Run Obsidian commands (open graph, toggle sidebar, etc.)

#### 3. jwhonce/obsidian-cli (MCP-native)

A standalone CLI tool with MCP mode.

```json
{
  "mcpServers": {
    "obsidian-cli": {
      "command": "obsidian-cli",
      "args": ["mcp", "--vault", "/path/to/vault"]
    }
  }
}
```

### Claude Code MCP Configuration

For Claude Code specifically, MCP servers are configured in `.claude/settings.json`
or the project-level `.claude` directory:

```json
{
  "mcpServers": {
    "obsidian": {
      "command": "npx",
      "args": ["-y", "mcp-obsidian"],
      "env": {
        "OBSIDIAN_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

### Tips

- **Direct file ops first** — Since Claude Code runs inside the vault, MCP adds an
  extra layer that is usually unnecessary. Use it only when you need specific MCP
  capabilities.
- **Check what is installed** — Before configuring an MCP server, verify its
  dependencies (REST API plugin, WebSocket plugin, etc.).
- **MCP is evolving** — The protocol and available servers are actively developed.
  Check for updates and new capabilities.
- **No MCP servers are currently configured** in this vault. Setup would require
  installing the MCP server package and adding configuration.

---

## 5. templater-automation — Template Application

### Description

The Templater plugin (installed in this vault) provides a powerful template system
with dynamic variables and JavaScript execution. When Claude Code creates notes
programmatically, it reads the template file, substitutes variables manually, and
writes the result. Claude does NOT invoke Templater directly; instead it performs
the variable replacement itself using the template as a structural guide.

### When to Use

- Every time you create a new note that matches an existing template category
- When the user asks to create a project, research note, daily note, etc.
- When consistency across notes of the same type is important

### Available Templates

All templates live in `09 Systems/Templates/`:

| Template | Purpose | Target Folder |
|----------|---------|---------------|
| Company Research v1.md | Company analysis and research | 03 Resources/ |
| Daily Note v1.md | Daily journal and task tracking | 00 Inbox/ or 01 Projects/ |
| Job Application v1.md | Job application tracking | 01 Projects/ or 02 Areas/ |
| Learning Plan v1.md | Structured learning roadmap | 01 Projects/ |
| Literature Note v1.md | Book/paper notes and annotations | 03 Resources/ |
| Networking Log v1.md | Contact and networking tracker | 02 Areas/ |
| Project v1.md | Project planning and tracking | 01 Projects/ |
| Quant Prep v1.md | Quantitative interview prep | 01 Projects/ or 10 School/ |
| Research Note v1.md | General research documentation | 03 Resources/ |
| Skill Log v1.md | Skill development tracking | 02 Areas/ |
| Template Index v1.md | Index of all templates | 09 Systems/ |
| Weekly Review v1.md | Weekly reflection and planning | 00 Inbox/ or 01 Projects/ |

### Template Workflow

#### Step 1: Read the Template

```
Read: /path/to/vault/09 Systems/Templates/Project v1.md
```

#### Step 2: Identify Variables to Replace

Common Templater variables you will see in templates:

| Variable | Replacement |
|----------|-------------|
| `<% tp.date.now("YYYY-MM-DD") %>` | Current date: `2026-02-12` |
| `<% tp.file.title %>` | The note title (filename without .md) |
| `<% tp.date.now("dddd, MMMM D, YYYY") %>` | `Thursday, February 12, 2026` |
| `<% tp.file.creation_date("YYYY-MM-DD") %>` | File creation date |
| `{{title}}` | Note title (alternative syntax) |
| `{{date}}` | Current date (alternative syntax) |

#### Step 3: Substitute and Write

Example — Creating a new project note from the Project template:

```
# Read the template
Read: /path/to/vault/09 Systems/Templates/Project v1.md

# Substitute variables and write
Write to: /path/to/vault/01 Projects/Build Personal Website.md
```

With content:

```markdown
---
title: Build Personal Website
date: 2026-02-12
type: project
status: active
tags:
  - web-development
  - portfolio
  - personal
deadline: 2026-03-15
---

# Build Personal Website

## Objective

Create a personal portfolio website to showcase projects and writing.

## Key Results

- [ ] Design wireframes
- [ ] Set up Next.js project
- [ ] Deploy to Vercel
- [ ] Add project showcase section
- [ ] Write about page

## Timeline

| Phase | Target | Status |
|-------|--------|--------|
| Design | 2026-02-20 | Not Started |
| Development | 2026-03-01 | Not Started |
| Content | 2026-03-10 | Not Started |
| Launch | 2026-03-15 | Not Started |

## Resources

-

## Log

### 2026-02-12
- Project created

## Related

-
```

### Full Example: Daily Note Creation

```
# Step 1: Read the Daily Note template
Read: /path/to/vault/09 Systems/Templates/Daily Note v1.md

# Step 2: Write today's daily note
Write to: /path/to/vault/00 Inbox/2026-02-12.md
```

```markdown
---
title: "2026-02-12"
date: 2026-02-12
type: daily
tags:
  - daily
---

# Wednesday, February 12, 2026

## Morning Review

- [ ] Review yesterday's notes
- [ ] Check calendar
- [ ] Set today's priorities

## Tasks

- [ ]

## Notes

-

## End of Day

### What went well?

-

### What could improve?

-

### Tomorrow's focus

-
```

### Tips

- **Do NOT invoke Templater programmatically** — Templater uses `<% %>` syntax that
  is processed by the Templater plugin when a user creates a note through the
  Obsidian UI. Claude Code should read the template as a structural guide and perform
  all substitutions manually.
- **Preserve template structure** — When substituting variables, keep the overall
  structure, headings, and formatting of the template intact.
- **Date formatting** — Use Python or shell commands if you need complex date formats:
  ```bash
  date "+%A, %B %d, %Y"  # Thursday, February 12, 2026
  ```
- **Check the template first** — Always read the actual template before creating a
  note. Templates may have been updated by the user.

---

## 6. dataview-ready-notes — Dataview-Compatible Frontmatter

### Description

Dataview is a powerful Obsidian plugin that enables database-like queries across
vault notes using frontmatter metadata. Even though Dataview is NOT currently
installed in this vault, structuring frontmatter for Dataview compatibility ensures
notes are queryable if/when the plugin is added. Well-structured frontmatter also
benefits other tools and manual organization.

### When to Use

- Every time you create or modify frontmatter on any note
- When the user asks about querying or organizing their notes
- When building dashboards or index notes

### Standard Frontmatter Schema

Every note should include these core fields:

```yaml
---
title: "Note Title"
date: 2026-02-12
type: note          # note | project | area | resource | daily | weekly | lecture | research
status: draft       # draft | active | review | complete | archived
tags:
  - tag-one
  - tag-two
source: ""          # URL, book, paper, person, etc.
aliases:
  - "Alternate Name"
---
```

### Type-Specific Fields

#### Projects (`type: project`)

```yaml
---
title: "Project Name"
date: 2026-02-12
type: project
status: active
tags:
  - project-tag
deadline: 2026-06-01
priority: high          # low | medium | high | critical
area: "Career"          # Links to an Area
---
```

#### Areas (`type: area`)

```yaml
---
title: "Area Name"
date: 2026-02-12
type: area
status: active
tags:
  - area-tag
review_frequency: weekly  # daily | weekly | monthly | quarterly
---
```

#### Resources (`type: resource`)

```yaml
---
title: "Resource Title"
date: 2026-02-12
type: resource
status: active
tags:
  - topic-tag
source: "https://example.com/article"
author: "Author Name"
---
```

#### Research (`type: research`)

```yaml
---
title: "Research Topic"
date: 2026-02-12
type: research
status: draft
tags:
  - research-area
source: "Paper or source reference"
methodology: ""
findings: ""
---
```

#### Daily Notes (`type: daily`)

```yaml
---
title: "2026-02-12"
date: 2026-02-12
type: daily
tags:
  - daily
mood: ""                # optional: track mood
energy: ""              # optional: track energy level
---
```

### Dataview Query Examples (For Future Use)

These queries will work once Dataview is installed.

#### List All Active Projects

```dataview
TABLE deadline, priority, status
FROM "01 Projects"
WHERE type = "project" AND status = "active"
SORT deadline ASC
```

#### Find All Research Notes Tagged with ML

```dataview
LIST
FROM #machine-learning
WHERE type = "research"
SORT date DESC
```

#### Task Tracker Across Vault

```dataview
TASK
FROM "01 Projects"
WHERE !completed
GROUP BY file.name
```

#### Recently Modified Notes

```dataview
TABLE file.mtime AS "Modified", type, status
FROM ""
SORT file.mtime DESC
LIMIT 20
```

#### Notes by Area

```dataview
TABLE type, status, date
FROM "02 Areas"
WHERE status != "archived"
SORT date DESC
```

### Static Fallback (No Dataview)

When Dataview is not installed, create static tables that Claude updates manually:

```markdown
## Active Projects

| Project | Status | Deadline | Priority |
|---------|--------|----------|----------|
| [[Build Personal Website]] | active | 2026-03-15 | high |
| [[ML Research Paper]] | draft | 2026-04-01 | medium |
| [[Job Search 2026]] | active | ongoing | high |

*Last updated: 2026-02-12*
```

Update these tables by using Edit to modify the table rows whenever a project
status changes.

### Tips

- **Consistent field names** — Always use the same field names (lowercase, underscores).
  Mixing `deadline` and `Deadline` breaks Dataview queries.
- **Tags as arrays** — Use YAML array syntax for tags, not inline comma-separated:
  ```yaml
  # Good
  tags:
    - machine-learning
    - research

  # Avoid
  tags: machine-learning, research
  ```
- **Dates in ISO format** — Always use `YYYY-MM-DD` format for dates. Dataview
  parses this natively.
- **Quotes around special values** — Wrap values with colons, brackets, or other
  YAML special characters in quotes:
  ```yaml
  title: "Note: An Important Discovery"
  source: "https://example.com"
  ```

---

## 7. git-vault-sync — Git Version Control

### Description

Using git to version-control an Obsidian vault provides backup, change history, and
synchronization across machines. This pattern covers initialization, proper
`.gitignore` configuration, commit workflows, and sync strategies.

### When to Use

- When the user wants to track changes to their vault
- When setting up vault backup
- When the user asks about syncing across devices
- Before making large-scale changes (commit first as a checkpoint)

### Note: Current Vault Status

This vault is NOT currently a git repository. The patterns below cover both
initialization and ongoing use.

### Initialization

```bash
cd "/path/to/vault"
git init
```

### Essential .gitignore

```
Write to: /path/to/vault/.gitignore
```

```gitignore
# Obsidian workspace (changes constantly, causes merge conflicts)
.obsidian/workspace.json
.obsidian/workspace-mobile.json

# Obsidian cache
.obsidian/cache

# macOS
.DS_Store
.DS_Store?
._*

# Trash
.trash/

# Plugin caches and temp files
.obsidian/plugins/*/data.json.bak

# Local environment files
.env
.env.local

# Claude Code artifacts (if running in vault)
.claude/
```

### Commit Patterns

#### Standard Commit

```bash
cd "/path/to/vault"
git add -A
git commit -m "vault: add research notes on transformer architecture"
```

#### Commit Message Conventions

Use a consistent prefix to categorize changes:

| Prefix | Usage |
|--------|-------|
| `vault:` | General vault changes, new notes |
| `project:` | Project-specific updates |
| `template:` | Template modifications |
| `system:` | Dashboard, config, system note changes |
| `archive:` | Moving notes to archive |
| `refactor:` | Reorganizing vault structure |

Examples:

```bash
git commit -m "vault: add ML research notes and update project tracker"
git commit -m "project: complete milestone 2 of website build"
git commit -m "template: update Research Note v1 with methodology section"
git commit -m "system: update agent dashboard with session log"
git commit -m "archive: move completed job applications to archive"
```

#### Before Large Changes

Always commit before making bulk operations:

```bash
cd "/path/to/vault"
git add -A
git commit -m "vault: checkpoint before bulk reorganization"
```

### Automated Sync Script

```bash
#!/bin/bash
# vault-sync.sh — Auto-commit and push vault changes
# Usage: Run via cron or launchd

VAULT="/path/to/vault"
cd "$VAULT" || exit 1

# Check for changes
if [ -n "$(git status --porcelain)" ]; then
    TIMESTAMP=$(date "+%Y-%m-%d %H:%M")
    git add -A
    git commit -m "vault: auto-sync $TIMESTAMP"

    # Push if remote is configured
    if git remote | grep -q origin; then
        git push origin main
    fi
fi
```

Make it executable:

```bash
chmod +x vault-sync.sh
```

### Handling Conflicts

The most common conflict source is `.obsidian/workspace.json`. This is why it must
be in `.gitignore`. If you encounter other conflicts:

```bash
# See which files conflict
git status

# For note conflicts, review both versions
git diff --name-only --diff-filter=U

# Accept current version
git checkout --ours "path/to/note.md"

# Accept incoming version
git checkout --theirs "path/to/note.md"

# After resolving
git add "path/to/note.md"
git commit -m "vault: resolve merge conflict in note"
```

### Tips

- **Never commit workspace.json** — It changes every time you switch notes and causes
  constant merge conflicts.
- **Commit before bulk operations** — Always make a checkpoint commit before running
  automated scripts that modify many notes.
- **Do not force-push** — Vault repos may have changes from other devices. Always
  pull before pushing.
- **Review diffs** — Before committing, review what changed with `git diff` to avoid
  accidentally committing sensitive information.
- **Large vaults** — For vaults with many images/PDFs, consider git-lfs for binary
  files to keep the repo size manageable.

---

## 8. agentic-dashboard — Agent Activity Dashboard

### Description

A dashboard note that tracks Claude Code activity in the vault: notes created,
links added, tasks completed, and session logs. This provides transparency and a
history of agent operations. The dashboard lives in the Systems folder and is
updated after significant operations.

### When to Use

- After completing a set of vault operations
- When the user asks what changes were made
- At the start/end of a session to log activity
- When creating a new vault setup

### Dashboard Location

```
09 Systems/Agent Dashboard.md
```

### Full Dashboard Template

```markdown
---
title: Agent Dashboard
date: 2026-02-12
type: system
status: active
tags:
  - dashboard
  - system
  - agent
aliases:
  - Dashboard
---

# Agent Dashboard

Central tracking for Claude Code activity in this vault.

## Session Log

### 2026-02-12

**Session Summary:** Initial vault setup and organization.

| Time | Action | Details |
|------|--------|---------|
| — | Notes Created | 3 new research notes in 03 Resources/ |
| — | Templates Used | Research Note v1, Project v1 |
| — | Links Added | 8 wiki-links across 4 notes |
| — | Tags Applied | machine-learning, research, project |

---

## Notes Created

| Date | Note | Location | Template |
|------|------|----------|----------|
| 2026-02-12 | [[Machine Learning Basics]] | 03 Resources/ | Research Note v1 |
| 2026-02-12 | [[Build Personal Website]] | 01 Projects/ | Project v1 |
| 2026-02-12 | [[Transformer Architecture Research]] | 03 Resources/ | Research Note v1 |

## Links Added

| Date | Source | Target | Context |
|------|--------|--------|---------|
| 2026-02-12 | Machine Learning Basics | Deep Learning Fundamentals | Related section |
| 2026-02-12 | Transformer Architecture Research | Neural Network Architectures | Related section |

## Tasks Completed

| Date | Task | Project | Status |
|------|------|---------|--------|
| 2026-02-12 | Create initial research notes | Vault Setup | done |
| 2026-02-12 | Set up project tracking | Vault Setup | done |

## Vault Statistics

| Metric | Count |
|--------|-------|
| Total Notes | — |
| Projects (active) | — |
| Areas | — |
| Resources | — |
| Archived | — |

*Last updated: 2026-02-12*
```

### Updating the Dashboard

After creating notes or making changes, update the dashboard:

```
# Add a new session entry
Edit: /path/to/vault/09 Systems/Agent Dashboard.md
  old_string: "## Session Log\n\n### 2026-02-12"
  new_string: "## Session Log\n\n### 2026-02-12 (Session 2)\n\n**Session Summary:** Added literature notes and updated project status.\n\n| Time | Action | Details |\n|------|--------|---------|\\n| — | Notes Created | 2 literature notes |\n| — | Status Updates | 1 project moved to review |\n\n---\n\n### 2026-02-12"
```

#### Add a New Note Entry

```
Edit: /path/to/vault/09 Systems/Agent Dashboard.md
  old_string: "| 2026-02-12 | [[Transformer Architecture Research]] | 03 Resources/ | Research Note v1 |"
  new_string: "| 2026-02-12 | [[Transformer Architecture Research]] | 03 Resources/ | Research Note v1 |\n| 2026-02-12 | [[Attention Is All You Need]] | 03 Resources/ | Literature Note v1 |"
```

#### Update Vault Statistics

Use Glob to count notes and update the statistics table:

```
# Count notes per folder
Glob: "01 Projects/*.md"   -> count for Projects
Glob: "02 Areas/*.md"      -> count for Areas
Glob: "03 Resources/*.md"  -> count for Resources
Glob: "99 Archive/*.md"    -> count for Archived
Glob: "**/*.md"            -> count for Total Notes

# Then update the table
Edit: old_string="| Total Notes | — |"
      new_string="| Total Notes | 47 |"
```

### Dataview-Powered Dashboard (When Installed)

If Dataview is installed, replace the static tables with dynamic queries:

````markdown
## Active Projects

```dataview
TABLE status, deadline, priority
FROM "01 Projects"
WHERE type = "project" AND status = "active"
SORT deadline ASC
```

## Recently Modified

```dataview
TABLE file.mtime AS "Modified", type
FROM ""
WHERE type != "daily"
SORT file.mtime DESC
LIMIT 10
```

## Task Overview

```dataview
TASK
FROM "01 Projects"
WHERE !completed
LIMIT 20
```
````

### Tips

- **Update consistently** — Update the dashboard after every significant operation,
  not just at the end of a session.
- **Keep session logs brief** — Use the summary format (table with action/details)
  rather than verbose descriptions.
- **Static tables work fine** — The static Markdown tables are perfectly functional
  without Dataview. They just require manual updates.
- **Wiki-links in tables** — Use `[[Note Name]]` in the dashboard tables to create
  clickable links in Obsidian.

---

## 9. auto-link-tag — Automated Linking & Tagging

### Description

Obsidian's power comes from its knowledge graph — the web of connections between
notes via wiki-links (`[[Note Name]]`) and tags. This pattern automates the process
of discovering and inserting links, suggesting tags, and maintaining Maps of Content
(MOCs) that serve as navigational hubs.

### When to Use

- After creating a new note, scan for linkable terms
- When the user asks to improve vault connectivity
- When building or updating MOC notes
- During periodic vault maintenance

### Auto-Linking Workflow

#### Step 1: Build a Title Index

Scan the vault for all note titles to know what can be linked.

```
# Get all note files
Glob: "**/*.md"

# Extract filenames (these become potential link targets)
# Result: list of note titles like "Machine Learning Basics", "Deep Learning Fundamentals", etc.
```

#### Step 2: Scan New Note for Linkable Terms

```
# Read the new note
Read: /path/to/vault/03 Resources/Neural Networks Overview.md

# Check if any existing note titles appear in the content
# For each match, insert a wiki-link
```

#### Step 3: Insert Links

```
Edit: /path/to/vault/03 Resources/Neural Networks Overview.md
  old_string: "builds on the transformer architecture"
  new_string: "builds on the [[Transformer Architecture Research|transformer architecture]]"
```

Use the aliased link format `[[Actual Note Name|display text]]` when the note title
does not match the natural phrasing in the sentence.

#### Step 4: Add Backlinks in Related Notes

When you link from Note A to Note B, also add a reference from Note B back to Note A:

```
Edit: /path/to/vault/03 Resources/Transformer Architecture Research.md
  old_string: "## Related\n\n-"
  new_string: "## Related\n\n- [[Neural Networks Overview]]"
```

### Auto-Tagging Strategy

#### Analyze Content for Tags

Read the note content and identify topic keywords. Cross-reference against existing
tags in the vault.

```
# Find all tags currently used in the vault
Grep: pattern="^tags:" glob="**/*.md" output_mode="content" -A=5

# Common tag patterns to look for:
# - Technical topics: machine-learning, deep-learning, python, web-dev
# - Note types: research, project, reference, lecture
# - Status: in-progress, review-needed, important
# - Areas: career, health, finance, learning
```

#### Apply Tags

```
Edit: /path/to/vault/03 Resources/Neural Networks Overview.md
  old_string: "tags:\n  - neural-networks"
  new_string: "tags:\n  - neural-networks\n  - deep-learning\n  - machine-learning\n  - fundamentals"
```

### Map of Content (MOC) Generation

MOCs are index notes that aggregate links to related notes by topic. They serve as
navigational hubs in the knowledge graph.

#### MOC Template

```markdown
---
title: "Machine Learning MOC"
date: 2026-02-12
type: moc
status: active
tags:
  - moc
  - machine-learning
aliases:
  - ML MOC
  - Machine Learning Index
---

# Machine Learning MOC

Map of Content for machine learning topics in this vault.

## Fundamentals

- [[Machine Learning Basics]]
- [[Neural Networks Overview]]
- [[Deep Learning Fundamentals]]

## Architectures

- [[Transformer Architecture Research]]
- [[Neural Network Architectures]]

## Applications

- [[Natural Language Processing]]
- [[Computer Vision Basics]]

## Papers & Literature

- [[Attention Is All You Need]]

## Projects

- [[ML Research Paper]]

---

*Auto-generated and maintained by Claude Code. Last updated: 2026-02-12.*
```

#### Generating a MOC from Existing Notes

```
# Step 1: Find all notes related to a topic
Grep: pattern="machine.learning|deep.learning|neural.network"
  path="/path/to/vault"
  output_mode="files_with_matches"

# Step 2: Read each matched note to understand its content and categorize it

# Step 3: Write the MOC with categorized links
Write to: /path/to/vault/03 Resources/Machine Learning MOC.md
```

#### Updating an Existing MOC

When new notes are created, add them to relevant MOCs:

```
# Check if the note fits any existing MOC
Grep: pattern="type: moc" glob="**/*.md" output_mode="files_with_matches"

# Read each MOC to see if the new note belongs
# Add the link in the appropriate section
Edit: /path/to/vault/03 Resources/Machine Learning MOC.md
  old_string: "## Fundamentals\n\n- [[Machine Learning Basics]]"
  new_string: "## Fundamentals\n\n- [[Machine Learning Basics]]\n- [[Statistical Learning Theory]]"
```

### Tips

- **Do not over-link** — Link to notes that are genuinely related, not every possible
  match. A note about "Python" does not need to link to every note that mentions
  Python in passing.
- **Use aliased links** — When the note title does not fit naturally in a sentence,
  use `[[Actual Title|display text]]`.
- **Bidirectional links** — When linking A to B, also link B back to A in its Related
  section. Obsidian shows backlinks automatically, but explicit links in the Related
  section are more visible.
- **MOC maintenance** — Update MOCs whenever you create notes in their topic area.
  A stale MOC is worse than no MOC.
- **Tag taxonomy** — Keep a consistent tag vocabulary. Use kebab-case (`machine-learning`
  not `Machine Learning` or `machineLearning`). Check existing tags before inventing
  new ones.

---

## 10. cli-tool-selection — Decision Framework

### Description

Multiple tools can interact with an Obsidian vault. This pattern provides a decision
framework for choosing the right tool based on the task requirements, what is
installed, and the trade-offs involved. The key principle: start with the simplest
tool that works, and escalate only when needed.

### Decision Tree — Updated to 3-Tier Hybrid Architecture

```
START: What do I need to do?
  |
  +--> Create, read, edit, delete note CONTENT?
  |      |
  |      YES --> Tier 1: Direct File Operations
  |              - Read/Write/Edit/Glob/Grep
  |              - Always available, no dependencies
  |              - STOP. This handles all CRUD.
  |
  +--> Discover vault structure, find orphans, query backlinks,
  |    aggregate tags/properties, search indexed content?
  |      |
  |      YES --> Tier 2: Obsidian CLI v1.12
  |              - /Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic [command]
  |              - Requires Obsidian 1.12+ running
  |              - If Obsidian not running → fall back to Tier 1 (slower)
  |
  +--> Open a note in Obsidian UI, trigger a search panel, invoke a command?
         |
         YES --> Tier 3: obsidian:// URI Scheme
                 - open "obsidian://open?vault=Agentic&file=..."
                 - Requires Obsidian running
```

### Updated Comparison Table

| Tier | Tool | When | Speed | Requires |
|------|------|------|-------|----------|
| **1** | **Direct File Ops** | CRUD, content editing, bulk writes | Instant | Claude Code in vault |
| **2** | **Obsidian CLI v1.12** | Discovery, graph queries, metadata | <1s indexed | Obsidian 1.12+ running |
| **3** | **obsidian:// URIs** | UI control, open notes, trigger commands | Low | Obsidian running |
| — | REST API | Structured JSON responses (if plugin installed) | Low | obsidian-local-rest-api |
| — | MCP Servers | Cross-tool AI agent integration | Medium | MCP server configured |

### Performance Comparison

| Operation | CLI v1.12 | Direct File Ops | Speedup |
|-----------|-----------|-----------------|---------|
| Orphan detection | 0.26s | 15.6s (grep) | 60x |
| Search | 0.32s | 1.6s (ripgrep) | 5x |
| Backlinks | 0.1s | Impossible* | — |
| Tag aggregation | 0.2s | ~3s (parse all YAML) | 15x |

*Backlink queries require knowing which files link TO a target. Direct file ops can grep for [[target]] but miss aliases and unresolved links.

### Combining Tools

The most effective workflows combine multiple patterns:

#### Workflow: Create Research Note with Full Integration

```
1. Read template            (Pattern 5: templater-automation)
2. Substitute variables     (Pattern 5)
3. Write note to vault      (Tier 1: Direct File Ops)
4. Add frontmatter fields   (Pattern 6: dataview-ready-notes)
5. Scan for wiki-links      (Pattern 9: auto-link-tag)
6. Insert links             (Tier 1: Direct File Ops)
7. Update MOC               (Pattern 9)
8. Update dashboard         (Pattern 8: agentic-dashboard)
9. Open in Obsidian         (Tier 3: obsidian:// URI)
```

#### Workflow: Vault Maintenance Session

```
1. Commit current state     (Pattern 7: git-vault-sync)
2. Detect orphan notes      (CLI: obsidian vault=Agentic orphans)
3. Detect dead-end notes    (CLI: obsidian vault=Agentic deadends)
4. Check unresolved links   (CLI: obsidian vault=Agentic unresolved)
5. Fix issues via file ops  (Pattern 1: vault-file-crud)
6. Refresh dashboard stats  (Pattern 8: agentic-dashboard)
7. Update MOCs              (Pattern 9: auto-link-tag)
8. Commit changes           (Pattern 7)
```

#### Workflow: Bulk Import and Organize

```
1. Commit checkpoint        (Pattern 7)
2. Create notes from data   (Tier 1: Direct File Ops + Pattern 5)
3. Apply consistent tags    (Pattern 9)
4. Build wiki-links         (Pattern 9)
5. Create/update MOC        (Pattern 9)
6. Update dashboard         (Pattern 8)
7. Commit results           (Pattern 7)
```

### Tips

- **Default to direct file ops** — If you are uncertain which tool to use, direct
  file operations are always correct. They are the most reliable and require zero
  setup.
- **Do not over-engineer** — Do not set up REST API, MCP, or external CLIs when
  Read/Write/Edit/Glob/Grep can do the job. Simpler is better.
- **Check before assuming** — Always verify what plugins are installed before
  attempting to use their features. Read `.obsidian/community-plugins.json`.
- **Combine patterns naturally** — Most real tasks use 2-4 patterns together. The
  decision framework is about choosing the right primary tool, not limiting yourself
  to one pattern.
- **User preferences matter** — Some users prefer opening notes in Obsidian after
  creation; others prefer staying in the terminal. Ask or adapt based on context.

---

## 11. cli-discovery — Obsidian CLI v1.12 Command Reference

### Description

Obsidian v1.12 includes a native CLI accessible at `/Applications/Obsidian.app/Contents/MacOS/Obsidian`. This CLI communicates with the running Obsidian instance via IPC, providing indexed access to vault metadata, graph data, and plugin management. CLI commands are 10-60x faster than grep-based alternatives because they query Obsidian's in-memory index directly.

### Prerequisites

- Obsidian 1.12+ must be installed and running
- Verify with: `/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic version`
- `vault=Agentic` MUST be the first parameter after the binary path

### When to Use

Use the CLI for **discovery and intelligence** operations — finding orphans, querying backlinks, aggregating tags, searching indexed content. Use direct file ops for **CRUD** operations — creating, reading, editing, deleting notes.

### Command Reference

#### Search (indexed)

```bash
# Basic search
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic search query="machine learning"

# Limited results
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic search query="transformer" limit=5

# JSON output
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic search query="status: active" format=json
```

#### Orphan Detection

```bash
# List all orphan notes (no incoming links)
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic orphans

# Get total count only
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic orphans total
```

#### Dead-End Detection

```bash
# List notes with no outgoing links
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic deadends

# Total count
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic deadends total
```

#### Unresolved Links

```bash
# List all unresolved [[links]]
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic unresolved

# Total count
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic unresolved total

# With per-file counts
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic unresolved counts

# Verbose: show which files contain each unresolved link
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic unresolved verbose
```

#### Tags

```bash
# List all tags in vault
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic tags all

# With counts, sorted by frequency
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic tags all counts sort=count
```

#### Properties

```bash
# List all frontmatter properties
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic properties all

# With totals and counts, sorted
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic properties all total sort=count counts
```

#### Backlinks

```bash
# Find all notes linking TO a specific note
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic backlinks path="03 Resources/Machine Learning Basics.md"
```

#### Outgoing Links

```bash
# Find all notes a specific note links TO
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic links path="03 Resources/Machine Learning Basics.md"
```

#### File Metadata

```bash
# Get detailed metadata for a note (size, dates, word count, link count)
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic file path="03 Resources/Machine Learning Basics.md"
```

#### Tasks

```bash
# All tasks across vault
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic tasks all

# Only incomplete tasks
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic tasks all todo

# Only completed tasks
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic tasks all done

# Total count
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic tasks all total
```

#### Plugin Management

```bash
# List enabled community plugins with versions
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic plugins enabled filter=community versions

# Install and enable a plugin
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic plugin:install id=dataview enable
```

#### Note Creation via CLI

```bash
# Create a note from a template
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic create name="New Research Note" path="03 Resources" template="Research Note v1"

# Append to daily note
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic daily:append content="- New task added by Claude"

# Read and resolve a template
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic template:read name="Research Note v1" resolve title="Quantum Computing"
```

### Hybrid Workflow Example: Vault Health Check

This is the canonical example of the 3-tier hybrid architecture in action:

```
# Step 1: CLI discovers problems (Tier 2)
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic orphans
# Output: list of orphan notes

/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic deadends
# Output: list of dead-end notes

/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic unresolved
# Output: list of unresolved links

# Step 2: Direct file ops fix the problems (Tier 1)
# For each orphan: Read the note, identify related notes, Edit to add [[links]]
# For each dead-end: Read the note, suggest outgoing links, Edit to add them
# For each unresolved link: Create the missing note or fix the link text

# Step 3: URI opens the results for review (Tier 3)
# open "obsidian://open?vault=Agentic&file=09%20Systems%2FAgent%20Dashboard"
```

### Tips

- **vault= is always first** — `/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic search query="test"` (correct) vs `/Applications/Obsidian.app/Contents/MacOS/Obsidian search query="test" vault=Agentic` (wrong vault)
- **Paths use quotes** — `path="03 Resources/Note.md"` not `path=03 Resources/Note.md`
- **CLI for discovery, file ops for CRUD** — Never use CLI to create notes when Write tool is available. CLI note creation is for template-based creation only.
- **Fallback ready** — If Obsidian is not running, all CLI operations fall back to Glob/Grep (slower but functional for most queries). Backlinks have no file-op fallback.
