# Analytical Reasoning

Phase 29 — research plans, decomposition, drivers, graph paths.

> Este motor es una **estrategia** dentro de Evidence Reasoning
> (`docs/intelligence/evidence-reasoning.md`): aporta las operaciones de
> `CAUSAL_ANALYSIS` y `DIAGNOSTIC`. El coordinador de escenarios, hipótesis,
> inferencias y completitud vive en esa fase, no acá.

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
