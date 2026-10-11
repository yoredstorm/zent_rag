# Finalization Policy — jerarquía de autoridad y política de cierre

Estado: **P2, P5, P8 completos; P3, P4, P6 entregados como contratos + tests;
P7, P9, P10 como roadmap especificado**. Complementa
`agent-run-state.md` (estado canónico y fases).

Regla rectora:

> JEV puede juzgar. El LLM puede proponer. Los gates pueden recomendar.
> Una decisión determinista autoritativa NO se anula con generación narrativa.

---

## 1. Jerarquía de autoridad

```
SAFETY          autorización de tools / allowlist / denegaciones
DETERMINISTIC   DecisionEnvelope / autoridad determinista
EVIDENCE        suficiencia documental / fallo operativo de retrieval
REASONING       completitud del análisis
TERMINATION     la petición original quedó satisfecha
GENERATION      borrador disponible
RESOURCE        cortes por presupuesto (degradado con evidencia)
```

Resolución única: `src/runtime/finalization_policy.py`

```python
FinalizationDecision = {
  action: CONTINUE | RETRIEVE_MORE | USE_TOOL | FINALIZE | ABSTAIN | BLOCK | UNDETERMINED,
  reason_code, authority, limited,
  signals, signals_ignored, conflicts, missing_requirements,
}
```

Reglas duras implementadas:

- JEV solo puede pedir cautela: un veredicto negativo es **única señal** no
  abstiene ni bloquea; se registra en `signals_ignored`.
- Una aprobación JEV nunca habilita respuesta sin evidencia
  (`jev_positive_without_evidence`).
- `RETRIEVAL_UNAVAILABLE` es fallo operativo: jamás se reporta como
  `EVIDENCE_INSUFFICIENT`.
- Consulta ejecutable sin autoridad determinista ⇒ `UNDETERMINED`.
- Autoridad presente ⇒ `FINALIZE` aunque JEV dude o el análisis esté incompleto
  (se registran ambas señales ignoradas).

## 2. Componentes y autoridad

| Componente | Entrada | Salida | Autoridad | ¿Bloquea? | ¿Modifica decisión? |
|---|---|---|---|---|---|
| Safety / allowlist / RBAC | tool + ctx | permitido/denegado | SAFETY | sí (no ejecuta) | no |
| `deterministic_authority.prepare_derived_authority` | query + evidencia | `DerivedPreparationResult` (envelope, claims) | DETERMINISTIC | no (provee) | sí: fija la decisión |
| `decision_envelope.finalize_authoritative_answer` | borrador + envelope + claims | texto final inmutable | DETERMINISTIC | sí (bloquea binario libre) | sí: corrige/impone |
| `derived_guard` | claims deterministas | override/contradicción | DETERMINISTIC | sí (override) | sí |
| `evidence` (registry/selection/sufficiency) | chunks/tools | selección + acción (`generate/retrieve_more/abstain`) | EVIDENCE | recomienda | no decide sola |
| `reasoning_step` | query + plan | `analysis_complete`, `blocks_early_answer` | REASONING | sí (early answer) | no |
| `termination` | respuestas JEV del paso | `{stop}` | TERMINATION | no | sí: corta el loop |
| `answer_gate` | borrador + evidencia | veredicto `approve/revise/retrieve/abstain/limits` | mezzanine (JEV) | sí (recomienda) | sí: gatea el borrador |
| `finalization_policy` (este pase) | `AgentRunState` + señales | `FinalizationDecision` | resuelve quién manda | sí (modo estricto) | sí (modo estricto) |
| `budget` (ledger + stop reasons) | consumo | corte/degradación | RESOURCE | sí | sí (cierre) |
| `final_authority_lock` | texto + envelope | texto consistente | DETERMINISTIC | sí (reconstruye) | sí |
| JEV (turn/gate/step/preflight) | estado del run | veredictos | observacional/mezzanine | solo vía gates | no directo |
| Narrative coverage | cobertura | ¿buscar más? | EVIDENCE/NARRATIVE | recomienda | no |
| Tool routing | estado del paso | subset de tools | SAFETY/EFFICIENCY | recomienda | sí (prompt) |

## 3. Guardas de transición (P3)

`src/runtime/run_guards.py`: tabla `(fase, evento, guards) → (fase, reason)`.
El loop conserva autonomía dentro de transiciones permitidas.

