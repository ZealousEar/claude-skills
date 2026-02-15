# RWEA v2 & Bayesian Bradley-Terry Formulas

## Bradley-Terry Model

### Likelihood per match

For match (i, k) judged by judge j:

```
P(i > k | j) = sigma(rho_j * (theta_i - theta_k) + pi_j * pos(i))
```

Where:
- `theta_i`: latent quality of idea i
- `rho_j`: judge j's reliability/discriminability (FIXED from calibration)
- `pi_j`: judge j's position bias
- `pos(i)`: +1 if idea i presented first, -1 if second
- `sigma(x) = 1 / (1 + exp(-x))`: logistic sigmoid

### Constraints

- **Identifiability**: `sum(theta_i) = 0` (sum-zero constraint)
- **rho_j**: NOT jointly estimated. Loaded from calibration weights file.
- **pi_j**: L2-regularized, estimated from ALL judgments (since every judgment has randomized A/B order with p=0.5)
  - Penalty: `lambda * sum(pi_j^2)`

### Estimation: MM Algorithm

Iterative Minorize-Maximize for theta and pi simultaneously:
1. Initialize theta_i = 0, pi_j = 0
2. For each iteration:
   a. For each idea i, update theta_i from wins/losses weighted by rho_j
   b. For each judge j, update pi_j from position-correlated outcomes
   c. Apply L2 penalty to pi_j
   d. Re-center theta: theta_i -= mean(theta)
3. Converge when max change < epsilon

### Bootstrap Uncertainty

1. Resample matches with replacement (B=200 times)
2. Re-estimate theta for each bootstrap sample
3. Report percentiles as confidence intervals
4. Ideas with < min_matches excluded from ranking

## Calibration

### Judge Reliability (rho_j)

From cross-tier comparison of known-quality papers:

```
accuracy_j = correct_cross_tier_calls / total_cross_tier_calls
position_bias_j = |mean(pos * winner_indicator)|  (estimated pi_j magnitude)
rho_j = accuracy_j * (1 - |position_bias_j|)
```

Normalized so max(rho_j) = 1.0

### Calibration Sampling

NOT exhaustive (10x10x3 = 300 pairs). Sampled:
- 15 matches per tier-pair (H-M, H-L, M-L) = 45 total
- Each paper appears in >= 3 matches
- 30% of matches have swapped presentation order
- Each judge model evaluates all 45 matches

## RWEA v2 Score

### Per-idea score (given portfolio state S)

```
RWEA2(i | S) = mu_i - lambda_u * sigma_i + lambda_E * E_i - lambda_risk * R_i - lambda_red * red(i, S)
```

Where:
- `mu_i`: BT posterior mean quality
- `sigma_i`: BT bootstrap standard deviation
- `E_i`: evidence score from verification (average of e_novelty, e_identification, e_data)
- `R_i`: risk score from mechanical gates + verifier flags
- `red(i, S)`: redundancy = max(cosine_sim(i, s) for s in S) + taxonomy_overlap_penalty

### Evidence Components

- `e_novelty`: 1 if novelty judge PASS, 0 if FAIL
- `e_identification`: 1 if >= 2 identification keywords present, 0 otherwise
- `e_data`: 1 if data gate passed with named free sources, 0.5 if accessible, 0 if unknown
- `E_i = (e_novelty + e_identification + e_data) / 3`

### Default Lambda Values

- `lambda_u = 0.3` (uncertainty penalty)
- `lambda_E = 0.1` (evidence bonus)
- `lambda_risk = 0.2` (risk penalty)
- `lambda_red = 0.4` (redundancy penalty)
