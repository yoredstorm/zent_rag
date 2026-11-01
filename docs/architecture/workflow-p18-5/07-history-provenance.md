# P18.5-07 — Historial con revisión, hashes y procedencia

## Identidad

- Commits: `e23b2ed`, `7730264`
- Archivos: `engine.py::run_detail/list_runs/get_workflow`,
  `WorkflowRunInspector.tsx`, `WorkflowTestHistory.tsx`,
  `workflowTestPresentation.ts`.

## Read model añadido

`run_detail` devuelve ahora:

- `graph_hash`, `policy_hash` (alias de `effective_scope_hash`)
- `published_version_id`, `workflow_version`, `definition_source`
- `simulated`, `effective_level`, `provider_verified=false`
- `agent_snapshot_hash`, `agent_snapshot_status`
- `has_provenance`

`list_runs` incluye `graph_hash`; `get_workflow` incluye `graph_hash` del grafo
actual. Son campos aditivos; no se renombró nada existente.

## Comparación en UI

`compareRunGraph(runHash, currentHash)` devuelve:

- `SAME`: huella del run == grafo actual.
- `DIFFERENT`: huellas presentes y distintas.
- `UNKNOWN`: falta la huella del run o la actual. La UI muestra “Sin huella” o
  “Huella sin comparar”; nunca infiere coincidencia.

El historial muestra un marcador por run y el inspector muestra
`definition_source · vN · grafo <hash12> · agente <estado>`.
El historial no mezcla un `test_report` con un `execution_run`: el reducer
conserva `runKind`.

## Pruebas

- `workflowTestPresentation.test.ts`: SAME / DIFFERENT / UNKNOWN.
- `test_p18_5_workspace_authorization.py`: `has_provenance=true` en run real y
  `graph_hash` en la lista de runs.
- La suite de UI del Workflow Studio pasó 112 tests después de los cambios.

## Límites

- Si un run legado no tiene huella, permanece `UNKNOWN`; no se recalcula desde
  el grafo actual.
- La comparación es de hash de grafo, no de payload ni de política.
- Un run de otro workspace se rechaza en servidor antes de llegar a la UI.

## Compatibilidad

- Sin migración.
- Campos nuevos en JSON; consumidores antiguos los ignoran.
- Rollback: revertir `7730264`; los runs históricos no se modifican.

## Decisión

**PASS** para procedencia y comparación de grafo.

## Próxima fase autorizada

P18.5-08.
