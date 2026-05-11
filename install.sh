#!/usr/bin/env bash
# install.sh — Symlink all Claude Code skills into ~/.claude/skills/
#
# Usage:
#   bash install.sh              # install all skills (skip existing directories)
#   bash install.sh --force      # overwrite existing directories
#   bash install.sh ralph llm    # install specific skills only
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$HOME/.claude/skills"
FORCE=false
SELECTED=()

# Parse arguments
for arg in "$@"; do
    if [[ "$arg" == "--force" ]]; then
        FORCE=true
    else
        SELECTED+=("$arg")
    fi
done

mkdir -p "$SKILLS_DIR"

echo "Installing Claude Code skills from $REPO_DIR/claude-code/"
echo "Target: $SKILLS_DIR"
echo ""

installed=0
skipped=0

for skill_dir in "$REPO_DIR"/claude-code/*/; do
    skill_name="$(basename "$skill_dir")"

    # If specific skills were requested, skip others
    if [[ ${#SELECTED[@]} -gt 0 ]]; then
        match=false
        for s in "${SELECTED[@]}"; do
            if [[ "$s" == "$skill_name" ]]; then
                match=true
                break
            fi
        done
        if [[ "$match" == "false" ]]; then
            continue
        fi
    fi

    target="$SKILLS_DIR/$skill_name"

    if [[ -L "$target" ]]; then
        echo "  $skill_name — already symlinked, updating"
        rm "$target"
    elif [[ -d "$target" ]]; then
        if [[ "$FORCE" == "true" ]]; then
            echo "  $skill_name — directory exists, overwriting (--force)"
            rm -rf "$target"
        else
            echo "  $skill_name — directory exists (NOT a symlink to this repo). Skipping."
            echo "      Future 'git pull' will NOT update this skill. Re-run with --force to replace it with a symlink."
            skipped=$((skipped + 1))
            continue
        fi
    fi

    ln -s "$skill_dir" "$target"
    echo "  $skill_name — linked"
    installed=$((installed + 1))
done

echo ""
echo "Done. $installed installed, $skipped skipped."
if [[ $skipped -gt 0 ]]; then
    echo ""
    echo "WARNING: $skipped skill(s) skipped because the target was a real directory, not a symlink."
    echo "  Those skills will NOT receive updates when you 'git pull' this repo."
    echo "  Re-run 'bash install.sh --force' to replace them with symlinks."
fi
echo ""
echo "Next steps:"
echo "  1. Set API keys for the skills you want to use (see docs/Getting-Started.md)"
echo "  2. For deep-research: export VAULT_ROOT=\"/path/to/your/obsidian/vault\""
echo "  3. Run: /debate, /research, /ralph, etc. in Claude Code"
