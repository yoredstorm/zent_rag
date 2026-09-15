# Zent Cognitive Workflows — Phase 0 Architecture Audit

> **Status:** Phase 0 (auditoría) completa. **Programa completo: Fases 1–8 implementadas** + E2E 1–3 (brief §31–§33). Modos de conocimiento, extract/compare/conflicts, investigate, contexto/presets del agente, join/merge/filter y costo, aprobación con evidencia, panel de contexto y narrativa de ejecución.
> **Fecha:** 2026-09-14
> **Base:** `feat/knowledge-cognitive-os` @ `33c238c` (Workflow Semantic Core Fases 0–8 + bloque 8.1).
> **Prerrequisito verificado:** `docs/architecture/workflow-semantic-core.md` ya existe y está implementado:
> `WorkflowContext`, contribuciones, `WorkflowValue`, `ContextAssembler`, `node-catalog`, `data-catalog`,
> evidencia/claims por referencia, persistencia (migraciones 115/116), Execution Inspector, hidratación resume/parcial.
> **Misión:** WORKFLOW = COORDINATION. KNOWLEDGE = TRUTH + EVIDENCE. AGENT = REASONING. DATA = CURRENT BUSINESS STATE.
> ACTION = EFFECT ON THE WORLD.
> Donde este documento y el código discrepen, **el código manda**.

---

## 0. Non-negotiables (ley del programa)

| Ley | Ancla actual |
|---|---|
| NO DUPLICATE COGNITIVE OS | `src/platform/cognitive/` (`CognitivePlanningService`, `CognitiveExecutor`) es el único motor de investigación |
| NO DUPLICATE STRUCTURED RETRIEVAL | `StructuredRetriever` (`src/rag/retrieval/structured.py`) |
| NO ANOTHER AGENT LOOP | `AgentRuntime.run` (`src/agents/runtime/agent_runtime.py:274`) |
| NO AUTOAPPROVE CLAIMS | `INFERRED != APPROVED`; `ClaimVerificationStatus.PROPOSED` es el único estado de creación |
| NO UNFILTERED CONTEXT TO LLM | `WorkflowContextAssembler` + `context_reads` + caps (Semantic Core) |
| NO INFO OUTSIDE ACL | retrieval filtra por org/workspace/role antes de rankear; refs de evidencia/claims se validan por org |
| NO CHAIN OF THOUGHT | `chain_of_thought_exposed=false`; inspector solo datos estructurados |
| NO LLM FOR SIMPLE CONDITIONS | `condition` evalúa en código (`_eval_condition`/`conditions.py`) |
| NO NEW ENGINE | `execute_graph` (runtime) + `node registry` existentes |

---

## 1. Prerequisite check — qué ya da el Workflow Semantic Core

Verificado contra código (no contra el prompt):

- Contexto compartido por run con secciones tipadas y `security` runtime-only (`context.py`).
- Contribuciones validadas con allowlist de `context_writes` (`contributions.py`, runtime).
- `WorkflowValue` + `Provenance` (`values.py`); `node_provenance` en nodos.
- Ensamblado acotado por nodo/agente (`context_assembler.py`); el agente recibe `AgentRunRequest.context` (first-class).
- Catálogo backend unificado (`node_catalog.py`, `GET /node-catalog`) + Data Catalog (`data_catalog.py`, `GET /workflows/{id}/data-catalog`).
- `kb_query` V2 tras flag con `citations` + `evidence_ids` reales del ledger; `query_business_data` con `rows/columns` y evidencia SQL.
- Persistencia: `workflow_context_contributions` + `workflow_run_contexts` (115) y `workflow_run_events` (116).
- Inspector: `context`, `contributions`, `evidence_refs`, `claim_refs`, `decisions`, `findings`, `artifacts`, `actions`, `events`.
- Planner IA consume el catálogo (`planner_hints`).

**Consecuencia:** este programa NO reconstruye la plomería. Extiende semántica de nodos, modos de conocimiento, salida de agente y narrativa.

---

## 2. CURRENT — seams de integración (verificados)

### 2.1 Nodo Knowledge (`kb_query`)

- Handler `_exec_kb_query` (`src/platform/workflows/nodes.py:470` aprox.): valida KB del tenant; con `RAG_KNOWLEDGE_V2_ENABLED` usa `_kb_query_v2` (StructuredRetriever + `build_citations` + `GroundingLedgerRecorder`), si no V1 `HybridRetriever`. Output: `chunks, count, documents, citations, evidence_ids, method`.
- **No hay modos**: search/answer/find_evidence/extract_facts/compare/check_conflicts/investigate no existen como concepto.
- La pila grounded completa (retriever + LLM + `GroundingService` + recorder) está implementada **solo** en la ruta `POST /api/v1/knowledge/workspaces/{corpus_id}/chat` (`src/api/routes/knowledge_workspaces.py:224`): arma prompt con contexto, `get_llm_provider().generate`, `GroundingService().ground`, registra evidencia. Es el seam a generalizar.
- `GroundedAnswer` (`src/rag/grounding/models.py:66`) trae `answer, claims, citations, confidence, missing_information, conflicts, sources_used`.
- Claims in-memory de grounding vs `ClaimRecord` del ledger: **hoy el nodo no escribe claims**; el único productor de claims es `CognitiveExecutor` (`provenance=INFERRED`, estado `PROPOSED` + `attach_evidence`).

