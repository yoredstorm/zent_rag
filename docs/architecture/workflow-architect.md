# Zent AI Workflow Architect — Phase 0 Architecture Audit

> **Status:** Phase 0 (auditoría) completa. **Fases 1–5 implementadas** (first delivery) y **fases 6, 9 y 10** (clarificación, readiness/simulación y evaluación con métricas).
> Faltan 7 (patching conversacional) y 8 (UX semántica de nodos).
> **Fecha:** 2026-09-15
> **Base:** `feat/knowledge-cognitive-os` @ `08803fe` (Workflow Semantic Core + Cognitive Workflows completos).
> **Prerrequisitos verificados:** contexto compartido y nodos knowledge/agent/data con resultado tipado, evidencia y decisiones.
> **Principio:** `TEXT → BUSINESS INTENT → SEMANTIC PLAN → VALIDATION → GRAPH → SIMULATION → HUMAN APPROVAL`.
> Donde este documento y el código discrepen, **el código manda**.

---

## 0. Non-negotiables

| Ley | Ancla |
|---|---|
| NO NEW WORKFLOW ENGINE | `WorkflowGraph` v2 + `execute_graph` |
| NO TEXT → GRAPH DIRECTO | LLM propone intent/plan; código compila (`architect_compiler.py`) |
| CAPABILITY-AWARE | `architect_discovery.py` sobre registries reales; nunca inventar Slack/Gmail/DB/agentes |
| VALIDACIÓN ANTES DE GRAFO | `architect_validator.py`; plan inválido no genera grafo |
| NO PERMISOS POR PLANNER | el planner no otorga nada; permisos del actor se validan, no se crean |
| NO AUTO-PUBLISH | el resultado es draft + preview; publicar es acción humana |
| NO CoT | solo `reason_summary` por paso (racional corto) |
| FALLBACK HEURÍSTICO | `copilot.py` se conserva para cuando no hay LLM; deja de ser la arquitectura primaria |

---

## 1. CURRENT — Copilot actual (verificado)

- `src/platform/workflows/copilot.py`: heurísticas regex con **escenarios fijos**:
  - `build_draft(prompt)` → `DraftPlan` (taxpayer/RUC o "brief diario de ventas" por defecto).
  - `_parse_time`, `_schedule_config`, listas de `MAYBE_QUESTIONS`.
  - Es el "AI Workflow" original: superficie limitada, no capability-aware, no planifica.
- `src/platform/workflows/copilot_v2.py`: pipeline LLM NL → `WorkflowIntent` (legacy) → `WorkflowPlan` (legacy) con
  `_capability_hints` + `planner_hints` (catálogo) inyectados; `heuristic_intent` reutiliza `copilot.build_draft` como fallback.
- `src/platform/workflows/intent.py`: `WorkflowIntent`/`WorkflowPlan` legacy (trigger, conditions, data_sources, analysis, actions),
  validadores y `intent_to_plan`.
- `src/platform/workflows/plan_compiler.py`: compiler determinístico `WorkflowPlan → WorkflowGraph` (`_Builder`), con
  `_data_node`, `_analysis_node`, `_action_node` y `load_capabilities`.
- `src/platform/workflows/capabilities.py`: `canvas_context`, `recommend_for_graph`, `cost_estimate`, `ports_for_action`.
- Catálogos backend: `GET /node-catalog`, `GET /workflows/{id}/data-catalog`, `GET /event-catalog`,
  integraciones/agents/knowledge-bases por sus APIs.
- Portal: `AskZent.tsx` (intent → compile → crea borrador; nunca publica solo).
- Runtime: nodos de conocimiento con operaciones (search/answer/find_evidence/extract_facts/compare/check_conflicts/investigate),
  agente con contexto/presets/`DecisionResult`, join/merge/filter tipados, aprobación con evidencia, narrativa.

**Problema confirmado:** el Copilot de `copilot.py` es regex/escenarios; el V2 ya usa LLM+catálogo pero su plan es
el legacy `WorkflowPlan` (data_sources/analysis/actions): **no expresa pasos semánticos, dependencias, decisiones ni
assumptions/uncertainties**, y no hay validator de plan previo al grafo.

---

## 2. GAPS (brief §2–§34)

| # | Gap | Sección |
|---|---|---|
| G1 | Sin Capability Discovery unificado (nodos+operaciones, triggers, agentes con propósito/tools, KBs, datos, integraciones, eventos, permisos, costos) | §4 |
| G2 | Sin `WorkflowIntent` rico (goal/trigger_intent/data_needs/knowledge_needs/reasoning_needs/approval/output/uncertainties/assumptions) | §5 |
| G3 | Sin `SemanticPlan` (pasos de negocio con `depends_on`, sin ids/posiciones/mustache) | §6 |
| G4 | Compiler legacy acopla análisis/acciones fijos; no compila pasos semánticos ni decisiones con ramas | §7 |
| G5 | Sin Plan Validator pre-grafo (disponibilidad, permisos, tipos, ciclos, integraciones faltantes, cost/risk) | §8 |
| G6 | Sin Clarification Engine ni política de assumptions (alto impacto obliga a preguntar) | §9–§10 |
| G7 | Sin `planning_reason_summary` por nodo generado | §24 |
| G8 | Sin preview "ENTENDÍ / CUÁNDO / OBTENER / …" desde el plan semántico | §14 |
| G9 | Sin patching conversacional del plan (`SemanticPlanPatch`) | §15 |
| G10 | Sin recomendaciones/UX semántica de nodos (nombres de negocio, help contextual, biblioteca por propósito) | §16–§19, §27 |
| G11 | Sin simulation/readiness unificados pre-publicación desde el plan | §23, §26 |
| G12 | Sin métricas del arquitecto ni dataset de evaluación ≥50 intents | §30–§31 |

