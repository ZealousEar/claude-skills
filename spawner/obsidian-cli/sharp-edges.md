# Sharp Edges: Obsidian CLI Automation

Deep-dive documentation for every known pitfall when automating Obsidian vaults
from the command line or programmatic tooling (Claude Code, scripts, MCP servers).

Each edge includes real-world scenarios, root causes, detection, fixes, and prevention.

---

## 1. uri-encoding-spaces (HIGH)

### What Happens
You construct an `obsidian://open?vault=Agentic&file=00 Inbox/Research Note` URI
and execute it. One of two things occurs: Obsidian opens the wrong file, or nothing
happens at all. No error is shown. The URI silently breaks at the first unencoded space.

### Why It Happens
The `obsidian://` protocol handler follows standard URI rules. Spaces are not valid
in URI path or query components. The OS URI dispatcher truncates or misparses the
string at the first space character. macOS may pass the full string in some contexts
but encode it differently than expected, leading to a file path mismatch.

The PARA folder structure makes this especially common because folders like
`00 Inbox`, `01 Projects`, `02 Areas`, `03 Resources`, `10 School`, and
`09 Systems` all contain spaces.

### How to Detect
- Search for `obsidian://` strings that contain literal spaces
- Pattern: `obsidian://[^"'\s]*\s+[^"'\s]*`
- Test: if a URI works for `Agentic` (no spaces) but fails for a subfolder path

### How to Fix

Bad:
```
obsidian://open?vault=Agentic&file=00 Inbox/Research Note
```

Good:
```
obsidian://open?vault=Agentic&file=00%20Inbox/Research%20Note
```

In code:
```javascript
// JavaScript
const uri = `obsidian://open?vault=Agentic&file=${encodeURIComponent(filePath)}`;
```

```python
# Python
from urllib.parse import quote
uri = f"obsidian://open?vault=Agentic&file={quote(file_path)}"
```

```bash
# Bash — use printf or sed
encoded=$(echo "00 Inbox/Research Note" | sed 's/ /%20/g')
open "obsidian://open?vault=Agentic&file=${encoded}"
```

### How to Prevent
- Create a URI builder helper that always encodes path components
- Never concatenate raw file paths into URI strings
- Encode the entire file path component, not just the filename
- Remember: folder names in PARA structure contain spaces too
- Test with the longest, most deeply nested path in the vault

---

## 2. frontmatter-corruption (CRITICAL)

### What Happens
A script writes or modifies a note's YAML frontmatter. Afterward, Obsidian's
metadata cache becomes corrupted for that file. Tags stop appearing in tag search,
properties panel shows errors, Templater cannot read variables, and any plugin
relying on frontmatter metadata (all of them) breaks for that note.

Common corruption patterns:
- Missing closing `---` delimiter
- Tabs instead of spaces in YAML indentation
- Duplicate keys (two `tags:` entries)
- Unquoted strings containing colons (e.g., `title: My Note: A Story`)
- Invalid YAML list syntax (mixing `- item` and `[item]` styles)

### Why It Happens
String concatenation to build YAML is fragile. A missing newline, a value
containing a colon or quote character, or appending to existing frontmatter
without parsing it first — any of these silently produce invalid YAML.

Obsidian's frontmatter parser is strict about the `---` delimiters appearing
on their own lines with no trailing whitespace. It is also strict about YAML
validity — a single syntax error causes the entire frontmatter block to be
treated as regular content.

### How to Detect
- Parse the frontmatter with a YAML library and check for errors
- Verify the file starts with `---\n` and has a matching `---\n`
- Check for tab characters between the delimiters
- Look for duplicate keys in the YAML block
- Obsidian shows a red "Invalid frontmatter" banner in the properties panel

Pattern to validate:
```python
import yaml

def validate_frontmatter(content: str) -> bool:
    if not content.startswith('---\n'):
        return False
    end = content.find('\n---\n', 4)
    if end == -1:
        end = content.find('\n---', 4)
        if end == -1:
            return False
    fm_text = content[4:end]
    try:
        data = yaml.safe_load(fm_text)
        return isinstance(data, dict)
    except yaml.YAMLError:
        return False
