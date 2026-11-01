# P18.5-11 — Robustez React, errores, accesibilidad y semántica

## Identidad

- Commit: `7730264`
- Archivos: `WorkflowTestHeader.tsx`, `WorkflowTestResult.tsx`,
  `workflowTestSession.ts`, `useWorkflowTestRunner.ts`,
  `WorkflowTestTechnical.tsx`.

## Cambios

- `WorkflowTestHeader` deriva el estado exacto (`Publicado y activo`,
  `Publicado · pausado`, `Archivado`, `Borrador sin publicar`) en vez de mostrar
  “Sin publicar” para cualquier status.
- El estado durable se muestra en un `role=status` con `aria-live=polite`, texto
  y `Badge`/tokens existentes.
- WAIT / aprobación pendiente no se presentan como resultado final.
- El reporte técnico muestra el `input_snapshot` sin secretos.
- `compareRunGraph` evita afirmar coincidencia sin huella.
- El hook cancela polling/requests al desmontar o cambiar identidad; ignora
  respuestas tardías.
- La UI no depende de un 200 inmediato para una operación durable: el POST
  inicial puede terminar en WAITING y el seguimiento continúa.

## Verificación ejecutada

```text
npm run typecheck   # OK
npm run lint        # 0 errors, warnings preexistentes
npm run test  # 136 files, 859 passed
npx vitest run ...WorkflowTestPanel.test.tsx  # 28 passed
```

## No ejecutado

- Prueba con lector de pantalla real (NVDA/VoiceOver): **NOT_RUN**.
- Axe sobre el panel y canvas: se ejecutará en P18.5-12; no se declara PASS.
- Matriz completa 390/820/1440 light/dark para los nuevos sellos de estado:
  **NOT_RUN** en esta fase.

## Compatibilidad

- Se conservan tabs Respuesta/Recorrido/Verificación, Probar/Resultado y el
  contrato `onRun`/`onSelectNode`.
- No se introdujeron colores nuevos; se usan tokens y `Badge` existentes.

## Decisión

**PASS** para robustez de estado y semántica; accesibilidad formal queda
**NOT_RUN** hasta P18.5-12.

## Próxima fase autorizada

P18.5-12.