---

## 3. TARGET — First delivery (brief §34)

```
prompt
  → discover_capabilities(org, workspace, permissions)         # G1
  → ArchitectIntent (LLM, validado)                            # G2
  → SemanticPlan (pasos de negocio, depends_on, assumptions)   # G3
  → validate_plan (issues: error/warning + requisitos)         # G5
  → compile_plan_to_graph (determinístico, refs semánticas)    # G4
  → preview (entendí/cuándo/obtener/consultar/analizar/…)      # G8
  → draft WorkflowGraph + readiness + costo + razones          # G7
```

- LLM propone `ArchitectIntent` y `SemanticPlan`; **código compila y valida**. Si no hay LLM: fallback heurístico
  (legacy `build_draft`) convertido a plan semántico mínimo con `source="heuristics"` y warning.
- Pasos de negocio soportados en el first delivery: `trigger_event|trigger_schedule|trigger_manual`, `business_query`,
  `knowledge_query` (operation), `agent_analysis`, `decision`, `human_approval`, `notify`, `integration_action`,
  `business_result`, `stop` (+ `filter`/`for_each`/`join`/`merge` cuando el plan los declara).
- Referencias: el LLM usa `input: {step, field}` (lenguaje de negocio); el compiler las traduce a
  `{{nodes.<step_id>.output.<field>}}`. Nunca mustache en el plan.
- Decisiones: `decision` referencia un `input` (p.ej. agente → `risk`/`requires_review`) y declara
  `expected: true`; los pasos siguientes usan `when: {step, outcome}` para ramificar.
- Contexto del agente: el compiler selecciona datos/knowledge/evidence de pasos previos vía `context_selectors`
  (nodos reales) y `context_mode: auto`.
