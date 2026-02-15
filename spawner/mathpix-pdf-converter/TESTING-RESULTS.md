# Mathpix PDF Converter - Testing Results

## Test Date
2026-01-19

## Test Files
Successfully converted 4 formal logic PDFs from JobTestPrep:
1. Formal-Logic-Guide-Generalisation-Statements.mmd (19K, 8 pages)
2. Formal-Logic-Guide-Exercise-1-Generalisations.mmd (14K)
3. Formal-Logic-Guide-Existence-Statements.mmd (12K)
4. Formal-Logic-Guide-Exercise-2-Existence.mmd (12K)

## Key Findings

### ✓ Working Pattern
```bash
# Submit PDF (no conversion_formats needed)
curl -s -X POST https://api.mathpix.com/v3/pdf \
  -H "app_id: $MATHPIX_APP_ID" \
  -H "app_key: $MATHPIX_APP_KEY" \
  -H "Content-Type: application/json" \
  --data '{"url": "PDF_URL"}' | jq -r '.pdf_id'

# Download .mmd file after completion
curl -s "https://api.mathpix.com/v3/pdf/$PDF_ID.mmd" \
  -H "app_id: $MATHPIX_APP_ID" \
  -H "app_key: $MATHPIX_APP_KEY" > output.mmd
```

### ✗ Issues Discovered

#### 1. conversion_formats Error
**Problem:** Using `"conversion_formats": {"mmd": true}` causes error:
```json
{"error":"Unknown: [\"mmd\"]"}
```

**Solution:** The .mmd format is available by default via the `.mmd` endpoint. Don't specify conversion_formats in the initial request.

#### 2. .env File Spacing
**Problem:** Space after `=` in .env file:
```bash
MATHPIX_APP_ID= farhadchichgar_07f92a_077ff7
```
Causes: `command not found: farhadchichgar_07f92a_077ff7`

**Solution:** Remove space:
```bash
MATHPIX_APP_ID=farhadchichgar_07f92a_077ff7
```

### Processing Performance
- Most PDFs completed almost immediately (< 5 seconds)
- Status progression: `received` → `split` → `completed`
- No manual polling needed for small PDFs (< 10 pages)

### Output Quality
Excellent quality for academic content:
- **Math formulas:** Properly converted to LaTeX `\( inline \)` and `\[ display \]`
- **Tables:** Clean LaTeX tabular format
- **Symbols:** Correctly escaped (arrows, negation, etc.)
- **Structure:** Headers, sections, and formatting preserved

## Updated Files
All skill files updated to reflect findings:
- ✓ skill.yaml - Removed conversion_formats from examples
- ✓ patterns.md - Updated all curl commands
- ✓ sharp-edges.yaml - Added new sharp edges for discovered issues
- ✓ example-usage.sh - Corrected API calls
- ✓ README.md - Updated quick start and advanced options

## Test Command Used
```bash
MATHPIX_APP_ID="farhadchichgar_07f92a_077ff7" \
MATHPIX_APP_KEY="1a8156f94d5ae2330b41d371df6dbbcf31e07bc5601b052fe45632016304f815" \
PDF_ID="67c88274-b3b5-4ceb-a11a-448109a1db9c"

# Poll and download
for i in {1..20}; do
  STATUS=$(curl -s "https://api.mathpix.com/v3/pdf/$PDF_ID" \
    -H "app_id: $MATHPIX_APP_ID" \
    -H "app_key: $MATHPIX_APP_KEY" | jq -r '.status')
  if [ "$STATUS" = "completed" ]; then
    curl -s "https://api.mathpix.com/v3/pdf/$PDF_ID.mmd" \
      -H "app_id: $MATHPIX_APP_ID" \
      -H "app_key: $MATHPIX_APP_KEY" > output.mmd
    break
  fi
  sleep 3
done
```

## Conclusion
The skill is fully functional and ready for use. The main gotcha is not to use conversion_formats in the initial request - just submit the PDF and download via the .mmd endpoint.
