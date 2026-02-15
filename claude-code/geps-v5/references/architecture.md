# GEPS v5 Architecture — 7-Stage Pipeline

## Overview

Graph-Guided Evolutionary Portfolio Search replaces debate-as-core with **search + ranking + calibration**. Debate is demoted to a targeted verification tool for finalists only.

## Stage A: Build Domain Map

- Ingest literature corpus (papers/abstracts) as PRIMARY source
- Build concept graph: nodes = concepts/keywords/methods, edges = PMI-weighted co-occurrence
- Overlay with existing ideas (secondary, to avoid amplifying bias)
- Identify structural holes: concept pairs with high individual frequency but low co-occurrence and high neighbor-set similarity

**Script**: `concept_graph.py`

## Stage B: Generate Population

Multi-channel generation with 4 channels:
1. **Graph-Explorer**: concept-pair recombination from structural holes
2. **Analogy-Transfer**: cross-domain method import
3. **Exploit-Refiner**: sharpen promising ideas from prior rounds
4. **Constraint-Injection**: force underused skills/methods

Each channel has configurable model assignment and weight (Thompson Sampling adjusts weights over iterations).

**Prompts**: `solver_structural_hole_explorer.md`, `solver_analogy_transfer.md`, `solver_exploit_refiner.md`, `solver_identification_engineer.md`

## Stage C: Mechanical Screens

5 hard gates (no LLM judgment):
1. **Data Gate**: named sources with known access path
2. **Complexity Gate**: deterministic complexity-points heuristic (threshold: 8)
3. **Identifiability Gate**: keyword presence for credible identification
4. **Novelty Gate**: TF-IDF cosine duplicate detection (< 0.90)
5. **Ethics Gate**: red-flag keyword check

**Script**: `mechanical_gates.py`

## Stage D: Pairwise Ranking Tournament

- Swiss-system pairing (O(N log N) comparisons)
- Adaptive judging: 1 judge in early rounds, 2-3 in later rounds
- Judge pool: 5 models from different providers (no same-provider duplicates per match)
- Disagreement escalation: split decisions get a 3rd judge
- Field reduction: cut to top-N after configurable rounds
- Position randomization: A/B order randomized per call
- Bradley-Terry aggregation with:
  - Fixed rho_j from calibration (mandatory)
  - Sum-zero theta constraint
  - L2-regularized position bias (pi_j) estimated from ALL judgments
  - Bootstrap uncertainty intervals

**Scripts**: `swiss_tournament.py`, `judge_pairwise.py`, `bradley_terry.py`

## Stage D.5: Calibration (prerequisite for Stage D)

- Cross-tier comparison of known-quality papers
- Sampled (not exhaustive): ~45 matches x 5 judges = ~225 calls (one-time)
- Produces judge reliability weights (rho_j) consumed by Bradley-Terry
- Idempotent: skip existing results on re-run

**Scripts**: `run_calibration_judging.py`, `calibration.py`

## Stage E: Finalist Verification

- Top-K finalists (default K=5)
- Round-robin pairwise fatal-flaw audit (C(K,2) pairs, 2 verifiers each)
- Novelty audit with retrieved paper summaries
- Evidence scoring: e_novelty + e_identification + e_data
- Optional Aristotle theorem prover on formalizable claims
- Deterministic recommendation: highest BT rank with <= 1 fatal flaw AND novelty PASS

**Scripts**: `verify_finalists.py`, `literature_retrieval.py`
**Prompts**: `debater_fatal_flaw_auditor.md`, `debater_novelty_judge.md`, `retrieval_summarizer.md`

## Stage F: Portfolio Optimization

- Greedy forward selection (no submodularity guarantee)
- Score: mu_i - lambda_u * sigma_i - lambda_risk * R_i
- Redundancy: max TF-IDF cosine to selected set + taxonomy overlap
- Taxonomy quotas from `taxonomy.json`
- Output: top-1 bet, top-3 variants, top-5 diversified

**Script**: `portfolio_optimizer.py`

## Stage G: Feedback Loop

- Bernoulli Thompson Sampling per generation channel
- Success = idea survives ALL gates AND finishes in top q% of tournament
- Persistent JSON failure ledger
- Exploration floor prevents channel starvation

**Script**: `failure_ledger.py`

## Scoring

RWEA2 formula: `RWEA2(i|S) = mu_i - lambda_u*sigma_i + lambda_E*E_i - lambda_risk*R_i - lambda_red*red(i,S)`

**Script**: `rwea_v2.py`
