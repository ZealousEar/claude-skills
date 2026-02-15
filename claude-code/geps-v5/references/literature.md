# GEPS v5 Literature References

## Core Architecture References

1. **Si et al. (2025)** — "Can LLMs Generate Novel Research Ideas?" arXiv:2409.04109
   - Finding: LLMs generate ideas rated as novel by humans but uniqueness collapses to ~5% at scale
   - Implication: Diversity enforcement is architecturally critical, not a prompt trick

2. **Zhao et al. (2025)** — "Deep Ideation" arXiv:2511.02238
   - Finding: Concept network + iterative workflow improves idea quality by +10.67%
   - Implication: Graph-guided generation outperforms naive prompting

3. **Baek et al. (2025)** — "ResearchAgent" arXiv:2404.07738
   - Finding: Literature-graph traversal + iterative review improves grounding
   - Implication: Retrieval-conditioned generation is superior to closed-context generation

4. **Su et al. (2025)** — "VirSci" arXiv:2410.09403
   - Finding: Multi-agent scientific ideation systems need benchmarking and grounding
   - Implication: Evaluation framework matters as much as generation

## Debate/MAD Critique

5. **Du et al. (2024)** — "Improving Factuality and Reasoning" arXiv:2305.14325
   - Finding: Multi-agent debate improves factuality on reasoning benchmarks
   - Implication: MAD useful for verifiable constraints only

6. **Liang et al. (2024)** — "Encouraging Divergent Thinking" arXiv:2305.19118
   - Finding: Controlled disagreement helps escape degeneration-of-thought
   - Implication: Debate as correction mechanism, not core evaluator

7. **Smit et al. (2024)** — "Demystifying debate" arXiv:2311.17371
   - Finding: MAD does not reliably outperform self-consistency/ensembling
   - Implication: Debate is not always worth the cost

8. **Wynn et al. (2025)** — "When debate harms" arXiv:2509.05396
   - Finding: Agents shift from correct to incorrect, preferring agreement over challenge
   - Implication: Consensus can actively reduce accuracy

9. **Pitre et al. (2025)** — "CONSENSAGENT" ACL Findings 2025
   - Finding: Sycophancy in multi-agent interactions is systematic
   - Implication: Anti-sycophancy must be mechanical, not just prompted

10. **Cui et al. (2025)** — "Free-MAD" arXiv:2509.11035
    - Finding: Consensus-based multi-round debate is costly and conformity-prone
    - Implication: Single-round + trajectory scoring + anti-conformity preferred

11. **Zhu et al. (2026)** — "Demystifying MAD" arXiv:2601.19921
    - Finding: Debate without mechanisms may not improve expected correctness
    - Implication: Diversity-aware initialization + confidence modulation required

## Evaluation & Bias

12. **Shi et al. (2025)** — "Position bias in LLM judges" arXiv:2406.07791
    - Finding: LLM judges exhibit systematic position bias in pairwise settings
    - Implication: A/B randomization + explicit bias estimation mandatory

13. **Hwang et al. (2025)** — "Persuasion attacks on LLM judges" arXiv:2508.07805
    - Finding: LLM judges vulnerable to persuasive language even when correctness is invariant
    - Implication: Style normalization before judging is critical

14. **Khan et al. (2024)** — "Debate for non-expert oversight" arXiv:2402.06782
    - Finding: Debate helps weaker judges pick truth more often
    - Implication: Useful for verification layer, not generation

## Ranking & Aggregation

15. **Bradley & Terry (1952)** — "Rank Analysis of Incomplete Block Designs"
    - Foundation: Pairwise comparison → latent quality estimation
    - Used for: Tournament aggregation model

16. **Arrow (1951)** — "Social Choice and Individual Values"
    - Foundation: No perfect aggregation; choose which axioms to violate
    - Implication: Portfolio-aware optimization, not scalar scoring

17. **Breiman (2001)** — "Random Forests"
    - Foundation: Ensemble error reduction requires de-correlated errors
    - Implication: Provider diversity is architecturally necessary

## Multi-Agent Systems

18. **Cemri et al. (2025)** — "MAS failure modes" arXiv:2503.13657
    - Finding: Inter-agent misalignment and design failures; diversity not automatic
    - Implication: Diversity enforcement must be structural

## Decoding Diversity

19. **Shi et al. (2025)** — "SemDiD" arXiv:2506.23601
    - Finding: Semantic-guided diverse decoding pushes generation into different directions
    - Implication: Future enhancement for concept-constrained generation

20. **Ruan et al. (2025)** — "G2" arXiv:2511.00432
    - Finding: Training-free diversity method via guide-to-generation
    - Implication: Approximable via multi-prompt paraphrase guides

## Calibration

21. **Gu et al. (2024)** — "Calibration-weighted LLM judges" arXiv:2411.15594
    - Finding: Judge reliability varies; calibration weighting improves aggregation
    - Implication: rho_j from calibration set is mandatory, not optional

## Ideation & Scientific Discovery

22. **Hayek (1945)** — "The Use of Knowledge in Society"
    - Foundation: Knowledge is dispersed; aggregate local signals
    - Implication: Prediction-market-style mechanisms viable for ideation scoring

23. **Wang et al. (2022)** — "Self-Consistency"
    - Finding: Sample N and select by majority; surprisingly strong baseline
    - Implication: Cheap baseline that tournament must beat

## Thompson Sampling

24. **Thompson (1933)** — "On the Likelihood that One Unknown Probability Exceeds Another"
    - Foundation: Bayesian bandit algorithm with Beta priors
    - Used for: Generation channel weight adaptation

25. **Russo et al. (2018)** — "A Tutorial on Thompson Sampling"
    - Foundation: Modern treatment with Bernoulli bandits
    - Used for: Failure ledger reward definition design