| Fase | Evento | Guard | Destino | reason_code |
|---|---|---|---|---|
| cualquier | cualquier | fase terminal | misma | `TERMINAL_NO_TRANSITIONS` |
| REASONING | REQUEST_TOOL | !autorizado | REASONING | `TOOL_NOT_AUTHORIZED` |
| REASONING | REQUEST_TOOL | duplicado | REASONING | `DUPLICATE_TOOL_CALL` |
| REASONING | REQUEST_TOOL | budget agotado | READY_TO_FINALIZE | `BUDGET_EXHAUSTED` |
| REASONING | REQUEST_TOOL | ok | ACTING | `TOOL_AUTHORIZED` |
| REASONING | REQUEST_RETRIEVAL | budget agotado | READY_TO_FINALIZE | `BUDGET_EXHAUSTED` |
| REASONING | REQUEST_RETRIEVAL | ok | RETRIEVING | `RETRIEVAL_ALLOWED` |
| READY_TO_FINALIZE | REQUEST_FINALIZE | ejecutable sin autoridad | UNDETERMINED | `AUTHORITY_MISSING_FOR_EXECUTABLE` |
| READY_TO_FINALIZE | REQUEST_FINALIZE | análisis incompleto | REASONING | `ANALYSIS_INCOMPLETE` |
| READY_TO_FINALIZE | REQUEST_FINALIZE | budget + evidencia | FINALIZED | `BUDGET_EXHAUSTED_WITH_EVIDENCE` |
| ACTING | OBSERVE_TOOL_RESULT | fallo transitorio | REASONING | `TOOL_RETRY_ALLOWED` |
| ACTING | OBSERVE_TOOL_RESULT | fallo permanente | REASONING | `TOOL_FAILED_PERMANENT_NO_RETRY` |

Tests parametrizados cubren: final nunca pasa a tool/retrieval, tool sin
autorización no ejecuta, budget agotado no gasta, ejecutable sin authority no
finaliza binario, análisis incompleto no finaliza, retry transitorio sí,
permanente no, duplicado bloqueado en el run, y el mismo call en un run nuevo
se permite (`LoopGuard` por run).

## 4. JEV decision value (P4)

`src/runtime/jev_value.py`: clasifica desde los `steps` (sin tocar decisiones):

- `CONFIRMED`: el veredicto coincide con la señal determinista canónica.
- `PREVENTED`: JEV fue más estricto (evitó pasar).
- `CHANGED`: difiere menos estricto (movió la decisión).
- `SKIPPED`: la fase no llamó JEV (passthrough / sin tools).
- `UNCLASSIFIED`: sin señal determinista comparable en el run.

Reporte: `summarize_jev_value(steps)` → llamadas por fase, valores,
`redundant_rate` (confirmados / comparables). Se publica en el flow de agente
(`flow["jev_value"]`) y sobre eso se deciden skips conservadores (los ya
existentes: reglas-first en turn intent, batching por paso, bypass fail-closed
en ejecutables, shadow/canary).

## 5. Budget: razones precisas de corte (P5)

`run_budget.py`: `STEP_BUDGET`, `TOOL_BUDGET`, `TOKEN_BUDGET`,
`COST_BUDGET`, `TIME_BUDGET`, `PROVIDER_RATE_LIMIT`, `PROVIDER_FAILURE`.
El estado canónico expone `budget.stop_reason` (y `stop_reason` en la
proyección pública). «¿Por qué se detuvo este run?» tiene una única respuesta.

Correcciones incluidas:

- `log_inference` ya no fabrica `prompt_tokens=total, completion_tokens=total//2`
  (sumaba 1.5×); usa los tokens reales del ledger.
- Cada corte (steps, tools, timeout, tokens, costo, call_plan agotado, router
  caído, circuito abierto, rate limit de deployment) marca su razón exacta.

Diferencias estructurales explícitas: `max_tokens_per_response` (tope de una
llamada) ≠ `max_total_tokens_per_run` (ledger); `provider RPM`/rate limit del
deployment ≠ límite de tool calls del agente.

## 6. Context Envelope (P6)

`src/runtime/context_envelope.py`: envuelve por procedencia sin copiar contenido.

| Origen | Scope | Trust |
|---|---|---|
| USER_TURN | RUN | SUPPORTING |
| CONVERSATION | CONVERSATION | SUPPORTING |
| MEMORY | USER | SUPPORTING |
| COMPANY_CONTEXT | TENANT | SUPPORTING |
| EVIDENCE | RUN | AUTHORITATIVE |
| WORKFLOW | RUN | SUPPORTING |
| TOOL_OBSERVATION | RUN | UNTRUSTED |

