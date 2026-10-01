# Cognitive Runtime — arquitectura única (programa W1–W6)

> **Estado:** spec aprobado 2026-10-01. Implementación por fases C1–C9 en
> `docs/superpowers/plans/`. Esta es la fuente de verdad del programa; donde el
> documento y el código discrepen, **manda el código**.
> **Relación:** `knowledge-os.md` define **qué sabe ZENT** (compilador,
> identidad canónica, evidencia, conflictos). Este programa define **cómo ZENT
> decide y usa lo que sabe**. `knowledge-cognitive-os.md` (fases 0–10) pasa a
> ser historia: construyó la capa cognitiva aislada que este programa integra.
> **Base:** `master` @ `7285c09` (Knowledge OS + Knowledge Compiler merged).

---

## 1. Leyes del programa

1. **Un solo runtime.** `/rag/query` es el entry (HTTP, chat, copilot, embed).
   Workflows y MCP usan el mismo núcleo vía servicio. El planner/DAG/executor
   cognitivo son maquinaria interna, no una API paralela de ejecución.
2. **Deterministic first.** regla determinística → consulta estructurada → JEV
   → LLM económico → LLM avanzado. No usar inteligencia costosa donde no aporta.
3. **JEV decide, nunca ejecuta.** Sus juicios se adoptan por modo y umbral.
4. **Evidencia primero.** Toda afirmación con refs (`kn:` canónico, `ev:`
   ledger). Los conflictos se retienen y se proponen; jamás se resuelven solos.
5. **Sin ACL después del LLM.** El scope filtra **antes** del retrieval.
6. **Sin chain-of-thought persistido.** Se guardan resúmenes y referencias.
7. **Default off.** Sin `RAG_COGNITIVE_OS_ENABLED` activo, el comportamiento
   productivo no cambia.
8. **Sin `cognitive_v1/v2` permanentes.** Los flags de migración son
   temporales, documentados y se podan en C9 (cutover).

## 2. Estado actual (anclas verificadas)

| Pieza | Path | Estado |
|---|---|---|
| Entry HTTP | `src/api/routes/query.py:403` | productivo |
| Runtime | `src/agents/runtime/orchestrator.py:1531` (`execute`) | productivo |
| Retrieval canónico | `orchestrator.py:1462` (`_run_knowledge_retrieve`) | productivo; usa solo `exact_needles` del planner |
| Retrieval planner | `src/rag/retrieval/planner.py` | corre; `representations`/`reasons`/`temporal_intent`/`structured_intent` sin consumir |
| JEV / decisión | `src/decision/**`, `orchestrator.py:4178` (`_preflight_gate`) | `DECISION_ROUTING_MODE=legacy`, preflight `off` |
| Evidencia | `src/runtime/evidence.py` | dedupe/rank/budget productivo |
| Answerability | `src/intelligence/**` | productivo (`RAG_ANSWERABILITY_ENABLED=true`) |
| Verificación | `src/rag/adaptive/grounding.py` + `ClaimVerifier` | adaptive `off` por default |
| Traza | `orchestrator.py:418` (`_build_flow`) + `src/rag/traceability.py` + `flow_story.py` | productivo |
| Cognitive aislado | `src/platform/cognitive/**`, `src/api/routes/cognitive.py`, migraciones 102–108 | flag `RAG_COGNITIVE_OS_ENABLED=off`; nadie del runtime lo llama |
| Knowledge OS | `src/knowledge/compiler/**`, `src/platform/knowledge_model/**` | productivo (ingesta) |
| Eventos de conocimiento | `knowledge_sessions`, `src/platform/knowledge_learning/events.py` | emiten durante ingesta; no disparan workflows de negocio |

## 3. Arquitectura target

```
Pregunta / Evento
  → S1 Intent                 src/intelligence/** (existente)
  → S2 Cognitive Plan         src/runtime/cognitive_plan.py
  → S3 JEV Preflight          src/decision/** (extendido)
  → S4 Knowledge Strategy     src/runtime/knowledge_strategy.py
  → S5 Retrieval multi-rep    runners por representación
  → S6 Evidence Assembly      engine único (runtime/agentes/workflows)
  → S7 Knowledge Compression  KnowledgeBrief (facts/relations/rules/excerpts)
  → S8 Reasoning              L0 corto · L1 barato · L2 fuerte · L3+ DAG cognitivo
  → S9 Verification           AnswerVerifier único → claim/evidence ledger
  → S10 Learning Signal       gaps, misses, verificación, JEV → stores existentes
```

