# Registro de flags con autoridad (Parte J)

Clase de cada flag y su condición de retiro. La regla: un flag que altera
autoridad **declara** qué es (migración / seguridad operativa / producto /
switch permanente), quién lo lee y cuándo se retira. Las combinaciones
contradictorias quedan pinneadas por `tests/test_flag_coherence.py`.

Clases: **M** migración (retiro con datos), **S** seguridad operativa
(permanente, default seguro), **P** producto (config del tenant/agente),
**W** switch de comportamiento (permanente por diseño).

## Autoridad del cierre y del estado

| Flag | Default | Clase | Efecto | Leído en | Retiro / condición |
|---|---|---|---|---|---|
| `RUNTIME_RUN_STATE_STRICT` | `off` | S | Fail-closed global por invariantes críticos (incluye cierre no autorizado) | `run_state.py:930` | Permanente (seguridad). Adopción por canary |
| `RUNTIME_RUN_STATE_STRICT_ORGS` | `""` | M | Canary del fail-closed por organización | `run_state.py:924` | Retirar cuando el global esté `on` en producción |
| `RUNTIME_FINALIZATION_ENFORCE` | `termination_trigger,draft_gate` | M | Etapas donde la política manda (hold fail-closed) | `enforcement.py:79` | Retiro por etapa cuando la divergencia medida sea 0 sostenida |
| `RUNTIME_FINALIZATION_ENFORCE_ORGS` | `""` | M | Override por organización | `enforcement.py:82` | Retirar junto con el flag global |
| `RUNTIME_FINALIZATION_ENFORCE_BY_ENV` | `""` | M | Override por `ENVIRONMENT` | `enforcement.py:89` | Retirar junto con el flag global |
| `RUNTIME_RUN_GUARDS_ENFORCE` | `off` | M | El veredicto de la tabla de guards deniega tools | `agent_runtime.py:1352` | Retirar cuando `zent_guard_divergence_total` sea 0 sostenido |
| `RUNTIME_ANSWER_GATE` | `off` | P | JEV juzga el borrador (`on`/`shadow`/`off`) | `answer_gate.py:170` | Permanente (producto); corregir el override string (P1-3) |
| `RUNTIME_AGENT_JEV_LOOP` | `on` | P | Juez por paso del loop + gate de respuesta | `agent_runtime.py:2717` | Permanente (producto) |
| `RUNTIME_AGENT_JEV_LOOP_CANARY_PERCENTAGE` | `0` | M | % de runs con loop activo | `agent_runtime.py:608` | Retirar al 100% |
| `RUNTIME_JEV_SKIP_PHASES` | `""` | M | Fases JEV saltadas por calibración (`answer_gate`,`agent_step`,`termination`) | `jev_value.py:107` | Retiro por fase con datos de `redundant_rate` |
| `RUNTIME_JEV_SKIP_SHADOW` | `off` | M | No paga la llamada en fases shadow | `jev_value.py:117` | Retirar cuando no queden fases shadow |
| `RUNTIME_TERMINATION_GATE` | `off` | M | Gate Noul de terminación | `termination.py:23` | Retirar cuando el loop JEV lo cubra (ADR-002 del hardening) |

## Decisión / JEV / retrieval / razonamiento

| Flag | Default | Clase | Efecto | Retiro / condición |
|---|---|---|---|---|
| `DECISION_ROUTING_MODE` | `legacy` | M | legacy/shadow/jev/hybrid | Retirar legacy cuando `hybrid` esté al 100% |
| `JEV_SHADOW_MODE` | `False` | M | Observación forzada (**deuda P1-1**: en modo `jev` no impide actuar) | Corregir antes de retirar |
| `RAG_JEV_PREFLIGHT_MODE` | `off` | M | off/shadow/on/canary del preflight | Retiro cuando el bloqueo JEV-only (P1-2) tenga segunda señal |
| `DECISION_BATCH_MODE` | `off` | M | Batching de juicios | Retirar con `on` estable |
| `DECISION_TARGET_SELECTION` | `off` | M | JEV elige target del dispatcher | Retirar con `on` + canary medido |
| `ADAPTIVE_RAG_MODE` | `off` | M | off/shadow/active/canary del plan de retrieval | Retiro tras golden set legacy vs adaptive |
| `RAG_LONG_CONTEXT_MODE` | `off` | M | off/shadow/active/canary de expansión | Retiro tras `off → shadow → canary → active` |
| `RAG_COGNITIVE_OS_ENABLED` | `off` | M | off/shadow/limited/active del runtime cognitivo | Retiro cuando el camino cognitivo sea el default |
| `RUNTIME_TURN_INTENT` | `on` | P | Clasificación de intención del turno | Permanente |
| `RUNTIME_FAST_PATH` | `on` | P | Responde sin LLM con autoridad determinista | Permanente |
| `RUNTIME_ANSWER_FACT_CHECK` | `on` | P | Corrige fechas/años contra evidencia | Permanente |
| `RUNTIME_NARRATIVE_FAST_PATH` | `on` | P | Ruta narrativa sin loop ReAct | Permanente |
| `RUNTIME_DETERMINISTIC_RENDER_MODE` | `adaptive` | P | Presentación del resultado determinista | Permanente |

## Combinaciones contradictorias (pinneadas)

| Combo | Comportamiento real | Riesgo |
|---|---|---|
| `RUNTIME_ANSWER_GATE=on` + `JEV_SKIP_PHASES=answer_gate` | El gate nunca juzga (`provider=skip_config`) y la etapa `answer_gate` del enforcement no puede dispararse | Se cree que hay gate; no hay señal ni fail-closed |
| `RUNTIME_TERMINATION_GATE=on` + `JEV_SKIP_PHASES=termination` | El gate no corta el loop (`stop=False`) | Gate encendido sin efecto |
| Modo `canary` con porcentaje 0 | Equivale a `off` (sin shadow ni juicio) | Rollout que no observa nada |
| `RUNTIME_FINALIZATION_ENFORCE=answer_gate` + `RUNTIME_ANSWER_GATE=off` | Etapa armada sin veredicto: hold inalcanzable | Enforcement silenciosamente no-op |
| `RUNTIME_AGENT_JEV_LOOP=on` + `RUNTIME_ANSWER_GATE=off` | El gate juzga igual (el loop fuerza `on`) salvo override del agente | El flag global deja de ser autoridad |
| Override del agente `answer_gate="shadow"` | Se ignora (solo `bool`) y cae al global | El agente no puede degradar a shadow |
| Override del agente `finalization_enforce=false` | Desarma el enforcement global | Fail-closed desactivado por config de agente (P1-3) |
| `JEV_SHADOW_MODE=true` + `DECISION_ROUTING_MODE=jev` | El juez **actúa** | Rollout que decide en producción (P1-1) |

## Deuda de inventario

`RAG_LONG_CONTEXT_*`, `RAG_COGNITIVE_OS_ENABLED` y `RAG_JEV_PREFLIGHT_*` no
aparecen en el inventario de flags (`src/scripts/flags_inventory.py:63-66`): sus
nombres no empiezan con los prefijos relevados. Deuda P2-1.