### 2.2 Cognitive OS

- `CognitivePlanningService.create_run(query, scope, budget, created_by)` y `CognitiveExecutor.execute_run(organization_id, run_id, scope)`.
- `CognitiveScope` (`src/core/domain/cognitive.py:242`): org/workspace/user/role/groups/source_ids/knowledge_base_id.
- Rutas `/api/v1/cognitive/runs` (create/execute/curate) gate `_require_cognitive_enabled()` + permiso `knowledge:write`; el ejecutor escribe `EvidenceRecord`/`ClaimRecord`.
- `conflict_detector` verifica `find_conflicting` + `classify_conflict` + `propose_resolution`; `critic`/`fact_checker`/`synthesizer` producen `answer`, conflicts, critique, debate.
- Inspector cognitivo sin CoT (`src/platform/cognitive/inspector.py`).
- **Nada de esto está expuesto como nodo de workflow** (ni como modo). No hay `CALLS_COGNITIVE` en `_CAPABILITY_PERMISSION`.

### 2.3 Grounding / evidencia / claims

- Ledger operativo: `evidence_ledger` / `claim_ledger` (migración 103), repos org-scoped, `attach_evidence`, `find_conflicting`.
- `GroundingLedgerRecorder.record_evidence` escribe una fila por cita.
- `context_store.filter_persistable_applied` + `validate_context_refs` validan refs por org (persistencia y pre-LLM).

### 2.4 Nodo Agent (`llm`)

- `_exec_llm` (`nodes.py`): resuelve prompt por refs, carga agente vivo, ensambla `AssembledContext` (si `config.context_reads`), llama `AgentRuntime`, aplica `output_schema` (`_apply_output_schema`) y contribuye `decisions`/`findings` con provenance `origin_kind="agent"`.
- `AgentRunRequest.context` (Semantic Core) ya transporta contexto estructurado; `AgentRuntime` lo renderiza como bloque acotado.
- **Gaps:** sin `context_mode` AUTO (hoy exige lista explícita), sin presets de resultado (TEXT/DECISION/CLASSIFICATION/BUSINESS_ASSESSMENT), sin tipo `DecisionResult`, sin `failure_kind` tipado (solo `error` string y `structured:false` + `schema_errors`).

### 2.5 Lógica: join / merge / filter / condition / for_each

- `join` (`_exec_join`): `{"merged": true, "values": {node_id: output}}` — posicional por id, sin nombres de negocio.
- `merge` (`_exec_merge`): primer predecesor disponible; sin estrategia configurable.
- `filter` (`_exec_filter`): una condición `field/operator/value`; sin lista de condiciones ni selección tipada de listas.
- `condition` (`_exec_condition`): árbol AND/OR (`conditions.py`) o legacy; refs resueltas (`_resolve_condition_field`); UX con `ConditionBuilder` + DataPicker.
- `for_each`: `collection/max_iterations/concurrency/fail_policy`; sin advertencia de costo por agentes dentro del loop (el estimador lo insinúa con `bulk_warning`).

### 2.6 Aprobaciones humanas

- Nodo `human_approval` (`_exec_human_approval`) crea fila en `workflow_approvals` con `node_id/action/summary/expires_at`; el run queda `pending_approval` y se reanuda con `decide_approval`.
- Rutas: `GET /runs/{run_id}/approvals`, `POST /runs/{run_id}/approvals/{approval_id}/decide` (`src/api/routes/workflows.py:400`).
- **Gap:** la aprobación NO guarda snapshot de contexto (decisión del agente, evidencia, citas, datos). **No hay UI de aprobación en el portal** (solo badge `pending_approval` en canvas/inspector).

### 2.7 business_result

- `_exec_business_result` persiste `BusinessResult` (title/summary/section/importance/metrics/insights/entities) + contribuye artifact. `business_results` ya guarda `evidence`, `actions_taken`, `recommendations` (migración 090).
- **Parcial:** no incorpora automáticamente `decision`/`evidence_refs` del contexto.

### 2.8 Estimación de costo

- `capabilities.cost_estimate` (`src/platform/workflows/capabilities.py:240`): solo precios de `integration_actions` (marketplace/business_node), `calls_per_run`, `monthly`, `bulk_warning`.
- **No estima** conocimiento, agentes ni cognitive calls; no hay warnings de "agente dentro de loop" ni "investigación en cada evento".

### 2.9 Portal (estudio)

- `NodeConfigPanel` + `BusinessParameterForm` renderizan `NodeBusinessSchema`; `DataPicker` consume `data-catalog`; `ConditionBuilder`; `NotificationBuilder`; `WorkflowRunInspector` (contexto/evidencia/decisiones/artefactos/acciones/eventos).
- **No existe** panel de "Contexto disponible" durante la edición; no hay vista narrativa del run; no hay panel de aprobación.

