#!/usr/bin/env bash
# ralph.sh — Fresh-context loop orchestrator for dissertation idea generation
#
# Calls 8 Python scripts per iteration, managing the full lifecycle:
#   model_selector → prompt_builder → session_manager --run →
#   idea_evaluator → memory_indexer → circuit_breaker → exit_evaluator
#
# Usage:
#   bash ralph.sh idea-generation              # run with defaults (max 200 iterations)
#   bash ralph.sh idea-generation 10           # cap at 10 iterations
#   bash ralph.sh idea-generation --resume s1234  # resume a previous session
#
# Exit codes:
#   0 = normal exit (saturation, budget, or max iterations reached)
#   1 = fatal error (no models available, config missing, etc.)
#   2 = user interrupt (Ctrl-C)

set -euo pipefail

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RALPH_DIR="$HOME/.claude/skills/ralph"
SCRIPTS="$RALPH_DIR/scripts"
CONFIG="$RALPH_DIR/settings/ralph-config.json"

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
PRESET="${1:-idea-generation}"
MAX_ITERATIONS_OVERRIDE=""
RESUME_SESSION=""

shift || true
while [[ $# -gt 0 ]]; do
    case "$1" in
        --resume)
            RESUME_SESSION="$2"
            shift 2
            ;;
        *)
            MAX_ITERATIONS_OVERRIDE="$1"
            shift
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Validate config
# ---------------------------------------------------------------------------
if [[ ! -f "$CONFIG" ]]; then
    echo "ERROR: Ralph config not found: $CONFIG" >&2
    exit 1
fi

# Validate llm skill dependency
if [[ ! -f "$HOME/.claude/skills/llm/scripts/llm_route.py" ]]; then
    echo "ERROR: /llm skill not found at ~/.claude/skills/llm/" >&2
    echo "Ralph requires the llm skill for model routing." >&2
    echo "Install it from the same repo: bash install.sh" >&2
    echo "Or manually: cp -r claude-code/llm ~/.claude/skills/" >&2
    exit 1
fi

PRESET_FILE="$RALPH_DIR/settings/presets/${PRESET}.json"
if [[ ! -f "$PRESET_FILE" ]]; then
    echo "ERROR: Preset not found: $PRESET_FILE" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Read config values
