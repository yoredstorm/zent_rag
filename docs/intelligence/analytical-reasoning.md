# Analytical Reasoning

Phase 29 — research plans, decomposition, drivers, graph paths.

## Research plan

`src/core/domain/research.py` — `ResearchPlan` / `ResearchStep` with statuses
`PENDING|RUNNING|DONE|FAILED|DATA_MISSING|CONTEXT_MISSING|SKIPPED` and budgets
(`max_steps`, SQL/retrieval/tool/token/cost/duration).

## Engine

`src/intelligence/analytical.py` — `AnalyticalReasoningEngine`

- `build_research_plan(question)` for why/causal questions
- `decompose` → period_comparison, variance, dimension_decomposition, top_contributors
- `driver_analysis` → contribution shares; **causality defaults to `not_established`**
- LoopGuard fingerprint checks for step budgets

## Graph

`src/intelligence/graph_reasoning.py` — bounded traversal (`max_depth`, `max_nodes`,
`allowed_edge_types`) with path explanations.