### 2.10 Retrieval de hechos y conflictos (reuso potencial)

- `src/platform/data_onboarding/document_facts.py`: `extract_document_facts(bytes, filename)`, `complete_document_facts(partial)`, `_llm_facts(text)` (privada), `_merge_facts`; statuses con HITL.
- `src/intelligence/source_conflict.py`: `SourceConflictAnalyzer.analyze(...)`.
- `src/intelligence/temporal.py`: `TemporalResolver.resolve_version(...)`.
- `src/core/domain/entities.py`: `KnowledgeEntity`/`KnowledgeFact`/`KnowledgeRelationship` inertes (sin callers), `CanonicalKind.ENTITY` genérico.

---

## 3. GAPS (mapeados al brief)

| # | Gap | Sección | Evidencia |
|---|---|---|---|
| G1 | Sin modos de conocimiento (`operation`) | §2–§9 | `_exec_kb_query` único camino |
| G2 | ANSWER stack solo vive en la ruta de chat (acoplada a corpus/workspace + flags + `knowledge:read`) | §4 | `knowledge_workspaces.py:224` |
| G3 | FIND_EVIDENCE: sin coverage ni assertion-targeted retrieval | §5 | no existe |
| G4 | EXTRACT_FACTS: extracción LLM de hechos sin seam público reutilizable | §6 | `_llm_facts` privada |
| G5 | COMPARE: sin diff grounded con contexto temporal | §7 | no existe |
| G6 | CHECK_CONFLICTS: analyzer y ledger `find_conflicting` no expuestos a workflow | §8 | `SourceConflictAnalyzer` sin consumidores de workflow |
| G7 | INVESTIGATE: Cognitive OS desacoplado del runtime | §9, §25 | sin nodo/modo ni permiso |
| G8 | Fallos de conocimiento/agente como strings | §26–§27 | `NodeOutcome.error` |
| G9 | Agent input: sin modo AUTO ni selección visual de contexto | §12–§13, §17 | `config.context_reads` manual |
| G10 | Sin presets de resultado estructurado ni `DecisionResult` | §14–§15 | `output_schema` crudo |
| G11 | Join por node_id, sin ramas nombradas | §19 | `_exec_join` |
| G12 | Merge sin estrategias explícitas | §20 | `_exec_merge` |
| G13 | Filter de una sola condición y sintaxis de campo | §21 | `_exec_filter` |
| G14 | Condition sin integración de contratos semánticos para decisiones del agente en UI | §16 | DataPicker no lee `output_schema` del nodo |
| G15 | for_each sin advertencia de costo/agente | §23 | estimador mínimo |
| G16 | Sin panel "Contexto disponible" en el editor | §24 | solo inspector de run |
| G17 | Aprobaciones sin snapshot de evidencia/contexto y sin UI | §28 | `workflow_approvals` (acción/resumen) |
| G18 | business_result no absorbe decisión/evidencia del contexto | §29 | handler fijo |
| G19 | Sin narrativa de ejecución en lenguaje de negocio | §30 | inspector técnico |
| G20 | Costo sin agentes/knowledge/cognitive ni warnings | §34 | `cost_estimate` |

---

## 4. TARGET — diseño objetivo

### 4.1 Knowledge operations (G1–G7)

Mantener `node_type="kb_query"` y añadir `config.operation` (default `"search"`, 100% backward compatible):

```text
search | answer | find_evidence | extract_facts | compare | check_conflicts | investigate
```

Resultado tipado común (aditivo en output):

```json
{
  "operation": "answer",
  "status": "ok | knowledge_not_found | insufficient_evidence | permission_restricted | conflicting_sources | not_supported",
  "answer": "...", "citations": [], "evidence_ids": [],
  "claims": [{"claim_id": "...", "text": "...", "status": "proposed|supported|...", "evidence_ids": []}],
  "entities": [{"kind": "policy", "label": "..."}],
  "conflicts": [], "coverage": {...}, "confidence": 0.0,
  "budget": {"llm_calls": 1, "tokens": 1234},
  "reason_codes": ["..."]
}
```

Implementación por modo (reuso, sin motores nuevos):

