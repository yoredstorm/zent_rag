# 00 — Resumen ejecutivo

> **Actualización 2026-10-21:** este resumen refleja la auditoría Prompt 00
> antes de la remediación. El planner real ya fue corregido y el Gold de venta
> pasa con Pro y con el fallback Flash. Ver
> [`../certification/universal-studio-remediation.md`](../certification/universal-studio-remediation.md).
> El veredicto de producción general sigue siendo NO-GO hasta completar la
> matriz y las experiencias pendientes.

## 1. Veredicto

**NO-GO para producción general.** El runtime existente está en mejor forma que
el informe anterior, pero el Universal Agent & Workflow Studio **no está
implementado** y los bloqueos de creación IA, publicación con evidencia,
durabilidad desde disparadores y bienestar siguen abiertos.

| Decisión | Estado |
|---|---|
| Runtime de workflows existente | GO condicionado a staging controlado |
| Creación de workflows con IA | NO-GO (Gold real FAILED en HEAD) |
| Universal Studio | NO-GO (plan 01–09, no implementado) |
| Publicación con certificación | NO-GO (gate no consume certificación) |
| Workflows durables desde schedule/webhook | NO-GO (no crean instancia) |
| Marketplace global | GO condicionado (`/products` canónico; canvas sin migrar) |
| Bienestar / roles sensibles | NO-GO (sin política de rol) |
| Operación empresarial | NO-GO (sin consola, budgets ni PII masking) |

## 2. Qué cambió desde el informe anterior

El informe
[`../certification/workflow-ai-go-no-go.md`](../certification/workflow-ai-go-no-go.md)
auditó `a826d8c`. El HEAD actual es `c65dbdf`, con **5 commits posteriores**:

| Cambio | Evidencia | Efecto |
|---|---|---|
| El portal ya usa el Architect como camino canónico, con Copilot legacy como rollback | `AskZent.tsx:22-56` | F-01 cerrado |
| Publicación del Architect revalida grafo, agente, snapshot y readiness | `versions.py:292-386`, `429-476` | F-02/F-03 parcialmente cerrados |
| Simulación ejecutable + certificación + sesiones persistentes | `workflow_simulation.py`, `design_sessions.py` | Nueva capacidad, pero **no conectada al publish** |
| `plan_workflow` valida el grafo compilado | `architect.py:747-771` | F-24 cerrado |
| Parser/budget del planner endurecidos | `planner_session.py`, `architect.py` | Gold real sigue fallando |
| `ai_decision` con contexto y fallback explícito | `nodes.py:2520-2627` | Nuevo comportamiento; simulación aún llama JEV real |

**No se puede reutilizar el veredicto anterior sin releer el código.** Varias
cosas mejoraron; otras siguen igual y aparecieron brechas nuevas.

## 3. Hallazgos comprobados (top 12)

| # | Hallazgo | Evidencia | Sev |
|---|---|---|---|
| 1 | El publish no consume la certificación de simulación | `versions.py:448-476`; no lee `workflow_design_revisions` | P0 |
| 2 | `READY_TO_PUBLISH` se alcanza con respuestas externas declaradas por el usuario | `workflow_simulation.py:246-289`, `845-853` | P0 |
| 3 | Scheduler/hook/evento/manual no crean `WorkflowInstance` para grafos durables | `engine.py:1548-1557`, `1625-1634`; `events.py:257`; `routes:1761` | P0 |
| 4 | Workflows manuales no tienen gate de readiness | `versions.py:335-337`; `readiness.py` no consumido | P0 |
| 5 | `llm` sin agente devuelve eco con `succeeded` en runtime | `nodes.py:2042-2057` | P0 |
| 6 | No hay política de rol para bienestar; solo PII masking | `ai_governance.py:52-68`; `agents` sin `safety_policy` | P0 |
| 7 | Gold real con LLM falla en HEAD: `planner.invalid_llm_output`, 0 pasos, 107807 tokens | `artifacts/certification/ai/gold-real-llm.c65dbdf.json` | P0 (proveedor) |
| 8 | No existe intake universal rol/proceso → agentes + workflows | `AgentBuilder` y `AskZent` separados; no `studio_solutions` | P1 |
| 9 | La versión de agente no gobierna el runtime del workflow | `entities.py:296-297` vs `nodes.py:1998` | P1 |
| 10 | Multi-agente posible en el grafo, sin contrato/UI/prueba | `architect_validator.py:1039-1046`; sin test dedicado | P1 |
| 11 | `for_each` semántico bloqueado; canvas con `_branch` vacío reporta éxito | `architect_validator.py:907-919`; `nodes.py:2902-2974` | P1 |
| 12 | Instancias y agente→workflows no filtran workspace | `instances.py:300-341`; `assistants.py:73-108` | P1 |