Modos de `RAG_COGNITIVE_OS_ENABLED`:

| Modo | Plan/strategy | Pipeline cognitivo | DAG L3+ | Ejecución legacy |
|---|---|---|---|---|
| `off` | no | no | no | completa |
| `shadow` | sí (traza) | no | no | completa |
| `limited` | sí | L0–L2 sí | no | tools/agentes |
| `active` | sí | sí | sí | solo tools |

## 4. Etapas S1–S10 (contratos)

Estado del turno: `CognitiveTurn` (`src/runtime/cognitive_state.py`): `intent`,
`plan`, `strategy`, `evidence`, `brief`, `claims`, `verification`, `budget`,
`loop`, `notes`. Cada etapa lee/escribe campos; nada de dicts sueltos.

| Etapa | Se construye/refactoriza | Fase |
|---|---|---|
| S1 Intent | retirar `src/rag/query_intelligence/` (inert); usar `IntelligenceEngine.understand` | C1/C4 |
| S2 Cognitive Plan | `cognitive_plan.py`: complejidad (existente) + needs `semantic_search · exact_lookup · structured_query · graph_traversal · temporal_lookup · cross_document_reasoning · rule_lookup · conflict_resolution · comparison · aggregation · calculation · external_tool · memory · no_retrieval` con razón por paso | C1 |
| S3 JEV Preflight | señales nuevas (`entity_resolved`, `exact_lookup_needed`, `deep_reasoning_needed`); determinista primero; JEV solo ambigüedad | C2/C4 |
| S4 Knowledge Strategy | consumir `RetrievalPlan` completo + entity→canonical + scope; trazada | C1/C2 |
| S5 Retrieval multi-rep | runners: vector (híbrido existente), exact (anchors/needles), structured (`tabular_*`, assertions), graph (canonical objects/edges), temporal (valid_from/to); fail-soft por runner | C2 |
| S6 Evidence Assembly | engine: dedupe · rank · group · connect · provenance · current-priority · conflictos retenidos · token budget; reemplaza el uso directo de top-K; blackboard cognitivo se retira | C3 |
| S7 Compression | `KnowledgeBrief`: Facts · Relations · Rules · Critical excerpts · Supporting excerpts con refs `kn:`/`ev:`; budget determinista (estructurado primero) | C3 |
| S8 Reasoning | L0 determinista · L1 LLM barato · L2 fuerte · L3+ DAG (`src/platform/cognitive/executor.py`) consumiendo EvidencePackage+Brief; tools siguen en `AgentRuntime` | C4/C5 |
| S9 Verification | `AnswerVerifier` único (soporte/conflicto/outdated/unsupported) → ledger; políticas approve/revise/abstain/limit; unifica adaptive claims + `fact_checker` | C4 |
| S10 Learning Signal | observaciones → `context_gaps`, KLE, curator, Knowledge Health; sin entrenar pesos | C4 |

## 5. JEV — puntos de decisión

Regla: determinista si se puede medir; JEV solo para ambigüedad; respuesta con
confianza; nunca ejecuta capacidades. Trazado por decisión (pregunta, respuesta,
confianza, efecto).

| Decisión | Existente | Nuevo |
|---|---|---|
| ¿Necesita Knowledge OS? | `needs_private_knowledge` | — |
| ¿Entidad resuelta? | — | `entity_resolved` (determinista si match exacto/alias; JEV si ambiguo) |
| ¿Búsqueda exacta además de semántica? | — | `exact_lookup_needed` (needles → determinista; JEV si duda) |
| ¿Razonamiento profundo o LLM barato? | `simple_deterministic_answer_possible`, tiers | `deep_reasoning_needed` (L≥3 + señales; JEV desempata) |
| ¿Evidencia suficiente? | `answerable_from_current_evidence` / `evidence_sufficient` | — |
| ¿Ambigüedad / falta dato crítico? | `critical_fact_missing`, `choice.ambiguous` | — |
| ¿Más fuentes? | `needs_multiple_evidence` | — |
| ¿Conflicto material? | `critical_conflict_unresolved` | — |
| ¿Respuesta respaldada? | `answer_grounded`, `answer_contains_unsupported_conclusion` | — |

## 6. Evidence Assembly + Knowledge Compression (W2)

