# Architecture Ownership Map — BEFORE

Estado: recon sobre `BASELINE_SHA` `5cd3dec1812955c28dd6ce338f56322022a2079c`
(CI 10/10 verde). Sin cambios de código en este documento.

## Cómo leer la matriz

- **AUT** = autoritativo (su salida obliga). **ADV** = advisory (aporta señal,
  no decide). **OBS** = observacional (no altera el run).
- *Transición* = puede mover `RunPhase`. *Terminal* = puede producir
  FINALIZED / ABSTAINED / BLOCKED / UNDETERMINED / FAILED / LIMIT_REACHED.
- *Sobreescrito por* lista quién puede anular su salida hoy.

## PERCEPTION

| Componente | Consume | Produce | Campos que modifica | Clase | Transición | Terminal | Sobreescrito por | Tests |
|---|---|---|---|---|---|---|---|---|
| **AgentRunState** (`src/runtime/run_state.py:711`) | señales de todos los writers | vista canónica del run | `phase`, sub-estados completos (vía métodos `observe*`, `set_*`, `note_*`, `try_advance`, `finish`) | AUT (vista) | sí | sí (mapper de texto) | cualquier writer con referencia; 3 módulos escriben `phase` | `test_run_state.py`, `test_adaptive_projection.py`, ratchet S0 |
| **RunIdentity** (`run_state.py:150`) | `AgentRunRequest`, agente | identidad inmutable del run | ninguno tras construcción | AUT | no | no | nadie (frozen de facto) | `test_run_state.py` |
| **ContextEnvelope** (`src/runtime/context_envelope.py:157`) | orígenes de cada fragmento | etiquetas de procedencia/confianza + headers de prompt | `state.context` al cierre | OBS (describe, no enforce) | no | no | nadie; `_publish_context_envelope` (`agent_runtime.py:1244`) | `test_conversation_isolation.py`, `test_prompt_block_headers.py` |
| **turn intent** (`src/runtime/turn_intent.py:811`) | mensaje, agente, settings | `TurnIntentDecision` (intent, route, direct, needs_external_evidence) | `turn.decision` (`agent_runtime.py:2595`; `orchestrator.py:3240` snapshot) | ADV (routing) | sí (CLASSIFIED) | no | camino agente vs RAG escriben la misma verdad | `test_turn_intent.py` |
| **Company Context** (`src/company/context.py:270`) | fuentes de compañía, memoria | contexto compilado para prompts | payload de prompt (no estado del run) | ADV | no | no | nadie | `test_company_*` |
| **memory** (`src/memory/service.py`) | conversación, org | recuerdos recuperados | payload de prompt; no toca estado del run | ADV | no | no | nadie | `test_memory_*`, `test_conversation_isolation.py` |
| **KnowledgeScope** (`src/core/domain/knowledge_scope.py:51`) | config de agente/org | scope efectivo (narrow-only) | `org_config` (source_ids/kb_ids/workspaces/knowledge_deny), `plan.authorized_scope` | AUT (restrictiva) | no | no | vacío = sin restricción (`tools_builtin.py:448-452`); `_extra_tables` del SQL Expert salta allowlist | `test_knowledge_scope.py`, `test_authorized_scope.py` |
| **retrieval** (`tools_builtin`, `orchestrator._safe_vector_search_full:3594`, `premise_retriever`) | query, scope, tenant | chunks, registros de evidencia | `plan.query_views/source_routing/passages`, `evidence.*`, `evidence.retrieval_failed` | AUT (produce evidencia) | sí (RETRIEVING) | no | rerank/selector pueden descartar; lane errors silencian fallos | `test_evidence_first_gate.py`, `test_sql_security.py`, `test_tenant_isolation.py` |
| **coverage / sufficiency** (`src/runtime/evidence.py:828` + `src/rag/adaptive/evidence.py:164`) | chunks, requisitos semánticos | `recommended_action`, missing sets, `evidence_complete` | `evidence.sufficiency`, `evidence.canonical_state`, `adaptive["quality"]` | AUT (medición) / ADV (recomendación) | sí (EVIDENCE_REQUIRED) | no directo | JEV sobreescribe `quality.recommended_action`; long-context stop actúa como completitud | `test_evidence_first_gate.py`, `test_run_state.py:203-315`, `test_finalization_policy.py:129` |
| **long-context expansion** (`src/rag/longcontext/engine.py:336-489`) | contexto recuperado, tiers | contexto expandido + stop reason | `evidence.long_context_*`, `adaptive["context"]` | ADV | sí (RETRIEVING) | no | `long_context_escalated` se trata como completitud canónica (`orchestrator.py:669-676`, `5066-5086`) | `test_longcontext_orchestrator.py`, `test_adaptive_projection.py` |

