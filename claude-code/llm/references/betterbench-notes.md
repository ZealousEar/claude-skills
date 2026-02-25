# BetterBench — Benchmark Quality Assessment

**Paper**: "BetterBench: Assessing AI Benchmarks, Uncovering Issues, and Establishing Best Practices"
**Authors**: Reuel, Hardy, Smith, Lamparth, Hardy, Kochenderfer (Stanford)
**Venue**: NeurIPS 2024 Spotlight
**ArXiv**: https://arxiv.org/abs/2411.12990

## Summary

BetterBench evaluates 24 major AI benchmarks across 46 criteria organized into 5 lifecycle stages. Key finding: benchmark quality varies massively — GPQA Diamond scores 11.0 while MMLU-Pro scores only 5.5. This means treating all benchmarks equally in model comparisons is fundamentally flawed.

## 5 Lifecycle Stages (46 Criteria)

| Stage | What it assesses | Key finding |
|---|---|---|
| **Design** (9 criteria) | Task relevance, scope, difficulty calibration | Most benchmarks score well here |
| **Implementation** (10 criteria) | Code quality, reproducibility, documentation | Weakest stage — 17/24 lack replication scripts |
| **Evaluation** (9 criteria) | Metric choice, statistical rigor, contamination handling | Contamination resistance is rare |
| **Analysis** (9 criteria) | Error analysis, failure modes, disaggregated results | Often neglected |
| **Reporting** (9 criteria) | Confidence intervals, metadata, versioning | Most benchmarks don't report CIs |

## Benchmark Quality Rankings (Relevant to Our System)

| Benchmark | BetterBench Score | Quality Tier | Contamination Resistant | Our Source |
|---|---|---|---|---|
| GPQA Diamond | 11.0 | High | Yes | Epoch AI |
| Chatbot Arena | 10.5 | High | Yes | LMArena (direct) |
| LiveBench | 10.0 | High | Yes | Epoch AI (via `live_bench_external.csv`) |
| SWE-bench Verified | 9.0 | Medium | Yes | Epoch AI |
| MATH Level 5 | 8.5 | Medium | No | Epoch AI |
| MMLU-Pro | 5.5 | Low | No | Epoch AI |

## How We Apply These Findings

### 1. Quality Tiers in `benchmark_quality` Column

Each model row in `rankings.csv` gets a quality tier based on data completeness:
- **"high"** — has GPQA (score 11.0) + Arena Elo + AA Intelligence Index
- **"medium"** — has at least 2 of: Arena Elo, GPQA, coding score, AA index
- **"low"** — only 1 data point or only pricing data

This lets downstream consumers know which model comparisons are well-supported.

### 2. Prioritizing Contamination-Resistant Sources

Our 4 data sources each contribute contamination-resistant signals:
- **Chatbot Arena** — fresh human preference data (contamination-proof)
- **GPQA Diamond** — expert-validated PhD-level questions (via Epoch AI)
- **LiveBench** — monthly-refreshed (via Epoch AI)
- **AA Intelligence Index** — composite of 10 evals with 95% CI < ±1%

### 3. What We Don't Do (Yet)

- We don't weight individual benchmark scores by BetterBench quality in a composite
- We don't compute confidence intervals (only AA provides these natively)
- We don't filter out low-quality benchmarks — we report them but flag quality

## Companion Paper: LBOps

**Paper**: "On the Workflows and Smells of Leaderboard Operations (LBOps): An Exploratory Study of Foundation Model Leaderboards"
**Authors**: Zhao, Bangash, Cogo, Adams, Hassan (SAIL, Queen's University)
**Venue**: IEEE Transactions on Software Engineering, 2025
**ArXiv**: https://arxiv.org/abs/2407.04065
**Repo**: https://github.com/SAILResearch/awesome-foundation-model-leaderboards (711 leaderboards catalogued)

Where BetterBench evaluates benchmark *design quality*, LBOps evaluates *operational quality* — how well leaderboards are maintained, updated, and managed. Key operational "smells" they identify:

| Smell | Description | Relevance to us |
|---|---|---|
| **Stale data** | Leaderboard stops updating without notice | We track `_meta.json` timestamps; AA has continuous updates |
| **Inconsistent scoring** | Same model scored differently across configs | Arena uses thinking-32k/16k variants; Epoch uses base model |
| **Missing metadata** | No confidence intervals, no versioning | Only AA provides 95% CI; we flag this in `benchmark_quality` |
| **Score aggregation bias** | Averaging unweighted benchmark scores | Our quality tiers partially address this |
| **Contamination drift** | Training data increasingly overlaps test sets | GPQA/Arena/LiveBench are contamination-resistant |

This reinforces our approach: don't just aggregate numbers — track *which* benchmarks contributed, flag data quality, and prefer contamination-resistant sources.

## Source Evaluation Methodology

When considering adding a new benchmark source, evaluate against:

1. **Data availability** — Is there a public API or downloadable data? (reject if scraping required)
2. **Overlap** — Does it duplicate data we already get? (reject if >80% overlap)
3. **Quality signal** — Does it provide unique, high-quality metrics? (prefer contamination-resistant)
4. **Update frequency** — How often is data refreshed? (prefer continuous/monthly over static)
5. **Attribution requirements** — Can we comply with terms of use?

### Sources We Fetch (4 active)

| Source | API | Unique value | Update freq |
|---|---|---|---|
| **Chatbot Arena** | GitHub CSV mirror | Human preference Elo (contamination-proof) | Continuous |
| **Epoch AI** | ZIP of CSVs | GPQA, MATH, SWE-bench, LiveBench, coding | Daily |
| **OpenRouter** | REST `/api/v1/models` | Pricing, context length | Real-time |
| **Artificial Analysis** | REST `/api/v2/data/llms/models` | Intelligence Index, speed (TPS/TTFT) | Continuous |

### Sources Evaluated and Skipped

| Source | Why Skipped |
|---|---|
| **LiveBench** | Already covered via Epoch AI's `live_bench_external.csv` |
| **LM Council** | Aggregator — curates same Epoch AI + Scale AI data we already fetch |
| **LLM Stats / ZeroEval** | Aggregator — leaderboard data from sources we already fetch |

### Full Landscape Evaluation (Feb 2025)

Cross-referenced against the [Awesome AI Leaderboard](https://github.com/SAILResearch/awesome-foundation-model-leaderboards) catalogue (711 leaderboards). Potentially interesting sources not yet added:

| Source | Category | Why not added (yet) |
|---|---|---|
| **SEAL Leaderboards** (Scale AI) | Comprehensive | No public API, private evals |
| **Humanity's Last Exam (HLE)** | Multimodal | Very new, few models tested. Monitor. |
| **HAL** (Princeton) | Agent | Agent evals are emerging; not enough coverage yet |
| **HELM** (Stanford) | Comprehensive | High overlap with Epoch AI data |
| **FrontierMath** | Math | Hosted by Epoch AI, already in their data |
| **MathArena** | Math | Overlap with MATH Level 5 from Epoch AI |
| **LiveCodeBench** | Code | Overlap with Aider polyglot from Epoch AI |
| **BigCodeBench** | Code | HuggingFace space, no bulk data API |
| **MLE-bench** | Code | OpenAI-hosted, ML engineering only (narrow) |
| **MCPMark** | Agent | Too new, MCP-specific |