```

### How to Fix
Step 1: Read the entire file content.
Step 2: Extract existing frontmatter using `---` delimiters.
Step 3: Parse it with a proper YAML library.
Step 4: Modify the parsed dictionary (not the raw string).
Step 5: Serialize back to YAML with the library.
Step 6: Reassemble: `---\n` + serialized YAML + `---\n` + body content.
Step 7: Write the complete file atomically.

Bad approach:
```python
# NEVER do this
content = f"""---
title: {title}
tags: {tags}
---
{body}"""
```

Good approach:
```python
import yaml

frontmatter = {
    'title': title,
    'tags': tags,
    'created': date_str,
}
fm_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
content = f"---\n{fm_str}---\n\n{body}"
```

### How to Prevent
- Always use a YAML library (PyYAML, js-yaml, ruamel.yaml) for frontmatter
- Never build frontmatter through string concatenation or f-strings
- Read-modify-write: parse existing frontmatter before changing it
- Validate the output YAML before writing to disk
- Use `yaml.dump()` with `default_flow_style=False` for readable output
- Quote strings that contain colons, brackets, or other YAML special chars

---

## 3. rest-api-self-signed-cert (HIGH)

### What Happens
You install the Local REST API plugin and try to call it:
```bash
curl https://localhost:27124/vault/
```
The request fails with an SSL certificate verification error. Every HTTP client
rejects the connection: curl, wget, fetch, axios, Python requests, httpx.

Error messages vary by client:
- curl: `SSL certificate problem: self-signed certificate`
- Python requests: `SSLError: CERTIFICATE_VERIFY_FAILED`
- Node fetch: `UNABLE_TO_VERIFY_LEAF_SIGNATURE`
- axios: `Error: self signed certificate`

### Why It Happens
The Local REST API plugin generates a self-signed HTTPS certificate on first run.
No certificate authority has signed it, so all TLS-aware HTTP clients correctly
reject it as untrusted. This is by design — the plugin uses HTTPS to protect the
API key in transit, even on localhost.

### How to Detect
- Any SSL/TLS error when calling `https://localhost:27124`
- Works with `--insecure` / `verify=False` but not without
- The plugin's data.json contains a generated certificate

### How to Fix
Each client has its own bypass mechanism:

```bash
# curl
curl --insecure https://localhost:27124/vault/

# wget
wget --no-check-certificate https://localhost:27124/vault/
```

```python
# Python requests
import requests
response = requests.get(
    'https://localhost:27124/vault/',
    headers={'Authorization': 'Bearer YOUR_API_KEY'},
    verify=False
)

# Suppress the InsecureRequestWarning
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
```

```javascript
// Node.js — set environment variable before any imports
process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';

// Or per-request with https agent
const https = require('https');
const agent = new https.Agent({ rejectUnauthorized: false });
fetch('https://localhost:27124/vault/', { agent });
```

### How to Prevent
- Prefer direct filesystem operations when Claude Code runs inside the vault
- Direct file read/write is faster, more reliable, and has no auth overhead
- Use REST API only for operations that require Obsidian's runtime (e.g., triggering
  commands, reading rendered Dataview output)
- Note: The Local REST API plugin is NOT currently installed in this vault

---

## 4. concurrent-file-access (HIGH)

### What Happens
Claude Code writes to a note that is currently open and visible in Obsidian's editor.
Obsidian detects the external change and either:
1. Shows a "File changed on disk, do you want to reload?" dialog
2. Auto-reloads and overwrites the user's unsaved edits
3. The user saves in Obsidian, overwriting Claude's changes
4. Both write simultaneously, producing a corrupted merge of content

In the worst case, the user loses their in-progress edits with no undo path.

### Why It Happens
Obsidian watches the filesystem for changes via `fs.watch`. When a file changes
externally, Obsidian reloads it. But if the user has unsaved modifications in the
editor buffer, there is a race condition. Obsidian's auto-save (default: 2 seconds)
compounds the problem — it may save the old buffer content right after Claude writes
the new content.

### How to Detect
- File content differs from what was just written (read-after-write check)
- Obsidian shows the "file changed on disk" modal
- File modification time is newer than expected after a write
- Content appears to be a partial merge of old and new versions

### How to Fix
1. Before writing: check the file's `mtime` and note it
2. Write the new content
3. After writing: check `mtime` again — if it changed unexpectedly, another
   process (Obsidian) also wrote to the file
4. If conflict detected: re-read and reconcile

```python
import os, time

def safe_write(path, content):
    mtime_before = os.path.getmtime(path) if os.path.exists(path) else 0
    with open(path, 'w') as f:
        f.write(content)
    time.sleep(0.1)  # Brief pause for FS events to propagate
    mtime_after = os.path.getmtime(path)
    actual = open(path).read()
    if actual != content:
        raise RuntimeError(f"Concurrent write detected on {path}")
```

