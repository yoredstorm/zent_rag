# P13 — 07 GO/NO-GO P00-P03

Fecha: `2026-10-25`.
SHA base: `b31b01402a2e10008eb09b77c148e48120af6004` (cambios en worktree, sin
commit).
`ZENT_GOLD_RELEASE_ENABLED=false`.

## 1. Evidencia ejecutada

| Gate | Comando | Resultado |
|---|---|---|
| Rojos P00 | `pytest tests/red/p13 --runxfail` | 7 failed por causa documentada; luego retirados al pasar |
| P13 core | `pytest tests/test_workflow_published_snapshot.py tests/test_workflow_event_identity.py tests/test_workflow_effective_policy.py tests/test_workflow_p13_migrations.py` | **23 passed** |
| Publicación/versiones | `pytest test_workflow_publication_gate test_workflow_studio test_workflows` | **32 passed** |
| Grafos/composición/policy/workspace | `pytest test_workflow_graph test_workflow_composition test_policy_enforcement test_workflow_workspace_isolation` | **39 passed** |
| Soluciones/Studio | `pytest test_solution_compiler test_workflow_studio test_workflow_publication_gate test_workflows test_workflow_test_studio` | **47 passed** |
| Durables | `pytest test_workflow_durable_instances test_workflow_durable_ingress` | **34 passed** |
| Migración | `alembic upgrade head` 169→170→171→172→173 | OK |
| Migración roundtrip | `alembic downgrade 169 && alembic upgrade head` | OK |
| P04 composer | `pytest tests/test_solution_composer.py` | **4 passed** |
| P05 verificación | `pytest tests/test_workflow_verification.py` | **6 passed** |
| Auditoría de punteros | `python scripts/workflow_p13_audit.py` | 0 faltantes, 0 duplicados, 0 hash mismatch |
| Portal unit | `WorkflowVersionsPanel.test.tsx` | **2 passed** |
| Portal typecheck | `npm run typecheck` | OK |
| Portal lint P13 | `npx eslint ...` | 0 errors, 1 warning preexistente |
| Portal build | `npm run build` | OK (19.16 s) |
| Ruff backend/scripts | `ruff check ...` | OK |
| Manifest | `artifacts/certification/p13/manifest.json` | generado |

JUnit principal: `artifacts/certification/p13/junit-p13-core.xml`.

## 2. Criterios

| Criterio | Estado |
|---|---|
| Workflow activo ejecuta snapshot certificado | PASS (9 tests P01) |
| Edición no cambia ejecución productiva | PASS |
| WAIT/RESUME conserva snapshot | PASS (durables) |
| Dos eventos idénticos legítimos operan por separado | PASS |
| Mismo provider_event_id no duplica | PASS |
| Misma clave + payload distinto → 409 | PASS |
| 100 concurrentes → 1 instancia | PASS |
| Nodo sin agente respeta scope/rol | PASS |
| Workspace ajeno no visible por workflow_id | PASS |
| Migración y downgrade/upgrade | PASS en DB local; downgrade de producción no ejecutado |
| Portal E2E A/B | **NOT_VERIFIED** (spec creado, sin stack levantado) |
| Caos Redis/PostgreSQL | **NOT_VERIFIED** |
| Proveedor/pago real | **NOT_VERIFIED** |
| LLM real masivo | **NOT_VERIFIED** |
| Sandbox/provider real | **NOT_VERIFIED**: adaptadores por defecto bloquean sin credenciales |

## 3. Decisión

- **GO para staging** de P00-P05 con los gates backend y migración anteriores.
- **NO-GO para piloto controlado o producción GA**: faltan Playwright E2E real,
  caos de bus/DB, proveedor real, LLM real masivo y usabilidad.
- No se activa `ZENT_GOLD_RELEASE_ENABLED` ni se emite `PROVIDER_VERIFIED`.

## 4. Riesgos residuales

- Baseline legacy masivo (260 filas en la DB local de pruebas) sin certificado:
  conserva comportamiento, no es evidencia de release.
- Productores de eventos no migrados al outbox.
- Instancias históricas pueden requerir política reconstruida.
- La UI E2E no se ejecutó; un test de componente no prueba el recorrido real.

## 5. Rollback

Ver `06-rollback-runbook.md`. El rollback de código exige alinear la fila viva
con el snapshot publicado antes de desplegar el SHA anterior.
