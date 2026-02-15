#!/usr/bin/env bash
# worktree_manager.sh — Create, list, and cleanup git worktrees for parallel Codex agents.
#
# Usage:
#   worktree_manager.sh create <session_id> <agent_count> [--base-dir /tmp/codex_worktrees]
#   worktree_manager.sh list   <session_id> [--base-dir /tmp/codex_worktrees]
#   worktree_manager.sh merge  <session_id> <agent_number> [--strategy diff-apply|cherry-pick]
#   worktree_manager.sh cleanup <session_id> [--base-dir /tmp/codex_worktrees]
#   worktree_manager.sh status <session_id> [--base-dir /tmp/codex_worktrees]

set -euo pipefail

BASE_DIR="/tmp/codex_worktrees"
MERGE_STRATEGY="diff-apply"

usage() {
    echo "Usage: $0 <command> <session_id> [options]"
    echo ""
    echo "Commands:"
    echo "  create  <sid> <N>     Create N worktrees for session"
    echo "  list    <sid>         List worktrees for session"
    echo "  merge   <sid> <i>     Merge agent i's changes back to current branch"
    echo "  cleanup <sid>         Remove all worktrees and branches for session"
    echo "  status  <sid>         Show status of all worktrees"
    echo ""
    echo "Options:"
    echo "  --base-dir <path>     Base directory for worktrees (default: $BASE_DIR)"
    echo "  --strategy <method>   Merge strategy: diff-apply or cherry-pick (default: $MERGE_STRATEGY)"
    exit 1
}

# Parse global options
while [[ $# -gt 0 ]]; do
    case "$1" in
        --base-dir) BASE_DIR="$2"; shift 2 ;;
        --strategy) MERGE_STRATEGY="$2"; shift 2 ;;
        *) break ;;
    esac
done

COMMAND="${1:-}"
SESSION_ID="${2:-}"

if [[ -z "$COMMAND" || -z "$SESSION_ID" ]]; then
    usage
fi

# Get the repo root
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "")"
if [[ -z "$REPO_ROOT" ]]; then
    echo "ERROR: Not in a git repository. Worktrees require git."
    exit 1
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
SESSION_DIR="${BASE_DIR}/${SESSION_ID}"

create_worktrees() {
    local agent_count="${3:-}"
    if [[ -z "$agent_count" ]]; then
        echo "ERROR: Agent count required. Usage: $0 create <sid> <N>"
        exit 1
    fi

    mkdir -p "$SESSION_DIR"

    echo "Creating $agent_count worktrees for session $SESSION_ID..."
    echo "  Repo: $REPO_ROOT"
    echo "  Base branch: $CURRENT_BRANCH"
    echo "  Worktree dir: $SESSION_DIR"
    echo ""

    local created=0
    for i in $(seq 1 "$agent_count"); do
        local wt_dir="${SESSION_DIR}/agent_${i}"
        local branch_name="codex-swarm-${SESSION_ID}-agent-${i}"

        if [[ -d "$wt_dir" ]]; then
            echo "  Agent $i: SKIP (already exists at $wt_dir)"
            continue
        fi

        # Create worktree on a new branch from current HEAD
        git worktree add -b "$branch_name" "$wt_dir" HEAD 2>/dev/null
        created=$((created + 1))
        echo "  Agent $i: CREATED at $wt_dir (branch: $branch_name)"
    done

    echo ""
    echo "Created $created worktrees. Total: $agent_count"
    echo ""
    echo "Agent working directories:"
    for i in $(seq 1 "$agent_count"); do
        echo "  Agent $i: ${SESSION_DIR}/agent_${i}"
    done
}