### How to Prevent
- Create NEW files rather than editing files the user might have open
- If editing existing files, pick ones not currently visible in the Obsidian editor
- Write to `00 Inbox/` as a staging area — new files there won't be open
- Use atomic write: write to a temp file, then `os.rename()` into place
- Avoid editing files during active user sessions when possible
- Communicate with the user: "I am about to modify X — please close it first"

---

## 5. templater-syntax-in-content (MEDIUM)

### What Happens
Claude writes a note containing the text `<% tp.date.now("YYYY-MM-DD") %>` as an
example or documentation snippet. When the user opens that note, Templater executes
the code and replaces the example text with today's date. The original content is
permanently altered.

More dangerous: `<% tp.file.rename("new name") %>` in content would rename the file
when opened. `<% tp.file.move("path") %>` would move it.

### Why It Happens
Templater (which IS installed in this vault) processes `<% %>` blocks in files
when they are opened or when "Templater: Replace templates in the active file"
is triggered. It does not distinguish between template files in the templates
folder and regular notes — any file with Templater syntax will be processed.

The Templater plugin configuration may have "Trigger Templater on new file creation"
enabled, which auto-processes any newly created file.

### How to Detect
- Search for `<%` and `%>` patterns outside the `09 Systems/Templates/` directory
- Pattern: files matching `<%.+%>` not in the templates folder
- Check Templater settings for auto-trigger configuration

```bash
# Find Templater syntax outside templates directory
grep -r "<%.*%>" "/path/to/vault/" \
  --include="*.md" \
  --exclude-dir=".obsidian" \
  --exclude-dir="09 Systems/Templates" \
  -l
```

### How to Fix
Escape Templater syntax in regular notes:

Option 1 — Code block (preferred):
````markdown
```
<% tp.date.now("YYYY-MM-DD") %>
```
````

Option 2 — Inline code:
```markdown
Use `<% tp.date.now() %>` in your templates.
```

Option 3 — Zero-width space insertion:
```markdown
<​% tp.date.now() %​>  <!-- zero-width space after < and before > -->
```

### How to Prevent
- Never write raw `<% %>` syntax in non-template files
- When Claude generates content referencing Templater, always wrap in code blocks
- Substitute template variables BEFORE writing to disk:
  ```python
  # Instead of writing: <% tp.date.now("YYYY-MM-DD") %>
  # Write the actual value:
  from datetime import date
  content = f"Created: {date.today().isoformat()}"
  ```
- Only place actual Templater templates in `09 Systems/Templates/`
- Check if "Trigger Templater on new file creation" is enabled and account for it

---

## 6. large-vault-search-performance (MEDIUM)

### What Happens
A grep or find command searching the vault takes 30+ seconds instead of under
1 second. Results include thousands of matches from `.obsidian/plugins/` — minified
JavaScript, CSS, JSON config files, and cached data that are completely irrelevant
to the search.

### Why It Happens
The `.obsidian/` directory contains:
- Every installed plugin's source code (JS bundles, often 1MB+ each)
- Plugin configuration files (data.json per plugin)
- Theme CSS files
- Obsidian's internal cache, including metadata and file index
- Workspace state, hotkey config, appearance settings

For a vault with a few plugins, `.obsidian/` can easily contain 10,000+ files
totaling hundreds of megabytes. The `terminal`, `calendar`, and `templater-obsidian`
plugins each bring their own bundle of files.

### How to Detect
- Search operations take more than 2-3 seconds on a normal vault
- Search results include paths containing `.obsidian/`
- `du -sh .obsidian/` reveals unexpectedly large size

### How to Fix
Always exclude non-content directories:

```bash
# Grep — use glob exclusions
grep -r "search term" "/path/to/vault/" \
  --include="*.md" \
  --exclude-dir=".obsidian" \
  --exclude-dir=".git" \
  --exclude-dir=".trash" \
  --exclude-dir="node_modules"

# ripgrep — much faster with built-in ignore support
rg "search term" "/path/to/vault/" \
  --type md \
  --glob '!.obsidian/**' \
  --glob '!.trash/**'

# find — exclude hidden directories
find "/path/to/vault/" \
  -name "*.md" \
  -not -path "*/.obsidian/*" \
  -not -path "*/.git/*" \
  -not -path "*/.trash/*"
```