**EvidenceAssembly** (C3) compone `src/runtime/evidence.py` (registry, dedupe,
rank, budget ya productivos) y agrega: normalización a identidad canónica,
agrupación (documento/entidad/claim), conexión entre fuentes, prioridad de
conocimiento vigente (`valid_from`/`valid_to`, supersession), retención de
conflictos y reparto de presupuesto por tipo. Salida: `EvidencePackage`
(items + brief + conflicts + gaps + budget_report), consumida por generación,
JEV, verificación y traza. Un solo engine para runtime, agentes y workflows.

**KnowledgeBrief** (C3): representación progresiva para el prompt con refs a la
fuente original:

```
Facts            (subject, predicate, object, vigencia, fuentes, confianza)
Relations        (entidad ↔ entidad, tipo, fuentes)
Rules            (rule_key, alcance, vigencia, excepciones)
Critical excerpts (literales/anchor, celdas, párrafos decisivos)
Supporting excerpts
```

Cada línea lleva `kn:<canonical_id>` / `ev:<evidence_id>`. El LLM nunca recibe
conocimiento sin referencia. Budget configurable por bloque; estructurado
primero, excerpts después. Nunca truncado arbitrario: lo que no entra se
declara en el paquete.

## 7. Cognitive Budget + loop controlado

- Budget = wallet existente (`src/runtime/wallet.py`) + `CognitiveBudget` por
  perfil de profundidad: L0 0 calls · L1 small · L2 default · L3+ budget del
  plan (`src/core/domain/cognitive.py`). Enforcement en frontera de etapa;
  gasto trazado.
- Loop: una ronda extra solo con justificación persistida
  `{what_missing, why_another_search}` (falta entidad/anchor/conflicto/versión).
  Cap `ADAPTIVE_RAG_MAX_RETRIEVAL_ATTEMPTS` + `LoopGuard`; JEV aprueba ronda
  extra solo con confianza ≥ umbral. Sin loops autónomos.

## 8. W3 — Traza + explicación humana

- Las etapas proyectan a la traza v2 existente (`traceability.py`,
  `execution_narrative.py`, `flow_story.py`). Un solo origen de eventos: las
  vistas renderizan, no duplican pasos.
- Niveles: **normal** (execution story humano) · **expandido** (JEV, budget,
  strategy, evidencia matemática) · **raw telemetry** (spans, tiempos, llamadas).
- Runs L3+ linkean `cognitive_run_id` al flow/query; inspector y traza comparten
  ids. Sin migración destructiva.

## 9. W4 — knowledge_scope + RBAC

- Dominio `KnowledgeScope`: `source_ids`, `knowledge_base_ids`, `corpora`,
  `workspaces`, `canonical_kinds`, `domains/tags`, sensibilidad. Vive en
  `agents.config_json.knowledge_scope` y nodos de workflow.
- Default = comportamiento actual (org-wide + `source_ids`). Scope **estrecha**,
  nunca amplía. Enforcement pre-retrieval en S4 (Qdrant + SQL + canonical por
  provenance). Evidence assembly hereda scope; JEV/verificación solo ven
  evidencia scoped.
- Propagación: runtime, `AgentRuntime`, MCP `search_knowledge`, workflows.

## 10. W5 — Knowledge events + workflows

- `KnowledgeEventType`: `NEW_ENTITY` · `NEW_RULE` · `RULE_CHANGED` ·
  `CONFLICT_DETECTED` · `SOURCE_SUPERSEDED` · `KNOWLEDGE_GAP_DETECTED` ·
  `HIGH_IMPACT_CHANGE`.
- Emisión desde compiler (`src/knowledge/compiler/pipeline.py`) y materializer →
  store durable + bus Redis `rag:events` (infra existente). Reemplaza
  `knowledge.changed` (registrado, nunca emitido).
- `HIGH_IMPACT_CHANGE`: score determinístico (referencias, agentes, workspaces),
  umbrales configurables. Nunca LLM.
- `workflow_event_triggers` acepta los tipos nuevos. Eventos se emiten por
  default; **cero acciones automáticas sin trigger y permisos configurados**.
- Payload: ids, fuente, diff, confianza, `requires_review`.

## 11. W6 — Evals + cutover

- Harness sobre `src/rag/evaluation/**` + shadow existente; escenarios del
  brief: simple factual · exact literal · structured Excel · graph relationship
  · temporal · conflicting sources · insufficient evidence · multi-document ·
  greeting (no knowledge) · tool-required · knowledge+tool · JEV sin
  intervención · JEV modifica ruta · verificación falla.