list_worktrees() {
    if [[ ! -d "$SESSION_DIR" ]]; then
        echo "No worktrees found for session $SESSION_ID"
        exit 0
    fi

    echo "Worktrees for session $SESSION_ID:"
    for wt_dir in "$SESSION_DIR"/agent_*; do
        if [[ -d "$wt_dir" ]]; then
            local agent_num
            agent_num=$(basename "$wt_dir" | sed 's/agent_//')
            local branch
            branch=$(cd "$wt_dir" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
            echo "  Agent $agent_num: $wt_dir (branch: $branch)"
        fi
    done
}

merge_agent() {
    local agent_num="${3:-}"
    if [[ -z "$agent_num" ]]; then
        echo "ERROR: Agent number required. Usage: $0 merge <sid> <i>"
        exit 1
    fi

    local wt_dir="${SESSION_DIR}/agent_${agent_num}"
    local branch_name="codex-swarm-${SESSION_ID}-agent-${agent_num}"

    if [[ ! -d "$wt_dir" ]]; then
        echo "ERROR: Worktree not found at $wt_dir"
        exit 1
    fi

    echo "Merging Agent $agent_num changes..."
    echo "  Strategy: $MERGE_STRATEGY"
    echo "  Source: $wt_dir (branch: $branch_name)"
    echo "  Target: $CURRENT_BRANCH"

    case "$MERGE_STRATEGY" in
        diff-apply)
            # Generate a patch from the worktree's changes and apply to current branch
            local patch_file="${SESSION_DIR}/agent_${agent_num}.patch"
            cd "$wt_dir"
            local has_changes
            has_changes=$(git diff HEAD --stat 2>/dev/null || echo "")
            local has_staged
            has_staged=$(git diff --cached --stat 2>/dev/null || echo "")
            local has_untracked
            has_untracked=$(git ls-files --others --exclude-standard 2>/dev/null || echo "")

            if [[ -z "$has_changes" && -z "$has_staged" && -z "$has_untracked" ]]; then
                echo "  No changes to merge from Agent $agent_num"
                return 0
            fi

            # Stage everything and create a patch
            git add -A 2>/dev/null
            git diff --cached > "$patch_file" 2>/dev/null

            if [[ ! -s "$patch_file" ]]; then
                echo "  No diff to apply from Agent $agent_num"
                return 0
            fi

            # Apply patch to repo root
            cd "$REPO_ROOT"
            if git apply --check "$patch_file" 2>/dev/null; then
                git apply "$patch_file"
                echo "  SUCCESS: Applied $(wc -l < "$patch_file") line patch"
            else
                echo "  CONFLICT: Patch does not apply cleanly. Saving to $patch_file for manual review."
                return 1
            fi
            ;;

        cherry-pick)
            # Commit in worktree and cherry-pick to current branch
            cd "$wt_dir"
            git add -A 2>/dev/null
            local has_staged
            has_staged=$(git diff --cached --stat 2>/dev/null || echo "")
            if [[ -z "$has_staged" ]]; then
                echo "  No changes to merge from Agent $agent_num"
                return 0
            fi
            git commit -m "codex-agent-${agent_num}: swarm session ${SESSION_ID}" 2>/dev/null
            local commit_hash
            commit_hash=$(cd "$wt_dir" && git rev-parse HEAD)

            cd "$REPO_ROOT"
            if git cherry-pick "$commit_hash" 2>/dev/null; then
                echo "  SUCCESS: Cherry-picked commit $commit_hash"
            else
                echo "  CONFLICT: Cherry-pick failed. Resolve manually."
                git cherry-pick --abort 2>/dev/null || true
                return 1
            fi
            ;;

        *)
            echo "ERROR: Unknown merge strategy: $MERGE_STRATEGY"
            exit 1
            ;;
    esac
}

cleanup_worktrees() {
    if [[ ! -d "$SESSION_DIR" ]]; then
        echo "No worktrees found for session $SESSION_ID"
        exit 0
    fi

    echo "Cleaning up worktrees for session $SESSION_ID..."

    for wt_dir in "$SESSION_DIR"/agent_*; do
        if [[ -d "$wt_dir" ]]; then
            local agent_num
            agent_num=$(basename "$wt_dir" | sed 's/agent_//')
            local branch_name="codex-swarm-${SESSION_ID}-agent-${agent_num}"

            # Remove worktree
            git worktree remove --force "$wt_dir" 2>/dev/null || rm -rf "$wt_dir"

            # Delete the branch
            git branch -D "$branch_name" 2>/dev/null || true

            echo "  Removed: Agent $agent_num ($wt_dir, branch $branch_name)"
        fi
    done

    # Remove session directory
    rm -rf "$SESSION_DIR"

    # Prune worktree metadata
    git worktree prune 2>/dev/null || true

    echo "Cleanup complete."
}

status_worktrees() {
    if [[ ! -d "$SESSION_DIR" ]]; then
        echo "No worktrees found for session $SESSION_ID"
        exit 0
    fi

    echo "Status for session $SESSION_ID:"
    echo ""

    for wt_dir in "$SESSION_DIR"/agent_*; do
        if [[ -d "$wt_dir" ]]; then
            local agent_num
            agent_num=$(basename "$wt_dir" | sed 's/agent_//')
            echo "Agent $agent_num ($wt_dir):"

            cd "$wt_dir"
            local branch
            branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
            echo "  Branch: $branch"

            # Count changes
            local modified added deleted untracked
            modified=$(git diff --stat 2>/dev/null | tail -1 || echo "no changes")
            untracked=$(git ls-files --others --exclude-standard 2>/dev/null | wc -l | tr -d ' ')

            echo "  Changes: $modified"
            echo "  Untracked: $untracked files"
            echo ""
        fi
    done
}

# Dispatch
case "$COMMAND" in
    create)  create_worktrees "$@" ;;
    list)    list_worktrees "$@" ;;
    merge)   merge_agent "$@" ;;
    cleanup) cleanup_worktrees "$@" ;;
    status)  status_worktrees "$@" ;;
    *)       usage ;;
esac