- **search**: camino actual (V2/V1) + `status`.
- **answer**: generalizar la pila de `workspace_chat`: `StructuredRetriever` + prompt con contexto no confiable + `get_llm_provider().generate` + `GroundingService().ground` + recorder. Scope: `knowledge_base_id` (KB V2) o workspace del run.
- **find_evidence**: retrieval orientado a una assertion/pregunta; `coverage = fuentes con soporte / fuentes consultadas`; escribe evidencia y devuelve `evidence_ids`.
- **extract_facts**: reusar `document_facts` (exponer wrapper público `extract_facts_from_text(text)` sobre `_llm_facts` + reglas) y `CognitiveExecutor` como alternativa; escribe `ClaimRecord(PROPOSED)` + `attach_evidence`; nunca aprueba.
- **compare**: retrieval A/B (dos queries o dos fuentes), diff por LLM grounded + `TemporalResolver` para vigencia; devuelve `differences[]`, `claims`, `evidence_ids`, `temporal_context`.
- **check_conflicts**: `SourceConflictAnalyzer.analyze` + `ClaimLedgerRepository.find_conflicting`; devuelve `conflicts[]` con `severity`, `evidence_ids`, `resolution_status` (`proposed|unresolved|resolved`). Nunca resuelve solo.
- **investigate**: `CognitivePlanningService.create_run` + `CognitiveExecutor.execute_run` con `CognitiveScope` derivado de `NodeContext` (org/workspace/actor/role) y `budget` del nodo; nueva capability `CALLS_COGNITIVE` → permiso `knowledge:write`; gate por flag cognitivo existente. Salida mapeada a `answer/findings/claims/evidence/conflicts/confidence`.

Contribuciones de contexto por modo: `knowledge` (answer/sources), `evidence` (refs), `claims` (refs del ledger), `entities` (etiquetas `kind/label`, sin identidad canónica todavía; D5 previo).

### 4.2 Agent workflow adapter (G9–G10)

- `config.context_mode`: `"manual"` (actual), `"auto"` (unión de `context_reads` por defecto + contribuciones de nodos predecesores), `"none"`.
- `config.context_selectors`: lista explícita (`trigger`, `data:<node_id>`, `knowledge:<node_id>`, `evidence`, `claims`, `decisions`, `findings`) editada con checkboxes en UI; el assembler ya soporta el filtrado.
- UI muestra "Contexto incluido automáticamente": N resultados, M evidencias, K claims (del `AssembledContext.sections_used` + conteos que el nodo devuelve en output `context_summary`).
- Presets de resultado (`config.output_type`): `text`, `decision`, `classification`, `business_assessment`, `json_schema` (custom). Generan `output_schema` canónico en backend (`parameters.py`/nuevo `output_presets.py`) y se validan con `validate_json_answer`; respuesta inválida → `structured:false`, `schema_errors`, `status="invalid_output"`, sin contribución de decisión.
- `DecisionResult` tipado (nuevo `src/platform/workflows/decisions.py`): `decision, status, confidence, reasons, evidence_refs, claim_refs, requires_review`. Se construye desde el JSON validado; contribuye `decisions` (ya existe la sección) y se refleja en output root para refs (`{{nodes.x.output.decision.risk}}` sigue funcionando).

### 4.3 Join / Merge / Filter / for_each (G11–G13, G15)

- **join**: output `{"merged": true, "branches": {"<label>": output}, "values": {node_id: output}}` con nombre = `label` del nodo (`merge`/`join` config `branch_labels` opcional) → fallback a `node_type` → `node_id`; contribuye `data` con `branches` nombradas. `values` se conserva (compat).
- **merge**: `config.strategy` = `first_available` (legacy) | `first_success` | `prefer_source` (+`source_node_id`) | `fallback` (+`sources[]`); el handler elige entre `rctx.inputs`; output conserva `first`/`values` y agrega `strategy`/`selected_from`.
- **filter**: `config.conditions[]` (AND) con `{field, operator, value}` reutilizando operadores del árbol de condiciones; legacy `field/operator/value` sigue. Output `filtered/count/total`.
- **for_each**: `expected_items`/`bulk_size` para el estimador; advertencia en UI si contiene nodos `llm`/`kb_query`/`investigate`.

### 4.4 Failure semantics (G8)

- Nodos knowledge: `status` + `reason_codes` en output (no en `error`); `error` queda para fallos técnicos. Condition puede ramificar por `{{nodes.kb.output.status}}`.
- Nodo agent: `status` ∈ `ok | low_confidence | insufficient_context | tool_error | budget_exceeded | permission_denied | invalid_output`; `AgentRunResult.status` (`completed|limit_reached|error`) + `cost`/tokens se mapean a este enum en el adaptador.
- `NodeOutcome` gana `failure_kind: str | None = None` (aditivo) para que runtime/inspector distingan; el run sigue fallando igual en errores técnicos.

### 4.5 Approval con evidencia (G17)

- Migración `117_workflow_approval_context.py`: `workflow_approvals.context JSONB NOT NULL DEFAULT '{}'` (snapshot acotado: `decision`, `evidence_refs`, `citations`, `data_summary`, `knowledge_summary`, `cost_ms`; nunca `security` ni filas crudas completas).
- `_exec_human_approval` llena `context` desde `NodeContext.context` (solo secciones permitidas + caps).
- `GET /runs/{run_id}/approvals` lo devuelve; panel portal (nuevo `WorkflowApprovalPanel`) muestra recomendación, evidencia, citas y datos con botones Aprobar/Rechazar (`workflow_approvals:approve`).

### 4.6 Context viewer + narrativa (G16, G19)