- Requisitos: si falta una integración/agente/KB → **issue con mensaje de negocio** ("Para enviar por Slack primero
  necesitas conectar Slack."), nunca inventarlo.

---

## 4. REUSE

| Componente | Uso |
|---|---|
| `registry.all()` + `node_catalog` + `parameters` | node types, operaciones, parámetros, riesgo |
| `load_capabilities` (`plan_compiler`) | agents/KBs/actions/event_types/managed_db |
| `event_registry.list_catalog` | triggers de evento y campos |
| `canonical`/catálogo de datos | fuentes disponibles (data_catalog) |
| `cost_estimate` + warnings | costo/costo IA del grafo compilado |
| `readiness_checks` | checklist de publicación |
| `WorkflowGraph`/`validate_graph` (`ir.py`) | grafo final y validación estructural |
| `copilot.py` `build_draft` | fallback heurístico |
| `copilot_v2._resolve_llm_provider` | provider LLM con overrides de test |
| `WorkflowIntent` legacy (`intent.py`) | compatibilidad + fallback |
| `decisions.py`/`values.py` | contratos que el compiler puede referenciar |

---

## 5. FILES TO KEEP / MODIFY / CREATE

**Keep:** `copilot.py` (fallback), `intent.py` (legacy), `plan_compiler.py` (compilador legacy), `capabilities.py`,
`node_catalog.py`, `parameters.py`, `ir.py`, `runtime.py`, portal `AskZent.tsx` (fase posterior).

**Create (first delivery):**
| Archivo | Contenido |
|---|---|
| `src/platform/workflows/architect_models.py` | `ArchitectIntent`, `SemanticPlan`, `PlanStep`, `PlanInputRef`, `WhenClause`, `PlanAssumption`, `PlanIssue` |
| `src/platform/workflows/architect_discovery.py` | `discover_capabilities()` + `requirement_message()` |
| `src/platform/workflows/architect_compiler.py` | `compile_semantic_plan()` → `WorkflowGraph` dict + `steps_map` |
| `src/platform/workflows/architect_validator.py` | `validate_semantic_plan()` (disponibilidad, permisos, ciclos, inputs, requisitos, cost/risk) |
| `src/platform/workflows/architect.py` | orquestador `plan_workflow()` (LLM + fallback + preview + issues) |
| `src/api/routes/workflows.py` | `POST /architect/plan` (aditivo) |
| `tests/test_workflow_architect.py` | dataset 12–15 intents (A–F + extras) con provider fake + fallback |

**Modify:** `node_catalog.py` (nada obligatorio), `docs/architecture/workflow-architect.md` (este doc).

**DB changes:** ninguna en el first delivery (todo es plan/draft en memoria; el grafo persiste por los endpoints existentes).

---

## 6. BACKWARD COMPATIBILITY

- Endpoints legacy `copilot/intent|compile` y `WorkflowIntent/WorkflowPlan` intactos; el Architect es aditivo.
- `POST /architect/plan` no persiste nada; el portal actual sigue funcionando.
- Fallback heurístico cuando el LLM falla o no está configurado.

---

## 7. RISKS

**Seguridad:** el planner no otorga permisos (el `permissions` efectivo del actor se pasa a discovery y validator);
no inventa integraciones/agentes/KB; outputs LLM siempre validados con pydantic (`extra="forbid"`); texto del usuario
es untrusted (el prompt lo declara); sin cross-tenant (todo scoped por org/workspace).
**Migración:** modelos nuevos; ninguno reemplaza shapes existentes; el compiler reusa `WorkflowGraph` v2.
**Performance:** discovery consulta DB (agents/KBs/actions); se puede cachear por request. Plan LLM = 1–2 llamadas.
**Calidad:** el dataset de intents verifica trigger correcto, selección de nodos (sin agentes innecesarios),
edges por `depends_on`, requisitos faltantes y plan válido.

---

## 8. PHASES

| Fase | Alcance | Estado |
|---|---|---|
| 0 | Auditoría (este doc) | ✅ |
| 1 | Capability Discovery | ✅ first delivery |
| 2 | ArchitectIntent | ✅ first delivery |
| 3 | SemanticPlan | ✅ first delivery |
| 4 | Compiler determinístico | ✅ first delivery |
| 5 | Plan Validator | ✅ first delivery |
| 6 | Clarification Engine + assumptions UI | ✅ (backend: clarifications/requirements en la respuesta) |
| 7 | Conversational patching (`SemanticPlanPatch`) | pendiente |
| 8 | UX semántica de nodos (help contextual, biblioteca por propósito) | pendiente |
| 9 | Simulation + readiness desde el plan | ✅ (readiness + `simulation` sin efectos) |
| 10 | Dataset ≥50 intents + métricas | ✅ (50 casos en `tests/data/workflow_architect_cases.json` + `architect_metrics.py`) |

---

## 9. Dataset del first delivery (tests)

A. venta > S/40,000 → política + aprobación.
B. contrato nuevo → conflictos → agente legal → aviso.
C. diario 8am → ventas vs ayer.
D. stock < 10 → aviso a Compras **sin agente**.
E. stock < 10 → datos+política+lead time → recomendación **con agente**.
F. integración demo (p. ej. Pokémon) → agente resume.
G. evento sin integración instalada → issue de requisito (Slack).
H. alta de cliente RUC → verificación + aviso.
I. facturas vencidas → aviso semanal (schedule).
J. ahorro: "si ventas caen 10% avísame" → decisión determinística sin agente.
K. contrato → investigación compleja (`investigate`) + aprobación.
L. stock → guardar resultado de negocio + notificar.
M. plan inválido (paso huérfano/ciclo) → validator rechaza con error claro.

## 10. Open decisions

| # | Decisión | Recomendación |
|---|---|---|
| D1 | Nuevos modelos vs extender `WorkflowIntent/Plan` legacy | nuevos (`ArchitectIntent`/`SemanticPlan`); legacy queda para compat/fallback |
| D2 | LLM en 1 o 2 llamadas | 2 (intent, luego plan con intent+capabilities) con fallback determinístico |
| D3 | Ramas de decisión | `when: {step, outcome}` en pasos posteriores (sin ids de nodo) |
| D4 | Agente por nombre vs capacidades | capacidades (`config.purpose`, tools, knowledge scope) + match de keywords del goal |
| D5 | Persistencia del plan | no persistir en first delivery; el grafo draft se crea con endpoints existentes |

---

## 11. Entregas posteriores al first delivery

**Fase 6 (2026-09-15)** — `architect_clarifications.py`: preguntas de negocio (máx 5, priorizadas por impacto) desde issues
(`missing.*`, `plan.agent_needs_selection`, `assumption.high_impact`, `intent.missing_information`) y `requirements` agrupados
(conexiones/setup). La respuesta del endpoint incluye `clarifications` y `requirements`.

**Fase 9 (2026-09-15)** — `readiness` del grafo compilado con `readiness_checks` (adaptando capacidades descubiertas) y `simulation`
sin efectos por paso (consulta OK, evidencia, decisión del agente, aprobación "se pediría", avisos simulados). El dry-run real sigue
en el flujo de Probar existente.

**Fase 10 (2026-09-15)** — `architect_metrics.py` (contadores y tasas: plan válido, compile, clarificación, requirements,
agente innecesario, revisiones) + dataset de **50 casos** `tests/data/workflow_architect_cases.json` con `tests/test_workflow_architect_eval.py`
(evalúa trigger, selección de nodos, ausencia de agente innecesario, operaciones de conocimiento, requisitos, referencias y readiness;
casos de integración faltante quedan sin grafo con requirement).