## REASONING

| Componente | Consume | Produce | Campos que modifica | Clase | Transición | Terminal | Sobreescrito por | Tests |
|---|---|---|---|---|---|---|---|---|
| **reasoning classification** (`src/agents/runtime/reasoning_step.py:49`) | clasificación de la consulta | regla de respuesta, condiciones de completitud, bloqueo de respuesta directa | `reasoning.run` (`agent_runtime.py:2116`) | AUT (gate de análisis) | sí (REASONING) | no | política puede ignorar la incompletitud si hay autoridad determinista | `test_agent_runtime.py`, `test_finalization_policy.py` |
| **grounded engine** (`src/intelligence/reasoning/grounded_engine.py:1048`) | reglas canónicas, hechos | resultado derivado o `UNANSWERABLE_*` / `RETRIEVAL_UNAVAILABLE` | `decisions.grounded_public`, envelope (`deterministic_authority.py:489-506`) | AUT (consultas ejecutables) | sí (READY_TO_FINALIZE) | sí (vía envelope) | nada puede contradecir un envelope autoritativo | `test_evidence_reasoning.py`, `test_fail_closed_authority.py` |
| **JEV judgements** (`src/decision/providers/jev.py`, `src/decision/event_judgment.py:90`) | evento/paso + contexto | veredicto, score, noul, choice | `decisions.jev`, `plan.preflight[...]`, `adaptive["quality"]`, gate verdicts | ADV por doctrina | indirecta | **no por doctrina**, sí por 10 conversiones (ver register P1-2) | política puede ignorar señal negativa con evidencia completa (`finalization_policy.py:226-231`) | `test_jev_preflight.py`, `test_judgment_fabric.py`, `test_answerability_engine.py` |
| **planner** (`PlanningState`, `rag/adaptive/plan.py`, `runtime/cognitive_plan.py`) | intención, scope, preflight | plan de retrieval, response plan, source routing | `plan.plan/strategy/response_plan/adaptive_plan/query_views/source_routing/anchor_roles/uncertainty` | ADV | sí (PLANNED) | no | autoridad determinista puede fijar el response contract | `test_adaptive_rag.py`, `test_agent_flow_v2.py` |
| **response planning** (`src/intelligence/response/wiring.py:80`, `deterministic_authority.py:411-470`) | hechos, envelope | contrato de respuesta (response contract) | `plan.response_plan` (`agent_runtime.py:2687`, `orchestrator.py:5016`) | ADV / AUT si viene de envelope | no | no | composer/presenter alteran el texto, no el contrato | `test_response_intelligence.py`, `test_response_composer.py` |
| **claims verification** (`src/runtime/decision_verification.py:768`, `answer_gate` claim checks) | claims del borrador, evidencia | claims no soportados, verdict | `answer.gate`, `decisions.citation_validation`, `derived_guard_public` | AUT dentro del gate | sí (revise) | vía answer_gate | fallo del extractor = "sin claims" (fail-open, `answer_gate.py:409-417`) | `test_response_presentation.py`, `test_derived_guard.py` |

## ACTION

