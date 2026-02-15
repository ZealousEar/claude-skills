# aristotle-prover

Natural-language math-to-Lean proving workflow powered by the Harmonic Aristotle API.

## Files

- `SKILL.md` — usage instructions, guardrails, and the end-to-end proving flow.
- `scripts/aristotle_submit.py` — submits a crafted prompt/problem payload to Aristotle and returns results.
- `settings/prompt-templates.json` — reusable prompt templates for theorem formalization and proof attempts.
- `references/lean-patterns.md` and `references/prompt-guide.md` — Lean 4 proof idioms and prompt design guidance.

## How it works

The skill starts from a natural-language theorem statement and shapes it into a Lean-friendly prompt. It applies template-driven instructions so the API receives consistent context and proof constraints. The submit script sends the request, then surfaces either a Lean 4 proof artifact or a failure/counterexample-style response for follow-up.
