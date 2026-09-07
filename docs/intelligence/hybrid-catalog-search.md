# Hybrid Semantic Catalog Search

Phase 27B ranking for catalog objects (tables, metrics, entities).

Distinct from document `HybridRetriever` in `src/rag/retrieval/hybrid.py`.

## Signals

`HybridCatalogSearch.score(query, candidates, signals)` returns each candidate with:

- `hybrid_score` — weighted sum
- `ranking_signals` — `lexical`, `embedding`, `business_mapping`, `verified_query`, `graph_proximity`, `historical_success`, `authority`

Weights are configurable via `HybridCatalogSearch(weights=...)`.

## Module

`src/catalog/hybrid_search.py`