| Componente | Consume | Produce | Campos que modifica | Clase | Transición | Terminal | Sobreescrito por | Tests |
|---|---|---|---|---|---|---|---|---|
| **tool routing** (`src/runtime/tool_routing.py`) | tools disponibles, intención | criterios, estado del agente, respuestas de routing | `plan.preflight`, selección de tool | ADV | no | no | `RUNTIME_TOOL_ROUTING_MODE` off por default en el loop JEV | `test_tool_routing*` |
| **tool authorization** (`src/agents/tools/registry.py:73-93`) | ToolContext, allowlist de agente, permisos del caller | `tool_allowed`, `resolve_allowed_tools` | `tools.allowed` | AUT | no | no | nada en el loop; dispatcher/embed/workflow tienen formas delegadas | `test_agent_security.py:119-206`, `test_mcp_server.py` |
| **tool execution** (`src/agents/tools/guards.py:102-167`) | tool autorizada + args validados | `ToolResult` (observación no confiable) | `tools.used/calls`, `trace`, historial del loop | AUT (ejecuta) | sí (ACTING) | no | rate limiter fail-open; run-guard denegación advisory por default | `test_agent_security.py:360-408`, `test_run_guards_shadow.py` |
| **RunGuards** (`src/runtime/run_guards.py:61-155`) | fase, evento, señales | `TransitionVerdict` (allowed, to_phase, reason_code) | ninguno (tabla) | AUT declarativa, ADV en ejecución | sí (shadow) | sí (`REQUEST_FINALIZE` en tabla) | loop decide; enforcement por flag (default off) | `test_run_guards_shadow.py`, `test_terminal_transitions_allowlist.py` |
| **RunBudgetLedger** (`src/runtime/run_budget.py:194-319`) | attempts de provider, usage, charges | consumo de tokens/costo, planes de tope | `result.*` (tokens/costo/steps), `budget.ledger`, `budget.stop_reason` | AUT (consumo) | sí (corte) | sí (LIMIT_REACHED) | bypass del juez (`record_judge_call`) y `answer_gate` | `test_run_accounting*.py`, `test_provider_attempts.py`, `test_budget_stop_reasons.py` |
| **cost accounting** (`src/runtime/run_accounting.py`) | provider, pricing, JEV, charges | líneas de uso + evento persistido | `result.*`, `usage_events`, contadores Redis | AUT (vía ledger, con bypasses) | no | no | tres writers de totales (register P0-5) | `test_run_accounting.py`, `test_run_accounting_rag.py` |

## AUTHORITY

| Componente | Consume | Produce | Campos que modifica | Clase | Transición | Terminal | Sobreescrito por | Tests |
|---|---|---|---|---|---|---|---|---|
| **DecisionEnvelope** (`src/runtime/decision_envelope.py:95`) | resultado determinista | contrato de autoridad (acción, facts, citations, limits) | `decisions.envelope/envelope_public` (vía `set_envelope`) | AUT | sí | sí | nada: un envelope distinto registra `envelope_conflict` | `test_fail_closed_authority.py`, `test_decision_envelope*` |
| **FinalizationPolicy** (`src/runtime/finalization_policy.py:181-344`) | señales de todos los gates | `FinalizationDecision` (acción, autoridad, reason_code, conflictos) | `decisions.finalization` | **AUT por contrato, ADV en baseline** (hold acotado) | sí | sí (contrato), **sin enforcement en `closure`** | ruta vigente la usa solo para hold/observación | `test_finalization_policy.py`, `test_finalization_golden.py`, `test_finalization_enforcement_scopes.py` |
| **termination gate** (`src/runtime/termination.py:44-93`) | JEV noul, tool calls | stop del loop | vía decisión del loop | ADV | sí | sí (finalize del loop) | política de cierre | `test_termination*`, `test_runtime_policies.py` |
| **answer gate** (`src/runtime/answer_gate.py:512-785`) | borrador, evidencia, JEV | `AnswerGateResult.verdict` (approve/revise/abstain/limits) | `answer.gate`, `answer.answer_state` indirecto, totales del juez | AUT con `mode=on` | sí | sí (abstain) | política convierte abstención JEV en `answer_with_limits` con evidencia canónica | `test_response_presentation.py`, `test_answerability_engine.py` |
| **narrative coverage** (`src/runtime/narrative_coverage.py:607-657`) | cobertura pedida por narrativa | decisión de ronda extra de búsqueda | `knowledge.coverage`, `knowledge.coverage_search_after_complete` | ADV (excluida para ejecutables) | sí | no | invariante rompe si busca con evidencia completa | `test_narrative_coverage.py`, `test_narrative_fast_path.py` |
| **evidence-first gate** (`orchestrator.py:5087-5199`) | retrieval failure, autoridad, sufficiency | estado de respuesta temprano | `answer.public_state`, `decisions.*` | AUT (early return) | sí | sí | long-context stop puede cancelar la abstención derivada | `test_evidence_first_gate.py` |
| **FINAL_AUTHORITY_LOCK** (`decision_envelope.py:466`, `agent_runtime.py:3371`, `orchestrator.py:5902`) | envelope autoritativo + texto | acción `preserved / rebuilt / blocked` | steps de traza; texto final | AUT (consistencia texto-decisión) | no | no | composer solo si no contradice el envelope | `test_derived_guard.py`, `test_decision_evidence*`, `test_traceability_v2.py` |
| **presentation / final answer** (generador + `runtime/response_composer.py` + `runtime/finalizer.py`) | evidencia, contract, envelope | texto final, citas | `answer.text/citations` vía `finalize_state` | ADV frente al envelope; AUT del texto | sí | sí (si el envelope lo permite) | strict block reemplaza el texto por mensaje no concluyente | `test_response_composer.py`, `test_finalizer*`, `test_answer_state_texts.py` |
| **failure taxonomy** (`src/runtime/failure_taxonomy.py`) | errores de provider/retrieval/tool/budget | clasificación de fallo | `answer_state`, `budget.stop_reason` | AUT (semántica) | sí | sí (BLOCKED) | paths con `except Exception` genéricos pueden borrar la causa | `test_failure_taxonomy.py` |
| **trace / Execution Story** (`src/rag/traceability.py:1807`, `runtime/story_view.py`, `rag/execution_narrative.py`) | steps, spans, decisiones | historia operacional | ninguno del estado del run | OBS | no | no | nadie | `test_traceability_v2.py`, `test_execution_story*` |
| **enforcement** (`src/runtime/enforcement.py:19-118`) | settings + config de agente | etapas armadas, holds | ninguno | AUT (config) | sí (hold) | indirecto | override de agente puede desarmar el global | `test_finalization_enforcement_scopes.py`, ratchet S0 |