When using Claude Code's Grep tool:
```
pattern: "search term"
glob: "*.md"
path: "/path/to/vault/"
```
The Grep tool respects `.gitignore` by default, which helps if `.obsidian/` is listed.

### How to Prevent
- Default to `--include="*.md"` or `--type md` for all vault searches
- Create a shell alias or function that includes proper exclusions
- Add `.obsidian/`, `.git/`, `.trash/` to `.gitignore` (helps tools that respect it)
- When using Claude Code tools, always specify the `glob: "*.md"` parameter
- Consider the vault's `.obsidian/` size when planning search strategies

---

## 7. git-obsidian-workspace-conflicts (HIGH)

### What Happens
Every `git status` shows `.obsidian/workspace.json` as modified, even though you
did not intentionally change any Obsidian settings. Pulling from a remote produces
merge conflicts in this file. The conflicts are unintelligible JSON with cursor
positions, scroll states, and pane layouts — impossible to meaningfully merge.

If multiple people (or devices) use the same vault via git, workspace.json conflicts
occur on virtually every pull.

### Why It Happens
Obsidian writes to `workspace.json` on nearly every user interaction:
- Opening or closing a file updates the file list
- Scrolling updates the scroll position
- Clicking in a pane updates the active pane state
- Resizing panes updates layout dimensions
- Opening settings, command palette, or any modal

This file changes dozens of times per minute during active use. It is per-device
state that has no value in version control.

### How to Detect
- `git status` always shows `.obsidian/workspace.json` as modified
- `git diff .obsidian/workspace.json` shows position/scroll changes
- Merge conflicts in `.obsidian/workspace.json` during pull/rebase

### How to Fix

If already tracked:
```bash
# Stop tracking but keep the local file
git rm --cached ".obsidian/workspace.json"
git rm --cached ".obsidian/workspace-mobile.json" 2>/dev/null

# Add to .gitignore
echo ".obsidian/workspace.json" >> .gitignore
echo ".obsidian/workspace-mobile.json" >> .gitignore

# Commit the removal and ignore rule
git add .gitignore
git commit -m "Stop tracking Obsidian workspace files"
```

### How to Prevent

Recommended `.gitignore` for an Obsidian vault:
```gitignore
# Obsidian workspace (changes on every click — never merge-worthy)
.obsidian/workspace.json
.obsidian/workspace-mobile.json

# Obsidian cache
.obsidian/cache

# System files
.trash/
.DS_Store

# Plugin data that may contain secrets
.obsidian/plugins/obsidian-local-rest-api/data.json

# Node/dev artifacts if running tools inside the vault
node_modules/
```

Set this up BEFORE the first commit. Removing tracked files after the fact requires
`git rm --cached` and coordination with everyone who clones the repo.

---

## 8. mcp-api-key-exposure (CRITICAL)

### What Happens
API keys, tokens, or other secrets are committed to the git repository. This includes:
- Local REST API plugin's API key in `.obsidian/plugins/obsidian-local-rest-api/data.json`
- MCP server configuration with API tokens
- Environment files with LLM API keys
- Bearer tokens hardcoded in automation scripts stored in the vault

Once pushed to a remote (even a private one), the secret is in git history permanently
unless the history is rewritten.

### Why It Happens
Obsidian plugins store their configuration in `.obsidian/plugins/<plugin-name>/data.json`.
This is a convenient location for the plugin but a dangerous one for version control.
The REST API plugin stores its API key in plaintext in this file.

Automation scripts or MCP configurations stored inside the vault may contain secrets
for convenience. A `git add .` or `git add -A` will capture everything.

### How to Detect

```bash
# Search for common secret patterns in tracked files
git ls-files | xargs grep -l -i \
  -e "api_key" \
  -e "api-key" \
  -e "apikey" \
  -e "Bearer " \
  -e "sk-[a-zA-Z0-9]" \
  -e "token.*=" \
  -e "secret.*=" \
  2>/dev/null

# Check if REST API plugin config is tracked
git ls-files | grep "obsidian-local-rest-api/data.json"

# Check for .env files
git ls-files | grep -E "\.env"
```

### How to Fix
1. Remove from tracking (keep local file):
   ```bash
   git rm --cached .obsidian/plugins/obsidian-local-rest-api/data.json
   git rm --cached .env 2>/dev/null
   ```
