# Architecture Ownership Map — AFTER

Estado: cierre de la fase de convergencia de autoridad (slices S0–S7).
Baseline: `5cd3dec1812955c28dd6ce338f56322022a2079c` (CI 10/10 verde).
Mapa BEFORE: `01-ownership-map-before.md`.

## Respuesta a las nueve preguntas (una autoridad por respuesta)

| Pregunta | Autoridad única | Aplicador / contrato | Ratchet que lo protege |
|---|---|---|---|
| ¿Quién posee el estado de un run? | `AgentRunState` (`run_state.py`) | métodos `observe*`/`set_*`; `finish()` aplica la fase | `test_authority_ownership.py` (familias de writers) |
| ¿Quién puede modificar cada estado? | el writer declarado por familia (allowlist con justificación) | `decision_writes`, `answer_writes`, `closure_writes` | `test_authority_ownership.py` |
| ¿Quién decide que existe evidencia suficiente? | `evidence.assess_sufficiency` mide; `evidence_semantics.classify_evidence_condition` clasifica la condición; `finalization_policy` resuelve | `COMPLETE_STOPS`/`PARTIAL_STOPS` fijados al motor | `test_evidence_semantics.py` |
| ¿Quién autoriza una acción? | `tools.registry.tool_allowed` (triple gate) en el loop; handlers del dispatcher declaran y verifican su permiso | contrato de handlers | `test_action_plane_authority.py` |
| ¿Quién ejecuta una acción? | `tools.guards.execute_tool_guarded` | 6 call sites declarados | `test_authority_ownership.py` (patrón de ejecución) |
| ¿Quién decide que el run termina? | `finalization_policy.resolve_closure_phase` (reducer) | `finish(phase_override=...)` | `test_closure_authority.py` + allowlist de transiciones |
| ¿Quién posee el costo? | `RunBudgetLedger` (`account_llm_usage`, `account_embedding_usage`, `account_judge_usage`, `account_charge`) | `run_accounting` solo invoca | `test_cost_authority.py` + familia `result_totals` |
| ¿Quién produce una decisión definitiva? | `DecisionEnvelope` + `FinalizationPolicy` | `decisions.closure` publica la resolución aplicada | `test_fail_closed_authority.py`, `test_closure_authority.py` |
| ¿Quién redacta la respuesta final? | generador + `FINAL_AUTHORITY_LOCK` + composer | el strict block (fail-closed) puede reemplazarla | `test_derived_guard.py`, `test_closure_authority.py` |

## Deltas de autoridad por componente (BEFORE → AFTER)

| Componente | BEFORE | AFTER |
|---|---|---|
| `AgentRunState.phase` | 3 módulos escribían; la fase terminal se derivaba del texto | un solo aplicador canónico (`_apply_terminal`); `try_advance` rechaza terminales; override post cierre solo no-concluyente (hardening) |
| `terminal_phase_for` | fuente de la fase terminal | **oráculo de consistencia**: su divergencia es invariante crítico; un fallo del reducer NO reabre el mapper (FAILED estructurado) |
| `FinalizationPolicy` | advisory + hold en 3 etapas; `closure` sin enforcement | autoridad del cierre en todos los modos; `closure_not_authorized` / `closure_authority_mismatch` / `closure_authority_failed` |
| `RUNTIME_RUN_STATE_STRICT` | documentado, inexistente (no-op) | campo real (default `off`), respetado, canary por org; **piso monotónico**: la config del agente solo refuerza |
| `RUNTIME_FINALIZATION_ENFORCE` | el scope más específico reemplazaba (agente podía desarmar) | unión de scopes (piso): ninguno resta etapas |
| JEV | podía actuar con `shadow_mode`; el preflight podía bloquear con un juicio solo | shadow no actúa; matriz determinista × JEV: un juicio solo nunca da acción definitiva |
| RunGuards | advisory por default sin clasificación | `GUARD_CLASS`: SECURITY/CORRECTNESS duplican autoridades canónicas; RESOURCE respeta el ledger |
| Flags contradictorios | 10 combinaciones pinneadas sin consecuencia | INVALID = startup failure; DANGEROUS = error en producción sin acknowledgement |
| `RunBudgetLedger` | autoridad con bypass del juez | autoridad única de totales; el juez entra por `account_judge_usage` |
| `usage_events` (`jev_judge:*`) | repetían tokens del juez (doble conteo) | 0 tokens + `judge_tokens`/`cost_source` en `routing`; costo del juez intacto |
| `budget.last_cut_reason` | representación muerta | eliminada; `stop_reason` es la única representación |
| Sufficiency | dos modelos rivales (`EvidenceSufficiency` / `EvidenceQuality`) | medición única + vocabulario de condición (`evidence_semantics`); `EvidenceQuality` queda como proyección del camino RAG (deuda S11) |
| Condición de evidencia | sin vocabulario; conflaciones invisibles | 9 condiciones canónicas + 2 conflictos medidos (métricas low-cardinality) |
| Permisos de workflow | `permissions` vacío escalaba a permisos de sistema en silencio | `resolve_workflow_permissions` fail-closed; contexto de sistema explícito |
| Handlers del dispatcher | autorización supuesta | contrato testeado por handler + behavioral (deny corta antes de ejecutar; shadow no ejecuta) |
| `decisions` durante el run | autoridad local hasta la finalización | publicación en el event boundary (SQL y envelope) |

## Campos críticos y su writer (AFTER)

| Campo | Writer | Tipo |
|---|---|---|
| `phase` | `run_state.try_advance` / `finish` | transición validada |
| `decisions.closure` | `DecisionState.observe_closure` | resolución del cierre |
| `decisions.finalization` | `finalization_policy.resolve_closure` | observabilidad (divergencia) |
| `answer.text/answer_state/citations` | `finalize_state` (+ strict block declarado) | cierre |
| `result.cost/prompt_tokens/completion_tokens/total_tokens/embedding_tokens` | `RunBudgetLedger` (4 métodos) | autoridad de consumo |
| `budget.stop_reason` | `agent_runtime._mark_budget_stop` | corte (8 razones) |
| `evidence.sufficiency/registry/selection` | `EvidenceView.observe` (reducer del estado) | medición |
| `tools.allowed/used/calls` | `ToolState.set_allowed/note_call` | acción |
| `organization_id` (ToolContext) | atributo de objeto confiable (AST-verificado) | frontera de confianza |
| `plan.authorized_scope` | `authorized_scope.scope_from_agent_config` | restrictivo |

## Registro de autoridad verificado por ratchet

Igual que en el mapa BEFORE (14 símbolos). Añadidos en la fase de convergencia:

| Estado crítico | Autoridad canónica |
|---|---|
| `closure_resolution` | `finalization_policy.resolve_closure_phase` |
| `evidence_condition` | `evidence_semantics.classify_evidence_condition` |
| `workflow_permissions` | `workflows.engine.resolve_workflow_permissions` |

Añadidos en el hardening de autoridad (H0–H9, `08-hardening-report.md`):

| Estado crítico | Autoridad canónica |
|---|---|
| `closure_failure_resolution` | `finalization_policy.closure_authority_failure` |
| `terminal_application` | `run_state.AgentRunState` (`_apply_terminal` / `apply_closure_override`) |
| `authorization_matrix` | `decision.preflight.resolve_authorization` |
| `shadow_authority` | `decision.settings.DecisionEngineSettings.acts` |
| `safety_floor` | `run_state.strict_mode_enabled` / `enforcement.enforcement_stages` |
| `config_validation` | `core.config_rules.assert_runtime_config` |
| `guard_classification` | `run_guards.GUARD_CLASS` |
 |
