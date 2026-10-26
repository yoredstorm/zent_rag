# P13 — Final GO/NO-GO

Fecha: `2026-10-26`.
SHA de código certificado: `22dfab27b499bbf7b05034a1e37682aa30720479`.
CI del SHA de código: run `40259575478` — **todos los jobs en success**
(`test`, `portal`, `portal-e2e`, `lint`, `sdk-node`, `sdk-python`, `kustomize`,
`pip-audit`, `secrets-scan`, `build`).
`ZENT_GOLD_RELEASE_ENABLED=false`. No se emitió `PROVIDER_VERIFIED`.

## 1. Evidencia ejecutada

| Gate | Evidencia | Resultado |
|---|---|---|
| Suite backend completa | CI run `40259575478`, job `test` | **PASS** |
| Portal unit/typecheck/lint/build | CI run `40259575478`, job `portal` | **PASS** |
| Portal E2E publicación inmutable | CI run `40259575478`, job `portal-e2e`; y local contra Docker (`8080`) | **PASS** |
| P13 core P01-P03 + migraciones | `pytest test_workflow_published_snapshot test_workflow_event_identity test_workflow_effective_policy test_workflow_publication_gate` | **33 passed** |
| P04 composer | `pytest tests/test_solution_composer.py` | **4 passed** |
| P05 verificación | `pytest tests/test_workflow_verification.py` | **6 passed** |
| Sandbox/provider negativos y metadata | P05 + gate + studio | **PASS** (adaptadores reales sin credenciales bloquean) |
| Seguridad negativa, workspace y durables | `pytest test_workflow_workspace_isolation test_policy_enforcement test_workflow_durable_instances` | **35 passed** |
| Caos hermético | `pytest tests/test_chaos_resilience.py` | **10 passed** |
| Concurrencia misma clave | `test_workflow_event_identity.py` (100 concurrentes → 1 instancia) | **PASS** |
| Migración head | Alembic `173` en DB limpia CI y Docker local | **PASS** |
| Roundtrip migración | `alembic downgrade 169 && alembic upgrade head` | **PASS** (local) |
| Auditoría de punteros | `scripts/workflow_p13_audit.py` | 0 activos sin puntero, 0 productions duplicadas, 0 hash mismatch, 370 baselines legacy |
| Docker local | `rag-api`, `rag-portal`, `rag-ingestion-worker` | **healthy**, migración `173`, API/portal 200 |
| E2E A/B real | publicar A, PATCH B, hook ejecuta A; recertificar/publicar B; portal muestra v2 | **PASS** |

El E2E A/B encontró y cerró un bug real: un certificado de un workflow
org-level (`workspace_id=NULL`) no era visible desde un contexto con workspace
activo y el gate devolvía `STALE`. La regresión está cubierta por
`test_org_level_certificate_is_visible_from_workspace_context`.

## 2. Matriz de criterios

| Criterio | Estado |
|---|---|
| P01 — producción ejecuta snapshot publicado | PASS |
| P01 — PATCH del draft no altera ejecución productiva | PASS |
| P01 — WAIT/RESUME conserva snapshot y política congelada | PASS |
| P01 — publish/promote/restore atómicos y certificados | PASS |
| P01 — aislamiento de workspace por workflow_id | PASS |
| P02 — identidad canónica de eventos y dedupe por fuente | PASS |
| P02 — misma clave + payload distinto → 409 | PASS |
| P02 — inbox/outbox, lease, backoff y DLQ | PASS (tests) |
| P03 — política efectiva inmutable por instancia | PASS |
| P03 — intersección RBAC ∩ workflow ∩ rol ∩ bindings ∩ acción | PASS |
| P03 — nodo sin `agent_id` no evade política | PASS |
| P04 — MissionSpec → CapabilityPlan → Blueprint → Graph → Materialization | PASS (template/compose/hybrid) |
| P04 — reutiliza Architect/planner; no segundo catálogo | PASS |
| P04 — integración ausente → `NEEDS_CONFIGURATION` sin inventar conectores | PASS |
| P05 — `sandbox_ready` no se acepta desde metadata | PASS |
| P05 — sandbox/provider reales | **NOT_VERIFIED** (sin credenciales/entorno) |
| P06 — suite completa | PASS |
| P06 — migración desde DB limpia y migrada | PASS |
| P06 — concurrencia multiworker y P95/P99 | **NOT_VERIFIED** (solo concurrencia de una clave) |
| P06 — caos real matando worker/API, cortando PostgreSQL/Redis/bus | **NOT_VERIFIED** (solo caos hermético inyectado) |
| P06 — LLM real por dominio y dataset ≥100/dominio | **NOT_VERIFIED** (sin proveedor) |
| P06 — usabilidad con ≥5 personas | **NOT_VERIFIED** (sin sesiones) |
| P06 — seguridad negativa | PASS |

## 3. Decisión

- **GO para staging** de P00-P05 y de los gates P06 reproducibles.
- **NO-GO para piloto controlado o producción GA**. Bloquean:
  1. `SANDBOX_VERIFIED`/`PROVIDER_VERIFIED` con credenciales reales;
  2. caos real de worker/API, PostgreSQL, Redis y bus;
  3. concurrencia multiworker con P95/P99;
  4. LLM real por dominio y dataset de evaluación;
  5. usabilidad con al menos 5 personas;
  6. aprobación explícita para `ZENT_GOLD_RELEASE_ENABLED=true`.

No se declara `PROVIDER_VERIFIED` ni se habilita producción. `NOT_VERIFIED`
significa no probado, no un PASS implícito.

## 4. Riesgos residuales

- Los 370 baselines legacy conservan comportamiento pero no son evidencia de
  release; la revocación está en `scripts/workflow_p13_revoke_legacy.py`.
- Productores de eventos aún no migrados al outbox.
- Instancias históricas pueden requerir reconstrucción de política.
- La suite backend tarda ~65 minutos en CI; no se redujo el alcance para
  acortarla.
- El stack Docker local contiene datos de pruebas y 20k instancias WAITING de
  corridas anteriores; no es un entorno de producción.

## 5. Rollback

Ver `06-rollback-runbook.md`. Antes de desplegar el SHA anterior, alinear la
fila viva con el snapshot publicado; el rollback de código no debe ejecutar un
grafo distinto al certificado.
