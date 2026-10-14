# Duplicated Authorities — registro BEFORE

Cada entrada declara: síntoma, evidencia (`file:line`), autoridad canónica
propuesta y slice que la resuelve. **No** se refactoriza nada hasta que esta
lista existe (requisito de la fase).

Estado por entrada (actualizado en cada slice): `ABIERTO`, `EN CURSO`,
`RESUELTO`. El detalle del cambio vive en `04-slice-log.md`; la matriz final en
`05-ownership-map-after.md`.

| ID | Estado |
|---|---|
| P0-1 | RESUELTO en S2 (campo estricto real; cierre por autoridad) |
| P0-2 | RESUELTO en S2 (reducer + invariante de construcción) |
| P0-3 | EN CURSO (S4/S8) |
| P0-4 | RESUELTO en S4 (vocabulario único de evidencia + conflictos medidos; la corrección de la cobertura parcial se adopta por canary) |
| P0-5 | RESUELTO en S5 (ledger como escritor único; sin doble conteo de tokens del juez) |
| P1-1 | RESUELTO (hardening H1: `JEV_SHADOW_MODE` no actúa en ningún modo) |
| P1-2 | RESUELTO (hardening H2: matriz determinista × JEV; JEV solo no bloquea) |
| P1-3 | RESUELTO (hardening H3/H4: piso monotónico + override del contrato honrado) |
| P1-4 | CERRADO por contrato con test (hardening H6: dispatcher/embed/cognitive; el plano de eventos queda P2 documentado) |
| P1-5 | RECLASIFICADO P3 CON EVIDENCIA (hardening H5: clasificación de guards) |
| P1-6 | RESUELTO (hardening H4: validación de inicio + combinaciones resueltas por construcción) |
| P1-7 | RESUELTO (hardening H0: representación muerta eliminada; una sola verdad `stop_reason`) |
| P2-1, P2-2 | PARCIAL en S9-lite (registro de flags con clase y retiro; falta cubrir los prefijos en el inventario) |
| P2-1..P2-6 | ABIERTO |

## P0 — la respuesta a "quién decide" es ambigua

### P0-1. El cierre no tiene enforcement, y el fail-closed global está muerto

- Síntoma: en defaults productivos, la decisión terminal **no tiene ninguna vía
  de enforcement**. El hold existe para `termination_trigger`, `draft_gate` y
  `answer_gate`, pero no para `closure`.
- Evidencia:
  - `src/runtime/enforcement.py:19-21` — `ENFORCE_STAGES` sin `closure`.
  - `src/runtime/enforcement.py:11-12` — el comentario delega el fail-closed del
    cierre al modo estricto del estado.
  - `src/runtime/run_state.py:930-931` — `getattr(settings, "RUNTIME_RUN_STATE_STRICT", "off")`.
  - `src/core/config.py:1441` — `Settings` solo define `RUNTIME_RUN_STATE_STRICT_ORGS`; el campo global no existe, el `getattr` siempre devuelve `"off"`.
  - `docs/architecture/finalization-policy.md`, `docs/architecture/enforcement`
    y `hardening/*` documentan el flag global como autoridad vigente.
- Autoridad canónica: `FinalizationPolicy` + `DecisionEnvelope`.
- Slice: **S2**. Crea el campo `RUNTIME_RUN_STATE_STRICT` (default `off`,
  respetado) y habilita `closure` en `ENFORCE_STAGES`.

### P0-2. La fase terminal se deriva del texto, no de la decisión

- Síntoma: `finish()` mapea `status` + `answer_state` + "¿hay texto?" a la fase
  terminal. Quien escriba último el texto decide el cierre. La resolución de la
  política corre en paralelo y solo observa divergencias.
- Evidencia:
  - `src/runtime/run_state.py:751-758` (`finish`), `:876-899` (`terminal_phase_for`).
  - `src/runtime/run_state.py:964-983` — `finalize_state` escribe texto y luego mapea fase.
  - `src/runtime/finalization_policy.py:388-399` — `decision_matches_terminal` compara, no decide.
  - `docs/architecture/finalization-policy.md` — adopción por etapas con CERO
    divergencias requeridas sobre el corpus.
- Autoridad canónica: `FinalizationPolicy` resuelve y `DecisionEnvelope` porta la
  decisión; la fase se aplica desde ahí.
- Slice: **S2**. `finish()` consume la resolución; `terminal_phase_for` queda
  como oráculo de consistencia con allowlist cerrada.

### P0-3. Answerability con ~10 deciders

- Síntoma: diez componentes pueden forzar un cierre no concluyente o reemplazar
  el resultado, sin un punto único que resuelva contradicciones.
