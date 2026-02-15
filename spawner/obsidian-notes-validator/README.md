# obsidian-notes-validator

Validation-focused skill for checking Obsidian notes against quality and structure gates.

## Files

- `skill.yaml` — validation workflow, scope, and expected pass criteria.
- `sharp-edges.yaml` — edge conditions and known validator blind spots.

## How it works

The skill defines rule-based checks for note quality, consistency, and compliance with vault conventions. It pairs baseline validation logic with sharp-edge awareness so failures are interpreted correctly. Use it as a gate before publishing or syncing notes to reduce avoidable quality regressions.
