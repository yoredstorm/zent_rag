# P18.4-02 — Arquitectura del refactor

- Fecha: 2026-10-30
- Rama: `p18.4-workflow-test-ux`

## 1. Antes y después

| Archivo | Antes | Después |
|---|---:|---:|
| `WorkflowTestPanel.tsx` | 674 | 302 |
| `useWorkflowTestRunner.ts` | no existía | 276 |
| `WorkflowTestResult.tsx` | no existía | 282 |
| `WorkflowTestSetup.tsx` | no existía | 120 |
| `WorkflowTestComposer.tsx` | no existía | 208 |
| `WorkflowTestModePicker.tsx` | no existía | 152 |
| `WorkflowTestVerification.tsx` | no existía | 164 |
| `WorkflowTestReadiness.tsx` | no existía | 144 |
| `workflowTestPresentation.ts` | no existía | puro, sin React |
| `workflowTestSession.ts` | no existía | reducer puro |

El panel dejó de ser chat + formulario + reporte + historial en un solo archivo. Ahora orquesta componentes y un hook de requests.

## 2. Fronteras

- `WorkflowTestPanel`: layout, CTA, confirmación, ciclo de vida visual.
- `useWorkflowTestRunner`: requests, token de operación, save-before-run, doble submit, historial.
- `workflowTestSession`: reducer y transiciones puras.
- `workflowTestPresentation`: etiquetas, requested/effective, capped, efectos, estado humano.
- `WorkflowTestResult`: Respuesta, Recorrido, Verificación y detalles.
- `WorkflowTestTrace`: reutiliza `WorkflowRunInspector`; no hay segundo motor visual.
- `WorkflowTestSetup`: modo, escenario, composer, readiness y previsión.

## 3. Estado explícito

```ts
view: setup | result
operation: idle | saving | preparing | executing | loading_result | completed | failed
requestedLevel: preview | simulation | sandbox | provider
effectiveLevel?: preview | simulation | sandbox | provider
runKind: test_report | execution_run
resultCode?: string
providerVerified: boolean // solo backend
activeRunId?: string
selectedPane: answer | path | verification
operationId: number
```

## 4. Reglas de concurrencia

- `operationRef` invalida respuestas tardías.
- `identityRef` asocia cada request a organización y workflow.
- `busyRef` bloquea doble submit de forma síncrona.
- Cambio de workflow resetea estado y overlay.
- Save-before-run falla y bloquea `/test` y `/run`.
- `loadRuns` es refresco de fondo; no mantiene el CTA bloqueado.
- `onRun(null)` al iniciar una operación evita overlay viejo.
- `onRan` no remonta el panel.

## 5. Run durable

`POST /run` tiene dos envoltorios según el flujo:

```ts
// Run simple
{ run_id: "..." }
// Run durable (aprobación, wait_event)
{ run: { run_id: "..." }, instance_id: "..." }
```

`useWorkflowTestRunner` acepta ambos. Si el backend envuelve el run y la UI solo leyera `run_id` raíz, pediría `/runs/undefined` y el backend devolvería `500 INTERNAL_ERROR`. El caso está cubierto por test unitario.

## 6. Montaje

- `useMediaQuery` decide un solo panel: aside en desktop, drawer en móvil.
- `?panel=test` sigue abriendo el drawer en móvil.
- El drawer usa `keepMounted`: conserva resultado al cerrar y reabrir. La apertura se difiere al siguiente tick para no montar el overlay dentro del click del botón.
- No hay doble instancia ejecutando.

## 7. Compatibilidad

- Props de `WorkflowTestPanel` intactas.
- `normalizeTestPayload` y `answerFromSteps` intactos.
- `/test` y `/run` intactos.
- `onRun`, `onSelectNode`, `onRan`, `onSaveBeforeRun`, `embedded`, `graph`, `issues`, `effectLabels` intactos.
- Test IDs principales conservados; los tests se migraron deliberadamente.

## 8. Pruebas

- 27 tests del panel.
- 20 tests de reducer/presentación.
- 1 test del inspector.
- E2E de workflow studio 2/2.
- E2E de drawer, modos, aprobación, wait y efecto real.
- Captura visual y axe del panel.
