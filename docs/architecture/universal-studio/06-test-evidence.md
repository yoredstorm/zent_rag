# 06 — Evidencia de pruebas (baseline y límites)

> **Regla:** este documento solo afirma lo que se ejecutó. Un `skip`, un timeout
> o un test no ejecutado **no** cuenta como PASS. Las pruebas con mocks, sandbox
> y proveedor real se separan explícitamente.
>
> **Actualización posterior:** la remediación del planner real y la evidencia
> nueva están en
> [`../certification/universal-studio-remediation.md`](../certification/universal-studio-remediation.md).
> Este documento conserva el baseline de la auditoría Prompt 00.

## 1. Entorno de ejecución

| Dato | Valor |
|---|---|
| Fecha | 2026-10-21 |
| HEAD | `c65dbdf729327eaf54fd74a9326cf5ae328dc0be` |
| OS | Windows (PowerShell) |
| Python | 3.13.7 (`.venv`) |
| Node | 22.22.1 |
| Postgres / Redis / Qdrant | Contenedores locales arriba (`docker ps`) |
| LLM real | Gateway LiteLLM configurado en `.env` (credenciales presentes) |
| Sandbox de pagos | **No ejecutado** (sin credenciales sandbox externas en este entorno) |

## 2. Resumen

| Suite | Tipo | Resultado | Duración |
|---|---|---|---|
| `tests/test_architecture.py` | unitario/arquitectura | **6 passed** | 24.42s |
| `tests/test_workflow_architect.py`, `test_workflow_semantic_v2.py`, `test_workflow_simulation.py`, `test_workflow_design_sessions.py`, `test_workflow_graph.py`, `test_capability_registry.py` | integración local, LLM mockeado | **81 passed** | 735.22s |
| `tests/test_workflow_planner_agentic.py`, `test_workflow_architect_capability_call.py`, `test_workflow_readiness.py`, `test_workflow_patches.py` | integración local, LLM mockeado | **44 passed** | 185.15s |
| `tests/test_agent_api.py`, `test_agent_versions.py`, `test_agent_readiness.py`, `test_agent_budget_closure.py` | integración local, LLM mockeado | **54 passed** | 322.19s |
| `npm run typecheck` | portal | **OK** | — |
| `vitest run src/components/workflowStudio ...` | portal unitario | **73 passed / 16 files** | 169.84s |
| `ruff check src tests` | lint | **OK** | — |
| `pytest tests/certification/workflows` | certificación local | **TIMEOUT ambiental** tras 7 tests; no verde | — |
| `pytest tests/certification/workflows/test_tenant_isolation.py` | certificación local | **5 passed** | 527.95s |
| `pytest tests/certification/workflows/test_signals.py` | certificación local | **TIMEOUT** | — |
| `pytest tests/certification/ai/test_real_llm_gold.py` (`RAG_CERT_REAL_LLM=1`) | **proveedor real** | **FAILED** | 420.71s |

## 3. Comandos y resultados

### 3.1 Arquitectura

```powershell
.venv/Scripts/python.exe -m pytest tests/test_architecture.py -q --no-header -p no:cacheprovider
```

Resultado: `6 passed, 3 warnings in 24.42s`.

Warnings esperados de configuración de desarrollo (password default, session
key default, `RUNTIME_ANSWER_GATE`). No son fallos.

### 3.2 Núcleo del Studio

```powershell
.venv/Scripts/python.exe -m pytest `
  tests/test_workflow_architect.py `
  tests/test_workflow_semantic_v2.py `
  tests/test_workflow_simulation.py `
  tests/test_workflow_design_sessions.py `
  tests/test_workflow_graph.py `
  tests/test_capability_registry.py `
  -q --no-header -p no:cacheprovider
```

Resultado: `81 passed, 3 warnings in 735.22s (0:12:15)`.

Cubre: plan semántico, compilación, validación, WAIT/LOOP/estado, simulación,
sesiones, grafo y registry. **No** cubre el gate de publicación ni el runtime
durable desde schedule/webhook.

### 3.3 Planner y readiness

```powershell
.venv/Scripts/python.exe -m pytest `
  tests/test_workflow_planner_agentic.py `
  tests/test_workflow_architect_capability_call.py `
  tests/test_workflow_readiness.py `
  tests/test_workflow_patches.py `
  -q --no-header -p no:cacheprovider
```

Resultado: `44 passed, 3 warnings in 185.15s (0:03:05)`.

### 3.4 Agentes

```powershell
.venv/Scripts/python.exe -m pytest `
  tests/test_agent_api.py `
  tests/test_agent_versions.py `
  tests/test_agent_readiness.py `
  tests/test_agent_budget_closure.py `
  -q --no-header -p no:cacheprovider
