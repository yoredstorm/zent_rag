# ZENT — AI Workflow Studio: Contrato Maestro de Ingeniería (Prompt 00)

> **Fase:** auditoría + contrato de arquitectura. **NO** se implementaron funcionalidades.
> **Fecha:** 2026-10-19. **Base:** `master` @ `70620a9` (`feat(auth): provisionar el password del platform admin desde el entorno`).
> **Árbol de trabajo:** limpio al iniciar (`git status --short` sin entradas).
> **Regla de lectura:** donde este documento y el código discrepen, **el código manda**. Todo hallazgo cita archivo y línea.

## Documentos

| # | Documento | Contenido |
|---|---|---|
| 1 | [`01-audit-as-is.md`](01-audit-as-is.md) | Auditoría de capacidades (matriz) y de recorridos (UI → runtime) |
| 2 | [`02-gap-matrix.md`](02-gap-matrix.md) | Matriz de brechas P0/P1/P2 con evidencia |
| 3 | [`03-target-architecture.md`](03-target-architecture.md) | Arquitectura TARGET, límites de responsabilidad, mapa de dependencias |
| 4 | [`04-adr.md`](04-adr.md) | ADR de decisiones técnicas |
| 5 | [`05-migration-plan.md`](05-migration-plan.md) | Plan de migración incremental y reversible |
| 6 | [`06-test-matrix.md`](06-test-matrix.md) | Matriz de pruebas por fase |
| 7 | [`07-go-no-go.md`](07-go-no-go.md) | Criterios de GO/NO-GO |
| 8 | [`08-findings-plan-risks.md`](08-findings-plan-risks.md) | Tabla de hallazgos, plan de implementación por archivos, riesgos de regresión y evidencia de verificación |
| 9 | [`09-canonical-architect.md`](09-canonical-architect.md) | Prompt 01: unificación del Architect, contrato canónico, estados, flag y resultados |
| 10 | [`10-capability-registry.md`](10-capability-registry.md) | Prompt 02: inventario, contrato `zent.capability/v1`, búsqueda, disponibilidad, composición, snapshots y métricas |
| 11 | [`11-agentic-planner.md`](11-agentic-planner.md) | Prompt 03: planner agéntico, tool calling read-only, presupuesto, MATCH/VERIFY/REPAIR y matriz de 23 pruebas |

## Alcance

Cerrar la brecha entre:

1. lo que el runtime de Zent puede ejecutar,
2. lo que el Capability Registry y el Marketplace conocen,
3. lo que el Workflow Architect comunica al LLM,
4. lo que el LLM transforma en un `SemanticPlan`,
5. lo que el compilador convierte en un `WorkflowGraph` ejecutable.

## No-objetivos (leyes respetadas en todo el contrato)

- NO nuevo Workflow Engine, scheduler, bus, colas ni runtime paralelo.
- `WorkflowGraph` v2 sigue siendo la representación ejecutable canónica.
- `execute_graph()` y `run_workflow()` siguen siendo los motores.
- Se reutilizan `WorkflowInstance`, checkpoints, WAIT/RESUME, señales, estado durable, Marketplace, bindings, `capability_call` y contratos de negocio.
- El LLM propone; el backend valida, autoriza, compila y ejecuta. El planner nunca otorga permisos ni obtiene secretos.

## Estado del sistema (resumen ejecutivo)

El runtime es **más capaz que el planner**. Verificado por enumeración de código (ver `01-audit-as-is.md` §1):

| Superficie | Conteo | Evidencia |
|---|---|---|
| Tipos de nodo registrados (ejecutables) | **29** | `nodes.py:3585-3893` (`registry.all()`) |
| Tipos de nodo con metadata semántica | **29** | `node_catalog.NODE_METADATA` |
| Tipos de nodo con schema de negocio (formularios) | **20** | `parameters.NODE_BUSINESS_SCHEMAS` |
| Tipos de paso que el `SemanticPlan` puede expresar | **18** | `architect_models.PLAN_STEP_TYPES` |
| Capacidades de negocio (`capability_call`) | 14 commerce + 5 pagos + `conversation.send` | `commerce/contracts.py:47-70`, `conversation_capability.py:42` |
| Acciones de Marketplace instalables | 14 (dev DB) | `integration_actions` (verificación local) |
| Endpoints del Architect usados por el portal | **0** | `AskZent.tsx:85,101` usa `/copilot/*` |

La IA puede hoy planificar 18 tipos de paso y compilar 22 de las 29 capacidades ejecutables. Quedan **7 capacidades ejecutables inalcanzables** para el planner (detalle en `01` §1.2) y **precondiciones de runtime que el validator no verifica** (F-04, F-05, F-07, F-11, F-12, F-13 en `02`), que rompen el run después de publicar.

## Cómo se obtuvo la evidencia

- Lectura directa del código en `src/platform/workflows`, `src/platform/marketplace`, `src/platform/commerce`, `src/api/routes/workflows.py`, `portal/src/components/workflowStudio`, `tests/`.
- Enumeración ejecutable del registry/catálogo/schemas con el intérprete del proyecto (`.venv`), sin mocks.
- Suite de tests ejecutada contra Postgres local real (`SELECT 1` OK): ver `08-findings-plan-risks.md` §4.
- Inspección de la base local (dev) para el catálogo de capacidades/acciones (no es producción).

## Limitaciones declaradas

- No se ejecutó un LLM real en esta fase: los pipelines se verifican con provider determinístico (`tests/test_workflow_architect_eval.py`) y con lectura de los prompts. La calidad del prompt se juzga por **contenido**, no por una corrida con modelo.
- Las métricas de la base local (acciones, capacidades) son del entorno de desarrollo; en producción cambian por instalaciones de cada tenant.
- Este documento **no declara Zent listo para producción**.