- Deciders (evidencia): `answer_gate.judge_answer` (`src/runtime/answer_gate.py:512-540,744-785`),
  `finalization_policy.evaluate_finalization` (`:181-344`), `derived_guard.enforce_derived_result`
  (`src/runtime/derived_guard.py:254-332`), `operation_compatibility.envelope_operation_compatible`
  (`src/runtime/operation_compatibility.py:1026-1044`), evidence-first gate
  (`src/agents/runtime/orchestrator.py:5087-5199`), `decision/preflight.LLMEscalationPolicy.evaluate`
  (`src/decision/preflight.py:795-893`), `intelligence/answerability.AnswerabilityGate.evaluate`
  (`src/intelligence/answerability.py:252-488`), `rag/longcontext/coverage.decide_generation_mode`
  (`src/rag/longcontext/coverage.py:548-571`), `premise_closure.run_premise_closure`
  (`src/runtime/premise_closure.py:735-1031`), `fast_path.evaluate_deterministic_fast_path`
  (`src/runtime/fast_path.py:120-257`), `answer_state.select_answer_state`
  (`src/runtime/answer_state.py:47-83`).
- Autoridad canónica: productores de señal (miden y recomiendan) + un resolver
  (`FinalizationPolicy`) + un contrato (`DecisionEnvelope`).
- Slices: **S2**, **S4**, **S8**.

### P0-4. Sufficiency duplicada entre runtime y adaptive

- Síntoma: dos modelos rivales con el mismo nombre de salida
  (`recommended_action`) y consumidores distintos.
- Evidencia:
  - `src/runtime/evidence.py:828-866` (`EvidenceSufficiency`, canónico del loop).
  - `src/rag/adaptive/evidence.py:164,240` (`EvidenceQuality`), sobreescrito por
    JEV en `:397-409`.
  - `src/agents/runtime/orchestrator.py:5038-5046,5089-5100` (consume quality),
    `src/agents/runtime/agent_runtime.py:3446-3453,5071-5084` (consume sufficiency).
- Conflaciones verificadas:
  - `long_context_escalated` tratado como completitud canónica
    (`src/rag/longcontext/engine.py:72,483`; `orchestrator.py:669-676`; efecto en
    `:5066-5086`): re-empacar contexto ya recuperado cancela abstenciones.
  - Errores de lane convertidos en "sin información": `src/runtime/premise_retriever.py:406-415`,
    `src/runtime/premise_closure.py:924-929`.
  - Historial del loop usado como evidencia cuando el registry está vacío:
    `src/agents/runtime/agent_runtime.py:3486-3491`.
  - `EvidenceSufficiency.conflicting_chunks` sin writer (`evidence.py:852`).
- Autoridad canónica: `assess_sufficiency` mide; la política resuelve.
- Slice: **S4**.

### P0-5. Costo: tres writers de totales y doble conteo de eventos JEV

- Síntoma: el ledger es la autoridad declarada, pero el juez escribe totales
  fuera de él y `usage_events` suma los mismos tokens dos veces.
- Evidencia:
  - Canónico: `src/runtime/run_budget.py:296-312` (`account_llm_usage`, `account_embedding_usage`).
  - Bypass 1: `src/runtime/run_accounting.py:217-221` (`record_judge_call` suma tokens directo).
  - Bypass 2: `src/runtime/answer_gate.py:712-713` (usage del juez escrito sobre el result).
  - Doble conteo: `src/decision/usage.py:75-94` persiste los mismos tokens como
    eventos `jev_judge:*`, y `src/agents/runtime/agent_runtime.py:2377-2384`
    persiste `agent_run` con `result.total_tokens`.
  - Cero silencioso: `src/decision/costs.py:63-66,89-91` (`amount=0.0, source="none"`).
  - Cuota con contador paralelo: `src/platform/billing/quota_service.py:139-181`
    (Redis), no lee el ledger.
  - Ratchet S0: `result_totals` = 16 hits en 3 archivos.
- Autoridad canónica: `RunBudgetLedger` (único); persistencia como proyección
  post-run con `billable` explícito.
- Slice: **S5**.

## P1 — no debería ser posible, pero no rompe el cierre

**Estado tras el hardening de autoridad (H0–H9, ver `08-hardening-report.md`)**:

| ID | Estado | Evidencia |
|---|---|---|
| P1-1 | RESUELTO | `DecisionEngineSettings.acts()` devuelve False con shadow; `tests/test_authorization_matrix.py::TestShadowNoActua` |
| P1-2 | RESUELTO | Matriz `resolve_authorization` (determinista × JEV); un juicio solo nunca da acción definitiva; `TestPreflightMatriz` |
| P1-3 | RESUELTO | Piso monotónico en `strict_mode_enabled` y `enforcement_stages`; override `shadow` honrado; `tests/test_safety_floor.py` |
| P1-4 | CERRADO por contrato con test | Dispatcher denegado/observacional no ejecuta; tool privilegiada no corre con permisos vacíos; DAG cognitivo recibe el tenant del run; `tests/test_action_plane_authority.py` |
| P1-5 | RECLASIFICADO P3 (evidencia) | `GUARD_CLASS`: SECURITY/CORRECTNESS duplican autoridades canónicas; `tests/test_run_guards_classification.py` |
| P1-6 | RESUELTO | `src/core/config_rules.py` + `assert_runtime_config` en `Settings`; combinaciones resueltas por construcción |
| P1-7 | RESUELTO | `last_cut_reason` eliminado; `stop_reason` es la única representación |

