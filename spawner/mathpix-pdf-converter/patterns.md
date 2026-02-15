# Mathpix PDF Converter - Patterns

## Folder Structure

Each document gets its own folder:

```
Transcripts/
├── Research Paper - Neural Networks/
│   └── Research Paper - Neural Networks.mmd
├── Calculus Textbook Chapter 3/
│   └── Calculus Textbook Chapter 3.mmd
└── Lecture Notes Physics/
    └── Lecture Notes Physics.mmd
```

## Pattern 1: Convert PDF from URL

**Trigger:** User provides a PDF URL

### Step 1: Submit PDF

```bash
# Store the PDF ID
PDF_ID=$(curl -s -X POST https://api.mathpix.com/v3/pdf \
  -H "app_id: $MATHPIX_APP_ID" \
  -H "app_key: $MATHPIX_APP_KEY" \
  -H "Content-Type: application/json" \
  --data '{
    "url": "https://example.com/paper.pdf"
  }' | jq -r '.pdf_id')

echo "Processing PDF with ID: $PDF_ID"
```

### Step 2: Poll for Completion

```bash
while true; do
  STATUS=$(curl -s -X GET "https://api.mathpix.com/v3/pdf/$PDF_ID" \
    -H "app_id: $MATHPIX_APP_ID" \
    -H "app_key: $MATHPIX_APP_KEY" | jq -r '.status')

  if [ "$STATUS" = "completed" ]; then
    echo "Conversion completed!"
    break
  elif [ "$STATUS" = "error" ]; then
    echo "Conversion failed"
    exit 1
  fi

  echo "Status: $STATUS - waiting..."
  sleep 5
done
```

### Step 3: Download Output

```bash
# Get title from metadata or use filename
TITLE="Research Paper"

# Create folder
mkdir -p "Transcripts/$TITLE"

# Download .mmd file
curl -s -X GET "https://api.mathpix.com/v3/pdf/$PDF_ID.mmd" \
  -H "app_id: $MATHPIX_APP_ID" \
  -H "app_key: $MATHPIX_APP_KEY" \
  > "Transcripts/$TITLE/$TITLE.mmd"

echo "Saved to: Transcripts/$TITLE/$TITLE.mmd"
```

## Pattern 2: Convert Local PDF File

**Trigger:** User provides a local file path

```bash
# Upload local file - .mmd format available by default
PDF_ID=$(curl -s -X POST https://api.mathpix.com/v3/pdf \
  -H "app_id: $MATHPIX_APP_ID" \
  -H "app_key: $MATHPIX_APP_KEY" \
  --form 'file=@"/path/to/document.pdf"' \
  | jq -r '.pdf_id')

# Then follow steps 2-3 from Pattern 1
```

## Pattern 3: Convert Specific Pages Only

**Use case:** Extract only relevant sections from a large document

```bash
curl -s -X POST https://api.mathpix.com/v3/pdf \
  -H "app_id: $MATHPIX_APP_ID" \
  -H "app_key: $MATHPIX_APP_KEY" \
  -H "Content-Type: application/json" \
  --data '{
    "url": "https://example.com/textbook.pdf",
    "page_ranges": "25-40"
  }' | jq -r '.pdf_id'
```

Example page ranges:
- `"1-10"` - Pages 1 through 10
- `"2,5,7"` - Pages 2, 5, and 7 only
- `"1-5,10-15,20"` - Combination of ranges and individual pages

## Pattern 4: Check Processing Status with Details

```bash
curl -s -X GET "https://api.mathpix.com/v3/pdf/$PDF_ID" \
  -H "app_id: $MATHPIX_APP_ID" \
  -H "app_key: $MATHPIX_APP_KEY" | jq '{
    status: .status,
    percent_done: .percent_done,
    num_pages: .num_pages,
    error: .error
  }'
```

Example output:
```json
{
  "status": "processing",
  "percent_done": 45,
  "num_pages": 30,
  "error": null
}
```

## Pattern 5: Batch Processing Multiple PDFs

```bash
# Array of URLs
urls=(
  "https://example.com/paper1.pdf"
  "https://example.com/paper2.pdf"
  "https://example.com/paper3.pdf"
)

# Submit all PDFs
pdf_ids=()
for url in "${urls[@]}"; do
  id=$(curl -s -X POST https://api.mathpix.com/v3/pdf \
    -H "app_id: $MATHPIX_APP_ID" \
    -H "app_key: $MATHPIX_APP_KEY" \
    -H "Content-Type: application/json" \
    --data "{\"url\": \"$url\"}" \
    | jq -r '.pdf_id')
  pdf_ids+=("$id")
  echo "Submitted: $id"
done

# Wait for all to complete
for id in "${pdf_ids[@]}"; do
  echo "Waiting for $id..."
  while true; do
    status=$(curl -s "https://api.mathpix.com/v3/pdf/$id" \
      -H "app_id: $MATHPIX_APP_ID" \
      -H "app_key: $MATHPIX_APP_KEY" | jq -r '.status')
    [ "$status" = "completed" ] && break
    sleep 5
  done

  # Download
  curl -s "https://api.mathpix.com/v3/pdf/$id.mmd" \
    -H "app_id: $MATHPIX_APP_ID" \
    -H "app_key: $MATHPIX_APP_KEY" \
    > "output_$id.mmd"
done
```