- Editor: panel "Contexto disponible" que combina `data-catalog` + `context_writes` por nodo + contribuciones del último run (`contributions`), agrupado por sección. Solo lectura.
- Narrativa: helper backend `run_story(run_detail) -> list[str]` en `readiness.py`/`engine.py` (lenguaje de negocio con `business_name` del catálogo; estados y acciones; sin CoT) expuesto como `story` en `run_detail`; el inspector la muestra arriba de los pasos.

### 4.7 Cost awareness (G20)

- `capabilities.cost_estimate` suma:
  - knowledge calls: `kb_query` (search/find_evidence) como llamadas LLM/embedding estimadas, `answer`/`compare`/`investigate` como llamadas LLM;
  - agent calls: `llm` × tokens estimados (sin precisión monetaria falsa; reportar "llamadas IA");
  - cognitive: `investigate` × presupuesto declarado;
  - `warnings[]`: `agent_inside_loop`, `investigation_per_event`, `expensive_schedule`, `bulk_size>100`.
- UI: `WorkflowHealthBar` muestra warnings y desglose, no solo S/.

### 4.8 business_result (G18)

- Params nuevos (`decision`, `evidence_ids`, `artifact_ids` opcionales) con fallback: si están vacíos, toma `decisions[c-1]` y `evidence_refs` del contexto del run; persiste en `business_results.metrics/entities` sin duplicar.

---

## 5. REUSE

| Componente | Uso |
|---|---|
| `StructuredRetriever` + `V2RetrievalOptions` | todos los modos knowledge |
| `GroundingService`/`GroundedAnswer`/`build_citations` | answer/compare |
| `GroundingLedgerRecorder` + `evidence_ledger` | refs de evidencia |
| `ClaimLedgerRepository` (`upsert`/`attach_evidence`/`find_conflicting`) | extract_facts/check_conflicts |
| `CognitivePlanningService`/`CognitiveExecutor` | investigate |
| `SourceConflictAnalyzer`/`TemporalResolver` | compare/check_conflicts |
| `document_facts._llm_facts` (+ wrapper público) | extract_facts |
| `AgentRuntime` + `AgentRunRequest.context` + `_apply_output_schema` | agent node |
| `WorkflowContext`/`ContextAssembler`/contribuciones | transporte y scope |
| `node_catalog`/`parameters.py` | operación, presets, UI |
| `cost_estimate` + `WorkflowHealthBar` | costo |
| `run_detail` + `WorkflowRunInspector` | narrativa y panel |
| `workflow_approvals` | snapshot de aprobación |

---

## 6. FILES TO KEEP / MODIFY / CREATE

### Keep (sin cambios)
`ir.py`, `runtime.py` (salvo `failure_kind` aditivo), `events.py`, `watchers.py`, `contributions.py`, `context*.py`, ledgers, `AgentRuntime`, `Cognitive*`, `knowledge_workspaces.py`.

### Modify
| Archivo | Cambio | Fase |
|---|---|---|
| `src/platform/workflows/nodes.py` | `operation` en `kb_query`; modos; `failure_kind`; join/merge/filter; for_each; `_exec_llm` (context_mode/presets/DecisionResult); approval context | 1–6 |
| `src/platform/workflows/parameters.py` | parámetros de operación, context selectors, output type, merge strategy, filtros múltiples | 1–5 |
| `src/platform/workflows/node_catalog.py` | metadata por modo (when_to_use, requires, supports_*), presets | 1–4 |
| `src/platform/workflows/decisions.py` (nuevo) | `DecisionResult` + builder | 4 |
| `src/platform/workflows/output_presets.py` (nuevo) | schemas canónicos de resultado | 4 |
| `src/platform/workflows/capabilities.py` | `cost_estimate` con IA/cognitive + warnings | 5 |
| `src/platform/workflows/engine.py` | `run_detail.story`; approvals con contexto; `context_summary` | 4, 6, 8 |
| `src/api/routes/workflows.py` | approvals ya existen (extender respuesta) | 6 |
| `src/infrastructure/db_init/versions/117_*.py` | `workflow_approvals.context` | 6 |
| `portal/src/components/NodeConfigPanel.tsx` / `workflowStudio/*` | UI de modos, contexto, presets, filtros, aprobación | 1–6 |
| `portal/src/components/WorkflowRunInspector.tsx` | narrativa + aprobaciones | 6, 8 |
| `src/platform/data_onboarding/document_facts.py` | wrapper público `extract_facts_from_text` | 2 |

### Create
`tests/test_workflow_knowledge_modes.py`, `tests/test_workflow_agent_context.py`, `tests/test_workflow_join_merge.py`, `tests/test_workflow_approval_context.py`, `tests/test_workflow_narrative.py`, `tests/test_cognitive_workflows_e2e.py` (tests 1–3 del brief), `portal/src/components/workflowStudio/WorkflowContextPanel.tsx`, `portal/src/components/workflowStudio/WorkflowApprovalPanel.tsx`, `docs/architecture/cognitive-workflows.md` (este doc).

---

## 7. DB CHANGES

- **117**: `ALTER TABLE workflow_approvals ADD COLUMN IF NOT EXISTS context JSONB NOT NULL DEFAULT '{}'` + índice `(run_id)` ya cubierto por FK/consultas existentes. Sin tabla nueva.
- Sin tablas nuevas de knowledge/claims/entities: ledger existente.
- `ensure_context_tables` no cambia; approvals ya tienen tabla (088).

