# Debate Question Template

Template for composing structured questions to pass to `/debate` during Phase 3 of the System Augmentor.

## Template Structure

```
I need to choose the best solution for a system capability gap.

## Context

**Gap identified:** {gap_name} ({gap_id})
**Severity:** {gap_severity}
**Description:** {gap_description}

**Current system state:**
{relevant_manifest_excerpt}

## Candidates

{for each candidate}
### Candidate {N}: {candidate_name}
- **What it is:** {description}
- **Install method:** {how_to_install}
- **Dependencies:** {dependencies}
- **Maintenance status:** {active/maintained/abandoned}
- **Key strengths:** {strengths}
- **Key weaknesses:** {weaknesses}
- **Source:** {url}
{end for}

## Evaluation Criteria

1. **Ease of integration** — How easily does it plug into the existing Claude Code system?
2. **Maintenance & reliability** — Is it actively maintained? Will it break?
3. **Capability coverage** — How completely does it fill the identified gap?
4. **Security** — Does it introduce security risks? Does it need broad permissions?
5. **Cost** — Free vs paid? Token/API costs?

## Constraints

- Must work with Claude Code's MCP protocol (if MCP solution) or as a CLI tool
- Must not require manual intervention once configured
- Prefer solutions that don't require paid API keys if a free alternative is comparable
- Must be installable on macOS

## Question

Which candidate is the best solution for this gap, and how should it be implemented?
```

## Usage Notes

- Claude composes the full question by filling in the template variables from Phase 1 (audit) and Phase 2 (research) findings
- The composed question is passed as the `$ARGUMENTS` to `/debate`
- Not all fields are required — omit sections that don't apply
- For trivial gaps (e.g., missing a single CLI tool), skip the debate entirely and implement directly
- The debate protocol will generate 4 independent solver answers, 4 adversarial reviews, and RWEA scoring to determine the winner

## When to Skip the Debate

Skip `/debate` and implement directly when:
- Only one candidate exists (no choice to evaluate)
- The solution is a simple `brew install` or `pip install`
- The gap severity is LOW and the fix is obvious
- The user explicitly says "just do it"

## Example Composed Question

```
I need to choose the best solution for a system capability gap.

## Context

**Gap identified:** No academic search MCP (MCP-004)
**Severity:** HIGH
**Description:** No MCP server for academic paper search (Semantic Scholar, arXiv, etc.)

**Current system state:**
- MCP servers installed: mind
- Skills: convolutional-debate-agent, system-augmentor
- Project: dissertation research (MSc Financial Technology, University of Bristol)

## Candidates

### Candidate 1: Semantic Scholar MCP Server
- **What it is:** MCP server wrapping the Semantic Scholar API for paper search, citation graphs, and author lookup
- **Install method:** npx or Docker
- **Dependencies:** Node.js
- **Maintenance status:** Active (last commit 2 weeks ago)
- **Key strengths:** Free API, no key needed for basic access, rich citation data
- **Key weaknesses:** Rate limited (100 req/5min without key), no full-text access

### Candidate 2: arXiv MCP Server
- **What it is:** MCP server for searching and downloading arXiv papers
- **Install method:** pip install
- **Dependencies:** Python 3.10+
- **Maintenance status:** Active
- **Key strengths:** Full text PDF access, no API key needed, preprint access
- **Key weaknesses:** arXiv only (no journals), no citation graph

### Candidate 3: Custom Research Aggregator
- **What it is:** Custom Python MCP server aggregating Semantic Scholar + arXiv + CrossRef
- **Install method:** Build from scratch
- **Dependencies:** Python stdlib + urllib
- **Maintenance status:** N/A (custom)
- **Key strengths:** Full control, combines multiple sources, tailored to dissertation needs
- **Key weaknesses:** Build time, maintenance burden, potential API breakage

## Evaluation Criteria
1. Ease of integration with Claude Code MCP
2. Maintenance & reliability
3. Capability coverage for dissertation research
4. Cost (prefer free)

## Question
Which candidate is the best solution for academic paper search in this dissertation research system?
```