# ---------------------------------------------------------------------------
MAX_ITERATIONS=$(python3 -c "
import json, pathlib
c = json.loads(pathlib.Path('$CONFIG').read_text())
print(c.get('loop', {}).get('max_iterations', 200))
")

COOLDOWN=$(python3 -c "
import json, pathlib
c = json.loads(pathlib.Path('$CONFIG').read_text())
print(c.get('loop', {}).get('cooldown_between_iterations_seconds', 5))
")

DOMAIN=$(python3 -c "
import json, pathlib
c = json.loads(pathlib.Path('$CONFIG').read_text())
print(c.get('model_selection', {}).get('domain', 'academic'))
")

# Override max iterations if provided
if [[ -n "$MAX_ITERATIONS_OVERRIDE" ]]; then
    MAX_ITERATIONS="$MAX_ITERATIONS_OVERRIDE"
fi

# ---------------------------------------------------------------------------
# Session setup
# ---------------------------------------------------------------------------
if [[ -n "$RESUME_SESSION" ]]; then
    SESSION_ID="$RESUME_SESSION"
    STATE_DIR="$RALPH_DIR/state/$SESSION_ID"
    if [[ ! -d "$STATE_DIR" ]]; then
        echo "ERROR: Session state not found: $STATE_DIR" >&2
        exit 1
    fi
    # Read current iteration from session.json
    ITERATION=$(python3 -c "
import json, pathlib
s = json.loads(pathlib.Path('$STATE_DIR/session.json').read_text())
print(s.get('iteration', 0))
")
    echo "=== RALPH LOOP — RESUMING SESSION $SESSION_ID at iteration $ITERATION ==="
else
    SESSION_ID="ralph-$(date +%Y%m%d-%H%M%S)"
    STATE_DIR="$RALPH_DIR/state/$SESSION_ID"
    mkdir -p "$STATE_DIR"
    ITERATION=0

    echo "=== RALPH LOOP — NEW SESSION $SESSION_ID ==="
    echo "Preset: $PRESET | Domain: $DOMAIN | Max iterations: $MAX_ITERATIONS"
    echo ""

    # Sync benchmarks (non-fatal)
    echo "[setup] Syncing benchmarks..."
    python3 "$SCRIPTS/benchmark_sync.py" 2>&1 || echo "[setup] Benchmark sync failed (non-fatal)"
    echo ""

    # Initialize session
    python3 "$SCRIPTS/session_manager.py" \
        --init \
        --session "$SESSION_ID" \
        --preset "$PRESET" \
        --state-dir "$STATE_DIR"
    echo "[setup] Session initialized: $STATE_DIR"
    echo ""
fi

# ---------------------------------------------------------------------------
# Temp files for inter-script communication
# ---------------------------------------------------------------------------
PROMPT_FILE=$(mktemp /tmp/ralph-prompt-XXXXX.txt)
RESULT_FILE=$(mktemp /tmp/ralph-result-XXXXX.json)
EVAL_SUMMARY=$(mktemp /tmp/ralph-eval-XXXXX.json)
trap 'rm -f "$PROMPT_FILE" "${PROMPT_FILE}.system" "$RESULT_FILE" "$EVAL_SUMMARY"; echo ""; echo "=== RALPH LOOP — INTERRUPTED ==="' EXIT INT TERM

# ---------------------------------------------------------------------------
# State file paths
# ---------------------------------------------------------------------------
CIRCUIT_STATE="$STATE_DIR/circuit-state.json"
IDEAS_BANK="$STATE_DIR/ideas-bank.json"
MEMORY="$STATE_DIR/memory.json"
SESSION_JSON="$STATE_DIR/session.json"
ITERATIONS_LOG="$STATE_DIR/iterations.jsonl"

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
echo "=== Starting iteration loop (max $MAX_ITERATIONS) ==="
echo ""

EXIT_REASON=""
CONSECUTIVE_FAILURES=0
MAX_CONSECUTIVE_FAILURES=10

while [[ $ITERATION -lt $MAX_ITERATIONS ]]; do
    ITERATION=$((ITERATION + 1))
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  ITERATION $ITERATION / $MAX_ITERATIONS"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # ------------------------------------------------------------------
    # Step 1: Select model
    # ------------------------------------------------------------------
    echo -n "[1/7] Selecting model... "
    MODEL=$(python3 "$SCRIPTS/model_selector.py" \
        --config "$CONFIG" \
        --domain "$DOMAIN" \
        --history "$ITERATIONS_LOG" \
        --circuit-state "$CIRCUIT_STATE" \
        2>/dev/null) || {
        echo "FAILED"
        echo "ERROR: No models available (all circuit-broken?)" >&2
        EXIT_REASON="ALL_MODELS_BROKEN"
        break
    }
    echo "$MODEL"

    # ------------------------------------------------------------------
    # Step 2: Build prompt
    # ------------------------------------------------------------------
    echo -n "[2/7] Building prompt... "
    LENS_INFO=$(python3 "$SCRIPTS/prompt_builder.py" \
        --model "$MODEL" \
        --preset "$PRESET" \
        --memory "$MEMORY" \
        --ideas-bank "$IDEAS_BANK" \
        --iteration "$ITERATION" \
        --output "$PROMPT_FILE" \
        --config "$CONFIG" \
        2>/dev/null) || {
        echo "FAILED"
        echo "WARNING: Prompt build failed, skipping iteration" >&2
        CONSECUTIVE_FAILURES=$((CONSECUTIVE_FAILURES + 1))
        if [[ $CONSECUTIVE_FAILURES -ge $MAX_CONSECUTIVE_FAILURES ]]; then
            EXIT_REASON="TOO_MANY_CONSECUTIVE_FAILURES"
            break
        fi
        continue
    }
    # Extract lens name from JSON output
    LENS_NAME=$(echo "$LENS_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin).get('lens_name','unknown'))" 2>/dev/null || echo "unknown")
    echo "lens=$LENS_NAME"

    # ------------------------------------------------------------------
    # Step 3: Call LLM
    # ------------------------------------------------------------------
    echo -n "[3/7] Calling $MODEL... "
    LLM_OK=true
    python3 "$SCRIPTS/session_manager.py" \
        --run \
        --model "$MODEL" \
        --prompt-file "$PROMPT_FILE" \
        --output "$RESULT_FILE" \
        --iteration "$ITERATION" \
        --state-dir "$STATE_DIR" \
        2>/dev/null || LLM_OK=false

    if [[ "$LLM_OK" == "false" ]]; then
        echo "FAILED"
        # Record failure in circuit breaker
        CB_STATE=$(python3 "$SCRIPTS/circuit_breaker.py" \
            --record-failure "llm_call_failed" \
            --model "$MODEL" \
            --state "$CIRCUIT_STATE" \
            2>/dev/null || echo "UNKNOWN")
        echo "  Circuit breaker for $MODEL: $CB_STATE"

        # Log failed iteration
        python3 "$SCRIPTS/session_manager.py" \
            --log-iteration \
            --session "$SESSION_ID" \
            --iteration "$ITERATION" \
            --model "$MODEL" \
            --result-file "$RESULT_FILE" \
            --state-dir "$STATE_DIR" \
            2>/dev/null || true

        # Update memory with failure
        python3 "$SCRIPTS/memory_indexer.py" \
            --result "$RESULT_FILE" \
            --memory "$MEMORY" \
            2>/dev/null || true

        CONSECUTIVE_FAILURES=$((CONSECUTIVE_FAILURES + 1))
        if [[ $CONSECUTIVE_FAILURES -ge $MAX_CONSECUTIVE_FAILURES ]]; then
            EXIT_REASON="TOO_MANY_CONSECUTIVE_FAILURES"
            break
        fi

        echo ""
        sleep "$COOLDOWN"
        continue
    fi

    # Extract duration from result
    DURATION=$(python3 -c "
import json, pathlib
r = json.loads(pathlib.Path('$RESULT_FILE').read_text())
print(f\"{r.get('duration_seconds', 0):.1f}s\")
" 2>/dev/null || echo "?s")
    echo "done (${DURATION})"

    # ------------------------------------------------------------------
    # Step 4: Evaluate idea
    # ------------------------------------------------------------------
    echo -n "[4/7] Evaluating idea... "
    EVAL_OUTPUT=$(python3 "$SCRIPTS/idea_evaluator.py" \
        --result "$RESULT_FILE" \
        --ideas-bank "$IDEAS_BANK" \
        --config "$CONFIG" \
        2>/dev/null) || {
        echo "FAILED (non-fatal)"
        EVAL_OUTPUT='{"idea_id":"unknown","combined_score":0,"is_duplicate":false,"error":"eval_failed"}'
    }
    echo "$EVAL_OUTPUT" > "$EVAL_SUMMARY"

    # Parse eval results
    IDEA_ID=$(echo "$EVAL_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('idea_id','?'))" 2>/dev/null || echo "?")
    SCORE=$(echo "$EVAL_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('combined_score',0))" 2>/dev/null || echo "0")
    IS_DUP=$(echo "$EVAL_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('is_duplicate',False))" 2>/dev/null || echo "False")
    TITLE=$(echo "$EVAL_OUTPUT" | python3 -c "import sys,json; t=json.load(sys.stdin).get('title',''); print(t[:60]+'...' if len(t)>60 else t)" 2>/dev/null || echo "")

    if [[ "$IS_DUP" == "True" ]]; then
        echo "$IDEA_ID | score=$SCORE [DUPLICATE]"
    else
        echo "$IDEA_ID | score=$SCORE"
    fi
    if [[ -n "$TITLE" ]]; then
        echo "  Title: $TITLE"
    fi

    # ------------------------------------------------------------------
    # Step 5: Update memory
    # ------------------------------------------------------------------
    echo -n "[5/7] Updating memory... "
    python3 "$SCRIPTS/memory_indexer.py" \
        --result "$RESULT_FILE" \
        --memory "$MEMORY" \
        2>/dev/null || echo "(failed, non-fatal)"
    echo "done"

    # ------------------------------------------------------------------
    # Step 6: Record circuit breaker success
    # ------------------------------------------------------------------
    echo -n "[6/7] Circuit breaker... "
    python3 "$SCRIPTS/circuit_breaker.py" \
        --record-success \
        --model "$MODEL" \
        --state "$CIRCUIT_STATE" \
        2>/dev/null || true
    echo "success for $MODEL"

    # ------------------------------------------------------------------
    # Step 7: Log iteration + check exit
    # ------------------------------------------------------------------
    # Enrich result file with eval data for log-iteration
    python3 -c "
import json, pathlib
r = json.loads(pathlib.Path('$RESULT_FILE').read_text())
e = json.loads(pathlib.Path('$EVAL_SUMMARY').read_text())
r['idea_id'] = e.get('idea_id', '')
r['combined_score'] = e.get('combined_score', 0)
r['is_duplicate'] = e.get('is_duplicate', False)
pathlib.Path('$RESULT_FILE').write_text(json.dumps(r, indent=2))
" 2>/dev/null || true

    python3 "$SCRIPTS/session_manager.py" \
        --log-iteration \
        --session "$SESSION_ID" \
        --iteration "$ITERATION" \
        --model "$MODEL" \
        --result-file "$RESULT_FILE" \
        --state-dir "$STATE_DIR" \
        2>/dev/null || true

    # Check exit condition
    echo -n "[7/7] Exit check... "
    EXIT_DECISION=$(python3 "$SCRIPTS/exit_evaluator.py" \
        --ideas-bank "$IDEAS_BANK" \
        --session "$SESSION_JSON" \
        --config "$CONFIG" \
        2>/dev/null) || EXIT_DECISION="CONTINUE"

    echo "$EXIT_DECISION"

    if [[ "$EXIT_DECISION" != "CONTINUE" ]]; then
        EXIT_REASON="$EXIT_DECISION"
        break
    fi

    # Reset consecutive failure counter on success
    CONSECUTIVE_FAILURES=0

    echo ""
    if [[ $ITERATION -lt $MAX_ITERATIONS ]]; then
        sleep "$COOLDOWN"
    fi
done

# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  RALPH LOOP COMPLETE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ -z "$EXIT_REASON" ]]; then
    EXIT_REASON="MAX_ITERATIONS_REACHED ($MAX_ITERATIONS)"
fi
echo "Exit reason: $EXIT_REASON"
echo "Session: $SESSION_ID"
echo "State: $STATE_DIR"
echo ""

# Generate report
python3 "$SCRIPTS/session_manager.py" \
    --report \
    --session "$SESSION_ID" \
    --state-dir "$STATE_DIR" \
    2>/dev/null || echo "(report generation failed)"

echo ""
echo "Ideas bank: $IDEAS_BANK"
echo "Iterations log: $ITERATIONS_LOG"
echo "Memory: $MEMORY"
