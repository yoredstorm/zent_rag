# Run Accounting — un writer, un ledger

Estado: **contabilidad unificada del camino RAG sobre `RunBudgetLedger`
(2026-10-11)**. Complementa `finalization-policy.md` (budget y stop reasons) y
`agent-run-state.md`.

Regla rectora:

> Un run tiene UN ledger y UN writer. El evento de uso LEE; nunca recalcula.

---

## 1. Componentes

| Componente | Rol |
|---|---|
| `RunBudgetLedger` (`run_budget.py`) | Vista del presupuesto sobre los campos reales del result (`prompt_tokens`, `completion_tokens`, `total_tokens`, `cost`, `llm_calls`, `logical_steps`, `tool_calls`, `embedding_tokens`). No lleva contadores paralelos. |
| `run_accounting.py` | Único writer: `record_llm_call`, `record_judge_call`, `record_search_call`, `record_embedding_call`, `record_rerank_call`, `record_charge`, `record_jev_observation`, `account_rag_result`. |
| `account_rag_result` | Contabilidad del camino RAG (agente ya contaba por `record_llm_call`): LLM + embedding + rerank + charge + JEV. Idempotente por run. |
| Evento de uso (agente y RAG) | Construido DESDE el ledger (`_build_usage_event` en el orquestador; el agente lee los mismos campos). |

## 2. Líneas del ledger

| Línea | type | Tokens | Costo | Nota |
|---|---|---|---|---|
| LLM | `llm` | prompt/completion/total | pricing table; `cost_status=unknown` si no hay tarifa | provider cost si el provider lo reporta |
| Embeddings | `embedding` | tokens | tarifa de embeddings; sin tarifa → unknown, jamás 0 disfrazado | query embedding ~4 chars/token, explícito |
| Rerank | `rerank` | — | `cost_status=unknown` (no hay tarifa por rerank) | línea explícita, nunca invento |
| Cargo externo | `charge` | — | reportado por el subsistema (p. ej. DAG cognitivo) | no se estima |
| JEV | `jev_usage` | input+output | solo si el proveedor lo reportó | `billed_separately=True`: el juez factura por su propio usage event (no hay doble conteo) |
| Búsqueda | `tool_call` | — | — | `search_knowledge` del fast path |

## 3. Política de costo desconocido

- Sin tarifa conocida: `cost_status="unknown"` y `cost_reason` con la causa.
  El costo NO se inventa y `unknown != 0` en las métricas.
- `resolve_call_cost`: provider cost > tabla de precios > unknown.
- Embeddings: `_embedding_cost` consulta la tarifa de embeddings de la misma
  tabla; sin ella → unknown.

## 4. Invariante

```text
ledger.consumed_total_tokens == usage_event.total_tokens
ledger.consumed_cost_usd   == usage_event.estimated_cost
```

con tolerancia únicamente donde `cost_status=unknown` esté explícito.
Tests: `tests/test_run_accounting_rag.py` (ledger == event, costo == fórmula
histórica, idempotencia, tarifa desconocida, líneas de embedding/rerank/JEV).

## 5. Provider failover y retries

- Retries de embeddings: `tests/test_llm_embed_retry.py` (429 → retry → éxito;
  presupuesto corta; no-transitorio no reintenta).
- Router no-streaming: `tests/test_llm_router.py` (retry transitorio, fallback,
  cuota directa al fallback, breaker por modelo).
- **Intentos visibles (F5)**: `generate_routed` registra cada intento en
  `LLMResponse.attempts` (provider, model, status, retry, fallback, latency_ms,
  error) y `record_llm_call` los materializa como líneas `provider_attempt`
  (sin tokens ni costo: intento no facturado) + métrica
  `zent_provider_attempts_total{provider,status,retry}`. Si todos los
  candidatos fallan, el error propaga `llm_attempts`. Test:
  `tests/test_provider_attempts.py` (429 → 429 → success con 2 líneas
  `provider_attempt` y 1 `llm`; ledger == éxito; error no reintentable va
  directo al fallback).
- Streaming: `tests/test_llm_stream_fallback.py` (429/timeout/circuit antes del
  primer token → fallback; tras emitir → error; todos fallan → propaga;
  estabilidad ×100). Los intentos del stream aún no viajan en el payload
  `done` (deuda P2: la línea `provider_attempt` cubre hoy el camino
  no-streaming y el timeout de la ruta narrativa).
- Regla: el intento fallido se registra con su modelo/proveedor; el failover no
  esconde el primer intento.

## 6. Deuda conocida

- El camino RAG no factura `request_cost` cuando el LLM no reporta tokens
  (antes se cobraba una vez por corrida con `estimate_cost` combinado). El
  cargo por request pertenece a la llamada LLM; sin llamada no se cobra.
- La tarifa del juez (JEV) sigue pendiente: tokens y costo reportado viajan,
  pero no se inventa precio.
