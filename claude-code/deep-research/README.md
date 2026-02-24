# deep-research

Multi-source research pipeline that extracts content from YouTube, arXiv, SSRN, PDFs, and web articles, then synthesizes comprehensive Obsidian research notes.

## Files

- `SKILL.md` — six-phase pipeline definition: classify, extract, analyze slides, web research, synthesize, validate and write.
- `scripts/source_classifier.py` — URL/path classification into source types with metadata extraction.
- `scripts/mathpix_convert.py` — Mathpix API integration: submit PDF, poll status, download markdown, postprocess math delimiters.
- `scripts/ssrn_download.py` — SSRN PDF download with Cloudflare cookie handling and TLS fallback guidance.
- `settings/extraction-defaults.json` — configurable defaults per source type (slide count, poll intervals, search depth).
- `settings/research-note-template.md` — structural template for the synthesis phase.
- `settings/credentials-paths.json` — credential file locations for Mathpix and SSRN.
- `references/obsidian-syntax-rules.md` — P0-P4 validation rules for math delimiters, Mermaid, and frontmatter.
- `references/source-type-guide.md` — per-source extraction methods, known issues, and workarounds.

## How it works

The skill runs a six-phase pipeline. Phase 0 classifies inputs by source type. Phase 1 extracts content in parallel — YouTube via `summarize` CLI, academic papers via Mathpix API, web articles via WebFetch. Phase 2 annotates YouTube slides using Claude's vision. Phase 3 runs broad web research. Phase 4 synthesizes all outputs into a structured research note. Phase 5 validates Obsidian syntax. Phase 6 writes everything to the vault.

## Setup

Requires `summarize` CLI, yt-dlp, ffmpeg, and Mathpix API credentials. Set `VAULT_ROOT` to your vault path. See [Getting Started](../../docs/Getting-Started.md) for full setup instructions.
