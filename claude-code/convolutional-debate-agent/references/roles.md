# Role Definitions

Roles enforce diversity in candidate generation, formal verification, and adversarial rigor in evaluation.

## Solver Roles (5)

Each solver runs independently via a parallel Task agent. No solver may see another's output.

### Solver A: First-Principles Reasoner
- Derive from fundamentals and explicit assumptions.
- Prefer structured reasoning (logical chains, formal arguments) over heuristics.
- Model: configurable per `solver_models[0]` in settings.

### Solver B: Code-First Engineer
- Approach the problem as an implementation challenge — think in algorithms, data structures, and system design.
- Evaluate computational complexity, API feasibility, and code-level trade-offs.
- Prefer solutions you could write working code for immediately over abstract proposals.
- Identify implementation bottlenecks, dependency risks, and technical debt implications.
- Model: configurable per `solver_models[1]` in settings. Best served by a code-specialized model (e.g., GPT-5.3 Codex).

### Solver C: Failure-Mode Analyst
- Start from ways the solution can break.
- Prioritize robustness, safety, and edge-case handling.
- Model: configurable per `solver_models[2]` in settings.

### Solver D: Clarity Optimizer
- Simplify while preserving correctness.
- Prefer clear communication and low cognitive overhead.
- Model: configurable per `solver_models[3]` in settings.

### Solver E: Research & Evidence Analyst
- Ground the answer in empirical evidence, existing literature, and real-world data.
- Identify analogous problems from other domains and what worked there.
- Evaluate second-order effects, feedback loops, and non-obvious consequences.
- Prefer answers backed by precedent over novel speculation.
- Model: configurable per `solver_models[4]` in settings. Benefits from broad-knowledge models (e.g., Gemini Pro 3).

### Solver Output Schema

```json
{
  "id": "A",
  "answer": "complete candidate answer",
  "assumptions": ["explicit assumption 1", "explicit assumption 2"],
  "risks": ["identified risk 1", "identified risk 2"],
  "confidence": 0.72
}
```

## Formalizer Role (Step 3.5 — Conditional, Non-Blocking)

Runs between solvers and debaters when formal verification is enabled. Designed for **zero added latency** — Aristotle proofs run in the background alongside debaters.

### Formalizer: Claim Extractor (~30 seconds)
- Reads all 5 solver outputs and extracts the **single most critical** logical/mathematical claim per candidate.
- Only 1 claim per candidate (Aristotle is slow — 1-15 min per proof). Be highly selective.
- Translates each claim into a precise, unambiguous natural-language proposition for Aristotle's INFORMAL mode.
- Uses domain-specific prompt templates from `~/.claude/skills/aristotle-prover/settings/prompt-templates.json`.
- Model: configurable via `formal_verification.formalizer_model` in settings (default: opus).
- If a candidate has no formalizable claims, skip it (return empty).

### Aristotle: Formal Verifier (Background, ~2 min timeout)
- Lean 4 theorem prover (ProofBench #1 at 71%).
- **SLOW** — each proof takes 1-15 minutes. Runs as background tasks alongside debaters.
- Receives formalized claims and returns PROVED (with Lean proof), DISPROVED (with counterexample), or INCONCLUSIVE (timeout).
- NOT a solver — it verifies claims, not generates answers.
- Results feed into `formal_score` per candidate in the RWEA scoring step.
- Claims still running at RWEA time are marked INCONCLUSIVE (not waited on).

### Formalizer Output Schema

```json
{
  "claims": [
    {
      "candidate_id": "A",
      "claim_index": 1,
      "original_text": "excerpt from solver output",
      "formalization": "Prove that if X_1,...,X_n are i.i.d. Bernoulli(θ), ...",
      "aristotle_status": "proved",
      "lean_proof": "theorem ... := by ..."
    }
  ],
  "formal_scores": {
    "A": 1.00,
    "B": -1.00,
    "C": 1.00,
    "D": 0.00,
    "E": 0.00
  }
}
```

## Debater Roles (4)

Each debater evaluates ALL five solver candidates. Debaters run in parallel via Task agents.

**Dynamic model assignment:** Debater models are **domain-specific** — each debater slot is assigned the model with the strongest benchmarks for that role in the detected domain. The domain's `debater_models.models` array in `benchmark-profiles.json` overrides the profile's static defaults. Profile defaults are used only when no domain is detected.

### Debater 1: Consistency Prosecutor
- Find contradictions, logical leaps, and invalid inferences.
- Focus: internal logical coherence of each candidate.
- Model: domain-specific — best logical reasoning model (e.g., Gemini for math/AIME #1, Opus for coding/SWE-bench #1).

### Debater 2: Counterexample Hunter
- Attack with adversarial scenarios, edge cases, and worst-case inputs.
- Focus: robustness under stress.
- Model: domain-specific — best adversarial/edge-case model (e.g., GPT-5.2EH for coding/IOI #1, Opus for math/ProofBench #2).

### Debater 3: Constraint Auditor
- Check compliance against user-stated constraints and acceptance criteria.
- Focus: requirements coverage.
- Model: domain-specific — best compliance/regulatory model (e.g., Gemini for finance/MortgageTax #1, Opus for academic/SAGE #1).

### Debater 4: Evidence Judge & Pairwise Arbiter
- Evaluate support quality and relevance of evidence.
- Run pairwise head-to-head comparisons between all candidates.
- Assign wins (0-4) per candidate.
- Model: domain-specific — broadest knowledge model for fair comparison (e.g., Gemini for math/MMLU Pro #1, Kimi for finance/CorpFin).

### Debater Output Schema (per candidate)

```json
{
  "candidate_id": "A",
  "support": 2,
  "evidence": 1,
  "major_risks": 0,
  "critical_fail": 0,
  "justification": "Short reason tied to concrete evidence."
}
```

Debater 4 additionally returns pairwise wins:

```json
{
  "pairwise_wins": {"A": 2, "B": 1, "C": 3, "D": 0, "E": 4}
}
```
