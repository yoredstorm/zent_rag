# P18.4 — Verificación ejecutada

- Fecha: 2026-10-30
- Rama: `p18.4-workflow-test-ux`
- Baseline: `bd142c480219eac56df020ca5a8642d513977fd2`

## 1. Pruebas unitarias y de contrato

| Comando | Resultado |
|---|---|
| `npm --prefix portal run typecheck` | PASS local |
| `npm --prefix portal run lint` (archivos tocados) | 0 errores; 2 warnings preexistentes en `Badge` y `WorkflowStudio` |
| `npm --prefix portal run test -- src/components/workflowStudio/WorkflowTestPanel.test.tsx` | 27/27 PASS |
| `npm --prefix portal run test -- src/components/WorkflowRunInspector.test.tsx` | 1/1 PASS |
| `npm --prefix portal run test -- src/components/workflowStudio/workflowTestSession.test.ts src/components/workflowStudio/workflowTestPresentation.test.ts` | 20/20 PASS |
| `uv run pytest tests/test_workflow_test_studio.py tests/test_workflow_test_report.py -q` | 10/10 PASS |
| `npm --prefix portal run build` | PASS |
| `npx playwright test e2e/workflows.spec.ts` contra `vite preview` real | 2/2 PASS |
| `npx playwright test e2e/p18-4-visual.spec.ts` con `E2E_VISUAL=1` | 1/1 PASS; axe del panel sin serious/critical |
| `axe-core` sobre el panel en 1440 setup/result y 390 setup | PASS acotado |

La suite completa del portal se intentó de nuevo con `--maxWorkers=2`, pero el reinicio del entorno la canceló antes de terminar. Se conserva el resultado de la primera pasada: 619 PASS y 22 errores de shutdown de workers. `NOT_CLEAN`; no se declara verde.

## 2. E2E real

Entorno: API y Postgres/Redis/Qdrant locales; portal servido con `vite preview`, no dev server. Tenant demo.

| Escenario | Comando | Resultado |
|---|---|---|
| Crear workflow, armar canvas, probar con agente, abrir API/Avanzado | `e2e/workflows.spec.ts` | 2/2 PASS |
| Captura visual setup/resultado 1440, 820, 390 | `E2E_VISUAL=1 e2e/p18-4-visual.spec.ts` | 1/1 PASS |
| Drawer móvil conserva resultado al cerrar y reabrir | `E2E_DOCK=1 e2e/p18-4-dock.spec.ts` | 1/1 PASS |
| Preview y proveedor capeado no llaman `/run`; cancelar confirmación no ejecuta | `E2E_MODES=1 e2e/p18-4-modes.spec.ts` | 1/1 PASS |
| `human_approval` real queda en “Esperando aprobación” | `E2E_APPROVAL=1 e2e/p18-4-approval.spec.ts` | 1/1 PASS |
| `wait_event` real queda en “Esperando mensaje”; señal reanuda la instancia | `E2E_WAIT=1 e2e/p18-4-wait.spec.ts` | 1/1 PASS |
| `notify` real solo corre tras confirmar `EJECUTAR`; efecto verificado | `E2E_EFFECTS=1 e2e/p18-4-effects.spec.ts` | 1/1 PASS |

Hallazgo corregido: el backend devuelve el run durable envuelto (`{ run: { run_id } }`) y el hook solo leía `run_id` en la raíz. Eso producía `GET /runs/undefined` y un `INTERNAL_ERROR` en la UI. Ahora acepta ambas formas y tiene test unitario.

## 3. Capturas revisadas

Directorio: `docs/architecture/workflow-test-ux-p18-4/captures/`

| Archivo | Estado |
|---|---|
| `1440-setup-dark.png` | Revisada |
| `1440-result-dark.png` | Revisada |
| `1440-provider-capped-dark.png` | Revisada |
| `1440-setup-light.png` | Revisada |
| `1440-result-light.png` | Revisada |
| `820-setup-dark.png` | Revisada |
| `390-setup-dark.png` | Revisada |
| `390-result-dark.png` | Revisada |

Observaciones de revisión:

- El panel desktop mostraba el CTA cortado porque el contenedor raíz usaba una altura fija que no descontaba el topbar. Se cambió a `flex-1 min-h-0` y se verificó de nuevo.
- El footer compartido aparecía también en Resultado, duplicando CTA con “Repetir prueba”. Ahora solo se muestra en Probar.
- El shell `app-main` ahora usa `h-[100dvh] overflow-hidden` solo en full-bleed; el panel y su CTA caben en 900 px.
- 390 px mantiene drawer inferior, CTA visible y scroll interno.
- Light/dark se capturó con `zent_theme` explícito.
- Las capturas no incluyen WAIT, aprobación, error de nodo, `workflow_error` ni resultado vacío. Esos estados se cubren con E2E de texto, no con imagen.

## 4. Lo que no se ejecutó

- `axe-core` de página completa: detectó `aria-prohibited-attr` en puertos del canvas, fuera del panel. El panel se auditó con scope y pasó.
- Navegación completa por teclado con lector de pantalla: `NOT_RUN`; solo se validó axe y semántica de tabs/radios.
- Cinco participantes no técnicos: `NOT_RUN`.
- Proveedor real: no disponible; el reporte real devolvió `effective_level=simulation`, `provider_verified=false`, `UNVERIFIED`, `capped_reason=provider_adapter_unavailable`.
- CI remoto: `NOT_VERIFIED`; no hay `gh` en el entorno.

## 5. Evidencia de endpoints

`POST /test` con `requested_level=provider` devolvió, en el entorno local:

```json
{
  "requested_level": "provider",
  "effective_level": "simulation",
  "capped_reason": "provider_adapter_unavailable",
  "provider_verified": false,
  "result": "UNVERIFIED"
}
```

La UI muestra ambos niveles y no emite sello de proveedor.

`POST /run` real se ejecutó en tres escenarios: aprobación humana, espera con señal y notificación in-app. En los tres la UI exigió `EJECUTAR`; la cancelación no llamó a `/run`. El run durable se resuelve tanto si el backend devuelve `run_id` en la raíz como si lo envuelve en `run`.

## 6. Riesgos abiertos

1. P18.3 `resolve_agent` sigue sustituyendo `tools=[]` certificadas por herramientas vivas. P0 independiente.
2. `GET /runs/{id}` y `/sample-outputs` no filtran por workspace. Deuda de backend.
3. El historial no compara el hash del grafo actual; muestra banner de resultado histórico.
4. La suite completa tiene errores de workers en la primera pasada; no se declara verde hasta repetirla con recursos controlados.
5. La evaluación humana y la navegación con lector de pantalla quedan `NOT_RUN`.
6. El E2E de efectos usa notificación in-app local; no certifica efectos externos, email ni webhooks.