---

## 8. BACKWARD COMPATIBILITY

- `kb_query` sin `operation` = `search` (comportamiento actual exacto).
- `join.values`, `merge.first`, `filter.field/operator/value`, `condition` legacy intactos.
- `human_approval` sin contexto funciona igual (columna default `{}`).
- `output_schema` existente sigue válido; presets son azúcar.
- Nuevas claves de output son aditivas; refs existentes no cambian.
- Flags: ANSWER/EXTRACT_FACTS requieren `RAG_KNOWLEDGE_V2_ENABLED`; INVESTIGATE requiere el flag cognitivo; sin flag → `status="not_supported"` con razón (no error técnico).

---

## 9. RISKS

**Migración**
1. `workflow_approvals.context` con snapshot grande: caps duros (solo refs + decisión + citas truncadas).
2. `operation` en graphs viejos: default `search`; validación en `readiness.py` (warning si `operation` desconocido).
3. Claims PROPOSED desde workflow: deben nacer `PROPOSED` y nunca pisar `evidence_ids` (ley del ledger).

**Seguridad**
4. INVESTIGATE corre con permisos del actor (`knowledge:write`); scope derivado de `NodeContext`, nunca del graph.
5. ANSWER/COMPARE con LLM: contexto marcado como no confiable; sin CoT persistido.
6. Approval snapshot: nunca `security` ni permisos efectivos; evidencia por referencia validada por org.
7. `status="permission_restricted"` debe reflejar denegaciones ACL pre-retrieval, no post-hoc.

**Performance**
8. ANSWER/INVESTIGATE agregan LLM calls: budget por nodo (`max_tokens`, `max_cost`, `max_llm_calls`) + caps del assembler.
9. `check_conflicts` sobre claims: `find_conflicting` indexa por subject+predicate; limitar a los claims del run.
10. `for_each` con agentes/knowledge multiplica llamadas: warning + `max_iterations`.

---

## 10. PHASES + E2E

| Fase | Alcance | Commit sugerido |
|---|---|---|
| 1 | Knowledge modes skeleton + typed result + status/failure codes; SEARCH intacto; ANSWER y FIND_EVIDENCE con V2 grounding + ledger + claims PROPOSED; UI select de operación | `feat(workflows): knowledge operations and typed results` |
| 2 | EXTRACT_FACTS (document_facts), COMPARE, CHECK_CONFLICTS (SourceConflictAnalyzer + claim ledger), entities label | `feat(workflows): knowledge extraction compare and conflicts` |
| 3 | INVESTIGATE vía Cognitive OS (scope, budget, capability `knowledge:write`, flags) | `feat(workflows): cognitive investigation node mode` |
| 4 | Agent: context_mode AUTO/selectors, output presets, `DecisionResult`, failure enum, `context_summary`, data-catalog lee `output_schema` | `feat(workflows): structured agent context and decisions` |
| 5 | join ramas nombradas, merge strategies, filter multi-condición, for_each costos, cost_estimate IA + warnings, UI | `feat(workflows): business join merge and filter semantics` |
| 6 | Approval context snapshot (117) + panel portal + inspector | `feat(workflows): approval evidence panel` |
| 7 | Context viewer del editor | `feat(portal): workflow context viewer` |
| 8 | Narrativa `run_story` + E2E tests 1–3 + doc | `feat(workflows): execution narrative and cognitive e2e` |

**E2E (brief §31–§33):**
1. Venta > 40k: sale event → condition → (business data ∥ knowledge) → join → agent → condition `requires_approval` → human approval (con snapshot) → notify. Verifica evidencia, decisión y aprobación con contexto.
2. Contrato nuevo: document event → knowledge compare/check_conflicts → condition severity → agent legal → notify.
3. Diario: schedule → business data → knowledge → agent → business_result → notify. Verifica narrativa y costo estimado.

---

## 11. OPEN DECISIONS

| # | Decisión | Recomendación |
|---|---|---|
| D1 | Modos como `config.operation` en `kb_query` vs node types nuevos | `config.operation` (compat total, un solo handler/catálogo) |
| D2 | INVESTIGATE como modo de `kb_query` vs nodo "Investigar con Zent" | modo (menos duplicación); el catálogo lo muestra como operación avanzada |
| D3 | Scope de ANSWER: KB (`knowledge_base_id`) vs workspace/corpus | KB V2 con fallback a workspace del run; reusar flags existentes |
| D4 | Claims de ANSWER/EXTRACT_FACTS: escribir `ClaimRecord(PROPOSED)` + `attach_evidence` vs solo refs in-memory | escribir PROPOSED en el ledger (auditable, sin autoapprove) |
| D5 | Nombres de ramas en join | label → node_type → node_id (con sufijo si colisiona) |
| D6 | Estrategias de merge | `first_available` (legacy), `first_success`, `prefer_source`, `fallback` |
| D7 | Snapshot de aprobación | solo refs + decisión + citas truncadas + resumen; nunca filas crudas |
| D8 | Narrativa: backend vs portal | backend (`run_story`) para testear y reusar en notificaciones |
| D9 | Presets de salida del agente | `text/decision/classification/business_assessment/json_schema` |

