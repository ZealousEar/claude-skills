#!/usr/bin/env bash
# ralph-analytics.sh — Standalone analytics loop for database-driven discovery
#
# Reuses unchanged Ralph infrastructure scripts (model_selector, session_manager --run,
# circuit_breaker, memory_indexer, benchmark_sync) without modifying any original files.
# Adds SQL execution layer between two LLM calls per iteration.
#
# 9-step per-iteration flow:
#   [1] model_selector.py         → pick model (unchanged)
#   [2] prompt_builder.py         → build prompt with analytics lenses (via analytics-config.json)
#   [3] session_manager.py --run  → LLM generates SQL queries (unchanged)
#   [4] sql_executor.py           → execute SQL via psql (analytics-specific)
#   [5] build_synthesis_prompt.py → combine prompt + SQL results (analytics-specific)
#   [6] session_manager.py --run  → LLM synthesizes findings from results (unchanged)
#   [7] analytics_evaluator.py    → score novelty + actionability + evidence (analytics-specific)
#   [8] memory_indexer.py         → update memory (unchanged)
#   [9] circuit_breaker.py        → record success/failure (unchanged)
#
# Usage:
#   bash ralph-analytics.sh              # run with defaults (15 iterations)
#   bash ralph-analytics.sh 5            # cap at 5 iterations
#   bash ralph-analytics.sh --resume ralph-analytics-20260226-123456
#
# Exit codes:
#   0 = normal exit (max iterations reached or saturation)
#   1 = fatal error
#   2 = user interrupt (Ctrl-C)

set -euo pipefail

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RALPH_DIR="$HOME/.claude/skills/ralph"
SCRIPTS="$RALPH_DIR/scripts"
CONFIG="$RALPH_DIR/settings/analytics-config.json"
PRESET="${RALPH_ANALYTICS_PRESET:-analytics}"
PRESET_FILE="$RALPH_DIR/settings/presets/${PRESET}.json"
SCHEMA_REF="${RALPH_SCHEMA_REF:-}"
OUTPUT_DIR="${RALPH_ANALYTICS_OUTPUT:-$RALPH_DIR/state}"

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
MAX_ITERATIONS="${1:-15}"
RESUME_SESSION=""

shift || true
while [[ $# -gt 0 ]]; do
    case "$1" in
        --resume)
            RESUME_SESSION="$2"
            shift 2
            ;;
        *)
            MAX_ITERATIONS="$1"
            shift
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------
if [[ ! -f "$CONFIG" ]]; then
    echo "ERROR: Analytics config not found: $CONFIG" >&2
    exit 1
fi
if [[ ! -f "$PRESET_FILE" ]]; then
    echo "ERROR: Preset not found: $PRESET_FILE" >&2
    exit 1
fi
if [[ ! -f "$SCHEMA_REF" ]]; then
    echo "ERROR: Schema reference not found: $SCHEMA_REF" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Read config values
# ---------------------------------------------------------------------------
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