```

Resultado: `54 passed, 3 warnings in 322.19s (0:05:22)`.

### 3.5 Portal

```powershell
cd portal
npm run typecheck
npx vitest run src/components/workflowStudio src/components/WorkflowApprovalPanel.test.tsx src/components/WorkflowRunInspector.test.tsx src/pages/marketplace/MarketplacePage.test.tsx
```

Resultado:

- `tsc --noEmit`: sin errores.
- `Test Files 16 passed (16)`, `Tests 73 passed (73)`, `169.84s`.

### 3.6 Lint

```powershell
.venv/Scripts/python.exe -m ruff check src tests
```

Resultado: `All checks passed!`.

## 4. Certificación de workflows (local)

### 4.1 Suite completa

```powershell
.venv/Scripts/python.exe -m pytest tests/certification/workflows -q --no-header -p no:cacheprovider
```

Resultado: **timeout ambiental** después de 7 tests. El log
`artifacts/universal-studio-baseline-cert.log` muestra el stack de
`pytest-timeout` en `asyncio/windows_events.py`, no un fallo de aserción.

**No se declara esta suite verde.** El informe anterior ya había reportado un
timeout ambiental similar.

### 4.2 Aislamiento de tenant (archivo separado)

```powershell
.venv/Scripts/python.exe -m pytest tests/certification/workflows/test_tenant_isolation.py -q --no-header -p no:cacheprovider
```

Resultado: `5 passed, 3 warnings in 527.95s (0:08:47)`.

Cubre:

- cross-tenant no lee/reanuda instancia;
- catálogo/órdenes aislados;
- webhook resuelve tenant propio;
- firma de tenant B no paga checkout de A;
- bindings tenant-scoped.

**No cubre workspace isolation.**

### 4.3 Señales

```powershell
.venv/Scripts/python.exe -m pytest tests/certification/workflows/test_signals.py -q --no-header -p no:cacheprovider
```

Resultado: **timeout**. No se declara PASS en este HEAD.

## 5. Proveedor real — Gold con LLM

```powershell
$env:RAG_CERT_REAL_LLM="1"
.venv/Scripts/python.exe -m pytest tests/certification/ai/test_real_llm_gold.py -q --no-header -p no:cacheprovider
```

Resultado: **FAILED** en `420.71s`.

Artefacto del run en HEAD: `artifacts/certification/ai/gold-real-llm.c65dbdf.json`.
El artefacto histórico `artifacts/certification/ai/gold-real-llm.json` se
conserva sin sobrescribir. `gold-real-llm.summary.json` sigue siendo el resumen
del run anterior (`a826d8c`); **no** se usó como evidencia de este HEAD.

Datos del artefacto:

| Campo | Valor |
|---|---|
| `state` | `BLOCKED` |
| `publishable` | `false` |
| `issues` | `planner.invalid_llm_output` |
| `llm_calls` | 9 |
| `tool_calls` | 5 |
| `total_tokens` | 107807 |
| `prompt_tokens` | 64924 |
| `completion_tokens` | 42883 |
| `duration_ms` | 229394 |
| `plan_steps` | 0 |
| `graph` | `false` |

Log: `artifacts/universal-studio-baseline-real-llm.log` contiene
`planner action output invalid` con `content_chars: 0`.

**Lectura:** la creación desde cero con el modelo real sigue bloqueada. No se
puede declarar GO del constructor inteligente ni del Gold conversacional.

## 6. Lo que NO se ejecutó

| Prueba | Estado | Motivo |
|---|---|---|
| Suite completa `tests/` | **NO EJECUTADA** | Tiempo; el baseline focalizado cubre el Studio |
| `tests/certification/restart` con `RAG_CERT_REAL_RESTART=1` | **NO EJECUTADA** | No se repitió en este HEAD |
| Sandbox real Stripe/IZIPAY | **NO EJECUTADO** | Sin credenciales sandbox externas |
| Carga/backpressure | **NO EJECUTADO** | Sin escenario de load en este HEAD |
| Chaos de caída durante reanudación | **NO EJECUTADO** | Sin entorno de chaos |
| Dataset 100 requerimientos | **NO EJECUTADO** | Bloqueado por Gold real |
| E2E Playwright del Studio | **NO EJECUTADO** | No hay servidor e2e levantado en esta fase |
| Worker restart | **NO EJECUTADO** | El reinicio real cubre API, no worker |

## 7. Separación por tipo de prueba

| Tipo | Qué se ejecutó | Qué significa |
|---|---|---|
| **Mock / hermético** | `test_workflow_*`, `test_agent_*`, portal vitest | LLM/proveedores mockeados; DB local real; no prueba calidad del modelo |
| **Sandbox** | Nada | No hay evidencia de proveedor sandbox en este HEAD |
| **Proveedor real** | `test_real_llm_gold.py` | **FAILED**; no hay workflow generado |
| **Carga / caos** | Nada | Sin evidencia |
| **Reinicio real** | Nada en este HEAD | El informe anterior lo certificó en `a826d8c`; no se revalidó |

## 8. Conclusión de evidencia

- El núcleo del Studio tiene una red de pruebas amplia y verde en el camino
  mockeado/integración local.
- El camino real de generación con LLM **sigue fallando**.
- La suite de certificación de workflows **no terminó verde** en este entorno;
  el aislamiento de tenant sí pasó por archivo separado.
- No hay evidencia de sandbox, carga, caos ni worker restart en este HEAD.
- Por tanto: **NO-GO para producción general**; GO condicionado solo para
  staging controlado con workflows existentes y sin creación IA.
