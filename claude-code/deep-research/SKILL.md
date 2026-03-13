---
name: research
description: >
  Multi-source deep research pipeline: extract content from YouTube, arXiv, SSRN,
  PDFs, and web articles, research the topic broadly, and synthesize into a
  comprehensive Obsidian research note. Invoked via /research slash command.
platform: claude-code
---

# Deep Research — Multi-Source Research Pipeline

Automates the full research workflow: classify sources, extract content in parallel,
research the topic broadly via web search, synthesize everything into a comprehensive
Obsidian research note, validate syntax, and write to the vault.

## When to Use

- Researching a YouTube video, arXiv paper, SSRN paper, PDF, or blog post
- Combining multiple sources into a single comprehensive research note
- Creating research notes that match the quality bar of `05 Research/Ralph Wiggum Loop/`
- Any "I watched/read this, now I want a deep note on it" workflow

## When NOT to Use

- Quick notes or daily log entries → use `/obsidian`
- Literature reviews across many papers → use manual research workflow
- Content that doesn't need web research → just use the extraction tools directly

## Invocation

```
/research <URL>                                        # Single source
/research <URL1> <URL2> <URL3>                         # Multiple sources
/research <URL> --output "05 Research/Custom Name"     # Custom output path
/research <URL> --no-broad-search                      # Skip Phase 3 web research
/research <URL> --slides-max 10                        # Override max slide count
/research ~/Downloads/paper.pdf --title "Paper Title"  # Local PDF with title
```

## Skill Directory

```
~/.claude/skills/deep-research/
├── SKILL.md                              # This file
├── scripts/
│   ├── mathpix_convert.py                # Mathpix API: submit, poll, download, postprocess
│   ├── ssrn_download.py                  # SSRN PDF download with Cloudflare bypass
│   └── source_classifier.py              # URL classification + metadata extraction
├── settings/
│   ├── extraction-defaults.json          # Default params per source type
│   ├── research-note-template.md         # Synthesis template + formatting rules
│   └── credentials-paths.json            # Credential file locations
└── references/
    ├── obsidian-syntax-rules.md          # P0-P4 validation rules
    └── source-type-guide.md              # Per-source extraction methods + known issues
```

## Vault Details

- **Path**: `/Users/farhad/Code/Agentic Obsidian Vault/Agentic/`
- **Credentials**: `.credentials/dissertation-research/.env` (Mathpix keys)
- **SSRN cookies**: `.credentials/cookies/ssrn-cookies.txt`

---

## Pipeline — Six Phases

### Phase 0: Input Classification

For each input URL or path:

1. Run classification (inline or via the script):
   ```bash
   python3 ~/.claude/skills/deep-research/scripts/source_classifier.py "<input>" --json
   ```
2. Returns: `type` (youtube | arxiv | ssrn | pdf_url | pdf_local | web_article),
   `id`, `url`, `slug`
3. Determine topic slug from classification output or `--title` override
4. Determine output location (see Output Routing below)

### Phase 1: Parallel Extraction

Extract content from each source. **Run independent sources in parallel** using
background Bash tasks or concurrent tool calls.

| Source Type | Extraction Method | Output |
|---|---|---|
| YouTube | `summarize "<URL>" --extract --json` then `summarize slides "<URL>" --slides-dir <dir>` | `raw-transcript.md` + `slides/*.png` |
| arXiv | `python3 scripts/mathpix_convert.py --url <pdf_url> --output <slug>.mathpix.md` | `<slug>.mathpix.md` + `<slug>.pdf` |
| SSRN | `python3 scripts/ssrn_download.py --ssrn-id <id> --output <slug>.pdf` then `python3 scripts/mathpix_convert.py --file <slug>.pdf --output <slug>.mathpix.md` | `<slug>.mathpix.md` + `<slug>.pdf` |
| PDF (URL) | `curl -L -o temp.pdf "<url>"` then `python3 scripts/mathpix_convert.py --file temp.pdf --output <slug>.mathpix.md` | `<slug>.mathpix.md` |
| PDF (local) | `python3 scripts/mathpix_convert.py --file <path> --output <slug>.mathpix.md` | `<slug>.mathpix.md` |
| Web article | `WebFetch(url, "Extract the full article...")` | `<slug>-article.md` |

**YouTube extraction details:**
1. Extract transcript: `summarize "<URL>" --extract --json`
   - Parse JSON output for title, content, metadata
   - Save as `raw-transcript.md` with frontmatter
