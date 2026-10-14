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
| `RUNTIME_RUN_STATE_STRICT` | `off` | S | Fail-closed global por invariantes críticos (incluye cierre no autorizado y fallo de autoridad del cierre) | `run_state.py:strict_mode_enabled` | Permanente (seguridad). Adopción por canary. **SAFETY FLOOR**: la config de agente/org solo refuerza (P1-D) |
| `RUNTIME_RUN_STATE_STRICT_ORGS` | `""` | M | Canary del fail-closed por organización | `run_state.py:strict_mode_enabled` | Retirar cuando el global esté `on` en producción |
| `RUNTIME_FINALIZATION_ENFORCE` | `termination_trigger,draft_gate` | M | Etapas donde la política manda (hold fail-closed) | `enforcement.py:enforcement_stages` | Retiro por etapa cuando la divergencia medida sea 0 sostenida. **SAFETY FLOOR** (P1-D): scopes suman |
| `RUNTIME_FINALIZATION_ENFORCE_ORGS` | `""` | M | Suma etapas por organización (ya no reemplaza) | `enforcement.py:enforcement_stages` | Retirar junto con el flag global |
| `RUNTIME_FINALIZATION_ENFORCE_BY_ENV` | `""` | M | Suma etapas por `ENVIRONMENT` | `enforcement.py:enforcement_stages` | Retirar junto con el flag global |
| `RUNTIME_CONFIG_ACK_DANGEROUS` | `""` | S | Acknowledgement de combinaciones DANGEROUS (P1-E) | `config_rules.py:assert_runtime_config` | Permanente; las combinaciones INVALID nunca se reconocen |
| `RUNTIME_RUN_GUARDS_ENFORCE` | `off` | M | El veredicto de la tabla de guards deniega tools | `agent_runtime.py:guards_enforced` | Retirar cuando `zent_guard_divergence_total` sea 0 sostenido. **Clasificado P1-G**: SECURITY/CORRECTNESS duplican autoridades canónicas que corren siempre; RESOURCE respeta el ledger; QUALITY/EXPERIMENTAL advisory. Reclasificado de P1 a P3 con evidencia (`tests/test_run_guards_classification.py`) |
| `RUNTIME_ANSWER_GATE` | `off` | P | JEV juzga el borrador (`on`/`shadow`/`off`) | `answer_gate.py:answer_gate_mode` | Permanente (producto). Contrato de override del agente corregido (P1-3): se honran `on`/`shadow`/`off` |
| `RUNTIME_AGENT_JEV_LOOP` | `on` | P | Juez por paso del loop + gate de respuesta | `agent_runtime.py:2717` | Permanente (producto) |
| `RUNTIME_AGENT_JEV_LOOP_CANARY_PERCENTAGE` | `0` | M | % de runs con loop activo | `agent_runtime.py:608` | Retirar al 100% |
| `RUNTIME_JEV_SKIP_PHASES` | `""` | M | Fases JEV saltadas por calibración (`answer_gate`,`agent_step`,`termination`) | `jev_value.py:107` | Retiro por fase con datos de `redundant_rate`. DANGEROUS si contradice un gate encendido (P1-E) |
| `RUNTIME_JEV_SKIP_SHADOW` | `off` | M | No paga la llamada en fases shadow | `jev_value.py:117` | Retirar cuando no queden fases shadow. DANGEROUS con `answer_gate=shadow` (P1-E) |
| `RUNTIME_TERMINATION_GATE` | `off` | M | Gate Noul de terminación | `termination.py:23` | Retirar cuando el loop JEV lo cubra (ADR-002 del hardening) |

## Decisión / JEV / retrieval / razonamiento

| Flag | Default | Clase | Efecto | Retiro / condición |
|---|---|---|---|---|
| `DECISION_ROUTING_MODE` | `legacy` | M | legacy/shadow/jev/hybrid | Retirar legacy cuando `hybrid` esté al 100% |
| `JEV_SHADOW_MODE` | `False` | M | Observación forzada en CUALQUIER modo (P1-1 corregido: `acts()` no actúa con shadow) | Retiro cuando no queden fases shadow |
| `RAG_JEV_PREFLIGHT_MODE` | `off` | M | off/shadow/on/canary del preflight | Retiro cuando la matriz determinista × JEV (P1-C) esté medida en producción |
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

| Combo | Comportamiento real | Clasificación P1-E | Regla |
|---|---|---|---|
| `RUNTIME_ANSWER_GATE=on` + `JEV_SKIP_PHASES=answer_gate` | El gate nunca juzga (`provider=skip_config`) y la etapa `answer_gate` del enforcement no puede dispararse | DANGEROUS (`dangerous_gate_phase_skipped`) | Warning en dev; error en producción sin `RUNTIME_CONFIG_ACK_DANGEROUS` |
| `RUNTIME_TERMINATION_GATE=on` + `JEV_SKIP_PHASES=termination` | El gate no corta el loop (`stop=False`) | DANGEROUS (`dangerous_termination_phase_skipped`) | Ídem |
| `RUNTIME_ANSWER_GATE=shadow` + `RUNTIME_JEV_SKIP_SHADOW=on` | Shadow declara observación y no hay llamada al juez | DANGEROUS (`dangerous_shadow_without_judge`) | Ídem |
| Modo `canary` con porcentaje 0 | Equivale a `off` (sin shadow ni juicio) | VALID DEGRADATION | Permitido (default documentado) |
| `RUNTIME_FINALIZATION_ENFORCE=answer_gate` + `RUNTIME_ANSWER_GATE=off` + loop off | Etapa armada sin veredicto: hold inalcanzable | **INVALID** (`invalid_enforcement_stage_without_judge`) | Startup failure en cualquier entorno |
| `RUNTIME_AGENT_JEV_LOOP=on` + `RUNTIME_ANSWER_GATE=off` | El gate juzga igual (el loop fuerza `on`) salvo override del agente | VALID DEGRADATION | Permitido; la etapa `answer_gate` sí puede dispararse |
| Override del agente `answer_gate="shadow"` | **Honrado** (`on|shadow|off`); antes caía al global | RESUELTO (P1-3) | Contrato documentado en `answer_gate_mode` |
| Override del agente `finalization_enforce=false` | **No desarma** el piso global: los scopes suman (P1-D) | RESUELTO (P1-3) | `enforcement_stages` es unión |
| `JEV_SHADOW_MODE=true` + `DECISION_ROUTING_MODE=jev` | Shadow gana: el juez observa y **no actúa** | RESUELTO (P1-1) | `DecisionEngineSettings.acts()` |
| `RUNTIME_RUN_STATE_STRICT=on` + agente `strict_run_state=false` | **No apaga** el piso: el agente solo refuerza | RESUELTO (P1-3) | `strict_mode_enabled` monotónico |

Las reglas viven en `src/core/config_rules.py` (códigos estables, versión
`config-rules-1`) y corren en la construcción de `Settings`
(`assert_runtime_config`): la instancia no arranca en una postura contradictoria.
Tests: `tests/test_config_rules.py`, `tests/test_safety_floor.py`.

## Deuda de inventario

`RAG_LONG_CONTEXT_*`, `RAG_COGNITIVE_OS_ENABLED` y `RAG_JEV_PREFLIGHT_*` no
aparecen en el inventario de flags (`src/scripts/flags_inventory.py:63-66`): sus
nombres no empiezan con los prefijos relevados. Deuda P2-1.
