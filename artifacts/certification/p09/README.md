# Evidencia P09

Base: `0cbb494ce4264077a1e6d4823f4520fbc32928b9` + P00–P08.

| Archivo | Resultado |
|---|---|
| `SolutionWorkspace.test.tsx` | 5 passed |
| `ModeSwitch.test.tsx` | 1 passed |
| `WorkflowTestPanel.test.tsx` | 13 passed |
| `SolutionBuilder.test.tsx` | 1 passed |
| `npm run typecheck` | OK |
| `npx eslint` archivos P09 | 0 errores (2 warnings) |

## Estado

- `/solutions/:solutionId` con datos reales de solución, materialización,
  workflow y gate.
- Barra de estado persistente con estado real.
- Modos Simple/Guiado/Avanzado sobre el mismo `ParameterLevel`.
- Pestañas Resumen/Proceso/Configuración/Conversación.
- Publicar solo con gate `allowed`.
- Copiloto con `WorkflowPatchPanel` (diff/apply/descarte).
- Primer uso cuando no hay materialización.
- Undo/redo del canvas con atajos.

## No verificado

- Multi-select del canvas.
- Estudio con ≥5 participantes (`p09-usability-protocol.md`).
- Playwright, lector de pantalla y WCAG.
- Conversación embebida (hoy enlazada al mismo workflow).