2. Add to `.gitignore` (see edge 7 for complete gitignore)
3. Rotate ALL compromised keys immediately — removal from git does not purge history
4. If pushed to remote: use `git filter-branch` or BFG Repo Cleaner to purge history

### How to Prevent
- Add sensitive paths to `.gitignore` before first commit
- Use environment variables for secrets, not files in the vault
- Never use `git add .` or `git add -A` — always add specific files
- Review `git diff --cached` before every commit
- Files to always gitignore:
  ```
  .env
  .env.*
  *.key
  *.pem
  .obsidian/plugins/obsidian-local-rest-api/data.json
  ```
- Store automation configs outside the vault directory

---

## 9. wiki-link-case-sensitivity (MEDIUM)

### What Happens
You create a note and link to it with `[[research note]]`. On macOS, this works
perfectly — macOS's filesystem (APFS) is case-insensitive by default, so
`Research Note.md` matches `research note`. You commit and push.

A collaborator clones on Linux (ext4, case-sensitive). The link `[[research note]]`
shows as an unresolved link because the file is actually named `Research Note.md`.
All internal cross-references break silently.

### Why It Happens
macOS APFS defaults to case-insensitive (but case-preserving). Linux ext4 is
case-sensitive. Obsidian resolves wiki-links by matching against the filesystem.
On macOS, `[[research note]]` finds `Research Note.md` through the OS's
case-insensitive lookup. On Linux, it does not find it because the case does not
match.

This also affects:
- CI/CD pipelines running on Linux containers
- GitHub Actions processing vault content
- Docker-based tools operating on the vault

### How to Detect
- Compare wiki-link text (case-insensitive) against actual filenames (exact case)
- Run a script that finds all `[[...]]` links and verifies exact-case file matches
- Test on a case-sensitive filesystem (Linux or macOS with case-sensitive APFS)

```bash
# Find potential mismatches: extract wiki links and compare to actual files
grep -ohr '\[\[[^]|#]*' "/path/to/vault/" \
  --include="*.md" \
  --exclude-dir=".obsidian" | \
  sed 's/\[\[//' | sort -u
```

### How to Fix
- Match the EXACT case of the target filename in every wiki-link
- Use Claude Code's Glob tool to find the actual filename before creating a link:
  ```
  # Find exact filename
  Glob: pattern="**/Research Note.md"
  # Then use: [[Research Note]] — matching the actual file's casing
  ```

### How to Prevent
- Establish a consistent naming convention (e.g., Title Case for all notes)
- Before writing a wiki-link, always resolve the actual filename first
- Use Glob to find the exact file path and extract the proper casing
- Document the naming convention in a vault style guide
- Consider this when creating notes: pick a casing style and stick to it

---

## 10. advanced-uri-plugin-missing (MEDIUM)

### What Happens
A script or automation tries to use the Advanced URI plugin:
```
obsidian://advanced-uri?vault=Agentic&commandid=templater:create-new-note
```
Nothing happens. No error dialog, no notification, no log entry. The URI is
silently dropped by Obsidian because the `advanced-uri` plugin is not installed.

### Why It Happens
The `obsidian://` protocol handler is built into Obsidian itself. It handles a set
of core actions: `open`, `new`, `search`, `hook-get-address`. The Advanced URI
plugin registers the `advanced-uri` action. Without the plugin, that action is
simply unrecognized and ignored.

Currently installed plugins: `terminal`, `calendar`, `templater-obsidian`.
The Advanced URI plugin is NOT installed.

### How to Detect
Check the community plugins list before using any Advanced URI features:

```bash
# Check installed plugins
cat "/path/to/vault/.obsidian/community-plugins.json"
# Look for "obsidian-advanced-uri" in the array
```

```python
import json
plugins_path = "/path/to/vault/.obsidian/community-plugins.json"
with open(plugins_path) as f:
    plugins = json.load(f)
has_advanced_uri = "obsidian-advanced-uri" in plugins
```

### How to Fix
Use basic `obsidian://` URIs that work without any plugins:

| Advanced URI action | Basic equivalent |
|---|---|
| Open file | `obsidian://open?vault=Agentic&file=path/to/note` |
| Create new note | `obsidian://new?vault=Agentic&file=path/to/note&content=...` |
| Search | `obsidian://search?vault=Agentic&query=search+term` |
| Open daily note | Create the file directly via filesystem, then `obsidian://open` |
| Run command | No basic equivalent — use filesystem operations instead |
| Write to file | Direct filesystem write, no URI needed |