DB_NAME=$(python3 -c "
import json, pathlib
c = json.loads(pathlib.Path('$CONFIG').read_text())
print(c.get('sql_execution', {}).get('db_name', 'analytics'))
")

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
    ITERATION=$(python3 -c "
import json, pathlib
s = json.loads(pathlib.Path('$STATE_DIR/session.json').read_text())
print(s.get('iteration', 0))
")
    echo "=== RALPH ANALYTICS — RESUMING SESSION $SESSION_ID at iteration $ITERATION ==="
else
    SESSION_ID="ralph-analytics-$(date +%Y%m%d-%H%M%S)"
    STATE_DIR="$RALPH_DIR/state/$SESSION_ID"
    mkdir -p "$STATE_DIR"
    ITERATION=0

    echo "=== RALPH ANALYTICS — NEW SESSION $SESSION_ID ==="
    echo "Preset: $PRESET | Mode: ANALYTICS | Domain: $DOMAIN | Max iterations: $MAX_ITERATIONS"
    echo "SQL execution: enabled (db=$DB_NAME)"
    echo ""

    # Sync benchmarks (non-fatal)
    echo "[setup] Syncing benchmarks..."
    python3 "$SCRIPTS/benchmark_sync.py" 2>&1 || echo "[setup] Benchmark sync failed (non-fatal)"
    echo ""

    # Initialize session — inline (does NOT call session_manager.py --init)
    python3 -c "
import json, time
from pathlib import Path

sid = '$SESSION_ID'
preset = '$PRESET'
max_iter = $MAX_ITERATIONS
state = Path('$STATE_DIR')

# session.json
json.dump({
    'session_id': sid,
    'preset': preset,
    'started_at': time.time(),
    'iteration': 0,
    'status': 'running',
    'output_bank': 'findings',
    'config_snapshot': {'max_iterations': max_iter, 'max_runtime_hours': 8},
    'top3_history': [],
}, (state / 'session.json').open('w'), indent=2)

# findings-bank.json
json.dump({
    'findings': [],
    'stats': {'total': 0, 'unique': 0, 'duplicates': 0, 'avg_combined_score': 0.0, 'top3_ids': []},
}, (state / 'findings-bank.json').open('w'), indent=2)

# memory.json
json.dump({'patterns': [], 'decisions': [], 'fixes': [], 'signs': []}, (state / 'memory.json').open('w'), indent=2)

# circuit-state.json
json.dump({}, (state / 'circuit-state.json').open('w'), indent=2)

# iterations.jsonl
(state / 'iterations.jsonl').write_text('')

print('Session initialized: ' + sid)
print('  Preset : ' + preset)
print('  Bank   : findings-bank.json')
print('  State  : ' + str(state))
print('  Files  : session.json, findings-bank.json, memory.json, circuit-state.json, iterations.jsonl')
" 2>&1
    echo "[setup] Session initialized: $STATE_DIR"
    echo ""
fi

# ---------------------------------------------------------------------------
# Temp files for inter-script communication
# ---------------------------------------------------------------------------
PROMPT_FILE=$(mktemp /tmp/ralph-analytics-prompt-XXXXX.txt)
RESULT_FILE=$(mktemp /tmp/ralph-analytics-result-XXXXX.json)
SQL_RESULTS=$(mktemp /tmp/ralph-analytics-sql-XXXXX.json)
SYNTH_PROMPT=$(mktemp /tmp/ralph-analytics-synth-XXXXX.txt)
SYNTH_RESULT=$(mktemp /tmp/ralph-analytics-synth-result-XXXXX.json)
EVAL_SUMMARY=$(mktemp /tmp/ralph-analytics-eval-XXXXX.json)
trap 'rm -f "$PROMPT_FILE" "${PROMPT_FILE}.system" "$RESULT_FILE" "$SQL_RESULTS" "$SYNTH_PROMPT" "${SYNTH_PROMPT}.system" "$SYNTH_RESULT" "$EVAL_SUMMARY"; echo ""; echo "=== RALPH ANALYTICS — INTERRUPTED ==="' EXIT INT TERM

# ---------------------------------------------------------------------------
# State file paths
# ---------------------------------------------------------------------------
CIRCUIT_STATE="$STATE_DIR/circuit-state.json"
FINDINGS_BANK="$STATE_DIR/findings-bank.json"
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
    # Step 1: Select model (reuses unchanged model_selector.py)
    # ------------------------------------------------------------------
    echo -n "[1/9] Selecting model... "
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
    # Step 2: Build prompt (reuses unchanged prompt_builder.py with analytics-config.json)
    # Uses analytics-config.json which points creative_lenses to analytics-lenses.yaml
    # Then appends schema reference to the system prompt file
    # ------------------------------------------------------------------
    echo -n "[2/9] Building prompt... "
    LENS_INFO=$(python3 "$SCRIPTS/prompt_builder.py" \
        --model "$MODEL" \
        --preset "$PRESET" \
        --memory "$MEMORY" \
        --ideas-bank "$FINDINGS_BANK" \
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
    LENS_NAME=$(echo "$LENS_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin).get('lens_name','unknown'))" 2>/dev/null || echo "unknown")
    echo "lens=$LENS_NAME"

    # Inject schema reference into the system prompt (post-process)
    if [[ -f "${PROMPT_FILE}.system" && -f "$SCHEMA_REF" ]]; then
        python3 -c "
from pathlib import Path
sys_path = Path('${PROMPT_FILE}.system')
schema = Path('$SCHEMA_REF').read_text()
existing = sys_path.read_text()
sys_path.write_text(existing + '\n\n## Database Schema Reference\n' + schema)
" 2>/dev/null || true
    fi

    # ------------------------------------------------------------------
    # Step 3: Call LLM — Phase 1 (generate SQL queries)
    # Reuses unchanged session_manager.py --run
    # ------------------------------------------------------------------
    echo -n "[3/9] Calling $MODEL... "
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
        CB_STATE=$(python3 "$SCRIPTS/circuit_breaker.py" \
            --record-failure "llm_call_failed" \
            --model "$MODEL" \
            --state "$CIRCUIT_STATE" \
            2>/dev/null || echo "UNKNOWN")
        echo "  Circuit breaker for $MODEL: $CB_STATE"

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

    DURATION=$(python3 -c "
import json, pathlib
r = json.loads(pathlib.Path('$RESULT_FILE').read_text())
print(f\"{r.get('duration_seconds', 0):.1f}s\")
" 2>/dev/null || echo "?s")
    echo "done (${DURATION})"

    # ------------------------------------------------------------------
    # Step 4: Execute SQL queries (analytics-specific)
    # ------------------------------------------------------------------
    echo -n "[4/9] Executing SQL... "
    python3 "$SCRIPTS/sql_executor.py" \
        --response "$RESULT_FILE" \
        --output "$SQL_RESULTS" \
        --db "$DB_NAME" \
        --config "$CONFIG" \
        2>/dev/null || echo "(sql execution failed, non-fatal)"

    SQL_OK=$(python3 -c "
import json, pathlib
try:
    r = json.loads(pathlib.Path('$SQL_RESULTS').read_text())
    print(f\"{r.get('queries_succeeded', 0)}/{r.get('queries_attempted', 0)} queries OK\")
except: print('0/0 queries OK')
" 2>/dev/null || echo "0/0 queries OK")
    echo "$SQL_OK"

    # ------------------------------------------------------------------
    # Step 5: Build synthesis prompt + call LLM — Phase 2
    # ------------------------------------------------------------------
    echo -n "[5/9] Synthesizing findings ($MODEL)... "
    python3 "$SCRIPTS/build_synthesis_prompt.py" \
        --prompt-file "$PROMPT_FILE" \
        --sql-results "$SQL_RESULTS" \
        --output "$SYNTH_PROMPT" \
        2>/dev/null || {
        echo "FAILED (synthesis prompt build)"
        # Fall back to using original result
        cp "$RESULT_FILE" "$SYNTH_RESULT"
    }

    if [[ -f "$SYNTH_PROMPT" ]]; then
        SYNTH_OK=true
        python3 "$SCRIPTS/session_manager.py" \
            --run \
            --model "$MODEL" \
            --prompt-file "$SYNTH_PROMPT" \
            --output "$SYNTH_RESULT" \
            --iteration "$ITERATION" \
            --state-dir "$STATE_DIR" \
            2>/dev/null || SYNTH_OK=false

        if [[ "$SYNTH_OK" == "false" ]]; then
            echo "FAILED (synthesis LLM call)"
            # Fall back to original result for evaluation
            cp "$RESULT_FILE" "$SYNTH_RESULT"
        else
            SYNTH_DUR=$(python3 -c "
import json, pathlib
r = json.loads(pathlib.Path('$SYNTH_RESULT').read_text())
print(f\"{r.get('duration_seconds', 0):.1f}s\")
" 2>/dev/null || echo "?s")
            echo "done (${SYNTH_DUR})"
        fi
    fi

    # ------------------------------------------------------------------
    # Step 6: Evaluate finding (analytics-specific evaluator)
    # ------------------------------------------------------------------
    echo -n "[6/9] Evaluating finding... "
    EVAL_OUTPUT=$(python3 "$SCRIPTS/analytics_evaluator.py" \
        --result "$SYNTH_RESULT" \
        --findings-bank "$FINDINGS_BANK" \
        --config "$CONFIG" \
        2>/dev/null) || {
        echo "FAILED (non-fatal)"
        EVAL_OUTPUT='{"finding_id":"unknown","combined_score":0,"is_duplicate":false,"error":"eval_failed"}'
    }
    echo "$EVAL_OUTPUT" > "$EVAL_SUMMARY"

    FINDING_ID=$(echo "$EVAL_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('finding_id','?'))" 2>/dev/null || echo "?")
    SCORE=$(echo "$EVAL_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('combined_score',0))" 2>/dev/null || echo "0")
    IS_DUP=$(echo "$EVAL_OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('is_duplicate',False))" 2>/dev/null || echo "False")
    TITLE=$(echo "$EVAL_OUTPUT" | python3 -c "import sys,json; t=json.load(sys.stdin).get('title',''); print(t[:60]+'...' if len(t)>60 else t)" 2>/dev/null || echo "")

    if [[ "$IS_DUP" == "True" ]]; then
        echo "$FINDING_ID | score=$SCORE [DUPLICATE]"
    else
        echo "$FINDING_ID | score=$SCORE"
    fi
    if [[ -n "$TITLE" ]]; then
        echo "  Title: $TITLE"
    fi

    # ------------------------------------------------------------------
    # Step 7: Update memory (reuses unchanged memory_indexer.py)
    # ------------------------------------------------------------------
    echo -n "[7/9] Updating memory... "
    python3 "$SCRIPTS/memory_indexer.py" \
        --result "$SYNTH_RESULT" \
        --memory "$MEMORY" \
        2>/dev/null || echo "(failed, non-fatal)"
    echo "done"

    # ------------------------------------------------------------------
    # Step 8: Circuit breaker (reuses unchanged circuit_breaker.py)
    # ------------------------------------------------------------------
    echo -n "[8/9] Circuit breaker... "
    python3 "$SCRIPTS/circuit_breaker.py" \
        --record-success \
        --model "$MODEL" \
        --state "$CIRCUIT_STATE" \
        2>/dev/null || true
    echo "success for $MODEL"

    # ------------------------------------------------------------------
    # Step 9: Log iteration + exit check
    # ------------------------------------------------------------------
    # Enrich result file with eval data for logging
    python3 -c "
import json, pathlib
r = json.loads(pathlib.Path('$SYNTH_RESULT').read_text())
e = json.loads(pathlib.Path('$EVAL_SUMMARY').read_text())
r['idea_id'] = e.get('finding_id', '')
r['combined_score'] = e.get('combined_score', 0)
r['is_duplicate'] = e.get('is_duplicate', False)
pathlib.Path('$SYNTH_RESULT').write_text(json.dumps(r, indent=2))
" 2>/dev/null || true

    python3 "$SCRIPTS/session_manager.py" \
        --log-iteration \
        --session "$SESSION_ID" \
        --iteration "$ITERATION" \
        --model "$MODEL" \
        --result-file "$SYNTH_RESULT" \
        --state-dir "$STATE_DIR" \
        2>/dev/null || true

    # Exit check — pass findings-bank to exit_evaluator.
    # Since it looks for "ideas" key and won't find it in findings-bank,
    # it will return CONTINUE (no saturation detected). Loop exits by MAX_ITERATIONS.
    echo -n "[9/9] Exit check... "
    EXIT_DECISION=$(python3 "$SCRIPTS/exit_evaluator.py" \
        --ideas-bank "$FINDINGS_BANK" \
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
echo "  RALPH ANALYTICS COMPLETE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ -z "$EXIT_REASON" ]]; then
    EXIT_REASON="MAX_ITERATIONS_REACHED ($MAX_ITERATIONS)"
fi
echo "Exit reason: $EXIT_REASON"
echo "Session: $SESSION_ID"
echo "State: $STATE_DIR"
echo ""

# Generate inline report (since session_manager --report only reads ideas-bank)
python3 -c "
import json, time
from pathlib import Path

state = Path('$STATE_DIR')
session = json.loads((state / 'session.json').read_text())
bank = json.loads((state / 'findings-bank.json').read_text())
stats = bank.get('stats', {})

iterations = []
log_path = state / 'iterations.jsonl'
if log_path.exists():
    for line in log_path.read_text().splitlines():
        if line.strip():
            iterations.append(json.loads(line))

total = len(iterations)
successful = sum(1 for it in iterations if it.get('success'))
duplicates = sum(1 for it in iterations if it.get('is_duplicate'))
started_at = session.get('started_at', 0)
elapsed_h = (time.time() - started_at) / 3600 if started_at else 0

mcounts = {}
mdur = {}
for it in iterations:
    m = it.get('model', 'unknown')
    mcounts[m] = mcounts.get(m, 0) + 1
    mdur[m] = mdur.get(m, 0.0) + it.get('duration_seconds', 0.0)

scored = sorted(
    [it for it in iterations if it.get('combined_score', 0) > 0],
    key=lambda x: x.get('combined_score', 0), reverse=True,
)[:5]

durations = [it.get('duration_seconds', 0) for it in iterations if it.get('success')]
avg_dur = sum(durations) / len(durations) if durations else 0

sep = '=' * 60
print(f'\n{sep}')
print('  RALPH SESSION REPORT')
print(sep)
print(f'  Session ID   : {session.get(\"session_id\", \"?\")}')
print(f'  Preset       : {session.get(\"preset\", \"?\")}')
print(f'  Status       : {session.get(\"status\", \"?\")}')
print(f'  Runtime      : {elapsed_h:.2f} hours')
print(f'  State dir    : {state}')
print(f'\n  ITERATIONS\n  {\"-\" * 40}')
print(f'  Total        : {total}')
print(f'  Successful   : {successful}')
print(f'  Failed       : {total - successful}')
print(f'  Duplicates   : {duplicates}')
print(f'  Avg duration : {avg_dur:.1f}s')
print(f'\n  FINDINGS\n  {\"-\" * 40}')
print(f'  Total findings: {stats.get(\"total\", 0)}')
print(f'  Unique findings: {stats.get(\"unique\", 0)}')
print(f'  Avg score    : {stats.get(\"avg_combined_score\", 0):.3f}')
print(f'  Top 3 IDs    : {\", \".join(stats.get(\"top3_ids\", [])) or \"none\"}')

if mcounts:
    print(f'\n  MODEL USAGE\n  {\"-\" * 40}')
    print(f'  {\"Model\":20s}  {\"Calls\":>6s}  {\"Total (s)\":>10s}  {\"Avg (s)\":>8s}')
    for m in sorted(mcounts, key=lambda x: mcounts[x], reverse=True):
        c = mcounts[m]
        d = mdur.get(m, 0)
        print(f'  {m:20s}  {c:6d}  {d:10.1f}  {d/c:8.1f}')

if scored:
    print(f'\n  TOP 5 SCORES\n  {\"-\" * 40}')
    print(f'  {\"Iter\":>5s}  {\"Model\":15s}  {\"Score\":>7s}  {\"Idea ID\"}')
    for it in scored:
        print(f'  {it.get(\"iteration\", 0):5d}  {it.get(\"model\", \"?\"):15s}  {it.get(\"combined_score\", 0):7.3f}  {it.get(\"idea_id\", \"\")}')

print(f'\n{sep}\n')
" 2>/dev/null || echo "(report generation failed)"

# ---------------------------------------------------------------------------
# Synthesis pass
# ---------------------------------------------------------------------------
echo "[post] Running synthesis pass..."
python3 "$SCRIPTS/synthesis_pass.py" \
    --findings-bank "$FINDINGS_BANK" \
    --output "$STATE_DIR/synthesis-report.json" \
    2>/dev/null || echo "(synthesis pass failed)"

# ---------------------------------------------------------------------------
# Copy to project output directory
# ---------------------------------------------------------------------------
mkdir -p "$OUTPUT_DIR/findings"
FINDINGS_DEST="$OUTPUT_DIR/findings/$SESSION_ID"
if [[ ! -d "$FINDINGS_DEST" ]]; then
    cp -r "$STATE_DIR" "$FINDINGS_DEST" 2>/dev/null || true
fi

# Update latest symlink
ln -sfn "$FINDINGS_DEST" "$OUTPUT_DIR/latest" 2>/dev/null || true

echo ""
echo "Findings copied to: $FINDINGS_DEST"
echo "Latest symlink: $OUTPUT_DIR/latest"
echo ""
echo "Bank: $FINDINGS_BANK"
echo "Iterations log: $ITERATIONS_LOG"
echo "Memory: $MEMORY"
