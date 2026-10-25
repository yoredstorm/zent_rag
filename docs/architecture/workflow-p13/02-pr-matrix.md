# P13 — 02 Matriz de PRs

| PR | Fase | Contenido | Depende de | Gate de salida |
|---|---|---|---|---|
| PR-0 | P00 | Baseline, gap register, tests rojos | — | `pytest tests/red/p13 --runxfail` falla por causa documentada |
| PR-1 | P01a | Migración 170, `definition.py`, runtime published/draft/instance | PR-0 | Hook/schedule ejecutan snapshot; WAIT conserva snapshot |
| PR-2 | P01b | publish/activate/promote/restore atómicos, PATCH If-Match, UI | PR-1 | 50 races, rollback certificado, E2E A/B |
| PR-3 | P02a | Migración 171, `event_identity.py`, inbox worker/outbox | PR-2 | Dos eventos idénticos = 2; mismo ID = 1; conflicto 409 |
| PR-4 | P02b | Schedule occurrence, effect ledger, caos bus/worker | PR-3 | Replay 3 veces = 1 efecto; outbox drena |
| PR-5 | P03a | Migración 172, `effective_policy.py`, PEP universal | PR-4 | Matriz negativa 100% |
| PR-6 | P03b | Workspace isolation completa y UI de denegaciones | PR-5 | Tenant/workspace A/B 100% |
| PR-7 | P03c | Evidencia, JUnit, ADR, runbooks | PR-6 | DoD P00-P03 |

## Reglas

- Una migración por PR. Sin solapamiento.
- Sin cambios cosméticos fuera de alcance.
- Sin nuevo engine, planner, scheduler, catálogo o tabla de agentes.
- `ZENT_GOLD_RELEASE_ENABLED=false` en todos los PR.
- Un P0 abierto bloquea el PR siguiente.
- Cada PR actualiza `docs/architecture/workflow-p13/` y `artifacts/certification/p13/`.
