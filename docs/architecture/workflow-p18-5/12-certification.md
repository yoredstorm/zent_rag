# P18.5-12 — E2E adversariales de seguridad y efectividad

## Identidad

- Rama: `fix/p18-5-security-execution-live-studio`
- Commits: `e23b2ed`, `732e25e`, `7730264`
- Baseline: `e6c42c2579df0e997ef2a0a0d0916f05dc735bef`
- Entorno: Windows, Python 3.11.16, Postgres/Redis/Qdrant Docker locales, API
  fuente en `127.0.0.1:8001`, Chromium Playwright, datos sintéticos.

## Suites backend ejecutadas

| Suite | Comando | Resultado |
|---|---|---|
| Snapshot de agente | `uv run pytest tests/test_p18_5_agent_snapshot_security.py -q` | 6 passed |
| Workspace | `uv run pytest tests/test_p18_5_workspace_authorization.py -q` | 2 passed, 1 skipped |
| Aprobaciones | `uv run pytest tests/test_p18_5_verified_approval.py -q` | 4 passed |
| Revocaciones | `uv run pytest tests/test_p18_5_revocation_resume.py -q` | 3 passed |
| Idempotencia | `uv run pytest tests/test_p18_5_effect_idempotency.py -q` | 2 passed |
| Timeline | `uv run pytest tests/test_p18_5_execution_timeline.py -q` | 2 passed |
| Payload | `uv run pytest tests/test_p18_5_payload_contract.py -q` | 2 passed |
| Regresión workflows | 21 archivos seleccionados | 150 passed, 1 skipped |

## E2E ejecutado

```text
$env:E2E_WAIT=1; $env:E2E_PORT=8091; $env:VITE_API_PROXY=http://127.0.0.1:8001
npx playwright test e2e/p18-5-live-resume.spec.ts
1 passed (1.6m)
```

Valida WAIT → señal → resume → COMPLETED sin refrescar, con un único POST /run.

Regresión P18.4 ejecutada contra la misma API fuente:

```text
npx playwright test e2e/p18-4-wait.spec.ts      # 1 passed
npx playwright test e2e/p18-4-approval.spec.ts  # 1 passed
npx playwright test e2e/p18-4-effects.spec.ts   # 1 passed
```

La prueba de effects usó un efecto interno de notificación, no un proveedor
externo productivo.

## E2E adversariales NO ejecutados

| Spec requerido | Estado | Motivo |
|---|---|---|
| `p18-5-approval-live.spec.ts` | NOT_RUN | El flujo de aprobación tiene cobertura backend + UI de la suite existente; no se ejecutó E2E dedicado con aprobación humana en navegador en esta sesión. |
| `p18-5-replay-safe.spec.ts` | NOT_RUN | La idempotencia se probó a nivel API; no hay E2E de doble pestaña/reload. |
| `p18-5-workspace.spec.ts` | NOT_RUN | El aislamiento se probó a nivel API; no se ejecutó cambio de workspace en navegador. |
| `p18-5-history-hash.spec.ts` | NOT_RUN | Comparación cubierta por unit test; no hay E2E de historial. |
| `p18-5-accessibility.spec.ts` | NOT_RUN | Axe/teclado/lector de pantalla no se ejecutaron. |

No se declara PASS de estas suites. No se ocultaron detrás de flags: los specs
no existen todavía y se listan como deuda bloqueante para P18.5-12.

## Efectos externos

- Cero cobros, correos de clientes o webhooks productivos.
- No se certificó ningún proveedor real; `provider_verified=false` en todos los
  runs de prueba.
- Las pruebas de aprobación/denegación confirman que el nodo no se ejecutó, pero
  no sustituyen una prueba de sandbox de proveedor.

## Criterio de gate

- P0 de código (snapshot, workspace, aprobación, revocación, idempotencia local):
  cerrados con pruebas.
- E2E adversarial completo y proveedor sandbox: **NOT_RUN**.
- Resultado del gate P18.5-12: **NOT_RUN**.

## Decisión

**NOT_RUN** para certificación adversarial completa. No habilitar piloto con
clientes ni operaciones irreversibles reales.
