# 04 — ADR del AI Workflow Studio

> Formato: contexto / decisión / consecuencias / alternativas descartadas.
> Estado: **propuestas** (esta fase no implementa).

---

## ADR-1 · Una sola fuente de verdad para la disponibilidad

**Contexto.** Hoy conviven tres lecturas del mismo hecho: `plan_compiler.load_capabilities` (sin estado), `capabilities._installed_status` (con estado de instalación, credenciales, purpose, versión) y `marketplace.resolver` (proveedores y reuso). El planner usa la más pobre, y esa es la causa de F-07.

**Decisión.** El snapshot de capacidades se construye sobre `capabilities._installed_status` + `marketplace.resolver` + `bindings.list_bindings` + `notifications.notification_targets`. No se crea catálogo nuevo: se compone lo existente y se expone una sola vez en `discover_capabilities()["capabilities"]` y `["actions"]`, con los estados de `packages.STATUSES`.

**Consecuencias.** Canvas, planner y validator comparten el mismo contrato de disponibilidad. Un cambio de estado se refleja en las tres superficies sin duplicar SQL.

**Alternativas descartadas.** (a) Tabla nueva de capacidades → catálogo redundante; (b) dejar el estado solo en el canvas → el planner sigue ciego.

---

## ADR-2 · `SemanticPlan` v2: aditivo, sin ids ni mustache

**Contexto.** El plan semántico cubre 18 tipos de paso; el runtime ejecuta 29 nodos. Ampliar el vocabulario es inevitable para cerrar F-08/F-09.

**Decisión.** Ampliar `PLAN_STEP_TYPES` de forma **aditiva** con `capability_call`, `loop`, `ai_decision`, `api_call`, `set_variable`, `business_node`; añadir `wait.on_timeout_step` (rama de timeout) y `for_each.body` (sub-pasos) manteniendo el lenguaje de negocio: sin ids de nodo, sin posiciones, sin `{{…}}`. Los planes v1 siguen siendo válidos y compilables.

**Consecuencias.** El compiler gana dos traducciones nuevas (`_branch`, puerto `timeout`). El validator debe validar cuerpos anidados (profundidad acotada).

**Alternativas descartadas.** (a) Un solo tipo `raw_node` con config libre → el LLM escribiría el grafo, violando "el LLM propone, el código compila"; (b) dejar el vocabulario y exigir canvas manual → mantiene la brecha principal.

---

## ADR-3 · Arranque durable transparente, sin scheduler nuevo

**Contexto.** `wait_event`/`loop` exigen instancia (F-04); los disparadores no la crean.

**Decisión.** Los disparadores existentes (scheduler, hook, evento, `/run`) deciden de forma determinística: si el grafo contiene al menos un nodo que requiere durabilidad (`wait_event`, `loop`) → `instances.start_workflow_instance`; si no, `run_workflow` como hoy. La decisión se materializa en una función pura (`graph_requires_instance(graph)`) y se audita en el run.

**Consecuencias.** Cero cambios al engine y al scheduler; los flujos cortos no pagan el costo de una instancia. Los flujos durables funcionan desde cualquier disparador.

**Alternativas descartadas.** (a) Instancia para todos los runs → costo y estado innecesarios; (b) exigir `/instances` manual → mantiene el fallo silencioso en producción.

---

## ADR-4 · El Copilot legacy no se rompe: modo compatibilidad con fecha

**Contexto.** `/copilot/intent|compile`, `WorkflowIntent/WorkflowPlan` y `heuristic_intent` están vivos en el portal y en workflows persistidos.

**Decisión.** Se conservan intactos durante la migración. `AskZent` pasa al Architect detrás de un flag (`workflow_studio_architect`, default off en el primer release) y el legacy queda como "modo compatibilidad" con telemetría de uso para retirarlo en un release posterior.

**Consecuencias.** Migración reversible; el usuario no pierde su flujo. El costo es mantener dos planners durante la ventana.

**Alternativas descartadas.** (a) Cambiar la UI de golpe → riesgo de regresión en el camino más usado; (b) eliminar el legacy ahora → rompe workflows y planes existentes.

---

## ADR-5 · Gate de publicación por fases para workflows nativos

**Contexto.** Publicar/activar no valida nada para workflows nativos (F-03) y arreglarlo de golpe puede dejar workflows existentes imposibles de reactivar.

**Decisión.** Tres pasos con el mismo código de readiness:
1. **report-only** (observar): `readiness` se computa y se registra, sin bloquear;
2. **warn**: la API devuelve `warning` + `blockers` y la UI exige confirmación explícita (`acknowledge_blockers=true`);
3. **block**: `error` impide publicar/activar; los workflows existentes con errores se pueden desactivar pero no reactivar hasta corregirlos.

La severidad efectiva se configura con un flag por organización (default: fase 2 al adoptar la versión).

