# Mathpix PDF to Markdown Converter

Convert PDF documents (and other formats) to Mathpix Markdown using the Mathpix API.

## What It Does

- Converts PDFs, EPUBs, DOCX, and other documents to markdown
- Extracts mathematical formulas as LaTeX
- Preserves tables and document structure
- Handles complex academic papers and textbooks
- Works with both URLs and local files

## Prerequisites

1. **Mathpix API credentials**
   - Sign up at https://console.mathpix.com
   - Get your `app_id` and `app_key`

2. **Tools**
   - `curl` (built-in on macOS)
   - `jq` for JSON parsing: `brew install jq`

3. **Environment setup**
   - Add credentials to `.env` file (already done ✓)
   - Load with: `source .env`

## Quick Start

### 1. Add Your API Credentials

Edit the `.env` file in your Vault root and replace the placeholders:

```bash
MATHPIX_APP_ID=your_actual_app_id
MATHPIX_APP_KEY=your_actual_app_key
```

### 2. Convert a PDF

#### From URL:
```bash
source .env

# Submit PDF (.mmd format available by default - no conversion_formats needed)
PDF_ID=$(curl -s -X POST https://api.mathpix.com/v3/pdf \
  -H "app_id: $MATHPIX_APP_ID" \
  -H "app_key: $MATHPIX_APP_KEY" \
  -H "Content-Type: application/json" \
  --data '{"url": "https://example.com/paper.pdf"}' \
  | jq -r '.pdf_id')

# Wait for completion (poll every 5 seconds)
while [ "$(curl -s https://api.mathpix.com/v3/pdf/$PDF_ID -H "app_id: $MATHPIX_APP_ID" -H "app_key: $MATHPIX_APP_KEY" | jq -r '.status')" != "completed" ]; do
  echo "Processing..."
  sleep 5
done

# Download result
curl -s "https://api.mathpix.com/v3/pdf/$PDF_ID.mmd" \
  -H "app_id: $MATHPIX_APP_ID" \
  -H "app_key: $MATHPIX_APP_KEY" \
  > output.mmd
```

#### From Local File:
```bash
source .env

# .mmd format available by default
PDF_ID=$(curl -s -X POST https://api.mathpix.com/v3/pdf \
  -H "app_id: $MATHPIX_APP_ID" \
  -H "app_key: $MATHPIX_APP_KEY" \
  --form 'file=@"document.pdf"' \
  | jq -r '.pdf_id')

# Then poll and download as above
```

### 3. Use the Example Script

```bash
cd ~/.spawner/skills/creative/mathpix-pdf-converter
./example-usage.sh
```

## Output Format

Converted files are saved to:
```
Transcripts/
└── <Document Title>/
    └── <Document Title>.mmd
```

The `.mmd` files contain:
- Clean markdown text
- Math formulas in LaTeX: `\( inline \)` and `\[ display \]`
- Properly formatted tables
- Preserved document structure

## Advanced Options

### Convert Specific Pages Only

```json
{
  "url": "https://example.com/large-book.pdf",
  "page_ranges": "25-40"
}
```

### Custom Math Delimiters

Use `$` instead of `\(` for compatibility with standard markdown:

```json
{
  "url": "https://example.com/paper.pdf",
  "math_inline_delimiters": ["$", "$"],
  "math_display_delimiters": ["$$", "$$"]
}
```

### Better Table Extraction

```json
{
  "url": "https://example.com/paper.pdf",
  "enable_tables_fallback": true
}
```

## Common Issues

See `sharp-edges.yaml` for detailed troubleshooting, but common issues include:

- **Unknown: ["mmd"] error**: Remove `conversion_formats` from your request - .mmd is available by default
- **401 Unauthorized**: Check API credentials in `.env`
- **command not found: your_app_id**: Remove spaces after `=` in `.env` file
- **File too large**: PDFs must be under 1GB
- **Password protected**: Remove password first with `qpdf`
- **Processing timeout**: Large docs can take 5-10 minutes (though most complete in seconds)

## Files in This Skill

- `skill.yaml` - Skill definition and instructions
- `patterns.md` - Detailed usage patterns and examples
- `sharp-edges.yaml` - Common errors and solutions
- `example-usage.sh` - Ready-to-use script
- `README.md` - This file

## Integration with Other Skills

Works well with:
- `media-transcript` - Extract YouTube transcripts
- `lecture-notes-sync` - Synthesize slides with transcripts
- `obsidian-notes` - Organize in your Obsidian vault

## Supported Input Formats

- PDF (up to 1GB)
- EPUB, AZW, AZW3, KFX, MOBI (ebooks)
- DOCX, DOC, ODT (documents)
- PPTX (presentations)
- DJVU, WPD

## API Limits

- Free tier: Limited pages per month
- Check usage at: https://console.mathpix.com
- Monitor with: `curl -s "https://api.mathpix.com/v3/pdf/$PDF_ID" | jq '.num_pages'`

## Resources

- API Docs: https://docs.mathpix.com
- Console: https://console.mathpix.com
- Mathpix Markdown Spec: https://docs.mathpix.com/#mathpix-markdown
