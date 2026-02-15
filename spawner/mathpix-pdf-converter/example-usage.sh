#!/bin/bash

# Mathpix PDF Converter - Example Usage Script
# This demonstrates how to convert a PDF to Mathpix Markdown

set -e  # Exit on error

# Check if .env file exists
ENV_FILE="${HOME}/Library/Mobile Documents/iCloud~md~obsidian/Documents/Vault 2/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "Error: .env file not found at $ENV_FILE"
    exit 1
fi

# Load environment variables
echo "Loading API credentials from .env..."
source "$ENV_FILE"

# Verify credentials are set
if [ -z "$MATHPIX_APP_ID" ] || [ "$MATHPIX_APP_ID" = "your_app_id_here" ]; then
    echo "Error: MATHPIX_APP_ID not configured in .env file"
    echo "Get your credentials at: https://console.mathpix.com"
    exit 1
fi

if [ -z "$MATHPIX_APP_KEY" ] || [ "$MATHPIX_APP_KEY" = "your_app_key_here" ]; then
    echo "Error: MATHPIX_APP_KEY not configured in .env file"
    echo "Get your credentials at: https://console.mathpix.com"
    exit 1
fi

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    echo "Error: jq is required but not installed"
    echo "Install with: brew install jq"
    exit 1
fi

# Function to sanitize filename
sanitize_filename() {
    echo "$1" | tr '/:*?"<>|' '-' | tr -s ' -'
}

# Function to convert PDF
convert_pdf() {
    local input=$1
    local title=${2:-"Converted Document"}

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Converting: $title"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Determine if input is URL or file
    if [[ $input =~ ^https?:// ]]; then
        echo "Source: URL"
        # Submit PDF via URL (.mmd format available by default)
        response=$(curl -s -X POST https://api.mathpix.com/v3/pdf \
            -H "app_id: $MATHPIX_APP_ID" \
            -H "app_key: $MATHPIX_APP_KEY" \
            -H "Content-Type: application/json" \
            --data "{\"url\": \"$input\"}")
    else
        echo "Source: Local file"
        # Check if file exists
        if [ ! -f "$input" ]; then
            echo "Error: File not found: $input"
            return 1
        fi
        # Submit PDF via file upload (.mmd format available by default)
        response=$(curl -s -X POST https://api.mathpix.com/v3/pdf \
            -H "app_id: $MATHPIX_APP_ID" \
            -H "app_key: $MATHPIX_APP_KEY" \
            --form "file=@\"$input\"")
    fi

    # Extract PDF ID
    PDF_ID=$(echo "$response" | jq -r '.pdf_id')

    if [ "$PDF_ID" = "null" ] || [ -z "$PDF_ID" ]; then
        echo "Error: Failed to submit PDF"
        echo "$response" | jq
        return 1
    fi

    echo "PDF ID: $PDF_ID"
    echo ""

    # Poll for completion
    echo "Processing..."
    local prev_percent=0
    while true; do
        status_response=$(curl -s "https://api.mathpix.com/v3/pdf/$PDF_ID" \
            -H "app_id: $MATHPIX_APP_ID" \
            -H "app_key: $MATHPIX_APP_KEY")

        status=$(echo "$status_response" | jq -r '.status')
        percent=$(echo "$status_response" | jq -r '.percent_done // 0')

        if [ "$status" = "completed" ]; then
            echo "✓ Conversion completed (100%)"
            break
        elif [ "$status" = "error" ]; then
            error=$(echo "$status_response" | jq -r '.error')
            echo "✗ Error: $error"
            return 1
        fi

        # Only print progress if it changed
        if [ "$percent" != "$prev_percent" ]; then
            echo "  Status: $status - ${percent}%"
            prev_percent=$percent
        fi

        sleep 5
    done

    # Get metadata
    num_pages=$(echo "$status_response" | jq -r '.num_pages')

    # Sanitize title and create folder
    safe_title=$(sanitize_filename "$title")
    output_dir="Transcripts/$safe_title"
    mkdir -p "$output_dir"

    # Download .mmd file
    output_file="$output_dir/$safe_title.mmd"
    curl -s "https://api.mathpix.com/v3/pdf/$PDF_ID.mmd" \
        -H "app_id: $MATHPIX_APP_ID" \
        -H "app_key: $MATHPIX_APP_KEY" \
        > "$output_file"

    # Get file size
    file_size=$(du -h "$output_file" | cut -f1)

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "✓ Conversion successful!"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Pages: $num_pages"
    echo "Size: $file_size"
    echo "Output: $output_file"
    echo ""
}

# Main script
echo ""
echo "╔═══════════════════════════════════════════╗"
echo "║   Mathpix PDF to Markdown Converter      ║"
echo "╚═══════════════════════════════════════════╝"
echo ""

# Example 1: Convert from URL
echo "Example 1: Converting PDF from URL"
echo ""
# Uncomment and modify with your PDF URL:
# convert_pdf "https://example.com/paper.pdf" "Research Paper Title"

# Example 2: Convert from local file
echo "Example 2: Converting local PDF file"
echo ""
# Uncomment and modify with your local file path:
# convert_pdf "/path/to/document.pdf" "Document Title"

# Interactive mode
read -p "Enter PDF URL or local file path (or press Enter to skip): " input

if [ -n "$input" ]; then
    read -p "Enter a title for this document: " title
    if [ -z "$title" ]; then
        title="Converted Document $(date +%Y%m%d_%H%M%S)"
    fi

    convert_pdf "$input" "$title"
else
    echo "No input provided. Edit this script to add your PDF URLs or file paths."
    echo ""
    echo "Usage examples:"
    echo "  convert_pdf \"https://example.com/paper.pdf\" \"Paper Title\""
    echo "  convert_pdf \"/path/to/file.pdf\" \"Document Title\""
fi

echo ""
echo "Done!"
