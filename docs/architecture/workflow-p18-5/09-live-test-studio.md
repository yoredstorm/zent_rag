# P18.5-09 — Test Studio en vivo: RUNNING, WAIT, RESUME, COMPLETED

## Identidad

- Commit: `7730264`
- Archivos: `useWorkflowTestRunner.ts`, `workflowTestSession.ts`,
  `WorkflowTestResult.tsx`, `workflowTestTypes.ts`,
  `portal/e2e/p18-5-live-resume.spec.ts`.

## Cambios

- `RunOut` conserva `instance_id` y `run` anidado sin romper `{run_id}` legacy.
- Tras un `/run` durable, el hook hace polling autorizado a
  `/instances/{id}` (1.5 s con backoff hasta 10 s) y, al observar un
  `last_run_id` nuevo, carga su `RunDetail`, actualiza `onRun` y el overlay.
- `AbortController` + token de seguimiento cancelan polling al desmontar o
  cambiar tenant/workflow/operación.
- Estados durables separados del run: `RUNNING`, `WAITING`, `SUSPENDED`,
  `COMPLETED`, `FAILED`, `CANCELLED`, `EXPIRED`, `CONNECTION_LOST`.
- WAIT se muestra como “En espera” con el `waiting_event_type`; nunca se marca
  COMPLETED solo porque `resumed=true`.
- Error de red se muestra como conexión perdida y se reintenta; no se crea otro
  run.
- La llave de idempotencia se mantiene por intención.
- `fetch` de polling es GET; no se reenvía `POST /run` al reconectar.

## Pruebas

```text
npx vitest run src/components/workflowStudio/WorkflowTestPanel.test.tsx
28 passed
```

Incluye un test que simula `WAITING → COMPLETED`, verifica que se actualiza el
nuevo segmento, que el answer cambia y que el POST `/run` ocurre exactamente una
vez.

```text
npx vitest run src/components/workflowStudio/workflowTestSession.test.ts
11 passed
```

Cubre WAIT ≠ COMPLETED, `run-refreshed`, limpieza de estado durable al iniciar
otro run.

## E2E ejecutado

```text
$env:E2E_WAIT=1
$env:E2E_PORT=8091
$env:VITE_API_PROXY=http://127.0.0.1:8001
npx playwright test e2e/p18-5-live-resume.spec.ts
1 passed (1.6m)
```

API desde fuente, Postgres/Redis locales, Chromium, sin refrescar la página:
WAIT visible → señal por API → estado COMPLETED en el dock → un solo POST /run.

También se ejecutó contra el stack Docker local actualizado (portal `:8080`,
API `:8000`, migración 177):

```text
$env:E2E_WAIT=1; $env:E2E_EXTERNAL=1; $env:E2E_BASE_URL=http://127.0.0.1:8080
npx playwright test e2e/p18-5-live-resume.spec.ts
1 passed (22.1s)
```



## Límites

- No se probó SSE porque esta ruta no tiene un stream con replay/cursor; se usó
  polling acotado sobre endpoints existentes.
- 401 durante polling muestra conexión perdida; no se implementó re-login
  automático. El CTA de reautenticación queda como deuda P2.
- Un `SUSPENDED` detiene el polling y muestra aviso; requiere acción del usuario.

## Decisión

**PASS** para el ciclo vivo local con E2E real.

## Próxima fase autorizada

P18.5-10.
