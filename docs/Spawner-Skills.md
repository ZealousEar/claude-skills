# Spawner Skills

These are domain knowledge packs, not executable workflows. They don't run code or call APIs. Instead, they encode expertise -- patterns that work, anti-patterns to avoid, sharp edges that will cut you, and architectural decisions with their rationale. Claude reads these files as reference context when working in the relevant domain.

Each Spawner skill lives in `~/.spawner/skills/<category>/<name>/` and follows an 8-file format.

## The 8-File Format

Every Spawner skill consists of 4 structured YAML files and 4 deep-dive Markdown files:

| File | Format | Purpose |
|------|--------|---------|
| `skill.yaml` | YAML | Core definition: identity, triggers, patterns, anti-patterns, handoffs |
| `sharp-edges.yaml` | YAML | Structured pitfalls with detection patterns and observable symptoms |
| `validations.yaml` | YAML | Quality gate checks that can be run against output |
| `collaboration.yaml` | YAML | Ecosystem: prerequisites, tools, alternatives, handoff rules |
| `patterns.md` | Markdown | Deep-dive pattern documentation with full code examples |
| `anti-patterns.md` | Markdown | What NOT to do, with bad/good comparisons |
| `decisions.md` | Markdown | Architectural decisions with rationale (ADR-style) |
| `sharp-edges.md` | Markdown | Detailed Why/Detect/Fix/Prevent for each pitfall |

Not every user-created skill has all 8 files populated. The YAML files carry the structured data; the Markdown files provide the narrative depth. A well-built skill has both.

## How They're Used

Spawner skills are **not invoked via slash commands**. They're loaded as reference context. When Claude is working on a task that touches a Spawner skill's domain, it reads the relevant files to inform its decisions. For example:

- About to create an Obsidian note? Read `obsidian-cli/skill.yaml` for the anti-patterns section to avoid dumping notes in the wrong folder.
- Converting a PDF with Mathpix? Read `mathpix-pdf-converter/skill.yaml` for the exact API workflow and error handling.
- Doing web research? Read `online-research/skill.yaml` for the SIFT verification methodology.

The key insight: these skills make Claude better at a domain without requiring any executable code. They're pure knowledge transfer.

---

## arxiv-pdf-reader

**What it knows:** How to fetch papers from arXiv and convert them to Obsidian-compatible markdown using the Mathpix API.

**Key details:**
- Constructs PDF URLs from arXiv abstract URLs (`/abs/` to `/pdf/`)
- Submits to Mathpix API, polls for completion, downloads `.mmd` output
- Adds frontmatter with arXiv metadata (ID, source URL, tags)
- Organizes output into `Papers/<sanitized-title>/` with both PDF and markdown
- Handles both URL-based and local file submissions

**Pairs with:** mathpix-pdf-converter, media-transcript

**Prerequisites:** Mathpix API credentials, curl, jq

---

## lecture-notes-sync

**What it knows:** How to synthesize lecture slides and video transcripts into unified study notes using vision models.

**Key details:**
- Sends slide images to OpenRouter vision model (Gemini Flash) for content extraction
- Extracts text, math (LaTeX), and diagrams (converts to Mermaid or ASCII art)
- Parses slide timestamps from filenames (e.g., `slide_0002_116.18s.png` -> 1:56)
- Matches slides to corresponding transcript sections by timestamp
- Generates per-slide insights about what's being taught
- Output format: single markdown file with slide sections separated by `---`

**Pairs with:** media-transcript (extracts the slides and transcripts this skill consumes)

**Prerequisites:** OpenRouter API key, existing slides and transcript from media-transcript

---

## mathpix-pdf-converter

**What it knows:** The general-purpose PDF-to-markdown conversion workflow via Mathpix API.

**Key details:**
- Handles PDFs, EPUBs, DOCX, PPTX, DJVU, and more (up to 1GB)
- Preserves LaTeX formulas, tables, diagrams, and document structure
- Supports page range selection (`"page_ranges": "2,4-6,10-15"`)
- Customizable math delimiters and advanced table processing options
- Output is Mathpix Markdown (`.mmd`) format
- Polling-based workflow: submit, wait for `completed` status, download

**Pairs with:** arxiv-pdf-reader (specialized version), lecture-notes-sync

**Prerequisites:** Mathpix API credentials, curl, jq

---

## media-transcript

**What it knows:** How to extract transcripts and slides from YouTube videos and PDFs using the `summarize` CLI tool.