`isolation_key() = tenant:conversation` (la conversación es parte real del
aislamiento). Reglas verificadas en tests: memory no es evidence, escenario de
usuario no es evidencia documental, company context no es autoritativo,
workflow es input del run, tools son untrusted.

Adopción: el envelope se publica al cierre del run en
`result.run_state.context` (tenant, conversación, evidencia seleccionada, tools
usadas, claves de workflow). El wiring del prompt assembly es incremental
(roadmap P10-7).

## 7. Roadmap P7 / P9 / P10

**P7 — Execution Story 2 vistas** (implementado como contrato; migración de
portal pendiente):

- `src/runtime/story_view.py`: `business_steps(steps)` con
  `{type, status, reason_code, facts}` (sin provider/tokens/latencia/checks) y
  `technical_steps(steps)` con payloads y contenido truncado.
- Diccionario inicial de reason codes: `EVIDENCE_COMPLETE/INCOMPLETE`,
  `ANSWER_APPROVED/LIMITED/ABSTAINED`, `AUTHORITY_*`, `CONSISTENCY_VIOLATIONS`,
  `TOOL_EXECUTED/FAILED`, `REQUEST_SATISFIED`, etc.
- Prohibido CoT: solo estados, decisiones, hechos, evidencia, reglas,
  eventos, reason codes, resultados.

**P9 — AgentRuntime legible**: extracciones chicas hechas en este programa
(`_record_finalization_decision`, `_mark_budget_stop`, `_publish_context_envelope`,
guards como tabla). Pendiente con criterio: extraer el finalizador y el
narrative fast path (~800 líneas) a módulos con parámetros explícitos, sin
reescribir el ReAct.

**P10 — Auditoría principal**: `docs/architecture/principal-audit.md` con el
TOP 10 (contabilidad partida, adopción del resolver, circuit breaker por
tenant, `adaptive` storage, skips JEV, extracción del runtime, prompt desde
ContextEnvelope, story para humanos, aislamiento por conversación, matriz
adversarial) y roadmap NOW/NEXT/LATER.

## 7b. Observabilidad de la resolución en el flow

- `flow["jev_value"]` (agente): llamadas JEV por fase + `redundant_rate`.
- `state.decisions.finalization`: resolución de autoridad del cierre.
- `state.context`: sobre de procedencia (tenant/conversación/trust).

## 8. Observabilidad de la resolución

Cada cierre guarda en `result.run_state.decisions.finalization`:

```json
{
  "action": "FINALIZE",
  "reason_code": "DETERMINISTIC_AUTHORITY",
  "authority": "DETERMINISTIC",
  "signals": {"evidence": "complete", "reasoning": "complete",
               "authority": "authoritative", "budget": "ok",
               "jev": "uncertain", "termination": "not_requested",
               "draft": "available", "retrieval": "exhausted", "tool": "not_requested"},
  "signals_ignored": ["jev_only_negative_signal"],
  "conflicts": [],
  "missing_requirements": [],
  "limited": false
}
```

- Step `finalization_policy` solo cuando la resolución NO coincide con la fase
  terminal (sin ruido en runs normales).
- `RUNTIME_RUN_STATE_STRICT=on`: si la resolución dice `UNDETERMINED`/`BLOCK`
  sobre un cierre `FINALIZED` (o hay invariantes críticos), la respuesta se
  sustituye por el mensaje no concluyente de código.

## 9. Verificación

| Suite | Resultado |
|---|---|
| `test_finalization_policy.py` (10 casos del prompt P2 + seguridad + observabilidad) | 14 passed |
| `test_adversarial_matrix.py` (matriz 192 combinaciones + estabilidad 100 runs + tool security) | 197 passed |
| `test_budget_stop_reasons.py` (STEP/TOOL/TOKEN/TIME/PROVIDER) | 6 passed |
| `test_runtime_policies.py` (transiciones + valor JEV + contexto + story views) | 20 passed |
| `test_run_state` + `test_agent_flow_v2` + `test_agent_runtime` (wiring P6, `flow["jev_value"]`, story view) | 134 passed |

Límites de este pase: el resolver corre en **observabilidad** + modo estricto;
los guards son tabla + tests (la adopción por el loop es incremental); el
ContextEnvelope se publica al cierre pero aún no construye los bloques del
prompt.