2. Extract slides: `summarize slides "<URL>" --slides-dir "<topic>/slides"`
   - Saves PNGs named `slide_NNNN_Ts.png` (number + timestamp)
   - Default max: 30 slides (override with `--slides-max`)

**SSRN fallback:** If cookies are expired or TLS fingerprint blocked:
1. Inform user cookies need refreshing
2. Provide the SSRN abstract URL for manual download
3. User provides local PDF path → continue with `mathpix_convert.py --file`

### Phase 2: Visual Analysis (YouTube only)

If the source includes YouTube slides:

1. Read each extracted slide image via Claude's Read tool (multimodal)
2. For each slide, produce a one-line annotation:
   `"Slide N (Ts): [description of what the slide shows]"`
3. Map slides to transcript timestamps for contextual embedding in the final note
4. This builds the `![[slide_NNNN_Ts.png]]` references used in synthesis

Skip this phase if `--no-broad-search` is set and there are no slides.

### Phase 3: Broad Topic Research

Unless `--no-broad-search` is set:

1. From the extracted content, generate 3-5 targeted WebSearch queries:
   - Community discussions (Reddit, HN, forums)
   - GitHub repositories and implementations
   - Blog posts, tutorials, practitioner guides
   - Official documentation or specs
   - Academic context (if not already an academic source)

2. Execute WebSearch queries (parallel when independent)

3. WebFetch the top 3-5 most relevant results from search

4. Compile findings with source attribution:
   ```
   [Source Title](url) — one-line summary of what it adds
   ```

### Phase 4: Synthesis

Read the research note template at `settings/research-note-template.md`, then compose
the research note using ALL Phase 1-3 outputs.

**Required structure:**
1. **Frontmatter**: YAML with real values — source URLs, authors, tags, status.
   Use the appropriate source fields from the template. No placeholders.
2. **Title**: `# Research Note: <Topic>`
3. **Question**: One clear question the note answers
4. **Key Idea**: 2-4 paragraph executive summary. Include canonical code/formula/diagram
5. **Numbered H2 sections** (`## N. Title`): 4-10 sections with H3/H4 hierarchy.
   Depth driven by content richness. Include:
   - Embedded slides: `![[slide_NNNN_Ts.png]]` where relevant
   - Code blocks with language identifiers
   - Blockquotes with attribution: `> "quote" -- source`
   - Comparison tables where applicable
   - Internal links: `[[raw-transcript.md]]`, `[[slug.mathpix.md]]`
6. **Evidence**: Primary sources (input content) + secondary sources (web research)
7. **Implications**: How this connects to our projects and workflows
8. **Links**: Internal wiki-links to extraction artifacts + related vault notes

**Quality bar:** The output should match `05 Research/Ralph Wiggum Loop/Ralph Wiggum Loop.md`
in depth — typically 300-500 lines with embedded slides, hyperlinked sources,
numbered sections, code examples, and comparison tables.

### Phase 5: Validation

Before writing the final note, validate against `references/obsidian-syntax-rules.md`:

**P0 — Math delimiters:**
- No `\[...\]` → must be `$$...$$`
- No backtick-wrapped LaTeX → must be `$...$`
- Mathpix `\(...\)` already converted by `mathpix_convert.py` postprocessor

**P1 — Mermaid syntax:**
- Labels with parentheses must be double-quoted: `F["text (with parens)"]`
- No LaTeX inside Mermaid labels
- No `\n` literals in labels — use em-dash separators
- No `<br/>` tags

**P3 — Frontmatter:**
- No placeholder tags (`topic-tags`, `[Author Name]`)
- All required fields present with real values

Fix any violations inline before proceeding to Phase 6.

### Phase 6: Write Output

1. Create the topic folder at the routed vault location:
   ```bash
   mkdir -p "<vault_root>/<output_path>/<topic_slug>"
   ```
2. Write the main research note: `<topic_slug>/<Topic Name>.md`
3. Write/move all supporting files:
   - `raw-transcript.md` (YouTube)
   - `<slug>.mathpix.md` (arXiv/SSRN/PDF)
   - `<slug>.pdf` (arXiv/SSRN/PDF)
   - `slides/` directory (YouTube)
   - `<slug>-article.md` (web articles)
4. Report completion:
   ```
   Research complete: <vault_root>/<output_path>/<topic_slug>/
   ├── <Topic Name>.md          (NNN lines)
   ├── raw-transcript.md        (if YouTube)
   ├── <slug>.mathpix.md        (if PDF source)
   ├── <slug>.pdf               (if PDF source)
   └── slides/                  (N slides, if YouTube)
   ```

