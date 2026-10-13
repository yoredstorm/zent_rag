# Simplification score — baseline

Generado por `python -m src.scripts.simplification_score` (solo lectura).
`adaptive_writers` fuera de la proyección debe ser 0; `terminal_transitions` vive en la allowlist cerrada.

| Subsistema | files | loc | adaptive_writers | terminal_transitions | reason_code_literals | fallbacks | settings_reads | authority_refs | except_exception |
|---|---|---|---|---|---|---|---|---|---|
| agent_runtime | 5 | 13879 | 10 | 4 | 0 | 77 | 22 | 49 | 168 |
| runtime_core | 70 | 29300 | 0 | 11 | 0 | 106 | 23 | 132 | 114 |
| decision | 35 | 10290 | 0 | 0 | 0 | 132 | 9 | 2 | 46 |
| cache | 2 | 214 | 0 | 0 | 0 | 0 | 0 | 0 | 10 |
| accounting | 2 | 1121 | 0 | 0 | 0 | 4 | 0 | 0 | 6 |
| metrics | 5 | 1500 | 0 | 0 | 0 | 6 | 0 | 0 | 2 |
| retrieval | 100 | 29471 | 0 | 0 | 2 | 144 | 0 | 18 | 112 |
| **total** | 219 | 85775 | 10 | 15 | 2 | 469 | 54 | 201 | 458 |

## Hotspots (LOC)

- `src/agents/runtime/orchestrator.py` — 7131
- `src/agents/runtime/agent_runtime.py` — 5841
- `src/rag/traceability.py` — 2262
- `src/decision/preflight.py` — 1796
- `src/runtime/agent_flow.py` — 1633
- `src/runtime/deterministic_authority.py` — 1623
- `src/runtime/narrative_fast_path.py` — 1343
- `src/infrastructure/observability/metrics.py` — 1276
- `src/runtime/evidence.py` — 1271
- `src/decision/registry.py` — 1206