Detalle por entrada (recon original):

### P1-1. `JEV_SHADOW_MODE` no shadowea

- Evidencia: `src/decision/settings.py:96-107` (`acts()` ignora shadow en modo
  `jev`), `src/decision/composite.py:46-47`.
- Riesgo: un flag de observación modifica ejecución real.
- Slice: **S8**.

### P1-2. Bloqueo JEV-only en preflight

- Evidencia: `src/decision/preflight.py:779-784,858-868` (≥2 preguntas sin
  satisfacer + confianza ≥ 0.70 bloquea la generación sin segunda señal
  determinista); efecto en `orchestrator.py:4617-4623`.
- Riesgo: probabilidad convertida en autorización implícita.
- Slice: **S8**.

### P1-3. Overrides que desarman autoridad global

- Evidencia: `src/runtime/enforcement.py:75-77` (config del agente tiene
  prioridad absoluta, incluso `false` con global armado);
  `src/runtime/answer_gate.py:163-171` (solo honra `bool`, ignora `"shadow"`).
- Riesgo: fail-closed desactivado por configuración de agente sin guard.
- Slice: **S9**.

### P1-4. Formas fail-open en el plano de acción

- Evidencia: `src/platform/workflows/engine.py:453-462` (`permissions` vacío
  escala en silencio a `_SYSTEM_NODE_PERMS`, que incluye
  `external_actions:execute` y `agents:execute`); `src/agents/tools/sql_expert_postgres.py:1131-1137`
  (`_extra_tables` salta el allowlist de tablas); `src/runtime/dispatcher.py:287-342`
  (ejecuta con `authorized=None`); `src/platform/cognitive/executor.py:168-359`
  (sin authz interno, gated por el caller); `src/api/routes/embed.py:156-191`
  (sin RBAC, solo token+origin).
- Riesgo: ejecución sin autorización explícita.
- Slices: **S6**, **S7**.

### P1-5. RunGuards advisory por default

- Evidencia: `src/agents/runtime/agent_runtime.py:1349-1353,5401-5423`
  (veredicto de guard solo deniega con `RUNTIME_RUN_GUARDS_ENFORCE=on`, default `off`).
- Slice: **S9**.

### P1-6. Combinaciones de flags contradictorias (10 detectadas)

Ejemplos verificados: `RUNTIME_ANSWER_GATE=on` + `RUNTIME_JEV_SKIP_PHASES=answer_gate`
(gate encendido que nunca juzga; vivo en `.env:251,254`);
`RUNTIME_TERMINATION_GATE=on` + `JEV_SKIP_PHASES=termination`;
modo `canary` con porcentaje 0 (equivale a `off`, sin shadow);
`RUNTIME_FINALIZATION_ENFORCE` armando `answer_gate` con `RUNTIME_ANSWER_GATE=off`.
- Slice: **S9**.

### P1-7. Representación muerta de cortes de budget

- Evidencia: `src/runtime/run_state.py:497,526` (`last_cut_reason` sin writer)
  vs `stop_reason` (`agent_runtime.py:1272-1276`, 8 sitios de corte).
- Slice: **S11**.

## P2 — higiene y deuda de mantenimiento

| ID | Hallazgo | Evidencia | Slice |
|---|---|---|---|
| P2-1 | Inventario de flags no cubre `RAG_LONG_CONTEXT_*`, `RAG_COGNITIVE_OS_ENABLED`, `RAG_JEV_PREFLIGHT_*` | `src/scripts/flags_inventory.py:63-66` | S9 |
| P2-2 | Flags sin owner ni fecha de retiro declarada en código | `docs/architecture/hardening/00-audit.md:58-59` (criterio general existe, no por flag) | S9 |
| P2-3 | Campos sin writer: `plan.strategy`, `knowledge.entities/brief/narrative_package`, `answer.gate`, `decisions.jev`, `tools.failures` | recon S0 (scan de writers) | S3/S11 |
| P2-4 | `is_organization_admin` / `is_platform_admin` sin callers | `src/agents/policies/authorization.py:34-45` | S7 |
| P2-5 | `_check_subqueries` no-op ante error de parse | `src/agents/tools/sql_expert_postgres.py:171-172` | S6 |
| P2-6 | `usage_logs` legacy convive con `usage_events` | `src/agents/runtime/orchestrator.py:5757-5762`, `src/infrastructure/postgres/relational_db.py:143-164` | S5 |