---

## 12. Entregas

**Fase 1 entregada (2026-09-14)** — `kb_query` acepta `config.operation` (default `search`, compat total):
- `search`: V2 con citations/evidencia o V1/legacy, con `status` tipado.
- `answer`: retrieval V2 + LLM grounded (`get_llm_provider`) + `GroundingService`; output `answer/claims/confidence/missing_information/conflicts`; claims de grounding con status en minúscula (no ledger todavía; D4 completo llega con extract_facts/Phase 2).
- `find_evidence`: `evidence[]` + `coverage{supported,evidence_count,citations,sources}` + `evidence_ids` del ledger.
- Modos pendientes (`extract_facts/compare/check_conflicts/investigate`) devuelven `status="not_supported"` con `reason_codes=["phase_pending"]`; operación desconocida devuelve `invalid_operation` + `allowed_operations` (nunca error técnico).
- Contribution de `knowledge` incluye `operation`/`status` (y answer/claims/coverage por modo); evidencia por referencia como siempre.
- Catálogo y Business Schema: parámetro `operation` (select de negocio) + outputs `status/answer/claims/coverage/reason_codes`; `OUTPUT_FIELDS` del portal alineado.
Tests: `tests/test_workflow_knowledge_modes.py` (6).

**Fase 2 entregada (2026-09-14)** — modos avanzados de conocimiento:
- `extract_facts`: usa `extract_facts_from_text` (nuevo wrapper público sobre reglas de `document_facts` + LLM best-effort), escribe
  `ClaimRecord(PROPOSED)` + `attach_evidence` por claim (máx 5 refs) y devuelve `facts/claims/entities` + `claim_ids` por referencia.
- `compare`: retrieval V2 de dos lados (`compare_left`/`compare_right`), diff grounded por LLM validado contra schema, `temporal_context`
  con `TemporalResolver` (si la metadata trae fechas), citations/evidence de ambos lados; `invalid_output` tipado si el LLM no cumple el JSON.
- `check_conflicts`: `ClaimLedgerRepository.list_by_subject` + `find_conflicting` + `classify_conflict` (severity + `resolution_status=unresolved`);
  requiere `subject` (o usa `query`); `has_conflicts` booleano para ramificar. No necesita V2 (es ledger puro).
- D4 cumplido: claims de extracción nacen PROPOSED, con evidencia adjunta; nunca se aprueban solos.
- Catálogo/params/OUTPUT_FIELDS actualizados (`subject`, `compare_left/right`, salidas de hechos/conflictos).
Tests: `tests/test_workflow_knowledge_facts_conflicts.py` (6).

**Fase 3 entregada (2026-09-14)** — modo `investigate` sobre Cognitive OS (sin motor nuevo):
- `CognitivePlanningService.create_run` + `CognitiveExecutor.execute_run` vía `_resolve_dep` (testeable con overrides).
- Scope derivado de `NodeContext` (org/workspace/actor, grupos ACL best-effort, `source_ids` opcionales) y KB opcional: `investigate` funciona con o sin
  `knowledge_base_id`; si viene, se valida ownership.
- Budget del nodo (`config.budget` JSON) sobre `CognitiveBudget`; gate por `COGNITIVE_OS_ENABLED` (off → `not_supported` + `cognitive_disabled`).
- Permiso a nivel **operación**: si falta `knowledge:write` → `status="permission_restricted"` (no `denied` de nodo, para no romper search/answer del mismo nodo).
- Mapeo defensivo de mensajes: `answer` (final_candidate), `findings`, `claim_ids`, `evidence_ids`, `conflicts` (plan_patch), `metrics` (tokens/cost/specialists);
  contribution con `knowledge` + refs de evidencia/claims reales (validadas por org al persistir).
Tests: `tests/test_workflow_cognitive_investigate.py` (3: E2E con scope/budget/refs, permission_restricted, plan fallido tipado).

**Fase 4 entregada (2026-09-14)** — nodo agent:
- `context_mode` = `auto` (default; solo secciones con contenido) | `manual` | `none`; `context_selectors` con `data:<node>`/`knowledge:<node>` y
  secciones (`trigger`, `evidence`, `claims`, `decisions`, ...). Los nodos con `context_reads` explícitos siguen en modo manual (compat).
- Presets `output_type`: `text/decision/classification/business_assessment/json_schema` (`output_presets.py`); `output_schema` explícito gana.
- `DecisionResult` tipado (`decisions.py`): `decision/status/confidence/reasons/evidence_refs/claim_refs/requires_review`; viaja en la contribución
  `decisions` como `decision_result` sin romper refs al output raíz.
- Enum de fallo: `ok | low_confidence | insufficient_context | tool_error | budget_exceeded | permission_denied | invalid_output` con `reason_codes`;
  `context_summary` con secciones/conteos/truncado para la UI.
