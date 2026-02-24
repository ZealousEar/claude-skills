# Source Type Extraction Guide

Per-source extraction methods, CLI commands, known issues, and workarounds.

---

## YouTube

### Extraction Method
1. **Transcript**: `summarize "<URL>" --extract --json`
   - Parse JSON: `extracted.title`, `extracted.content`, `extracted.siteName`
2. **Slides**: `summarize slides "<URL>" --slides-dir "<output_dir>"`
   - Detects scene changes (slide transitions)
   - Saves PNGs: `slide_NNNN_Ts.png` (slide number + timestamp)
   - Optional OCR: `--slides-ocr` (requires tesseract)
3. **Visual analysis**: Read each slide image via Claude's Read tool for annotation

### Known Issues
- **yt-dlp bot detection**: YouTube may block downloads. Fix: `yt-dlp --cookies-from-browser brave`
- **yt-dlp outdated**: `brew upgrade yt-dlp` — old versions fail silently
- **Live streams**: May not have captions. `summarize` will attempt audio transcription
- **Age-restricted content**: Requires cookies from logged-in browser session
- **Long videos (>2hr)**: Transcript may be very large. Consider `--max-length` flag

### Output Files
```
<topic>/
├── raw-transcript.md         # Full timestamped transcript
└── slides/
    ├── slide_0001_0.00s.png
    ├── slide_0002_112.03s.png
    └── ...
```

---

## arXiv

### Extraction Method
1. Parse arXiv ID from URL: `https://arxiv.org/abs/2301.12345` → `2301.12345`
2. Construct PDF URL: `https://arxiv.org/pdf/2301.12345.pdf`
3. Submit to Mathpix: `python3 mathpix_convert.py --url <pdf_url> --output <slug>.mathpix.md`
4. Mathpix handles: math formulas, tables, figures, references

### Known Issues
- **v1 suffix**: Some papers need explicit version: `2512.06392v1` not `2512.06392`
- **Large papers (50+ pages)**: May timeout. Use `--page-ranges "1-30"` for partial processing
- **Scanned PDFs**: Older papers may be image-only. Mathpix OCR handles most, but quality varies
- **Supplementary materials**: Usually a separate PDF. Must be fetched independently

### Output Files
```
<topic>/
├── <slug>.mathpix.md          # Mathpix-converted markdown (postprocessed)
└── <slug>.pdf                 # Original PDF
```

---

## SSRN

### Extraction Method
1. Parse SSRN abstract ID from URL
2. Download PDF: `python3 ssrn_download.py --ssrn-id <id> --output <slug>.pdf`
3. Convert: `python3 mathpix_convert.py --file <slug>.pdf --output <slug>.mathpix.md`

### Known Issues
- **Cookie expiration**: `__cf_bm` ~30min, `SSRN_TOKEN` ~24hr
  - Must re-export from browser (papers.ssrn.com) immediately before use
- **Domain mismatch**: Cookies from `hq.ssrn.com` won't work for `papers.ssrn.com`
  - Export from the exact subdomain used for downloads
- **TLS fingerprint**: Cloudflare ties `cf_clearance` to browser TLS fingerprint
  - curl's fingerprint differs from Chrome → download often fails
  - **Primary fallback**: Download PDF manually in browser, then `mathpix_convert.py --file`
  - **Alternative**: `curl_cffi` or Playwright to impersonate Chrome TLS
- **Working papers**: May be updated/versioned. Check for latest revision

### Fallback Workflow (when cookies fail)
1. Tell user: "SSRN cookies have expired. Please download the PDF manually."
2. Provide direct URL: `https://papers.ssrn.com/sol3/papers.cfm?abstract_id=<ID>`
3. User downloads → provides local path
4. Process with: `python3 mathpix_convert.py --file <local.pdf> --output <slug>.mathpix.md`

### Output Files
```
<topic>/
├── <slug>.mathpix.md
└── <slug>.pdf
```

---

## Generic PDF (URL)

### Extraction Method
1. Download PDF via curl: `curl -L -o temp.pdf "<url>"`
2. Verify: check `%PDF-` magic bytes
3. Convert: `python3 mathpix_convert.py --file temp.pdf --output <slug>.mathpix.md`

### Known Issues
- **Password-protected PDFs**: Mathpix cannot process these
- **Very large PDFs (>1GB)**: Mathpix rejects. Use `--page-ranges`
- **DRM-protected**: Cannot be converted
- **Redirect chains**: Use `curl -L` to follow redirects

---

## Generic PDF (Local)

### Extraction Method
1. Verify file exists and has `%PDF-` header
2. Convert: `python3 mathpix_convert.py --file <path> --output <slug>.mathpix.md`

### Known Issues
- Same as generic PDF URL minus download issues

---

## Web Article / Blog Post

### Extraction Method
1. Use Claude's WebFetch tool: `WebFetch(url, "Extract the full article content...")`
2. WebFetch returns processed markdown
3. For JavaScript-heavy sites: escalate to Playwright MCP

### Known Issues
- **Paywalled content**: WebFetch cannot bypass paywalls
- **JavaScript-rendered SPAs**: WebFetch gets empty content. Use Playwright MCP
- **Rate limiting**: Some sites block rapid requests
- **403 errors**: See escalation ladder in online-research skill
  - Level 1: Retry with proper headers
  - Level 2: Try alternative URLs (mobile, print, API)
  - Level 3: Playwright MCP
  - Level 4: Alternative data sources (OpenAlex, Semantic Scholar)
  - Level 5: Accept and document limitation

### Output Files
```
<topic>/
└── <slug>-article.md          # Extracted article content
```

---

## Mixed Source Notes

When a research note has multiple sources:
1. Extract each source independently (in parallel when possible)
2. All artifacts go into the same topic folder
3. Synthesis note references all extraction artifacts via `[[wiki-links]]`
4. Frontmatter uses `sources:` array (not single `source_*` field)
