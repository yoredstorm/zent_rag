# 11 — P09: Solution Workspace universal

Fecha: `2026-10-23`. Base: `0cbb494ce4` + P00–P08.

## 1. Un solo workspace

`/solutions/:solutionId` es el **Solution Workspace**. Carga datos reales:

- solución y validación (`/studio/solutions/{id}`);
- materialización (`/studio/solutions/{id}/materialization`);
- workflow materializado (`/workflows/{id}`);
- gate de publicación (`/workflows/{id}/release-gate?action=publish`).

La barra de estado es persistente y `aria-live`: nombre, estado de solución,
estado del proceso, gate, bloqueos y versión. No hay estado inventado en el
cliente.

## 2. Tres modos, un modelo

`Simple`, `Guiado` y `Avanzado` usan el mismo `ParameterLevel` del backend:

- Simple: resultado y preparación;
- Guiado: roles, agente, proceso y bloqueos;
- Avanzado: hashes del gate, nivel requerido y detalle de bloqueos.

Las pestañas **Resumen**, **Proceso**, **Configuración** y **Conversación**
comparten el mismo estado. Conversación enlaza al chat del workflow y al Test
Studio; no crea un segundo motor ni una segunda conversación.

## 3. Publicación

El botón **Publicar** solo se habilita cuando el gate P01 devuelve `allowed`.
Si está bloqueado muestra el primer blocker debajo del botón y el título del
botón. El handler vuelve a comprobar `allowed` antes del POST y pide confirmación.
Un test verde o una simulación no habilitan publicar.

## 4. Copiloto y canvas

- **Editar con IA** embebe `WorkflowPatchPanel`: preview de diff, issues,
  `apply` o descarte cerrando sin aplicar.
- Undo/redo en la cabecera del Workflow Studio y atajos `Ctrl/Cmd+Z`,
  `Ctrl/Cmd+Shift+Z`, `Ctrl/Cmd+Y`; historial acotado a 40 pasos y coalescencia
  de 350 ms para no guardar cada movimiento de arrastre.
- Autosave y conflicto ya existían: guardado con debounce, `409` muestra que
  otra pestaña guardó y conserva el borrador local; `Ctrl/Cmd+S` guarda.
- Primer paso: si no hay materialización, el workspace muestra tarjeta de
  primer uso y enlace a revisión/materialización.

## 5. Pruebas

| Comando | Resultado |
|---|---|
| Portal `SolutionWorkspace.test.tsx` | **5 passed** |
| Portal `ModeSwitch.test.tsx` | **1 passed** |
| Portal `WorkflowTestPanel.test.tsx` | **13 passed** |
| Portal `SolutionBuilder.test.tsx` | **1 passed** |
| Portal `npm run typecheck` | OK |
| Portal `npx eslint` archivos P09 | 0 errores (2 warnings) |

Cubre: barra real, gate bloqueado/ALLOW, publish deshabilitado/habilitado,
primer paso, hashes en Avanzado y modos.

## 6. Límites y deuda explícita

- **Multi-select del canvas no está implementado.** El lienzo mantiene selección
  simple; no se afirma lo contrario.
- Undo/redo está implementado y pasa typecheck, pero no tiene un test unitario
  dedicado en este corte.
- La conversación está enlazada, no embebida en el mismo panel; la sincronización
  se basa en el mismo `workflow_id` y estado de backend.
- **Estudio de usabilidad con ≥5 participantes: NOT_VERIFIED.** El protocolo
  está en `p09-usability-protocol.md`; no se ejecutó en este entorno.
- No se ejecutó Playwright ni una prueba de accesibilidad con lector de
  pantalla; WCAG sigue siendo un objetivo de diseño, no una certificación.
- `npm run lint` completo agotó 300 s en este entorno; se verificaron con
  `npx eslint` solo los archivos P09 (0 errores).
- El copiloto depende de `WorkflowPatchPanel` y de un workflow materializado.

## 7. Rollback

Frontend only: revertir `SolutionWorkspace`, `ModeSwitch`, la ruta
`/solutions/:id`, el enlace desde SolutionBuilder y undo/redo. Sin migración ni
cambio de contrato backend.

## 8. Dictamen

**GO P09 para staging controlado** en workspace unificado, estado real, modos,
primer uso, gate de publicación y undo/redo. **NO-GO release:** multi-select,
estudio con 5 usuarios y E2E de accesibilidad siguen abiertos.
