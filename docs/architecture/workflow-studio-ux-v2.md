# Workflow Studio UX v2 — Data Inspector + Node Debugger + Partial Runs

> **Status:** Fases 1, 2 (consolidación), 5 (extensión), 6 implementadas. Fase 3/4 (ejecución parcial y pinned data) implementadas backend + UI básica. Fases 8/9 pendientes.
> **Fecha:** 2026-09-13
> **Base:** `feat/knowledge-cognitive-os` @ `aba6bc2`
> **Regla:** potencia disponible + complejidad progresiva. JSON nunca es la vista primaria.

## 1. CURRENT (verificado)

| Área | Hoy |
|---|---|
| Canvas | `WorkflowCanvas` con drag, zoom, pan, edges con flechas, highlight de ejecutados y opacidad de skipped; `overlay` por nodo (status, duration, error, text) |
| Editor | `WorkflowCanvasEditor` inserta nodos auto-conectados, marketplace drawer, costos, inspector flotante; nivel Simple/Guiado/Avanzado en `editor_state.config_level` |
| Inspector | `NodeConfigPanel`: formularios de negocio (BusinessParameterForm/ConditionBuilder/Schedule/Notification), data picker con labels, secretos, y bloque Avanzado con policies/ports/JSON |
| Runs | `workflow_runs` (status, duration, error, simulate, correlation) + `workflow_run_steps` (node_id, status, input, output, error, retries, duration, idempotency) |
| Run UI | `WorkflowRunInspector`: lista de pasos con badges; detalle en JSON mono; `WorkflowTestPanel` con simulate/real y runs recientes |
| Debug | `simulate` + `planned_effects`; no hay input/output humano por nodo, ni ejecución parcial, ni pinned data |
| Data refs | `{{nodes.<id>.output.<path>}}` con DataPicker de labels; refs estables por node id |

## 2. GAPS

1. El inspector del nodo no muestra INPUT/OUTPUT reales del último run; el usuario mira JSON.
2. No existe ejecución parcial (node/until/from) aunque el DAG y `resume` ya tienen la base.
3. No existe pinned data para tests (aislada de producción).
4. Tokens/costo por nodo no se muestran en la tarjeta del nodo (solo en inspector de runs).
5. Avanzado está en un único bloque, sin agrupar Ejecución/Errores/Seguridad/Developer.
6. Sin preview de datos en conexiones (Fase 8) ni undo/redo/multi-select (Fase 9).

## 3. TARGET

### 3.1 Inspector con pestañas

CONFIGURAR | INPUT | OUTPUT | RUN, más AVANZADO (colapsable):

- CONFIGURAR: exactamente lo actual (formularios de negocio).
- INPUT/OUTPUT: `DataView` humano (claves → valores, arrays con conteo y "Ver registros" como tabla compacta, `Ver JSON` al final, nunca primario).
- RUN: estado, duración, reintentos, timestamp, error resumido, planned effects; acciones `Ejecutar nodo`, `Ejecutar hasta aquí`, `Ejecutar desde aquí`, `Reintentar`.
- AVANZADO agrupado: Ejecución (timeout/retries/backoff), Errores (error_policy), Seguridad (riesgo/capacidades), Developer (type/version/ports/raw config).

### 3.2 Ejecución parcial (contrato backend)

`POST /api/v1/workflows/{id}/run` acepta:

```json
{ "payload": {}, "simulate": true,
  "run_mode": "full" | "node" | "until_node" | "from_node",
  "target_node_id": "n3",
  "source_run_id": "uuid?" }
```

Semántica:

- `full`: como hoy.
- `until_node`: ejecuta el flujo y se detiene al completar `target_node_id`; el resto queda `skipped`. Requiere trigger normal.
- `node`: arranca en `target_node_id` y se detiene ahí; los predecesores se hidratan desde `source_run_id` (o el último run del workflow) y/o pinned data. Si falta data de un predecesor → error humano, no se ejecuta a ciegas.
- `from_node`: arranca en `target_node_id` y continúa descendientes; misma hidratación.

El runtime ya tiene los primitivos (`entrypoints`, `cached` de resume, `stop`); se extiende con `stop_after`, `entry_override`, `preloaded`. No hay motor nuevo.

`workflow_runs` persiste `run_mode`, `target_node_id`, `source_run_id` (migración 112).

### 3.3 Pinned data (solo pruebas)

Tabla `workflow_pinned_data` (tenant scoped: organization + workflow + node, único por nodo). API:

- `GET /api/v1/workflows/{id}/pinned-data`
- `PUT /api/v1/workflows/{id}/pinned-data/{node_id}` body `{output: {...}}`
- `DELETE /api/v1/workflows/{id}/pinned-data/{node_id}`

Reglas: el runtime SOLO usa pinned cuando `simulate=true`; en runs reales se ignora. La UI muestra "Datos fijados para pruebas" y permite quitarlos. Nunca se guardan en el graph.

### 3.4 Overlay / tarjetas

Extender el overlay existente con `tokens`/`cost` cuando el step los traiga (llm), y resumen en la tarjeta. Si no hay dato, no se muestra (nada inventado).

## 4. ARCHIVOS

**Backend**

- `src/infrastructure/db_init/versions/112_studio_debug.py` + SQL mirror 84
- `src/platform/workflows/runtime.py` (stop_after, entry_override, preloaded, pinned en simulate)
- `src/platform/workflows/engine.py` (run_mode/target/source, persistencia, pinned loader)
- `src/platform/workflows/pinned.py` (CRUD tenant scoped)
- `src/api/routes/workflows.py` (RunIn v2 + endpoints pinned)
- Tests: `tests/test_workflow_partial_runs.py`

**Portal**

- `portal/src/lib/humanData.ts` (formato humano, tablas compactas)
- `portal/src/components/workflowStudio/DataView.tsx`
- `portal/src/components/NodeConfigPanel.tsx` (pestañas, avanzado agrupado, acciones)
- `portal/src/components/WorkflowCanvasEditor.tsx` / `WorkflowStudio.tsx` (pasar run steps)
- `portal/src/components/WorkflowRunInspector.tsx` (human-first + Ver JSON)
- `portal/src/components/WorkflowCanvas.tsx` (tokens/costo en tarjeta, estado queued/running)
- Tests: `DataView.test.tsx`, `NodeConfigPanel.test.tsx`

## 5. FUERA DE ESTA ENTREGA

- Fase 8 (preview de datos sobre conexiones), Fase 9 completa (undo/redo/multi-select/keyboard shortcuts), minimap.
- Pinned data en ejecuciones productivas: prohibido por diseño.
