# media-transcript

Transcription-oriented skill for converting audio/video content into reliable text artifacts.

## Files

- `skill.yaml` — main transcription workflow and operating instructions.
- `sharp-edges.yaml` — pitfalls like speaker confusion, noise artifacts, and formatting drift.
- `patterns.md` — preferred transcript structures, cleanup patterns, and output styles.
- `validations.yaml` — checks for completeness, coherence, and quality thresholds.

## How it works

The skill applies structured transcription patterns rather than a single raw pass. It highlights common error modes and enforces validation checks so transcripts stay usable for downstream tasks. The result is a cleaner, quality-gated transcript with explicit handling for difficult media conditions.