**Key details:**
- Uses `summarize "<URL>" --extract --json` for transcript extraction
- Slide extraction via `summarize slides "<URL>" --slides-dir <path>` with scene change detection
- Creates organized folder structure: `Transcripts/<Title>/<Title> - Transcript.md`
- Adds Obsidian-compatible frontmatter (source, type, date, tags)
- Handles YouTube, PDF, and generic web content
- Optional OCR on extracted slides (`--slides-ocr`, requires tesseract)

**Pairs with:** lecture-notes-sync (consumes transcripts and slides), obsidian-cli

**Prerequisites:** `summarize` CLI (`npm i -g @steipete/summarize`), Node.js 22+, yt-dlp, ffmpeg

---

## obsidian-cli

**What it knows:** Everything about Obsidian vault automation. This is the largest Spawner skill in the collection -- 13 patterns, 9 anti-patterns, 13 owned domains, and a detailed identity section with battle scars.

**Key details:**
- **3-tier tool hierarchy:** direct file ops (primary) > Obsidian CLI v1.12 (discovery) > URI scheme (UI control)
- **13 patterns:** vault CRUD, URI commands, REST API, MCP bridge, Templater automation, Dataview-ready notes, git sync, dashboards, auto-linking, CLI discovery, CLI graph intelligence, CLI management, tool selection
- **9 anti-patterns:** REST-API-for-everything, dump-in-inbox, notes-without-frontmatter, manual-link-lists, hardcoded-paths, overwrite-without-checking, mixing-tools-inconsistently, assuming-plugins-installed
- **PARA method enforcement** with folder selection guide
- **CLI v1.12 command reference** with performance benchmarks (orphan detection: 0.26s CLI vs 15.6s grep)
- **Handoff definitions** -- receives from obsidian-notes-validator, lecture-notes-sync, media-transcript; hands to validator, lecture-sync, graph-engineer

**Pairs with:** obsidian-notes-validator, lecture-notes-sync, media-transcript

**This is the Spawner counterpart to the Claude Code `obsidian` skill.** The Claude Code skill executes; this Spawner skill provides the knowledge base.

---

## obsidian-notes-validator

**What it knows:** How to validate Obsidian notes for common rendering and formatting issues before they're finalized.

**Key details:**
- **Frontmatter checks:** YAML delimiters present, required fields (tags, date, source), lowercase hyphenated tags
- **Mermaid validation:** no `<br/>` tags (use `<br>`), no numbered lists in labels, valid link syntax, no unsupported diagram types
- **TikZ validation:** no `arrows.meta`/`external`/`tikzmark` libraries, correct arrow syntax
- **Wiki-link verification:** all `[Note Name](Note Name.md)` links point to existing files
- **LaTeX math:** proper `$...$` and `$$...$$` delimiters
- **Charts plugin:** valid YAML in chart blocks with required fields

**Pairs with:** lecture-notes-sync, media-transcript

**Prerequisites:** Notes following the vault's conventions

---

## online-research

**What it knows:** Systematic web research methodology, from query decomposition to source verification.

**Key details:**
- **SIFT verification** -- Stop, Investigate source, Find better coverage, Trace claims
- **PRISMA-inspired flow** -- identified, screened, included tracking
- **Site structure mapping** -- understand URL patterns before extracting
- **Query decomposition** -- break complex questions into sub-questions before searching
- **Cross-reference rule** -- triangulate critical claims across 3+ sources
- **403 error recovery** -- alternative approaches when sites block automated access
- **Academic API alternatives** -- fallback paths for paywalled content

**Pairs with:** browser-automation, documentation-engineer

---

## ssrn-pdf-reader

**What it knows:** How to fetch working papers from SSRN (Social Science Research Network), handling Cloudflare protection.

**Key details:**
- SSRN uses Cloudflare, so you need exported browser cookies in Netscape format
- Full browser header spoofing required (User-Agent, Sec-Fetch-*, Referer, --compressed)
- PDF verification step -- checks `file` output to catch HTML error pages disguised as PDFs
- Cookie expiration guidance: session cookies die with browser, `__cf_bm` expires in ~30 minutes
- Batch processing support with delays between papers
- Includes a table of known SSRN paper IDs for a specific research corpus

**Pairs with:** arxiv-pdf-reader, mathpix-pdf-converter, lecture-notes-sync

**Prerequisites:** Mathpix API credentials, SSRN cookies (Netscape format), active SSRN account, curl, jq

---

## Navigation

- [Home](Home.md) -- Back to overview
- [Claude Code Skills](Claude-Code-Skills.md) -- The executable skill counterparts
- [Architecture](Architecture.md) -- How Claude Code and Spawner skills work together
- [Getting Started](Getting-Started.md) -- Installation guide
