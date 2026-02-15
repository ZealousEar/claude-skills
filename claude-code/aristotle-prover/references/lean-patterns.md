# Common Lean 4 Patterns for Prompt Translation

## Pattern: Simple Theorem with Sorry

```lean
import Mathlib

theorem my_theorem (n : ℕ) : n + 0 = n := by
  sorry
```

## Pattern: Theorem with Proof Hint

```lean
import Mathlib

/--
PROVIDED SOLUTION
Use induction on n. Base case is trivial.
Inductive step: assume P(n), prove P(n+1) by rewriting.
-/
theorem my_theorem (n : ℕ) : 0 + n = n := by
  sorry
```

## Pattern: Multiple Sorries

```lean
import Mathlib

theorem part_a : statement_a := by sorry
theorem part_b : statement_b := by sorry
-- Aristotle fills ALL sorries. Use `admit` to skip specific ones.
```

## Pattern: Probability/Measure Theory

```lean
import Mathlib
open MeasureTheory ProbabilityTheory

theorem bayes (Ω : Type*) [MeasurableSpace Ω] (μ : Measure Ω)
    [IsProbabilityMeasure μ] (A B : Set Ω)
    (hA : MeasurableSet A) (hB : MeasurableSet B)
    (hB_pos : μ B ≠ 0) :
    μ[A | B] = μ (A ∩ B) / μ B := by
  sorry
```

## Pattern: Real Analysis

```lean
import Mathlib
open Filter Topology

theorem squeeze_theorem (f g h : ℝ → ℝ) (a L : ℝ)
    (hfg : ∀ᶠ x in nhds a, f x ≤ g x)
    (hgh : ∀ᶠ x in nhds a, g x ≤ h x)
    (hf : Tendsto f (nhds a) (nhds L))
    (hh : Tendsto h (nhds a) (nhds L)) :
    Tendsto g (nhds a) (nhds L) := by
  sorry
```

## Pattern: Linear Algebra

```lean
import Mathlib
open Matrix

theorem det_transpose {n : Type*} [Fintype n] [DecidableEq n]
    (M : Matrix n n ℝ) :
    det M.transpose = det M := by
  sorry
```

## Pattern: Algorithm Correctness

```lean
import Mathlib

def mySort (l : List ℕ) : List ℕ := sorry  -- use `admit` if you don't want Aristotle to define this

theorem mySort_sorted (l : List ℕ) : (mySort l).Sorted (· ≤ ·) := by
  sorry

theorem mySort_perm (l : List ℕ) : (mySort l).Perm l := by
  sorry
```

## Tips for Translation

- Use `ℕ` not `Nat`, `ℝ` not `Real`, `ℤ` not `Int` in theorem statements
- Import `Mathlib` (full) unless you know the specific module
- Use `by sorry` for tactic proofs (most common)
- Use `open` to bring namespaces into scope
- For counterexample requests, just state the theorem — Aristotle will disprove if false