El detalle completo, con archivo/línea, estado y prueba de aceptación, está en
[`03-gap-matrix.md`](03-gap-matrix.md).

## 4. Evidencia ejecutada

| Suite | Resultado |
|---|---|
| `pytest` núcleo Studio (6 archivos) | **81 passed** (735s) |
| `pytest` planner/readiness/patch | **44 passed** (185s) |
| `pytest` agentes (4 archivos) | **54 passed** (322s) |
| `npm run typecheck` | **OK** |
| `vitest` workflowStudio + marketplace | **73 passed / 16 files** |
| `ruff check src tests` | **OK** |
| `pytest tests/certification/workflows` | **timeout** tras 7 tests; no verde |
| `pytest test_tenant_isolation.py` | **5 passed** (528s) |
| `pytest test_signals.py` | **timeout** |
| `pytest test_real_llm_gold.py` (`RAG_CERT_REAL_LLM=1`) | **FAILED** (421s) |

Separación completa mock/sandbox/proveedor real en
[`06-test-evidence.md`](06-test-evidence.md).

## 5. Plan 01–09

| Fase | Objetivo | Depende de | GO clave |
|---|---|---|---|
| 01 | Fundaciones, contratos, flags, migraciones nullable | — | migraciones aditivas, flags off, baseline verde |
| 02 | Agente universal, roles, versión fijada | 01 | rol + política + versión en runtime |
| 03 | Compositor rol/proceso → agentes + workflows | 02 | blueprint, materialización con confirmación |
| 04 | Capacidades y marketplace único | 01 | readiness sobre snapshot, canvas sobre `/products` |
| 05 | Ejecución endurecida (durable, budgets, service identity) | 02, 04 | durable triggers, límites, workspace |
| 06 | Simulación y gate de publicación | 04, 05 | evidencia vigente, efectos declarados ≠ READY |
| 07 | Seguridad, bienestar, PII, audit, RBAC | 02, 06 | wellness sin diagnóstico, PII fuera, audit |
| 08 | Studio UX y operación | 03, 05, 06 | un flujo, consola read-only, aprobaciones |
| 09 | Certificación, rollout, GA | todas | Gold + 100 casos + sandbox + load + rollback |

Detalle de archivos candidatos, puntos de integración y criterios en
[`05-plan-01-09.md`](05-plan-01-09.md).

## 6. Decisiones de arquitectura

Los ADR nuevos están en [`04-adr-universal.md`](04-adr-universal.md). Los
principales:

1. El blueprint universal es un artefacto de diseño, no un runtime.
2. El rol es metadata de producto, no permiso.
3. La política de rol se aplica de forma determinística, no solo por prompt.
4. La versión de agente gobierna el workflow.
5. Multi-agente se expresa con el DAG, sin orquestador nuevo.
6. Los disparadores existentes crean instancia durable cuando el grafo la
   requiere.
7. La certificación es evidencia obligatoria del publish.
8. `/api/v1/products` es el único storefront.
9. La operación es una vista read-only workspace-scoped.
10. Rollout por flags con rollback de datos no destructivo.

## 7. Riesgos abiertos

| Riesgo | Propietario | Estado |
|---|---|---|
| Gold real / calidad del planner | AI/Workflow Lead | Abierto |
| Sandbox real de pagos | QA/Partners | Abierto |
| Carga, caos y worker restart | SRE Lead | Abierto |
| Política de bienestar | Safety Lead | Abierto |
| PII en trazas | Security Lead | Abierto |
| Workspace isolation | Platform Lead | Abierto |
| Gate de certificación | Workflow Lead | Abierto |
| Timeout de certificación | QA Lead | Abierto |

Registro completo en [`08-risks-rollout.md`](08-risks-rollout.md).

## 8. Recomendación

1. **No publicar** el Universal Studio como producto terminado.
2. **Mantener** workflows existentes y ejecución durable en staging controlado.
3. **Bloquear** creación/publicación con IA para tenants productivos.
4. **No exponer** roles de bienestar hasta fase 07.
5. **Iniciar fase 01** con flags off y migraciones aditivas.
6. **Reevaluar** al cerrar fase 06 y fase 09 con evidencia real.

La decisión formal está en [`07-go-no-go.md`](07-go-no-go.md).
