# 12 — Release Gold horizontal

> **Fecha:** 2026-10-22.
> **Decisión:** NO-GO de producción. Staging controlado solo para el runtime ya existente.
> **Flag:** `ZENT_GOLD_RELEASE_ENABLED=false`. Completar esta nota no activa producción.
> **Rollback:** dejar el flag en false. No toca `definition_snapshot` de instancias vivas.

ZENT no tiene un engine por profesión. Vendedor, mentor, tutor, auditor, soporte y bienestar usan el mismo `execute_graph`, el mismo `WorkflowGraph` v2, el mismo marketplace `/api/v1/products` y los mismos tipos de nodo. Lo que cambia es la misión, el allowlist y los escenarios. Eso está en código. El ciclo completo con LLM real, checkout sandbox y reinicio no está demostrado para las seis soluciones.

## Umbrales antes de un GO

No se rellenan con estimaciones. Una celda vacía es “no medido”.

| Métrica | Umbral para GO | Medido en este corte |
| --- | --- | --- |
| Grafo válido desde cero con LLM real | 6/6 soluciones en `DRAFT_READY` y con `workflow_id` | 1 solución (ventas) llegó a `DRAFT_READY` en sesión de diseño. `workflow_id` null en los artefactos citados. Mentor, tutor, auditor, soporte y bienestar: no medido |
| Resolución de capacidades | Cada capacidad del grafo tiene binding del tenant o queda `UNVERIFIED` | No medido de punta a punta |
| Escenarios obligatorios | passed solo con doble o proveedor. unverified no publica | Catálogo en `test_report.ROLE_SCENARIOS`. No corridos contra grafo real |
| Multi-turno durable | Carrito, progreso o ticket sobreviven un WAIT y un reinicio | Motor certificado en cortes anteriores. No repetido aquí con las seis soluciones |
| Aislamiento | Otro tenant no lee carrito, progreso ni nota de bienestar | Política en `data_mapper` y tests de unidad. No hay ensayo de dos tenants reales |
| Costo por solución | Bajo el presupuesto del planner y del workflow | Ventas Pro: ver artefacto. Las otras cinco: no medido |
| p95 / p99 | Definir por producto en staging antes de GO | No medido |
| Handoff | Crítico en bienestar y soporte deriva sin diagnóstico ni herramienta prohibida | Política y ejemplos. No hay traza de proveedor |
| Primera configuración UX | Un creador no técnico termina sin JSON | Recorrido de portada cubierto por test de portal. Sin video |

## Evidencia que sí existe

| Artefacto | Qué dice | Qué no dice |
| --- | --- | --- |
| `artifacts/certification/ai/gold-real-llm.summary.json` | `BLOCKED`, `publishable: false`, `planner.invalid_llm_output`, 0 pasos, 0 nodos. 7 y 6 llamadas LLM | No es un pase |
| `artifacts/certification/ai/gold-real-llm.pro-pass.json` | Sesión de ventas. Estado posterior `DRAFT_READY`. `publishable: true` dentro del planner. `plan_hash` y `capability_snapshot_hash` presentes | `workflow_id` null al inicio del archivo. No hay checkout sandbox ni una sola orden persistida en este informe |
| `artifacts/certification/ai/gold-real-llm.deepinfra-pass.json` | La sesión de ventas llega a `DRAFT_READY` y `publishable: true` en estados posteriores del JSON | Tampoco sustituye la ejecución durable ni las otras cinco profesiones |
| `docs/architecture/certification/universal-studio-remediation.md` | El fallo de thinking y el contrato del planner. Declara que no hay GO global | La matriz de 100 casos y las 5 experiencias no se cerraron por balance del proveedor |
| Tests de este árbol | Composición, mapper, marketplace return, informe de prueba, operación, panel | No son Gold con LLM real |

## Matriz Requisito, capacidad, test, evidencia

| Solución | Requisito | Nodo o capacidad | Test | Evidencia |
| --- | --- | --- | --- | --- |
| A Vendedor | Carrito durable, stock, un cobro, un inventario | `wait_event`, `loop`, `state_*`, `capability_call` `payments.checkout.create` `inventory.stock.get` | `ROLE_SCENARIOS["ventas"]` marca la señal de pago duplicada | Artefacto Pro de diseño. Ejecución sandbox y webhook duplicado en vivo: no medido |
| B Mentor | Nivel, ejercicio, progreso consentido, reanudar al día siguiente | `llm`, `capability_call` `learning.exercise.evaluate`, `long_term_memory` | `role_scenario("mentor")` | No hay artefacto LLM real |
| C Tutor | Paso a paso, respuesta incorrecta, no inventar resultado | `learning.exercise.evaluate` con `correct: false` | `role_scenario("tutor")` | No hay artefacto LLM real |
| D Auditor | Dos fuentes, evidencia, WAIT de aprobación | `human_approval`, `wait_event` | `expect_waiting` en el escenario auditor | No hay artefacto LLM real |
| E Soporte | KB, ticket autorizado, derivación | `kb_query`, `support.case.open`, handoff | `route_support` en tests de composición | No hay artefacto LLM real de incidente |
| F Bienestar | Sin diagnóstico, consentimiento, crisis deriva | allowlist sin `clinical.diagnose`, handoff | `role_scenario("bienestar")` y `route_wellness` | No hay ensayo adversarial con persona |

## Cómo reproducir sin publicar

1. Dejar `ZENT_GOLD_RELEASE_ENABLED=false`.
2. Entrar a `/workflows/new`. Los tres caminos abren el mismo lienzo.
3. Para mentor: `/workflows/new/manual?plantilla=mentor`. Revisar la ficha. No activar.
4. Para ventas con LLM real, usar el architect solo en staging y guardar el JSON de la sesión. No marcar PASSED si el estado no es `DRAFT_READY` o si `workflow_id` sigue vacío.
5. Simular con el nivel “Simulación determinista”. Si hay efecto sin doble, la UI dice `UNVERIFIED`.
6. Certificación con proveedor solo cuenta si el proveedor respondió. Si no, queda `UNVERIFIED`.
7. Activar un flujo con ficha de misión debe responder 409 mientras el flag esté apagado.
8. Portabilidad: exportar el paquete con `export_workflow_package`, inspeccionar en otro tenant, resolver capacidades en `/marketplace`, no copiar secretos ni `organization_id`. Este corte no ejecutó Tenant A contra Tenant B.

## Manual corto

Creador: describir o partir de plantilla, revisar la ficha, mapear fuentes, resolver capacidades en el marketplace global, simular, no activar si el informe tiene huecos.

Operador: `/operations` y `docs/architecture/universal-studio/11-operations-runbook.md`. Cancelar y suspender exigen `workflows:run`. No reejecutar pagos para depurar.

## CI

No se añadió un job que llame al LLM real ni que publique. Las pruebas de política son `tests/test_workflow_test_report.py` y `tests/test_workflow_operations.py`.

## Decisión

Producción deshabilitada. Staging controlado para el runtime durable que ya existía. No hay GO de las seis soluciones. No hay certificación de proveedor financiero. Cualquier Gold que siga en `BLOCKED` o sin `workflow_id` mantiene el NO-GO.
