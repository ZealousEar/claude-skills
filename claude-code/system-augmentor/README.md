# system-augmentor

Self-improvement workflow that finds capability gaps and proposes implementable upgrades.

## Files

- `SKILL.md` — end-to-end process for scanning, researching, evaluating, and applying improvements.
- `scripts/system_scanner.py`, `scripts/gap_analyzer.py` — inventory current capabilities and classify missing coverage.
- `settings/scan-targets.json` and `settings/search-templates.json` — scan scope and research query templates.
- `references/gap-taxonomy.md` and `references/debate-question-template.md` — gap categories and evaluation prompts.

## How it works

The skill scans the current system and maps findings to a gap taxonomy so missing capabilities are explicit. It then researches candidate solutions and frames a debate-style evaluation to compare quality, risk, and fit. The top candidate is selected for implementation with a bias toward practical, testable improvements.
