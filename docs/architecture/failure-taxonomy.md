# Failure Taxonomy — clasificación única de fallos

Estado: **implementado (F6, `failure-taxonomy-1`)**. Complementa
`finalization-policy.md`, `run-accounting.md` y `answer_state.py`.

Regla rectora:

> Un fallo se clasifica por lo que FALLÓ, nunca por lo que el usuario ve.
> Prohibido mezclar realidades: provider timeout ≠ evidencia insuficiente;
> permiso denegado ≠ tool fallida; retrieval caído ≠ «no hay información».

---

## 1. Clases

| failure_class | Qué significa |
|---|---|
| `USER_ERROR` | el pedido del usuario no es accionable (vocabulario reservado) |
| `POLICY_BLOCK` | una política/guard bloqueó la acción (allowlist, duplicado) |
| `AUTHORIZATION_ERROR` | falta permiso del caller/agente (RBAC, grants) |
| `AUTHORITY_MISSING` | falta autoridad determinista (no hay sí/no) |
| `EVIDENCE_INSUFFICIENT` | el contenido no alcanza (conclusión, no fallo operativo) |
| `EVIDENCE_CONFLICT` | las fuentes se contradicen (conclusión) |
| `RETRIEVAL_FAILURE` | la búsqueda no llegó a ejecutarse (fallo operativo) |
| `PROVIDER_FAILURE` | el proveedor de modelos falló / circuito abierto |
| `RATE_LIMIT` | cuota o RPM del proveedor |
| `TIMEOUT` | el proveedor/tool agotó el tiempo |
| `BUDGET_EXHAUSTED` | corte por presupuesto (steps/tokens/costo/tiempo) |
| `DEPENDENCY_ERROR` | una dependencia (reglas, tool) falló |
| `INTERNAL_ERROR` | bug o fallo de motor interno |

Cada `FailureInfo` declara además: `reason_code`, `retryable`,
`user_visible`, `operational`.

## 2. API (`src/runtime/failure_taxonomy.py`)

- `classify_reason_code(code)` — `reason-codes-1`.
- `classify_stop_reason(code)` — `run_budget.STOP_REASONS`.
- `classify_answer_state(state)` — `answer_state` (todo el vocabulario).
- `classify_provider_attempt(status)` — status del router (`rate_limited`,
  `timeout`, `circuit_open`, `auth_error`, `provider_error`, `error`).
- `classify_failure(code)` — busca en los vocabularios cerrados.
- Un código desconocido devuelve `None`: es deuda, no una clasificación
  inventada. `READY`, `NEED_DRAFT`, `TOOL_AUTHORIZED`, `RETRIEVAL_ALLOWED`,
  `READY_TO_FINALIZE`, `ANALYSIS_INCOMPLETE`, `REASONING_INCOMPLETE` y
  `TERMINATION_SATISFIED` son señales de control, no fallos.

## 3. Contrato CI de reason codes

`tests/test_failure_taxonomy.py::TestContratoDeReasonCodesEnElRuntime` escanea
`src/runtime/**` y `src/agents/runtime/**` buscando literales emitidos como
`reason_code` / `"reason_code": "X"`; si el código no pertenece a
`reason-codes-1`, CI falla. Agregar un código es un cambio de contrato: se
declara en `src/runtime/reason_codes.py` (y se bumpa la versión si aplica).

También verifica que el catálogo no tenga strings paralelos (dos formas del
mismo concepto, p. ej. mayúsculas/minúsculas).

## 4. Cobertura verificada

- `run_budget.STOP_REASONS` completo (STEP/TOOL/TOKEN/COST/TIME,
  PROVIDER_RATE_LIMIT, PROVIDER_FAILURE).
- Todo `ANSWER_STATE_*` está clasificado o es `DERIVED_RESULT` (éxito).
- No-mezcla: retrieval caído vs evidencia insuficiente; permiso denegado vs
  tool fallida; timeout de provider vs evidencia; rate limit vs fallo de
  provider; autoridad ausente vs evidencia.

## 5. Deuda

- El vocabulario de `reason_codes` del motor de decisión RAG
  (`decision.reason_codes`, p. ej. `EXECUTION_ERROR`) vive fuera de
  `reason-codes-1`: su unificación es un pase propio (P2).
- `USER_ERROR` queda reservado: hoy ningún emisor del runtime lo produce.
