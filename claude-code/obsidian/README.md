# obsidian

Three-tier automation skill for operating an Obsidian vault through files, CLI, and URI actions.

## Files

- `SKILL.md` — routing rules for choosing the right execution tier per vault operation.
- `references/cli-cheatsheet.md` — Obsidian CLI command reference and usage reminders.

## How it works

The skill chooses the lightest tier that can safely complete the task. Tier 1 uses direct file CRUD for straightforward edits and note management. Tier 2 uses Obsidian CLI v1.12 for graph-aware operations such as backlinks or orphan detection, and Tier 3 uses URI actions when the desktop app needs to open or focus notes.