## Registro de autoridad (verificado por ratchet)

Cada estado crítico declara su autoridad canónica. El ratchet
`tests/test_authority_ownership.py` verifica que el símbolo exista y que este
documento no pierda componentes.

| Estado crítico | Autoridad canónica |
|---|---|
| `terminal_phase` | `finalization_policy.evaluate_finalization` |
| `finalization_contract` | `decision_envelope.DecisionEnvelope` |
| `run_state` | `run_state.AgentRunState` |
| `cost_totals` | `run_budget.RunBudgetLedger` |
| `accounting_recorder` | `run_accounting.record_llm_call` |
| `evidence_measure` | `evidence.assess_sufficiency` |
| `tool_authorization` | `tools.registry.tool_allowed` |
| `tool_execution` | `tools.guards.execute_tool_guarded` |
| `trusted_context` | `entities.TenantContext` |
| `knowledge_scope` | `knowledge_scope.KnowledgeScope` |
| `failure_classification` | `failure_taxonomy.classify_failure` |
| `answer_state_vocabulary` | `answer_state.select_answer_state` |
| `run_guards` | `run_guards.evaluate_transition` |
| `enforcement_stages` | `enforcement.enforcement_stages` |

## Resumen de autoridad por pregunta

| Pregunta | Respuesta inequívoca en baseline |
|---|---|
| Estado del run | `AgentRunState` (3 writers de fase) |
| Modificar cada estado | métodos `observe*`/`set_*`, con excepciones directas (ratchet S0 las fija) |
| Evidencia suficiente | **ambigua**: `EvidenceSufficiency` vs `EvidenceQuality` |
| Autorizar acción | `registry.tool_allowed` en el loop; formas delegadas fuera del loop |
| Ejecutar acción | `execute_tool_guarded` |
| Decidir el fin | **ambigua**: texto en `finish()` vs `FinalizationPolicy` (sin enforcement en closure) |
| Costo | `RunBudgetLedger` (con 3 bypasses) |
| Decisión definitiva | `DecisionEnvelope` |
| Redactar respuesta | generador + composer + LOCK + strict block |