**Consecuencias.** Ningún workflow en producción queda inutilizable sin decisión humana; la migración es reversible bajando de fase.

**Alternativas descartadas.** (a) Bloquear desde el día uno → incidentes de continuidad; (b) no bloquear nunca → F-02/F-04 siguen llegando a producción.

---

## ADR-6 · El eco deja de ser fallback en grafos v2

**Contexto.** `llm` sin agente devuelve eco con `status=succeeded` (F-02). Cambiarlo a `error` sin matices rompería workflows legacy (v1) creados por el Copilot antiguo, que a veces no asignaban agente.

**Decisión.** En grafos `workflow_version >= 2` (o `metadata.architect`), `llm` sin `agent_id` devuelve `NodeOutcome(error=…)` accionable ("elige un agente o quita el paso de IA"). En grafos legacy (`workflow_version == 1` / `metadata.legacy`), se conserva el eco **marcado** (`echo=True`) para no romper ejecuciones existentes, y readiness lo reporta como `error` de migración.

**Consecuencias.** Se elimina el fallo silencioso en todo lo nuevo sin romper lo viejo.

**Alternativas descartadas.** (a) Cambio global → regresión en workflows v1; (b) dejar el eco → decisiones de negocio sobre texto inventado.

---

## ADR-7 · Trazas de plan en tabla append-only

**Contexto.** Sin trazas no hay auditoría, ni base confiable para patch, ni dataset real (F-15).

**Decisión.** Nueva tabla `workflow_plan_traces` (append-only: org, workspace, actor, prompt_hash, intent jsonb, plan jsonb, graph_hash, source, issues, created_at). Se escribe **después** de la validación, no altera `workflows`, `workflow_instances` ni `definition_snapshot`. El patch exige `trace_id` y verifica que el plan vigente coincida con el hash (evita parches sobre planes obsoletos).

**Consecuencias.** Auditoría y reproducibilidad sin tocar el runtime ni las instancias activas. Retención sujeta a la política de datos del tenant (no guarda prompt crudo por defecto, solo hash + resumen).

**Alternativas descartadas.** (a) Guardar el plan dentro de `workflows.metadata` → mezcla definición ejecutable con artefactos de IA y provoca churn del grafo; (b) no persistir → se mantiene F-15.

---

## ADR-8 · Contrato de ejecución por nodo, derivado del registry

**Contexto.** El compiler asigna a todo nodo `max_attempts=1`, `timeout_ms=60000`, `error_policy=fail` (`architect_compiler.py:349-351`), ignorando que cada capacidad tiene política razonable (una aprobación humana no puede expirar en 60s, una consulta cognitiva necesita más tiempo).

**Decisión.** Un contrato declarativo por `node_type` (retry, timeout, error policy, requires, riesgo, durabilidad) derivado del registry + `NODE_METADATA`, consumido por validator y compiler para el grafo generado. **No** se añade tabla ni catálogo nuevo: una constante versionada en `node_catalog` que el registry referencia.

**Consecuencias.** Los grafos generados dejan de tener políticas uniformes incorrectas. Los grafos existentes no se reescriben.

**Alternativas descartadas.** (a) Timeouts por nodo definidos por el LLM → el modelo no debe fijar política de ejecución; (b) dejar 60s → fallos por timeout en operaciones legítimamente largas.

---

## ADR-9 · La simulación real se reutiliza, no se reimplementa

**Contexto.** El Architect devuelve `simulation_plan` textual (F-15/F-21) mientras el runtime ya tiene dry-run con pinned data.

**Decisión.** El Architect conserva el preview de negocio (comprensible) y **encadena** el dry-run real existente (`run_workflow(simulate=True)`) cuando el grafo se persiste. El nodo simulado ya respeta contratos (`nodes.py` casos `simulate`), por lo que no hay efectos.

**Consecuencias.** El usuario ve "qué entendí" y "qué pasó de verdad" en el mismo acto de creación. Sin motor de simulación nuevo.

**Alternativas descartadas.** (a) Simulador propio → runtime paralelo; (b) solo texto → falsa sensación de validación.

---

## ADR-10 · Métricas y evaluación con el dataset existente

**Contexto.** `architect_metrics` vive en memoria y el dataset de 50 casos usa un provider plantilla (`tests/data/workflow_architect_cases.json`).

**Decisión.** El gate de calidad se apoya en el dataset (unitario, determinístico) más una evaluación separada opcional con LLM real (no bloqueante en CI). No se crea almacén de métricas: los contadores siguen en proceso y se exponen por el mismo mecanismo de observabilidad existente cuando ya lo haya.

**Consecuencias.** CI determinístico; la calidad con modelo real se mide en un job aparte.

**Alternativas descartadas.** (a) LLM real en CI → coste y flakiness; (b) eliminar métricas → sin señal de regresión.