---

## Output Routing

**Strategy: Use `--output` if provided. Otherwise, infer or ask.**

| Context | Behavior |
|---|---|
| `--output` provided | Use exact path under vault root |
| arXiv/SSRN paper on a dissertation topic | Route to `10 School/Dissertation Research/Papers/<slug>/` |
| General research / tutorial / technique | Route to `05 Research/<Topic>/` |
| Ambiguous | **Ask the user** via AskUserQuestion |

When asking, suggest 2-3 locations based on content analysis:
```
AskUserQuestion:
  "Where should this research note be saved?"
  options:
    - "05 Research/<Topic>" (general research)
    - "10 School/Dissertation Research/Papers/<slug>" (dissertation)
    - "03 Resources/<Topic>" (reference material)
```

---

## Configuration

### extraction-defaults.json

| Key | Default | Purpose |
|---|---|---|
| `youtube.slides.max_slides` | 30 | Max slides to extract |
| `youtube.slides.threshold` | 0.3 | Scene change detection threshold |
| `mathpix.poll_interval_seconds` | 5 | Seconds between status polls |
| `mathpix.poll_timeout_seconds` | 300 | Max wait for Mathpix processing |
| `web_search.queries_per_topic` | 4 | Number of search queries in Phase 3 |
| `web_search.max_fetch_results` | 5 | Max pages to WebFetch per search |
| `output.default_location` | `05 Research` | Default vault subfolder |

### credentials-paths.json

| Credential | Path | Notes |
|---|---|---|
| Mathpix `.env` | `.credentials/dissertation-research/.env` | `MATHPIX_APP_ID`, `MATHPIX_APP_KEY` |
| SSRN cookies | `.credentials/cookies/ssrn-cookies.txt` | Netscape format, expires fast |

All paths relative to vault root: `/Users/farhad/Code/Agentic Obsidian Vault/Agentic/`

---

## Prerequisites

- **summarize CLI**: `npm i -g @steipete/summarize` (for YouTube transcript + slides)
- **yt-dlp**: `brew install yt-dlp` (keep updated: `brew upgrade yt-dlp`)
- **ffmpeg**: `brew install ffmpeg` (for slide extraction)
- **jq**: `brew install jq` (for JSON parsing in shell)
- **Mathpix API**: Credentials in `.credentials/dissertation-research/.env`
- **Python 3.10+**: For scripts (system Python on macOS works)

Optional:
- **tesseract**: For OCR on extracted slides (`--slides-ocr`)
- **SSRN cookies**: Only needed for SSRN papers

---

## Error Handling

| Error | Cause | Recovery |
|---|---|---|
| `summarize` fails | yt-dlp outdated or bot detection | `brew upgrade yt-dlp`, try `--cookies-from-browser brave` |
| Mathpix 401 | Bad API credentials | Check `.credentials/dissertation-research/.env` |
| Mathpix timeout | Large PDF (50+ pages) | Use `--page-ranges` for partial processing |
| SSRN HTML instead of PDF | Cookies expired | Re-export from browser, or download PDF manually |
| SSRN TLS blocked | Cloudflare fingerprint mismatch | Download manually, use `mathpix_convert.py --file` |
| WebFetch 403 | Site blocks automated requests | Try Playwright MCP or note limitation |
| WebFetch empty content | JavaScript-rendered SPA | Escalate to Playwright MCP |

---

## Examples

### Single YouTube Video
```
/research https://www.youtube.com/watch?v=I7azCAgoUHc
```
→ Extracts transcript + slides, researches Ralph Wiggum loops broadly,
synthesizes into `05 Research/Ralph Wiggum Loop/Ralph Wiggum Loop.md`

### arXiv Paper
```
/research https://arxiv.org/abs/2502.07766
```
→ Downloads PDF, converts via Mathpix, researches the topic,
synthesizes into research note with embedded formulas

### Multiple Sources
```
/research https://www.youtube.com/watch?v=abc123 https://blog.example.com/post
```
→ Extracts both in parallel, combines into single research note

### Custom Output
```
/research https://arxiv.org/abs/2301.12345 --output "10 School/Dissertation Research/Papers/my-paper"
```
→ Routes output to dissertation folder

### Local PDF
```
/research ~/Downloads/paper.pdf --title "Market Microstructure Dynamics"
```
→ Converts local PDF, researches the topic, writes note

### Skip Web Research
```
/research https://arxiv.org/abs/2301.12345 --no-broad-search
```
→ Extract and synthesize only from the source content, no web search
