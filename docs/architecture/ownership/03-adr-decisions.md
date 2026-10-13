# ADRs — Fase de convergencia de autoridad

Formato corto: contexto, decisión, consecuencias, alternativas descartadas.
Estado: `aceptado` salvo indicación.

---

## ADR-001. Postura de la fase: construir la autoridad y adoptar por canary

- **Contexto**: el contrato de cierre (`FinalizationPolicy` + `DecisionEnvelope`)
  existe y está probado, pero en defaults productivos solo observa: `closure` no
  es armable (`enforcement.py:19-21`) y el fail-closed global del estado no
  existe (`config.py:1441`). Los ratchets de S0 fijan los writers actuales.
- **Decisión**: convertir la autoridad en **estructuralmente imposible de
  esquivar por construcción** (tests que fallan si aparece un writer o bypass
  nuevo) y adoptar el enforcement **por canary**, con rollback intacto. No se
  cambian defaults de producto en esta fase.
- **Consecuencias**: cero cambio de resultados RAG/agente por default; la deuda
  queda visible y bloqueada contra regresión; la adopción posterior es decisión
  operativa medida (divergencia de la política sobre corpus real).
- **Descartado**: enforcement total desde el primer slice (riesgo de cambio de
  respuestas en producción) y "solo contratos" (deja la ambigüedad viva).

---

## ADR-002. `RUNTIME_RUN_STATE_STRICT` se crea como campo real

- **Contexto**: `strict_mode_enabled` documenta tres niveles (agente, orgs
  canary, global) pero el campo global no existe: `getattr` con default `"off"`
  (`run_state.py:930-931`). Documentación y código divergen: el fail-closed del
  cierre no tiene autoridad global.
- **Decisión**: crear el campo `RUNTIME_RUN_STATE_STRICT` en `Settings`
  (default `off`), respetarlo en `strict_mode_enabled`, agregar el contrato de
  entorno (`.env.example` + test) y dejarlo **apagado**. La adopción se hace por
  orgs canary o por config de agente.
- **Consecuencias**: el comportamiento documentado es real y controlable; los
  defaults no cambian; el inventario de flags lo cubre.
- **Descartado**: retirar el claim de los docs (pierde la capacidad de
  fail-closed global declarada) y encenderlo por default (cambio de
  comportamiento observable sin medición).

---

## ADR-003. Uso del juez JEV: un solo total, eventos no facturables

- **Contexto**: los tokens del juez se suman a `result` por un lado
  (`run_accounting.py:217-221`) y se persisten otra vez como eventos
  `jev_judge:*` (`decision/usage.py:75-94`), mientras el evento `agent_run`
  incluye `result.total_tokens`. Sumar eventos duplica el consumo.
- **Decisión**: el total viaja **solo** por el ledger
  (`RunBudgetLedger.account_llm_usage`); los eventos por fase se conservan para
  trazabilidad con `billable=false` explícito y quedan excluidos de las
  agregaciones facturables (`cost_breakdown`, `aggregation`, invoices). Las
  líneas del juez pasan por el ledger: `record_judge_call` y
  `answer_gate.py:712-713` dejan de escribir totales.
- **Consecuencias**: sin cambio en los números facturados; el desglose sigue
  disponible; una sola autoridad de consumo para enforcement, observabilidad y
  billing.
- **Descartado**: eliminar los eventos por fase (pierde desglose) y arreglar
  solo la agregación (deja la ambigüedad de autoridad).

---

## ADR-004. Autoridad terminal única: `finish()` consume la resolución

- **Contexto**: la fase terminal se deriva del texto y del dict `answer_state`
  (`run_state.py:876-899`). Tres módulos escriben `phase`. La política de cierre
  corre en paralelo y su divergencia solo se registra.
- **Decisión**: el cierre pasa por un **contrato único**:
  señales + evidencia + razonamiento + inputs deterministas se resuelven en
  `evaluate_finalization`; la resolución se porta en el `DecisionEnvelope`; el
  estado aplica la fase desde la resolución (`apply_closure`) y `finish()` deja
  de mapear texto. `terminal_phase_for` sobrevive como **oráculo de
  consistencia** con allowlist cerrada: si el oráculo y la resolución discrepan,
  el run es inconsistente y el ratchet lo detecta (no se publica una fase
  derivada del texto).
- **Consecuencias**: una sola respuesta a "quién decide que el run termina"; el
  `deterministic_finalized_without_envelope` deja de ser observable y pasa a ser
  imposible por construcción; los sitios allowlisted de transición terminal
  bajan.
- **Descartado**: mantener el mapper como fuente (ordena la ambigüedad) y
  reemplazar `AgentRunState` (god object nuevo).

---

## ADR-005. Alcance: cero motores nuevos, solo convergencia

- **Contexto**: existen `FinalizationPolicy`, `DecisionEnvelope`, `RunGuards`,
  `RunBudgetLedger`, `AgentRunState`, `enforcement` y `failure_taxonomy`. La
  deuda es de **autoridad duplicada**, no de capacidad faltante.
- **Decisión**: prohibido en esta fase crear un motor, orchestrator, planner o
  bus de eventos nuevo; prohibido CQRS/event sourcing y dependencias nuevas
  (Neo4j/graph DB). Las extracciones solo se hacen cuando **borran una
  responsabilidad** del módulo original y tienen caller real.
- **Consecuencias**: los diffs se miden por writers eliminados, terminal sites y
  bypasses cerrados, no por LOC.
- **Descartado**: "Agent Runtime V3" y abstracciones generadas sin callers.

---

## ADR-006. Entregables versionados en el repo

- **Contexto**: la fase produce mapas, registro de duplicaciones, ADRs y
  métricas before/after que deben auditarse junto al código que describen.
- **Decisión**: todo vive en `docs/architecture/ownership/` y se actualiza en el
  mismo commit que el cambio de autoridad. Un test verifica que el registro de
  autoridad del ratchet y el mapa no pierdan componentes.
- **Consecuencias**: el mapa no puede quedar desactualizado en silencio.
- **Descartado**: documentos fuera del repo (no versionados, no verificables).