- Data Catalog lee `output_schema` del nodo: los campos del agente (p. ej. «Riesgo») aparecen con label y ref en el Data Picker/ConditionBuilder.
Tests: `tests/test_workflow_agent_context.py` (8).

**Fase 5 entregada (2026-09-14)** — semántica de lógica y costo:
- `join`: output `{merged, branches, values, branch_order}` con nombres de negocio (label → tipo → id, override `branch_labels`); contribuye `data` con ramas.
  (Corrige el join previo, que indexaba por puerto y devolvía `values: {"in": null}`.)
- `merge`: estrategias `first_available` (legacy) | `first_success` | `prefer_source` (+`source_node_id`) | `fallback` (+`sources`); output incluye
  `strategy/selected_from/selected_label`; contribuye `data`.
- `filter`: multi-condición (`conditions[]` + `op` and/or) manteniendo `field/operator/value` legacy; parsea listas JSON de referencias; output con
  `conditions/count/total`.
- `for_each`: `warnings` con `expensive_branch` si la rama usa agentes/conocimiento + `billable_calls_estimate`.
- `cost_estimate`: `ai_calls_per_run`/`knowledge_calls_per_run`/`cognitive_calls_per_run` y `warnings` (`agent_inside_loop`, `investigation_per_event`,
  `high_frequency_schedule`, `large_batch`); sin precisión monetaria falsa. UI muestra warnings como chips.
- `NodeContext` expone `node_labels`/`node_types` (solo lectura) para nombrar ramas y advertir costos.
Tests: `tests/test_workflow_join_merge.py` (6).

**Fase 6 entregada (2026-09-14)** — aprobación con evidencia:
- Migración `117_workflow_approval_context.py`: `workflow_approvals.context JSONB` (+ paridad en `ensure_context_tables`).
- `human_approval` guarda snapshot acotado: decisiones (hasta 3), evidencia/claims por referencia (8), citas (5, truncadas), artefactos (3),
  resumen de datos (5 claves + answer 240 chars). Nunca incluye `security` ni filas crudas.
- `GET /runs/{run_id}/approvals` devuelve `context`; el output del nodo también lo expone.
- Portal: `WorkflowApprovalPanel` (montado en el inspector cuando el run está `pending_approval`) muestra recomendación, evidencia,
  claims, citas y datos, con Aprobar/Rechazar (`approved|rejected`); decide y oculta la tarjeta.
Tests: `tests/test_workflow_approval_context.py` (1 E2E) + `WorkflowApprovalPanel.test.tsx` (2).

**Fase 7 entregada (2026-09-14)** — panel de contexto del editor:
- `WorkflowContextPanel` (workflowStudio): solo lectura, combina Data Catalog (`sources`), `contextWrites` del catálogo de nodos y las
  contribuciones del último run inspeccionado; agrupado por sección con conteos y vacíos claros.
- `WorkflowCanvasEditor`: botón "Contexto" (`wf-context-toggle`) y overlay (`wf-context-panel`); se oculta cuando el inspector de nodo está abierto.
Tests: `WorkflowContextPanel.test.tsx` (2).

**Fase 8 entregada (2026-09-14)** — narrativa + E2E de aceptación:
- `narrative.py`: `run_story(run_detail)` convierte steps/decisiones/ramas en frases de negocio; sin chain of thought ni JSON crudo. `run_detail.story`
  lo expone y el inspector lo muestra arriba de los pasos (`wf-run-story`).
- `tests/test_cognitive_workflows_e2e.py`: E2E 1 venta > 40k (condition → datos ∥ conocimiento → join → agente → condition → aprobación con
  evidencia → approve → notify), E2E 2 contrato vs política (compare + conflicts → condition → agente legal → notify) y E2E 3 diario
  (schedule → datos → conocimiento → agente → business_result → notify simulada), con narrativa verificada.
Tests: `tests/test_workflow_narrative.py` (2) + E2E (3).

**D5 entregado (2026-09-14)** — entidades con identidad canónica existente:
- `entities.py`: `resolve_entity_ref` consulta `CanonicalKnowledgeRepository.get_by_natural_key(..., CanonicalKind.ENTITY, entity_natural_key(label, kind))`;
  encontrada → `resolution="canonical"` + `canonical_id`; si no o si falla → `resolution="label_only"` (nunca IDs inventados).
- Productores: `extract_facts` (party → organization, resto concept), `business_result` y `business_node` (config `entities` string/dict) contribuyen
  la sección `entities` (declarada en `context_writes`). Cero registros paralelos.
Tests: `tests/test_workflow_entities.py` (3) + aserción de resolución en facts.

**Metering de runs (2026-09-14)** — `run_workflow` registra un `usage_events` idempotente (`event_type="workflow_run"`,
`request_id=run_id`) con status, latencia y `cost_tags.cost_ms`; el costo monetario de agentes sigue registrado por AgentRuntime (sin doble conteo).
Test: `tests/test_workflow_usage.py` (1).
