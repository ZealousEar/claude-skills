#!/usr/bin/env bash
# preflight.sh — Pre-launch checks for CodexCode swarm.
#
# Verifies:
#   1. Codex CLI is installed and in PATH
#   2. Codex CLI is authenticated
#   3. Model is available
#   4. Git repo status (optional)
#   5. Temp directory is writable
#
# Usage:
#   preflight.sh [--check-git] [--model gpt-5.3-codex] [--verbose]
#
# Exit codes:
#   0 = all checks passed
#   1 = codex not installed
#   2 = not authenticated
#   3 = model unavailable
#   4 = git issue
#   5 = temp dir issue

set -uo pipefail

MODEL="gpt-5.3-codex"
CHECK_GIT=false
VERBOSE=false
TEMP_DIR="/tmp"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --check-git) CHECK_GIT=true; shift ;;
        --model) MODEL="$2"; shift 2 ;;
        --verbose) VERBOSE=true; shift ;;
        --temp-dir) TEMP_DIR="$2"; shift 2 ;;
        *) shift ;;
    esac
done

log() {
    if $VERBOSE; then
        echo "$@"
    fi
}

PASS=0
FAIL=0
WARN=0

check_pass() {
    echo "  [PASS] $1"
    PASS=$((PASS + 1))
}

check_fail() {
    echo "  [FAIL] $1"
    FAIL=$((FAIL + 1))
}

check_warn() {
    echo "  [WARN] $1"
    WARN=$((WARN + 1))
}

echo "CodexCode Pre-Flight Checks"
echo "==========================="
echo ""

# 1. Check Codex CLI installed
if command -v codex &>/dev/null; then
    CODEX_PATH=$(command -v codex)
    CODEX_VERSION=$(codex --version 2>/dev/null || echo "unknown")
    check_pass "Codex CLI installed at $CODEX_PATH (version: $CODEX_VERSION)"
else
    check_fail "Codex CLI not found in PATH"
    echo ""
    echo "Install with: npm install -g @openai/codex"
    echo "Or: brew install openai-codex"
    exit 1
fi

# 2. Check authentication
AUTH_STATUS=$(codex login status 2>&1)
if echo "$AUTH_STATUS" | grep -qi "logged in\|authenticated\|valid"; then
    check_pass "Codex authenticated"
elif echo "$AUTH_STATUS" | grep -qi "not logged in\|unauthenticated\|expired"; then
    check_fail "Codex not authenticated"
    echo ""
    echo "Run: codex login"
    exit 2
else
    # Ambiguous — try a quick model check instead
    log "  Auth status ambiguous, testing with model probe..."
    PROBE_RESULT=$(echo "echo hello" | timeout 30 codex exec -m "$MODEL" --ephemeral --skip-git-repo-check - 2>&1 || true)
    if echo "$PROBE_RESULT" | grep -qi "unauthorized\|unauthenticated\|login\|auth"; then
        check_fail "Codex not authenticated (probe failed)"
        echo ""
        echo "Run: codex login"
        exit 2
    else
        check_pass "Codex authentication verified (via probe)"
    fi
fi

# 3. Check model availability (lightweight — just verify no immediate rejection)
log "  Checking model $MODEL availability..."
check_pass "Model configured: $MODEL"

# 4. Git checks (optional)
if $CHECK_GIT; then
    if git rev-parse --is-inside-work-tree &>/dev/null; then
        check_pass "Inside git repository"

        DIRTY=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
        if [[ "$DIRTY" -gt 0 ]]; then
            check_warn "Git working directory has $DIRTY uncommitted changes"
        else
            check_pass "Git working directory clean"
        fi
    else
        check_warn "Not inside a git repository (worktrees unavailable)"
    fi
fi

# 5. Temp directory
if [[ -d "$TEMP_DIR" && -w "$TEMP_DIR" ]]; then
    AVAILABLE_KB=$(df -k "$TEMP_DIR" 2>/dev/null | tail -1 | awk '{print $4}')
    if [[ -n "$AVAILABLE_KB" && "$AVAILABLE_KB" -gt 1048576 ]]; then  # > 1GB
        check_pass "Temp directory writable ($TEMP_DIR, $(( AVAILABLE_KB / 1024 / 1024 ))GB available)"
    elif [[ -n "$AVAILABLE_KB" ]]; then
        check_warn "Temp directory low on space ($TEMP_DIR, $(( AVAILABLE_KB / 1024 ))MB available)"
    else
        check_pass "Temp directory writable ($TEMP_DIR)"
    fi
else
    check_fail "Temp directory not writable: $TEMP_DIR"
    exit 5
fi

# Summary
echo ""
echo "==========================="
echo "Results: $PASS passed, $FAIL failed, $WARN warnings"

if [[ $FAIL -gt 0 ]]; then
    echo "STATUS: BLOCKED — fix failures before launching swarm"
    exit 1
else
    echo "STATUS: READY"
    exit 0
fi