- Métricas: grounding · citas · abstain correcto · latencia · tokens · costo ·
  acuerdo JEV · strategy correcta · rondas de loop.
- Gates: `shadow → limited` (sin regresión, grounding ≥ baseline, costo
  acotado) · `limited → active` L0–L2 (suite verde) · L3+ (profundos verdes en
  budget).
- Cutover (borrado, C9): `query_intelligence`, verificación duplicada,
  `EvidenceBlackboard`, `POST /cognitive/runs/{id}/execute`, flags temporales.
  Rollback: flag a `off`. Migraciones aditivas hasta C9.

## 12. Archivos

**Crear (por fase):** `src/runtime/cognitive_plan.py` (C1),
`src/runtime/knowledge_strategy.py` (C1), `src/runtime/cognitive_state.py` (C1),
runners de representación (C2), `src/runtime/evidence_assembly.py` +
`src/core/domain/knowledge_brief.py` + `src/runtime/compression.py` (C3),
`src/runtime/verification.py` + `src/runtime/learning_signal.py` (C4),
`src/core/domain/knowledge_scope.py` (C7), `src/core/domain/knowledge_events.py`
(C8).

**Modificar:** `src/agents/runtime/orchestrator.py`, `src/decision/preflight.py`,
`src/decision/registry.py`, `src/runtime/evidence.py`,
`src/rag/retrieval/planner.py`, `src/api/routes/query.py` (solo si el contrato
de respuesta lo exige), `src/knowledge/compiler/pipeline.py`,
`src/platform/workflows/event_registry.py`, `src/platform/cognitive/executor.py`
(C5).

**Retirar (C9):** `src/rag/query_intelligence/**`, `EvidenceBlackboard`
(`src/core/domain/cognitive.py`), verificación cognitiva duplicada,
`POST /api/v1/cognitive/runs/{id}/execute` (queda inspección).

## 13. Tablas, migraciones, flags

- Reusar 102–108 (`knowledge_canonical_*`, `evidence_ledger`, `claim_ledger`,
  `cognitive_runs/tasks/agent_messages/agent_executions`, curator, shadow).
- Migraciones nuevas solo aditivas; una por fase como máximo; cadena lineal.
- Flag principal `RAG_COGNITIVE_OS_ENABLED` (`off|shadow|limited|active`).
  Sub-flags temporales de fase se documentan y se eliminan en C9.

## 14. Riesgos

| Riesgo | Mitigación |
|---|---|
| Regresión del path principal | modos + shadow + gates de paridad (W6) |
| Costo L3+ | perfiles de budget + JEV small-tier + least-sufficient level |
| Leak ACL/scope | scope pre-retrieval + tests cross-tenant |
| Prompt injection | neutralización existente; evidencia = dato no instrucción |
| Duplicación durante migración | flags documentados; poda C9 |
| Migración de DB | solo aditiva; rollback por flag |

## 15. Fases

| Fase | Contenido | Modo default | Plan |
|---|---|---|---|
| C1 | TurnState + cognitive plan + strategy + traza (shadow kernel) | `shadow` (default off) — **shipped** | `docs/superpowers/plans/2026-10-01-cognitive-runtime-c1-shadow-kernel.md` |
| C2 | Runners de representación + entity resolution + señales JEV nuevas | shadow | pendiente |
| C3 | EvidenceAssembly + KnowledgeBrief | shadow | pendiente |
| C4 | AnswerVerifier único + ruteo L0–L2 + loop/budget + learning signal | limited | pendiente |
| C5 | DAG L3+ vía runtime + persistencia runs + link inspector | active L3+ | pendiente |
| C6 | W3 traza/explicación 3 niveles + portal | — | pendiente |
| C7 | W4 knowledge_scope + RBAC | — | pendiente |
| C8 | W5 knowledge events + triggers | — | pendiente |
| C9 | W6 evals completas + poda legacy | cutover | pendiente |

## 16. Verificación

- Por fase: tests unitarios del dominio nuevo + integración con fakes del
  runtime + `ruff check src tests`.
- Regresión relevante: `tests/test_architecture.py`,
  `tests/test_retrieval_planner.py`, `tests/test_jev_preflight_flow.py`,
  `tests/test_rag_query.py` (o suite equivalente), `tests/test_cognitive_*`.
- Promoción de modo: suite W6 verde en shadow y limited antes de `active`.