### How to Prevent
- Always check `community-plugins.json` before using plugin-specific URIs
- Build automation around core `obsidian://` actions and direct filesystem access
- Document which plugins are required for which automations
- Create a plugin-check utility function:
  ```python
  def has_plugin(vault_path: str, plugin_id: str) -> bool:
      import json
      plugins_file = f"{vault_path}/.obsidian/community-plugins.json"
      try:
          with open(plugins_file) as f:
              return plugin_id in json.load(f)
      except (FileNotFoundError, json.JSONDecodeError):
          return False
  ```

---

## 11. dataview-not-installed (MEDIUM)

### What Happens
Claude creates a dashboard note with Dataview queries:

````markdown
## Active Projects
```dataview
TABLE status, due-date
FROM "01 Projects"
WHERE status != "completed"
SORT due-date ASC
```
````

The user opens the note and sees the raw code block instead of a rendered table.
The dashboard is useless — it displays the query source code as a grey code block
rather than live query results.

### Why It Happens
Dataview is a community plugin that registers custom code block processors. Without
it installed, Obsidian treats `` ```dataview `` blocks as regular fenced code blocks
and renders them as monospace text. There is no fallback mechanism.

Dataview is NOT currently installed in this vault. The installed plugins are:
`terminal`, `calendar`, `templater-obsidian`.

### How to Detect
```bash
# Check for Dataview blocks in notes
grep -r '```dataview' "/path/to/vault/" \
  --include="*.md" \
  --exclude-dir=".obsidian" \
  -l

# Verify Dataview is not installed
cat "/path/to/vault/.obsidian/community-plugins.json" \
  | grep -c "dataview"
# Returns 0 if not installed
```

### How to Fix
Provide a dual-format pattern — a static table that is always readable, with an
optional Dataview query for dynamic updates if the plugin is installed later:

````markdown
## Active Projects

<!-- Static table — always renders correctly -->
| Project | Status | Due Date |
|---------|--------|----------|
| Vault Automation | In Progress | 2026-02-28 |
| Research Paper | Planning | 2026-03-15 |

<!-- Dynamic version — requires Dataview plugin
```dataview
TABLE status, due-date
FROM "01 Projects"
WHERE status != "completed"
SORT due-date ASC
```
-->
````

### How to Prevent
- Check for Dataview in `community-plugins.json` before writing Dataview queries
- Default to static Markdown tables which always render
- If Dataview is needed, document it as a dependency in the note itself
- Use the dual-format pattern: static table as primary, Dataview in HTML comment
- Claude should generate static content by reading actual files rather than writing
  queries that require a plugin to resolve
- Consider: Claude Code CAN read all vault files directly and build tables from data,
  making Dataview unnecessary for one-time report generation

---

## 12. path-with-special-chars (MEDIUM)

### What Happens
A note is created with a filename containing special characters:
- `Meeting Notes | 2026-02-12.md` (pipe character)
- `Chapter #3 — Introduction.md` (hash, em-dash)
- `Task [TODO] Review.md` (square brackets)
- `50% Complete.md` (percent sign)

Wiki-links to these files break because Obsidian uses these characters for link
syntax: `|` for aliases, `#` for heading references, `^` for block references,
`[` and `]` for the link brackets themselves.

CLI tools also struggle: `#` starts a comment in bash, `|` is a pipe, `[]` are
glob characters.

### Why It Happens
Obsidian's wiki-link syntax overloads several characters:
- `[[Note|Display Text]]` — pipe separates target from alias
- `[[Note#Heading]]` — hash links to a heading
- `[[Note^blockid]]` — caret links to a block
- `[[Note]]` — brackets are the link delimiters

If the filename itself contains these characters, the link parser cannot distinguish
between syntax and literal characters. There is no escaping mechanism in wiki-links.

On the filesystem side, most characters are technically allowed in filenames on
macOS and Linux (except `/` and null byte), but they cause problems with:
- Shell commands (unquoted paths break on spaces, pipes, etc.)
- URI encoding (each special char needs specific encoding)
- Git operations (some chars are problematic on Windows if vault is synced)
- Regular expressions (chars have special meaning in regex)

### How to Detect
```bash
# Find files with problematic characters
find "/path/to/vault/" \
  -name "*.md" \
  \( -name "*|*" -o -name "*#*" -o -name "*\[*" -o -name "*\]*" \
     -o -name "*^*" -o -name "*%*" \) \
  -not -path "*/.obsidian/*"
```

