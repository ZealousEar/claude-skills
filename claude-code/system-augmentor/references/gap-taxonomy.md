# Gap Taxonomy

Classification schema for system capability gaps detected by the System Augmentor.

## Severity Levels

| Level | Meaning | Action |
|-------|---------|--------|
| **CRITICAL** | System is missing a fundamental capability for its stated purpose | Must fix — blocks core workflows |
| **HIGH** | Significant capability gap that limits effectiveness | Should fix — noticeably degrades output quality |
| **MEDIUM** | Missing convenience or secondary capability | Nice to fix — improves workflow efficiency |
| **LOW** | Minor gap or informational finding | Optional — fix if easy or relevant to current task |

## Gap Categories

### 1. MCP Servers (`mcp_servers`)

Missing Model Context Protocol servers that provide tool access.

**What to check:**
- `~/.claude/mcp.json` — global MCP server registry
- Project-level `.mcp.json` if present

**Common gaps:**
- No web search/scraping server (Firecrawl, Browserless, Tavily)
- No database access server (SQLite, PostgreSQL)
- No academic search server (Semantic Scholar, arXiv)
- No file conversion server (Pandoc, PDF tools)
- No monitoring/observability server

**Severity heuristic:**
- CRITICAL if the MCP category is needed for the project's stated purpose
- HIGH if the user has expressed interest in the capability area
- MEDIUM otherwise

### 2. CLI Tools (`cli_tools`)

Missing command-line tools that Claude Code can invoke via Bash.

**What to check:**
- `shutil.which()` for each tool in the scan list

**Common gaps:**
- Build tools: docker, make, cargo, go
- Data tools: jq, sqlite3, psql
- Search tools: rg (ripgrep), fd, fzf
- Document tools: pandoc, pdflatex
- Media tools: ffmpeg, magick/convert

**Severity heuristic:**
- HIGH if the tool is needed for active project work
- MEDIUM if broadly useful
- LOW if niche

### 3. API Keys (`api_keys`)

Missing or unconfigured API credentials.

**What to check:**
- Environment variables (`os.environ`)
- Key store files (`.env`, provider-keys.env, OAuth stores)
- Never read actual values — check existence only

**Common gaps:**
- LLM providers: OpenAI, Anthropic, Google, Moonshot
- Search: SerpAPI, Tavily
- Cloud: AWS, GCP credentials
- Code: GitHub token

**Severity heuristic:**
- HIGH if needed for an installed skill (e.g., debate agent needs provider keys)
- MEDIUM if broadly useful
- LOW if niche

### 4. Skills & Commands (`skills`)

Missing or misconfigured Claude Code skills and slash commands.

**What to check:**
- `~/.claude/skills/` — skill directories with SKILL.md
- `~/.claude/commands/` — slash command .md files
- Cross-reference: skills without commands, commands without skills

**Structural gaps:**
- Orphaned command: .md file in commands/ that references a missing skill
- Skill without command: skill directory exists but no invoking command
- Missing category: no skill covering a common capability (review, test, deploy)

**Severity heuristic:**
- MEDIUM for structural mismatches
- LOW for informational

### 5. Project Context (`project`)

Missing project-level configuration that helps Claude Code understand the codebase.

**What to check:**
- CLAUDE.md presence and content
- .claude/ directory for project-specific settings
- Standard project files (package.json, pyproject.toml, etc.)

**Severity heuristic:**
- CRITICAL if CLAUDE.md is missing in the active project
- LOW for other markers

## Focus Filtering

When `--focus <keyword>` is provided:
1. Only return gaps whose name, description, category, or suggestion matches the keyword
2. Expand keyword synonyms (e.g., "paper" → also check "academic", "research", "arxiv")
3. If no built-in rules match, flag this as "custom gap area — needs Claude reasoning"

## Extending the Taxonomy

To add new gap categories:
1. Add rules to `get_builtin_rules()` in `gap_analyzer.py`
2. Add a check handler function
3. Register the handler in `CHECK_HANDLERS`
4. Update this taxonomy document
