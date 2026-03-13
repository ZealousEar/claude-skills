#!/usr/bin/env bash
# verify_model.sh — Verify the actual model served by Codex CLI.
#
# Uses RUST_LOG trace inspection to check the real model in SSE responses,
# not just what was requested. Catches silent model substitution.
#
# Technique: https://gist.github.com/banteg/0ea5484d58e80b8223fcba64bd0d29db
#
# Usage:
#   verify_model.sh [model]        # default: gpt-5.3-codex
#   verify_model.sh gpt-5.2-codex  # check a specific model
#
# Exit codes:
#   0 = model matches
#   1 = model mismatch
#   2 = could not determine (trace empty)

set -uo pipefail

MODEL="${1:-chatgpt-5.4}"

echo "Verifying model: $MODEL"
echo "========================"

TRACE_FILE="/tmp/codex_model_verify_$$.txt"
RUST_LOG="codex_api::sse::responses=trace" \
    codex exec \
        --skip-git-repo-check \
        -s read-only \
        -m "$MODEL" \
        'Say exactly: "model verification check"' \
        1>/dev/null 2>"$TRACE_FILE" || true

ACTUAL_MODELS=$(grep -oE '"model":"[^"]+"' "$TRACE_FILE" 2>/dev/null | sed 's/"model":"//;s/"//' | sort -u)
MODEL_COUNT=$(echo "$ACTUAL_MODELS" | grep -c . || true)
rm -f "$TRACE_FILE"

if [[ -z "$ACTUAL_MODELS" || "$MODEL_COUNT" -eq 0 ]]; then
    echo "[WARN] Could not extract model from trace logs."
    echo "       The Codex CLI may have changed its logging format."
    echo "       Requested: $MODEL"
    exit 2
fi

if [[ "$MODEL_COUNT" -eq 1 && "$ACTUAL_MODELS" == "$MODEL" ]]; then
    echo "[OK] Requested: $MODEL"
    echo "     Served:    $ACTUAL_MODELS"
    exit 0
fi

echo "[MISMATCH] Requested: $MODEL"
echo "           Served:    $(echo "$ACTUAL_MODELS" | tr '\n' ', ' | sed 's/,$//')"
echo ""
echo "The API is silently substituting a different model."
exit 1
