# 07 — Criterios de GO / NO-GO

> Estos criterios son el contrato de la **fase siguiente** (implementación). No autorizan declarar Zent listo para producción.

## GO de la auditoría (esta fase)

| # | Criterio | Estado |
|---|---|---|
| A1 | Matriz de capacidades con contrato in/out, permisos, ejecutor, disponibilidad, visibilidad al planner, soporte del compiler, validación y certificación | ✅ `01-audit-as-is.md` §1 |
| A2 | Recorridos trazados UI → runtime para creación (legacy, Architect, plantilla), edición, validación, simulación, publicación, WAIT/RESUME, capacidades internas, marketplace | ✅ `01` §2 |
| A3 | Brechas clasificadas P0/P1/P2 con archivo/función/comportamiento | ✅ `02-gap-matrix.md` |
| A4 | Contrato de responsabilidades de las 9 etapas + interfaces a reutilizar/evolucionar | ✅ `03-target-architecture.md` |
| A5 | ADR de decisiones técnicas (10) | ✅ `04-adr.md` |
| A6 | Plan de migración incremental y reversible, sin tocar instancias/snapshots | ✅ `05-migration-plan.md` |
| A7 | Matriz de pruebas con cobertura objetivo y faltantes | ✅ `06-test-matrix.md` |
| A8 | Evidencia de verificación ejecutada (tests + inspección) | ✅ `08-findings-plan-risks.md` §4 |
| A9 | Sin cambios de funcionalidad (solo documentación) | ✅ `git status --short` → solo `?? docs/architecture/ai-workflow-studio/`; `git diff --stat` vacío |

## GO por fase de implementación

Una fase se autoriza a **empezar** solo si:

1. La fase anterior dejó su suite verde (incluida la certificación gold y durable).
2. Existen los tests de la fase escritos y fallando (TDD) antes del cambio.
3. El flag de la fase está definido con su default y su rollback documentado.
4. No hay migraciones destructivas.
5. Se preserva: `WorkflowGraph` v2 canónico, `execute_graph`/`run_workflow`, `WorkflowInstance` y snapshots congelados.

## NO-GO (bloqueantes duros)

Se declara **NO-GO** para avanzar de fase si ocurre cualquiera de estos:

| # | Condición |
|---|---|
| N1 | Un test de `tests/certification/workflows/` (gold, durabilidad, señales, portabilidad, addons, pagos, tenant isolation) queda rojo |
| N2 | Se introduce un engine, scheduler, bus o cola nuevos |
| N3 | El LLM gana capacidad de otorgar permisos, instalar, publicar o ejecutar durante la planificación |
| N4 | Un grafo compilado por la IA puede publicarse con `error` de readiness sin confirmación explícita |
| N5 | Se rompe la ejecución de un workflow `graph_source='legacy'` o de un plan legacy |
| N6 | Se modifican instancias activas o `definition_snapshot` |
| N7 | Se introduce una segunda fuente de verdad para disponibilidad de capacidades |
| N8 | Un hallazgo P0 se "cierra" solo por existir archivo/endpoint/test con mocks (sin ejecución real) |
| N9 | El Architect (o cualquier planner) puede devolver un grafo que `validate_graph` rechaza |

## Criterios de aceptación de la DEFINICIÓN DE TERMINADO del Prompt 00

| # | Criterio | Evidencia |
|---|---|---|
| D1 | Está claro **qué piezas** hay que modificar para que un requerimiento en lenguaje natural se convierta en un `WorkflowGraph` correcto y ejecutable | `03` §3-§4 + `08` §2 (plan por archivo) |
| D2 | Tabla de hallazgos | `08` §1 |
| D3 | Plan de implementación por archivos | `08` §2 |
| D4 | Riesgos de regresión | `08` §3 |
| D5 | Evidencia de verificaciones realizadas | `08` §4 |
| D6 | Declaración explícita de que Zent **no** queda declarado listo para producción | `README.md` (Limitaciones) + `08` §5 |

## Métricas de éxito de la implementación (a medir, no inventar)

| Métrica | Baseline hoy | Objetivo |
|---|---|---|
| Cobertura registry ↔ pasos planificables | 22/29 | 28/29 (`end` lo emite el compiler, no es paso semántico) |
| Nodos con schema de negocio | 20/29 | 26/29 |
| Precondiciones de runtime validadas | 0/7 | 7/7 |
| Workflows nativos publicables con `error` de readiness | sí | no (fase 3) |
| Fallos en primer run por nodo durable desde trigger | posible | 0 |
| Casos del dataset de evaluación | 50 | ≥ 58 |