```python
import re
UNSAFE_PATTERN = re.compile(r'[|#\^\[\]%{}\\<>]')

def has_unsafe_chars(filename: str) -> bool:
    return bool(UNSAFE_PATTERN.search(filename))
```

### How to Fix
Rename files to use only safe characters:
```python
import re

def sanitize_filename(name: str) -> str:
    """Replace unsafe characters with safe alternatives."""
    replacements = {
        '|': '-',
        '#': '',
        '^': '',
        '[': '(',
        ']': ')',
        '%': 'pct',
        '{': '(',
        '}': ')',
        '\\': '-',
        '<': '',
        '>': '',
    }
    for char, replacement in replacements.items():
        name = name.replace(char, replacement)
    # Collapse multiple spaces/hyphens
    name = re.sub(r'\s+', ' ', name)
    name = re.sub(r'-+', '-', name)
    return name.strip()
```

After renaming, update all wiki-links that referenced the old filename.

### How to Prevent
- Safe filename characters: `a-z A-Z 0-9 space - _ . ( ) ,`
- Avoid: `| # ^ [ ] % { } \ < > : " / ? *`
- Establish a naming convention and enforce it during note creation
- When Claude creates notes, always sanitize the filename first
- Use hyphens or underscores where special characters might be tempting
- Example transforms:
  - `Meeting Notes | 2026-02-12` -> `Meeting Notes - 2026-02-12`
  - `Chapter #3` -> `Chapter 3`
  - `Task [TODO]` -> `Task (TODO)` or `Task - TODO`
  - `50% Complete` -> `50 Percent Complete`

---

## 13. cli-requires-obsidian-running (HIGH)

### What Happens
You run `/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic orphans` and the command hangs. No output appears. After 30 seconds or more, you give up — nothing happened. Or worse, Obsidian launches in full GUI mode instead of processing the CLI command.

### Why It Happens
The Obsidian CLI binary at `/Applications/Obsidian.app/Contents/MacOS/Obsidian` IS the Obsidian application itself. CLI commands communicate with an already-running Obsidian process via IPC (inter-process communication). When Obsidian is not running, there is no process to receive the command. The binary may attempt to start a new Obsidian instance in GUI mode, or it may hang waiting for an IPC connection that never establishes.

### How to Detect
```bash
# Check if Obsidian is running
pgrep -x Obsidian
# Returns PID if running, empty if not

# Quick test: version command should return instantly
timeout 3 /Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic version
# Should return "1.12.1" within 1 second
```

### How to Fix
```bash
# Start Obsidian if not running
if ! pgrep -x Obsidian > /dev/null; then
    open /Applications/Obsidian.app
    sleep 3  # Wait for vault to load
fi

# Now CLI commands will work
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic orphans
```

Fallback when Obsidian cannot be started:
```bash
# Search fallback: use Grep instead of CLI search
# Instead of: obsidian vault=Agentic search query="machine learning"
Grep: pattern="machine learning" path="/path/to/vault" glob="*.md"

# Orphan fallback: manual link scanning (60x slower but works)
# This requires scanning every file for every other file's name

# Tag fallback: parse frontmatter with Grep
Grep: pattern="^tags:" glob="**/*.md" -A=5
```

### How to Prevent
- Before any CLI command, check: `pgrep -x Obsidian > /dev/null`
- Set up a wrapper function that checks and starts Obsidian if needed
- Document in workflows that CLI commands require Obsidian running
- Always have a file-op fallback for critical operations

---

## 14. cli-vault-parameter-first (MEDIUM)

### What Happens
You run `/Applications/Obsidian.app/Contents/MacOS/Obsidian search query="test" vault=Agentic` and get results from a different vault, or no results at all. The search worked, but on the wrong vault.

### Why It Happens
The CLI parser requires `vault=` as the very first parameter after the binary path. It uses positional parsing — the first argument is always the vault selector. When `vault=` appears after a command keyword like `search`, the parser may:
- Use the default vault (usually the last opened vault)
- Interpret `vault=Agentic` as an option to the `search` command
- Silently target the wrong vault

### How to Detect
- Compare CLI results with direct file searches on the same vault
- If results seem wrong or empty when they shouldn't be, check parameter order
- Run `obsidian vault=Agentic version` to confirm you can target the vault

### How to Fix
Always put `vault=Agentic` immediately after the binary:

