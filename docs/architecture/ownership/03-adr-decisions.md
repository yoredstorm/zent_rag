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
  (`RunBudgetLedger`); los eventos por fase se conservan para
  trazabilidad del juez (modelo, latencia, costo estimado y su procedencia)
  **sin repetir tokens**. Las líneas del juez pasan por el ledger:
  `record_judge_call` deja de escribir totales.
- **Refinamiento registrado en S5 (implementación)**: un único booleano
  `billable` no expresa la realidad medida: los *tokens* del juez ya viajan en
  el evento del run (duplicarlos infla cualquier suma), pero el *costo
  estimado* del juez NO está en el costo del run (es la única fuente de ese
  costo). Se resolvió en la fuente: el evento del juez escribe 0 tokens con
  `routing["token_accounting"]="run_event"` y `routing["judge_tokens"]=<n>`,
  y conserva `estimated_cost` + `routing["cost_source"]`. Sin migración de
  esquema y sin sweep de 40+ agregaciones: la duplicación desaparece donde se
  producía.
- **Consecuencias**: sin cambio en los números facturados de dinero; el
  desglose del juez sigue disponible; una sola autoridad de consumo para
  enforcement, observabilidad y billing.
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

---

## ADR-007. Aplicador terminal único; el fallo de autoridad no reabre el mapper

- **Contexto**: `try_advance` aceptaba fases terminales desde cualquier fase y un
  fallo de `resolve_closure_phase` degradaba a `phase_override=None`, cayendo al
  mapper por texto: un answer no vacío podía terminar FINALIZED sin autorización
  de cierre.
- **Decisión**: `try_advance` solo progresa fases no terminales; los terminales
  los aplica el aplicador canónico (`_apply_terminal`, privado) o
  `apply_closure_override` (corrección de seguridad post cierre, restringida a
  fases no-concluyentes). El fallo del reducer produce una resolución explícita
  `closure_authority_failed` → FAILED, con motivo estructurado y traza.
- **Consecuencias**: el mapper legacy sobrevive como oráculo de divergencia;
  ratchets estáticos y behavioral impiden mutaciones terminales nuevas.
- **Descartado**: allowlists de callers en runtime (security by convention) y
  borrar el mapper (todavía mide divergencia).

---

## ADR-008. El piso de seguridad es monotónico; el downgrade está prohibido

- **Contexto**: la config del agente tenía prioridad absoluta y podía desarmar
  `RUNTIME_RUN_STATE_STRICT` y `RUNTIME_FINALIZATION_ENFORCE`.
- **Decisión**: `effective = global ∪ environment ∪ organización ∪ agente`.
  Ningún scope normal resta; un downgrade operacional exigiría break-glass
  auditado, que el producto **no necesita hoy** (por eso no se construye).
- **Consecuencias**: cambiar de opinión sobre un piso exige cambiar el global o
  el canary, nunca la config de un agente; los overrides solo endurecen.
- **Descartado**: break-glass sin caso de uso (superficie nueva sin riesgo real)
  y "el agente manda" (fail-closed desarmable).

---

## ADR-009. JEV juzga, la matriz autoriza; shadow no actúa

- **Contexto**: `JEV_SHADOW_MODE` no impedía actuar en modo `jev`; el preflight
  podía bloquear con un juicio solo (≥2 insatisfechas + confianza ≥0.70).
- **Decisión**: `acts()` devuelve False con shadow; `resolve_authorization`
  compone determinista × JEV con la tabla documentada (DENY gana; ALLOW no se
  invierte; UNKNOWN + señal JEV sola → advisory/retrieve/corroboración, nunca
  acción definitiva). El juicio múltiple del mismo juez no es segunda señal.
- **Consecuencias**: una probabilidad nunca se convierte en autorización; el
  peor resultado de una señal sola es pedir corroboración o advertir.
- **Descartado**: majority voting genérico (correlaciona errores del mismo juez)
  y umbrales de confianza como autoridad.

---

## ADR-010. Las posturas contradictorias no arrancan

- **Contexto**: 10 combinaciones contradictorias de flags quedaron pinneadas en
  tests, sin consecuencia operativa.
- **Decisión**: `src/core/config_rules.py` clasifica el inventario existente:
  INVALID (startup failure en cualquier entorno), DANGEROUS (warning en dev,
  error en producción sin `RUNTIME_CONFIG_ACK_DANGEROUS`), VALID DEGRADATION y
  EXPERIMENT. La validación corre en la construcción de `Settings`.
- **Consecuencias**: una instancia no puede declarar una protección sin efecto
  sin que quede registrado; los códigos son estables y versionados.
- **Descartado**: convertir toda combinación no recomendada en error (bloquea
  calibraciones legítimas) y validar solo en runtime (la postura ya está activa).
