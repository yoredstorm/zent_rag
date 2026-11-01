# P18.5-10 — Recorrido de canvas basado en la traza real

## Identidad

- Commit: `7730264`
- Archivos: `WorkflowTestResult.tsx`, `WorkflowTestTrace.tsx`,
  `workflowTestPresentation.ts`.

## Cambio

- `flowPreview(graph)` sigue siendo una lista de componentes almacenados, pero la
  UI ahora la rotula **“Componentes del flujo (estructura)”** y aclara que no es
  el camino ejecutado.
- La pestaña **Recorrido** usa exclusivamente `WorkflowRunInspector` con el
  `RunDetail` persistido (pasos, `node_id`, status, output sanitizado).
- Un nodo sin `workflow_run_steps` no se pinta como ejecutado.
- El click de un paso sigue llamando `onSelectNode`; el inspector existente
  conserva el fallback para nodos históricos ausentes en el lienzo.
- WAIT se comunica por el estado durable del segmento, no por un porcentaje
  inventado.

## Pruebas

- `WorkflowTestPanel.test.tsx` y `WorkflowTestTrace` dentro de la suite de 28
  tests: la pestaña Recorrido muestra el inspector, no el preview estático.
- `workflowTestPresentation.test.ts`: comparación de huellas y presentación.
- La suite completa de Workflow Studio (112 tests) pasó.

## No implementado en esta fase

- Diferenciación visual de ramas verdaderas/falsas por decisión observada y
  marcado “No recorrido” para nodos omitidos: el inspector actual ya muestra
  status por paso, pero no se añadió un mapa de aristas ejecutadas al canvas.
  Queda como P2 de pulido, sin inventar datos.
- Virtualización para cientos de pasos: no medida; el inspector usa lista
  existente.

## Decisión

**PASS parcial**: se eliminó la presentación engañosa de estructura como
recorrido. La proyección causal completa en el canvas queda como deuda P2.

## Próxima fase autorizada

P18.5-11.
