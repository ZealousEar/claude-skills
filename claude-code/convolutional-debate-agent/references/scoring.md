# RWEA Scoring

RWEA = Reliability-Weighted Evidence Aggregation.

## Inputs per Candidate

| Field    | Source    | Range | Description                            |
|----------|-----------|-------|----------------------------------------|
| wins     | Debater 4 | 0-4   | Pairwise comparison victories          |
| support  | All       | 0-2   | Per-debater support score              |
| evidence | All       | 0-2   | Per-debater evidence score             |
| major_risks   | All  | 0-2   | Per-debater risk severity              |
| critical_fail | All  | 0-1   | Per-debater fatal flaw flag            |

## Equations

For candidate `c` with reviews from `n` debaters:

```
base(c)         = mean(support_i + evidence_i)              range [0, 4]
risk(c)         = mean(major_risks_i + 2*critical_fail_i)   range [0, 4]
pairwise(c)     = wins(c) / (num_candidates - 1)            range [0, 1]
model_weight(c) = benchmark reliability weight for c's model in detected domain  range [0, 1]
formal_score(c) = (proved - disproved) / total_claims        range [-1, 1]

score(c) = w_base * base(c) + w_pairwise * pairwise(c) - w_risk * risk(c)
         + w_reliability * model_weight(c) + w_formal * formal_score(c)
```

### Formal Score Computation

The `formal_score` is computed from Aristotle's verification of claims extracted from each candidate.

**Speed note:** Aristotle is slow (1-15 min per proof). It runs as background tasks **in parallel with debaters** so it adds zero latency. Only 1 claim per candidate is extracted to keep total proof count low (~5 max). Claims still running at RWEA scoring time are marked INCONCLUSIVE.

- **proved**: number of claims Aristotle formally proved correct
- **disproved**: number of claims Aristotle found counterexamples for
- **timeout/still running**: claims Aristotle could not resolve in time (treated as neutral, excluded from ratio)
- **total_claims**: proved + disproved (timeouts excluded)
- If no claims were formalizable or all timed out: `formal_score = 0.0`

### Default Weights (no domain / general)

| Weight | Value | Purpose |
|--------|-------|---------|
| w_base | 0.50 | Rewards well-supported, evidence-backed reasoning |
| w_pairwise | 2.00 | Heavily rewards winning head-to-head comparisons |
| w_risk | 0.70 | Penalizes identified risks and critical failures |
| w_reliability | 0.00 | No reliability bonus without domain classification |
| w_formal | 0.00 | No formal verification bonus without Aristotle |

### Domain-Specific Weight Overrides

When a domain is detected (Step 1.5), weights shift based on what matters most:

| Domain | w_base | w_pairwise | w_risk | w_reliability | w_formal | Rationale |
|--------|--------|------------|--------|---------------|----------|-----------|
| coding | 0.60 | 1.80 | 0.80 | 0.50 | 0.35 | Code is verifiable; bugs have consequences; algorithm correctness provable |
| math | 0.70 | 1.50 | 0.50 | 0.60 | 0.60 | Formal correctness paramount; claims directly provable by Aristotle |
| finance | 0.55 | 1.90 | 0.85 | 0.50 | 0.45 | Financial errors are costly; no-arbitrage/pricing identities provable |
| legal | 0.65 | 1.70 | 0.75 | 0.55 | 0.30 | Evidence and precedent matter; partly interpretive, not purely formal |
| academic | 0.60 | 1.80 | 0.65 | 0.50 | 0.40 | Diverse perspectives valuable; statistical properties often provable |
| strategy | 0.45 | 2.20 | 0.85 | 0.45 | 0.20 | Head-to-head comparison most informative; judgment-heavy, few formal claims |
| general | 0.50 | 2.00 | 0.70 | 0.40 | 0.25 | Standard weights; low-moderate formal bonus |

### Model Reliability Weights

Each model gets a reliability weight per domain based on Vals.ai benchmark performance.
The model with the strongest benchmarks in a domain gets weight 1.00; others scale relative.

Example (math domain): Gemini 3 Pro = 1.00 (AIME #1), Opus = 0.70, GPT-5.2 EH = 0.65

Full weights are in `settings/benchmark-profiles.json`.

## Elimination Rule

**Eliminate** candidate `c` if **two or more** debaters assign `critical_fail = 1`.

Rationale: a single critical_fail could be a false positive; two independent critics
flagging the same candidate indicates a real structural flaw.

## Decision Rules

1. **Clear winner**: highest `score(c)` among non-eliminated candidates
2. **Hybrid synthesis**: if top-two score gap < 0.40, synthesize from both candidates' non-conflicting strengths
3. **Insufficient confidence**: if no candidates survive, or top score < 1.20, ask focused follow-up questions

## Tie Handling

If two candidates have identical scores:
1. Prefer fewer `critical_fail` flags
2. If still tied, prefer higher `base` score
3. If still tied, synthesize and optionally rerun one quick debate pass

## Running the Scorer

```bash
# Score from file
python3 ~/.claude/skills/convolutional-debate-agent/scripts/rwea_score.py \
  --input payload.json --pretty

# Human-readable summary
python3 ~/.claude/skills/convolutional-debate-agent/scripts/rwea_score.py \
  --input payload.json --summary

# Validate payload without scoring
python3 ~/.claude/skills/convolutional-debate-agent/scripts/rwea_score.py \
  --validate payload.json

# Score from stdin
echo '{"candidates": [...]}' | python3 ~/.claude/skills/convolutional-debate-agent/scripts/rwea_score.py \
  --stdin --pretty
```
