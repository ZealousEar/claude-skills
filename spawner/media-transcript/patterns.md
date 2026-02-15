# Media Transcript Extractor - Patterns

## Folder Structure

Each video/document gets its own folder:

```
Transcripts/
├── Lecture 1 - Intro to Crypto/
│   ├── Lecture 1 - Intro to Crypto - Transcript.md
│   └── slides/
│       ├── slide_0001.png
│       ├── slide_0002_116.18s.png
│       └── ...
├── Another Video Title/
│   ├── Another Video Title - Transcript.md
│   └── slides/
│       └── ...
└── PDF Document Name/
    └── PDF Document Name - Transcript.md
```

## Basic YouTube Transcript

**Trigger:** User provides a YouTube URL

```bash
# Extract transcript with metadata
summarize "https://www.youtube.com/watch?v=VIDEO_ID" --extract --json
```

**Steps:**
1. Parse JSON for `extracted.title` and `extracted.content`
2. Create folder: `mkdir -p "Transcripts/<Title>"`
3. Save to: `Transcripts/<Title>/<Title> - Transcript.md`

**Output file example:** `Transcripts/Lecture 1 - Intro to Crypto/Lecture 1 - Intro to Crypto - Transcript.md`

```markdown
---
source: https://www.youtube.com/watch?v=VIDEO_ID
type: transcript
date: 2026-01-18
tags:
  - transcript
  - youtube
---

# Lecture 1 - Intro to Crypto

[Transcript content...]
```

## YouTube with Slides

**Trigger:** User wants transcript AND slides

**Requires:** summarize CLI v0.10.0+ (`npm update -g @steipete/summarize`)

```bash
# Step 1: Get transcript (to extract title)
summarize "https://www.youtube.com/watch?v=VIDEO_ID" --extract --json

# Step 2: Extract slides into the same folder (v0.10.0+ syntax)
summarize slides "https://www.youtube.com/watch?v=VIDEO_ID" \
  --slides-dir "Transcripts/<Title>/slides" \
  --slides-max 50

# Alternative: Combined transcript + slides
summarize "https://www.youtube.com/watch?v=VIDEO_ID" --slides --extract
```

> **Note:** Check `summarize --version` before use. Slide extraction was added in v0.10.0.

**Result:**
```
Transcripts/Lecture 1 - Intro to Crypto/
├── Lecture 1 - Intro to Crypto - Transcript.md
└── slides/
    ├── slide_0001.png
    ├── slide_0002_116.18s.png
    └── ...
```

## PDF Document Extraction

**Trigger:** User provides a PDF URL or local path

```bash
# Extract from PDF URL
summarize "https://example.com/paper.pdf" --extract --json

# Extract from local PDF
summarize "/path/to/document.pdf" --extract --json
```

**Output:** `Transcripts/<Document Title>/<Document Title> - Transcript.md`

## Filename Sanitization

Remove problematic characters from titles before creating folders/files:

| Character | Replacement |
|-----------|-------------|
| `/` | `-` |
| `\` | `-` |
| `:` | `-` |
| `*` | `` |
| `?` | `` |
| `"` | `'` |
| `<` | `` |
| `>` | `` |
| `\|` | `-` |

**Example:**
- Original: `Lecture 1: Intro to Crypto & Cryptocurrencies`
- Sanitized: `Lecture 1 - Intro to Crypto & Cryptocurrencies`

## Frontmatter Template

```yaml
---
source: <original URL>
type: transcript
date: <YYYY-MM-DD>
tags:
  - transcript
  - <content-type>
---
```

## Content Type Detection

```
URL contains youtube.com/youtu.be → tag: youtube
URL ends with .pdf → tag: pdf
URL is web page → tag: web
Local file → tag: local
```

## Slide Extraction Options (v0.10.0+)

```bash
# Basic slide extraction
summarize slides "URL" --slides-dir "Transcripts/<Title>/slides" --slides-max 50

# With OCR (extract text from slides)
summarize slides "URL" --slides-dir "..." --slides-ocr

# Custom scene detection threshold (0.1-1.0, default 0.3)
summarize slides "URL" --slides-dir "..." --slides-scene-threshold 0.5

# Minimum duration between slides (default 2 seconds)
summarize slides "URL" --slides-dir "..." --slides-min-duration 5
```

> **Caveat:** Scene detection may capture the lecturer speaking instead of slide content.
> This is a limitation of automated extraction. Some slides may need manual review.

## Batch Processing

When user provides multiple URLs, process each sequentially:

```bash
# Process each URL
for url in "${urls[@]}"; do
  # Get title from JSON
  title=$(summarize "$url" --extract --json | jq -r '.extracted.title')

  # Create folder
  mkdir -p "Transcripts/$title"

  # Save transcript
  summarize "$url" --extract --format md > "Transcripts/$title/$title - Transcript.md"

  # Optionally extract slides
  summarize slides "$url" --slides-dir "Transcripts/$title/slides"
done
```