## Pattern 6: Convert with Custom Math Delimiters

**Use case:** Output compatible with specific markdown processors

```bash
# Use $ for inline and $$ for display (standard markdown)
curl -X POST https://api.mathpix.com/v3/pdf \
  -H "app_id: $MATHPIX_APP_ID" \
  -H "app_key: $MATHPIX_APP_KEY" \
  -H "Content-Type: application/json" \
  --data '{
    "url": "https://example.com/paper.pdf",
    "math_inline_delimiters": ["$", "$"],
    "math_display_delimiters": ["$$", "$$"]
  }' | jq -r '.pdf_id'
```

Default delimiters:
- Inline: `\(` and `\)`
- Display: `\[` and `\]`

## Pattern 7: Get Metadata After Conversion

```bash
# Get full metadata including page count, processing time, etc.
curl -s "https://api.mathpix.com/v3/pdf/$PDF_ID" \
  -H "app_id: $MATHPIX_APP_ID" \
  -H "app_key: $MATHPIX_APP_KEY" | jq '{
    pdf_id: .pdf_id,
    status: .status,
    num_pages: .num_pages,
    file_size: .file_size,
    md5: .md5,
    percent_done: .percent_done
  }'
```

## Complete Example Script

```bash
#!/bin/bash

# Load environment variables
source .env

# Function to convert PDF
convert_pdf() {
  local url=$1
  local title=$2

  echo "Converting: $title"

  # Submit PDF (.mmd format available by default)
  PDF_ID=$(curl -s -X POST https://api.mathpix.com/v3/pdf \
    -H "app_id: $MATHPIX_APP_ID" \
    -H "app_key: $MATHPIX_APP_KEY" \
    -H "Content-Type: application/json" \
    --data "{\"url\": \"$url\"}" \
    | jq -r '.pdf_id')

  echo "PDF ID: $PDF_ID"

  # Poll for completion
  while true; do
    response=$(curl -s "https://api.mathpix.com/v3/pdf/$PDF_ID" \
      -H "app_id: $MATHPIX_APP_ID" \
      -H "app_key: $MATHPIX_APP_KEY")

    status=$(echo "$response" | jq -r '.status')
    percent=$(echo "$response" | jq -r '.percent_done // 0')

    if [ "$status" = "completed" ]; then
      echo "✓ Conversion completed!"
      break
    elif [ "$status" = "error" ]; then
      error=$(echo "$response" | jq -r '.error')
      echo "✗ Error: $error"
      return 1
    fi

    echo "Progress: ${percent}%"
    sleep 5
  done

  # Create output folder
  mkdir -p "Transcripts/$title"

  # Download .mmd file
  curl -s "https://api.mathpix.com/v3/pdf/$PDF_ID.mmd" \
    -H "app_id: $MATHPIX_APP_ID" \
    -H "app_key: $MATHPIX_APP_KEY" \
    > "Transcripts/$title/$title.mmd"

  echo "Saved to: Transcripts/$title/$title.mmd"

  # Get page count
  pages=$(echo "$response" | jq -r '.num_pages')
  echo "Pages processed: $pages"
}

# Example usage
convert_pdf "https://example.com/paper.pdf" "Research Paper"
```

## Output Format Examples

### Math Formula Example

**Input PDF contains:**
> The Pythagorean theorem states that a² + b² = c²

**Output .mmd:**
```markdown
The Pythagorean theorem states that \( a^2 + b^2 = c^2 \)
```

### Table Example

**Input PDF contains a table**

**Output .mmd:**
```markdown
| Variable | Definition | Units |
|----------|-----------|-------|
| \( F \) | Force | Newtons |
| \( m \) | Mass | kg |
| \( a \) | Acceleration | m/s² |
```

### Complex Equation Example

**Input PDF contains:**
> Einstein's field equations

**Output .mmd:**
```markdown
Einstein's field equations:

\[
R_{\mu\nu} - \frac{1}{2}Rg_{\mu\nu} + \Lambda g_{\mu\nu} = \frac{8\pi G}{c^4}T_{\mu\nu}
\]
```

## Filename Sanitization

Same rules as media-transcript skill:

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

Example:
- Original: `Chapter 3: Quantum Mechanics & Wave Functions`
- Sanitized: `Chapter 3 - Quantum Mechanics & Wave Functions`

## Status Values

| Status | Meaning |
|--------|---------|
| `received` | PDF upload confirmed |
| `loaded` | PDF loaded into system |
| `split` | Pages being separated |
| `processing` | OCR in progress |
| `completed` | Ready for download |
| `error` | Processing failed |
