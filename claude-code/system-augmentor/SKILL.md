---
name: system-augmentor
description: >
  Audits the Claude Code system for capability gaps, researches solutions online,
  evaluates candidates via the /debate protocol, and implements the winner.
  Invoked via /improve slash command.
platform: claude-code
---

# System Augmentor for Claude Code

Identifies what your Claude Code system *cannot* do, finds solutions, evaluates them
rigorously, and installs the best one. A meta-skill that makes all other skills better.

## When to Use

- You want to extend Claude Code with new capabilities (MCP servers, CLI tools, skills)
- You suspect something is missing but aren't sure what
- You want to compare competing solutions before installing
- You want a full audit of your system's strengths and gaps

## When NOT to Use

- You already know exactly what to install (just install it)
- You want to debug an existing skill (fix it directly)
- You want to modify project code (use normal Claude Code)

## Invocation

```
/improve                     # Full system audit
/improve web scraping        # Focused audit on web scraping capability
/improve paper search        # Focused audit on academic paper search
/improve testing             # Focused audit on testing tools
```

## The Four Phases

```
User: /improve [focus]
     |
     v
[Phase 1: Deep System Audit]
  - system_scanner.py → filesystem inventory
  - gap_analyzer.py → structural gap detection
  - Claude reasoning → capability-level gaps
  - STOP: present findings, ask which gaps to research
     |
     v
[Phase 2: Online Research]
  - WebSearch queries from search-templates.json
  - WebFetch promising results
  - Ranked candidate list per gap
  - STOP: present candidates, ask which to debate
     |
     v
[Phase 3: Evaluate via /debate]  (optional — skip for trivial fixes)
  - AskUserQuestion: thinking token budget (small/medium/high)
  - Compose question from debate-question-template.md
  - Call Skill(skill="debate", args="[TOKEN_BUDGET: X]\n\n<question>")
  - Full protocol: 5 solvers, 4 debaters, RWEA scoring
  - STOP: present winner, ask permission to implement
     |
     v
[Phase 4: Implement]
  - Execute chosen solution
  - Follow safety checklist
  - Test the implementation
  - Report what changed
```

## Phase Details

### Phase 1: Deep System Audit

1. Run `system_scanner.py --output-json --pretty` to inventory the filesystem
2. Read discovered files to understand current capabilities
3. Run `gap_analyzer.py --manifest <path> --pretty` to detect structural gaps
4. Apply reasoning to identify capability-level gaps not caught by rules
5. Present findings to user with severity ratings

### Phase 2: Online Research

For each user-approved gap:
1. Load query templates from `settings/search-templates.json`
2. Run 2-4 WebSearch queries per gap, substituting keywords
3. WebFetch top results to extract: description, install method, dependencies, maintenance status
4. Produce ranked candidate list (2-4 candidates per gap)

### Phase 3: Evaluate via /debate

For non-trivial choices (2+ viable candidates):
1. Ask user for thinking token budget via AskUserQuestion (small/medium/high)
2. Compose question using `references/debate-question-template.md`
3. Fill in context from Phase 1 manifest and Phase 2 candidates
4. Call `Skill(skill="debate", args="[TOKEN_BUDGET: <selection>]\n\n<composed question>")`
5. Debate runs full protocol (5 solvers, 4 debaters, RWEA) and returns winner

Skip the debate when:
- Only one candidate exists
- Solution is a simple install command
- Gap severity is LOW
- User says "just do it"

### Phase 4: Implement

Execute the winning solution following the safety checklist:
- Check if target already exists before creating
- Never write API keys directly — create `.env.example` templates
- Test the installation (run a smoke test)
- Report what was created/modified

## File Structure

```
~/.claude/commands/improve.md                  # Slash command (orchestration)
~/.claude/skills/system-augmentor/
  SKILL.md                                     # This file
  scripts/
    system_scanner.py                          # Filesystem inventory scanner
    gap_analyzer.py                            # Structural gap detector
  settings/
    scan-targets.json                          # Configurable scan paths & tools
    search-templates.json                      # WebSearch query patterns per category
  references/
    gap-taxonomy.md                            # Gap classification schema
    debate-question-template.md                # Template for /debate questions
```

## Safety Rules

1. **Idempotent**: Always check existence before creating files/dirs
2. **No secrets**: Never write API keys into files — create `.env.example` templates
3. **User consent**: Stop between every phase for user confirmation
4. **Reversible**: Prefer solutions that can be easily uninstalled
5. **Respect permissions**: Check `settings.local.json` allowlist before adding Bash permissions
6. **Minimal scope**: Only install what's needed for the identified gap
