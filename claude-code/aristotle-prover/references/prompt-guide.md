# Aristotle Prompt Guide

## How Aristotle Works

Aristotle is a formal theorem prover that:
1. Takes natural language math OR Lean 4 code with `sorry` stubs
2. Uses Monte Carlo Graph Search + informal reasoning + Lean REPL
3. Returns **formally verified** Lean 4 proofs (kernel-checked, zero hallucination)
4. When statements are false, returns **counterexamples** with proof of negation

## Writing Good Prompts

### Do: Be Precise
```
BAD:  "Prove Bayes' theorem"
GOOD: "Prove that if P(B) > 0, then P(A|B) = P(A ∩ B) / P(B),
       where P is a probability measure on a measurable space (Ω, F)."
```

### Do: Make Assumptions Explicit
```
BAD:  "Prove the posterior mean of a Beta-Bernoulli model"
GOOD: "Let X_1, ..., X_n be i.i.d. Bernoulli(θ) random variables.
       Let θ ~ Beta(a, b) with a, b > 0. Prove that
       E[θ | X_1, ..., X_n] = (a + sum(X_i)) / (a + b + n)."
```

### Do: Specify the Mathematical Objects
```
BAD:  "Show the estimator is consistent"
GOOD: "Let X_1, ..., X_n be i.i.d. with mean μ and finite variance σ².
       Let X̄_n = (1/n) Σ X_i. Prove that X̄_n converges in probability to μ
       as n → ∞."
```

### Do: Provide Proof Hints When Possible
Aristotle accepts English proof sketches tagged with "PROVIDED SOLUTION" in Lean comments.
This dramatically improves success rate on hard theorems.

```lean
/--
Prove that every continuous function on [a,b] is bounded.

PROVIDED SOLUTION
Use the fact that [a,b] is compact and continuous images of compact sets are compact,
hence bounded. Specifically, apply IsCompact.exists_isMaxOn and IsCompact.exists_isMinOn.
-/
theorem continuous_bounded (f : ℝ → ℝ) (a b : ℝ) (hab : a ≤ b)
    (hf : ContinuousOn f (Set.Icc a b)) :
    BddAbove (f '' Set.Icc a b) := by
sorry
```

## Mode Selection Guide

| Scenario | Mode | Input |
|----------|------|-------|
| "Prove that X" in plain English | `informal` | Natural language text |
| Lean file with `sorry` to fill | `formal` | `.lean` file path |
| English question + Lean definitions | `informal` + context | Text + `.lean` context |
| Research paper theorem | `informal` | Paper excerpt as text |
| Algorithm verification | Either | Pseudocode or Lean def |

## Domains Where Aristotle Excels

1. **Pure mathematics** — algebra, analysis, topology, number theory
2. **Probability theory** — measure-theoretic statements
3. **Algorithm correctness** — 96.8% on VERINA benchmark
4. **Combinatorics** — IMO competition problems
5. **Linear algebra** — matrix properties, spectral theory

## Domains Where Aristotle May Struggle

1. **Very novel constructions** — theorems requiring entirely new abstractions
2. **Extremely long proofs** — may timeout on 50+ step proofs
3. **Non-Mathlib formalizations** — works best with standard Mathlib types
4. **Applied/numerical claims** — "this converges in 10 iterations" is empirical, not formal

## Timeout Expectations

| Difficulty | Expected Time |
|-----------|---------------|
| Trivial (in Mathlib) | 1-2 minutes |
| Undergraduate exercise | 2-5 minutes |
| Graduate-level theorem | 5-15 minutes |
| Research-level | 15-45 minutes |
| Open problem | 45+ minutes or may not solve |
