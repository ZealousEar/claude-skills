---
name: aristotle-prover
description: >
  Translates natural language mathematical questions into optimal prompts for
  Harmonic's Aristotle formal theorem prover, submits them via the aristotlelib
  API, and returns the verified Lean 4 proof or counterexample.
platform: claude-code
---

# Aristotle Prover Skill

## When to Use

- User wants to **formally prove** a mathematical statement (convergence, bounds, correctness)
- User wants to **verify** whether a claim is true or find a **counterexample**
- User wants to **formalize** natural language math into Lean 4
- User has a **Lean file with `sorry`** stubs to fill
- User wants to **prove algorithm correctness** (sorting, optimization, numerical methods)
- User asks about **regret bounds**, **estimator properties**, **convergence guarantees**

## When NOT to Use

- General coding tasks (use normal Claude Code)
- Data analysis, ML training, visualization
- Non-mathematical questions
- Tasks that don't benefit from formal verification

## Invocation

```
/prove <natural language math question or file path>
```

## Architecture

```
User prompt
    |
    v
[Prompt Translator] -- Claude converts user's question into
    |                   an optimal Aristotle-compatible prompt
    |                   (formal Lean or structured informal)
    v
[aristotle_submit.py] -- Submits to Aristotle API, polls for result
    |
    v
[Solution] -- Lean 4 proof or counterexample returned to user
```

## Capabilities

1. **Informal mode**: Natural language -> Aristotle formalizes and proves
2. **Formal mode**: Lean 4 theorem with `sorry` -> Aristotle fills proofs
3. **Hybrid mode**: Lean theorem + English proof hints (PROVIDED SOLUTION)
4. **Counterexample detection**: When statements are false, returns proof of negation

## Requirements

- `aristotlelib` Python package (v0.7.0+)
- `ARISTOTLE_API_KEY` environment variable set
- Python 3.10+

## File Structure

```
~/.claude/skills/aristotle-prover/
├── SKILL.md                    # This file
├── scripts/
│   └── aristotle_submit.py     # API submission + polling script
├── settings/
│   └── prompt-templates.json   # Domain-specific prompt templates
└── references/
    ├── lean-patterns.md        # Common Lean 4 patterns for translation
    └── prompt-guide.md         # How to write effective Aristotle prompts
```