```bash
# CORRECT — vault= first
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic search query="test"
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic orphans
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic backlinks path="note.md"

# WRONG — vault= after command
/Applications/Obsidian.app/Contents/MacOS/Obsidian search query="test" vault=Agentic
/Applications/Obsidian.app/Contents/MacOS/Obsidian orphans vault=Agentic
```

### How to Prevent
- Define a shell alias: `alias obs='/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic'`
- Then use: `obs search query="test"`, `obs orphans`, `obs backlinks path="note.md"`
- In documentation and patterns, always show the full command with vault= first
- Never construct CLI commands by appending vault= at the end

---

## 15. cli-scope-without-all-flag (MEDIUM)

### What Happens
You run `/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic tasks` expecting to see all tasks in the vault. The command returns empty output — no tasks listed, no error, nothing.

### Why It Happens
Several CLI commands (`tasks`, `tags`, `properties`) operate in two modes:
- **File-scoped**: Pass `file="path.md"` or `path="folder/"` to query a specific note or folder
- **Vault-wide**: Pass `all` to query across the entire vault

Without either a file target or the `all` flag, the command has no scope to work with. It returns empty output because no files were specified and vault-wide mode was not explicitly requested.

### How to Detect
- Empty results from `tasks`, `tags`, or `properties` commands
- Adding `all` suddenly produces the expected results
- Works fine with `file=` parameter but empty without it

### How to Fix
```bash
# CORRECT — vault-wide with 'all'
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic tasks all
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic tasks all todo
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic tags all counts sort=count
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic properties all total

# CORRECT — file-scoped
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic tasks file="01 Projects/MyProject.md"
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic tags path="03 Resources/"

# WRONG — no scope (returns empty)
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic tasks
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic tags
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic properties
```

### How to Prevent
- Always include `all` for vault-wide queries
- When querying a specific file, always include `file=` or `path=`
- Create wrapper commands that default to `all` if no scope is provided

---

## Quick Reference: Edge Severity Matrix

| Edge | Severity | Likelihood | Impact | Detection Ease |
|------|----------|-----------|--------|----------------|
| frontmatter-corruption | CRITICAL | High | High | Medium |
| mcp-api-key-exposure | CRITICAL | Medium | Very High | Easy |
| uri-encoding-spaces | HIGH | Very High | Medium | Easy |
| rest-api-self-signed-cert | HIGH | High | Low | Easy |
| concurrent-file-access | HIGH | Medium | High | Hard |
| git-obsidian-workspace-conflicts | HIGH | Very High | Low | Easy |
| templater-syntax-in-content | MEDIUM | Medium | Medium | Easy |
| large-vault-search-performance | MEDIUM | High | Low | Easy |
| wiki-link-case-sensitivity | MEDIUM | Low | Medium | Medium |
| advanced-uri-plugin-missing | MEDIUM | Medium | Low | Easy |
| dataview-not-installed | MEDIUM | Medium | Low | Easy |
| path-with-special-chars | MEDIUM | Low | Medium | Medium |
| cli-requires-obsidian-running | HIGH | Medium | High | Easy |
| cli-vault-parameter-first | MEDIUM | Medium | Medium | Medium |
| cli-scope-without-all-flag | MEDIUM | High | Low | Easy |

## Decision Tree: Which Edge Am I Hitting?

```
Is your operation failing silently?
├── Yes: URI-based operation?
│   ├── Yes: Spaces in path? → Edge 1 (uri-encoding-spaces)
│   │        Advanced URI? → Edge 10 (plugin-missing)
│   └── No:  Writing Templater syntax? → Edge 5 (templater-syntax)
│            Dataview query not rendering? → Edge 11 (dataview-not-installed)
├── Error message present?
│   ├── SSL/TLS error → Edge 3 (rest-api-self-signed-cert)
│   ├── YAML parse error → Edge 2 (frontmatter-corruption)
│   ├── Git merge conflict → Edge 7 (workspace-conflicts)
│   └── File content wrong → Edge 4 (concurrent-file-access)
└── Performance issue?
│   └── Search slow? → Edge 6 (large-vault-search-performance)
└── CLI command issue?
    ├── Command hangs? → Edge 13 (cli-requires-obsidian-running)
    ├── Wrong results? → Edge 14 (cli-vault-parameter-first)
    └── Empty results? → Edge 15 (cli-scope-without-all-flag)
```
