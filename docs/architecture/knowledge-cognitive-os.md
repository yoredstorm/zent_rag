# Zent Knowledge Cognitive OS — Architecture Audit & Canonical Knowledge Model (Phase 0 + Phase 1)

> **Status:** Phase 0 audit + Phase 1 canonical model — slice 1 shipped (branch `feat/knowledge-cognitive-os`): domain + port + migration 102 + Postgres adapter + 11 tests. No productive wiring, no data migration.
> **Date:** 2026-09-11
> **Base:** `master` @ `1a42c20` (Knowledge Workspaces UX, grounding, Knowledge V2 slices A–H in production-flag `false`).
> **Relation to prior ADR:** `docs/architecture/enterprise-knowledge-refactor.md` is the Knowledge Engine V2 program (SOURCE → STRUCTURED → SEMANTIC → INDEX → RETRIEVAL → GROUNDING). This document is the **Cognitive OS program** built on top of it (agents, evidence, claims, temporal/conflict intelligence, learning governance). Where this document and the code disagree, **the code wins**.
> **Scope:** Phase 0 (this audit) + Phase 1 (Canonical Knowledge Model, slice 1 only). Phases 2–10 are designed as contracts here but not implemented.

---

## 0. Non-negotiables (program law)

Taken verbatim from the brief and mapped to repo reality. These constrain every later phase.

| Law | Current anchor |
|---|---|
| Do not rewrite the project | `src/api`, `src/knowledge`, `src/rag`, `src/catalog`, `src/platform` stay |
| No second vector DB | Qdrant `rag_documents` only (`src/infrastructure/qdrant/vector_store.py:65`) |
| No second LLM gateway | LiteLLM only (`src/infrastructure/llm/provider.py`) |
| No Neo4j | Graph stays in Postgres (`KnowledgeGraphService`, `catalog_lineage`) |
| No productive mocks | tests use fakes; production paths use real stores |
| `INFERRED != APPROVED` | `_assert_approval_law` (`src/core/domain/knowledge_v2.py:105`), catalog provenance |
| No ACL after the LLM | Qdrant filter pre-retrieval (`vector_store.py:239`), SQL org rewrite |
| No infinite delegation / free agent chat | **does not exist yet**; Phase 3–6 gates it by design |
| No chain-of-thought storage | store `reasoning_summary` only (existing LLM analyses do this) |
| No silent internet | `call_api` tool is allowlist + org-gated (`src/agents/tools/tools_builtin.py:199`) |
| No auto-approving inference | Review Queue / KLE questions / `knowledge_business_rules` |
| Do not claim READY without evaluation | KLE gate + `assess_v2_readiness` |

---

## 1. CURRENT — what the code actually ships

Nine overlapping knowledge subsystems exist today. They share org isolation and, most of the time, Postgres/Qdrant/LiteLLM. They do **not** share one knowledge identity.

### 1.1 Ingestion + document structure

| Piece | Path | State |
|---|---|---|
| V1 ingestion engine | `src/knowledge/engine/service.py` (`KnowledgeIngestionEngine`) | Production. Durable jobs, retry, resume, orphan vector delete |
| V1 normalizers | `src/knowledge/normalize/*` | Production. Bytes → flat Markdown |
| V2 parsers | `src/knowledge/structure/*` (`pdf_parser`, `text_parser`, `docx_parser`, `html_parser`) | Flag-gated `RAG_KNOWLEDGE_V2_ENABLED`. PDF with bbox/reading order/tables |
| V2 persistence | `src/infrastructure/postgres/structured_documents.py`, migration `098` | `structured_documents` + `structured_blocks` (node_type block/page/section/table/figure) |
| V2 chunking | `src/knowledge/structure/chunker.py` | parent/child over sections; child chunks → Qdrant with `v2_chunk=true` payload |
| V2 versions | `structured_document_versions` (migration `100`), `DocumentChangeKind` | `created/unchanged/updated`; no snapshot content, no dependent invalidation |
| V2 summaries | `src/knowledge/summarize/service.py` | Shadow only (`RAG_KNOWLEDGE_SUMMARY_MODE=off`), **never persisted** |
| Corpora | `knowledge_corpora` (migration `099`), `PostgresKnowledgeCorpusRepository` | Persisted overlay; **not used by retrieval** |
| Usage/cost | `knowledge_usage` (migration `101`), `KnowledgeUsageTracker` | Embedding tokens estimated, LLM real |

### 1.2 Retrieval + grounding

| Piece | Path | State |
|---|---|---|
| V1 hybrid retriever | `src/rag/retrieval/hybrid.py` (`HybridRetriever`) | Production |
| Fusion | `src/rag/retrieval/fusion.py` (`rrf_fusion`, `weighted_fusion`) | Production |
| Rerank | `src/rag/reranking/` (`LLMReranker`, `CrossEncoderReranker`) | Production (flag) |
| V2 retriever | `src/rag/retrieval/structured.py` (`StructuredRetriever`, `AssembledContext`) | Shadow + promote flags; parent expansion currently ineffective (see findings) |
| Orchestrator | `src/agents/runtime/orchestrator.py` (`RAGOrchestrator`) | Production; V2 shadow `_maybe_v2_shadow`, promote `_run_v2_retrieve` |
| Grounding | `src/rag/grounding/` (`GroundedAnswer`, `Citation`, `ClaimVerifier`) | Productive only in `/knowledge/workspaces/{id}/chat`; main `/rag/query` still `[Doc: N]` |
| Query intelligence | `src/rag/query_intelligence/intents.py` (`build_query_plan`) | Built only in the shadow path; intents/entities/date filters unused by retrieval routing |
| Evaluation | `src/rag/evaluation/*` (V1 runner + V2 metrics/evaluator/judge) | V1 production CLI; V2 evaluator tests-only |
| Locate | `src/knowledge/locate/service.py` (`CitationLocator`) | Productive for PDF highlight, flag for LLM assist |

### 1.3 Query-time intelligence

`src/intelligence/` — `IntelligenceEngine` composes understand → plan → evidence → signals → answerability gate → answer/abstain. Includes `SourceConflictAnalyzer`, `TemporalResolver`, `GraphReasoningEngine` (tests-only), `calibrate/benchmark` (tests-only). `EvidenceObject` exists **in memory only** (traces JSONB), no ledger table.

### 1.4 Agents, tools, MCP

- `AgentRuntime` (`src/agents/runtime/agent_runtime.py:152`): flat ReAct loop, per-step model candidate fallback, ToolContext with tenant + caller RBAC + agent grants, guardrails (max_steps/tokens/cost/time, tool rate limit, LoopGuard, approvals). `agent_runs.steps` JSONB is the only run record; no `agent_messages`.
- Tools: `search_knowledge`, `query_database`, `call_api`, `marketplace_action`, vertical demo tools (`src/agents/tools/tools_builtin.py`).
- MCP server (`src/mcp_server/`) exposes the same capabilities with its own policy/rate limit/audit.
- Model routing: LiteLLM + `zent-routed` DB chain (`src/platform/model_gateway/gateway.py`), aliases `zent-fast|cheap|default|quality`.
- No `CognitiveTaskGraph`, no declarative agent registry, no inter-agent messages, no evidence blackboard, no delegation — confirmed absent.

### 1.5 Catalog + learning

- Semantic Catalog (`src/catalog/`): `catalog_*` tables (migration `080`), `SemanticInference`, Review Queue, authority, glossary, metrics, lineage, `EntityResolutionEngine` (in-memory contract, **no persistence table**).
- KLE FASE 33 (`src/platform/knowledge_learning/`): runs/steps/events/scores + LLM analyses (095) + business rules (096) + questions/feedback (097). Postgres-only knowledge graph. Knowledge Score with gate.
- FASE 25 (`src/learning/`): improvements, approvals, replay, spider, revocation. A **second** learning/approval loop.
- Data onboarding (`src/platform/data_onboarding/`): `document_insights` (093) + deterministic/LLM facts with HITL statuses.
- Knowledge Hub (`src/platform/knowledgehub/`, `knowledge_sources`/`documents`, migration `065`): legacy parallel source registry with wrong permissions (`billing:*`).

### 1.6 Governance + platform

RBAC/ACL pre-retrieval, tenant middleware, workspace resolver, audit (`audit_logs`, fail-soft), usage/metering (`usage_events`), traces (`traces`/`trace_spans`), SSE (RAG, KLE events, platform realtime), workers (`worker_entry.py`, dual queue), connectors (two registries), observability (Prometheus/OTEL/structlog).

### 1.7 Portal

Four-pillar operator IA (`Resumen · Fuentes · Semántica · Mejora`) plus Knowledge Workspaces (source-first 3 panes, `[1]` citations → PDF highlight). E2E locks the 4-pillar nav (per existing ADR decision; do not change it in this program's early phases).

---

## 2. ARCHITECTURE FINDINGS (verified)

Severity: **P1** = correctness/security impact today (flag-on or main path), **P2** = blocks the cognitive roadmap, **P3** = debt/duplication.

| # | Finding | Evidence | Sev |
|---|---|---|---|
| F1 | V2 parent chunks are never written to Qdrant; `StructuredRetriever._expand_parents` silently returns nothing, so V2 promote runs with children only (tests use fake parents). | `src/knowledge/engine/service.py:452` (only `PARENT_CHILD` upserted); `src/rag/retrieval/structured.py:228` (`get_documents` fetch); `tests/test_structured_retriever.py:109` (fake parents) | **P1** |
| F2 | V2 chunk payload does not copy `visibility`/`acl_users`/`acl_groups` from the source; adapter defaults to org-wide public, so a restricted document indexed through V2 would leak to the whole org. | `src/knowledge/engine/service.py:490-508` (payload); `src/infrastructure/qdrant/vector_store.py:583-605` (ACL defaults) | **P1** |
| F3 | Agent tool execution re-checks only the agent allowlist, not caller RBAC/agent grants (`resolve_allowed_tools` filters only the prompt list). A model naming a tool present in `agent.tools` but denied by grants still executes it. | `src/agents/runtime/agent_runtime.py:638` (prompt list) vs `:781` (execution check); `src/agents/tools/registry.py:73` | **P1** |
| F4 | `workspace_id` never reaches retrieval: `RetrievalQuery` has no workspace field, Qdrant supports the filter but no caller passes it; workspace isolation exists for SQL/catalog/delete paths only. | `src/rag/retrieval/models.py:24-55`; `src/infrastructure/qdrant/vector_store.py:264-270`; `src/agents/runtime/orchestrator.py:700-717` | **P1** |
| F5 | V2 chunks are never deleted on source delete / document shrink (point ids are positional `source+external+chunk_index`); `delete_for_source` has no callers in `src`. Stale V2 points outlive their document. | `src/knowledge/engine/service.py:64-68`, `:511`; `src/infrastructure/postgres/structured_documents.py:222`; `src/core/ports/structured.py:48` | **P1** |
| F6 | RRF scores (server-side `search_hybrid`) are not cosine-comparable with the 0.1 meaningful-score floor used in the orchestrator and `filter_by_threshold`. `strategy=hybrid` + server fusion can drop valid hits into the no-info path. `fusion_weights` is accepted and ignored. | `src/infrastructure/qdrant/vector_store.py:468-512`; `src/agents/runtime/orchestrator.py:203,894`; `src/rag/retrieval/hybrid.py:79-81,127-145` | **P1** |
| F7 | `structured_blocks` and all V2 node ids are regenerated per parse; `structured_blocks` rows are deleted+reinserted. Citations by `block_id` do not survive re-ingestion; no canonical identity per node. | `src/infrastructure/postgres/structured_documents.py:96-118`; parsers (`pdf_parser.py:161-164`) | **P2** |
| F8 | No canonical identity across silos: `catalog_entities`, `EnterpriseEntity` (inert), `KnowledgeEntity` (inert), `document_insights`, `business_definitions` represent the same business objects with no mapping. Entity resolution has no persistence. | `src/catalog/entity_resolution.py`; `src/core/domain/entity_resolution.py`; `src/core/domain/knowledge_v2.py:437`; migration `093` | **P2** |
| F9 | Three source registries (`kb_sources`, `catalog_sources`, Hub `knowledge_sources`), two learning systems (FASE 25 vs KLE 33), three readiness metrics (`catalog/readiness`, `knowledge_score`, agent readiness + Hub coverage), two eval stacks. | migrations `065/080/094-097`, `src/learning/*`, `src/platform/knowledge_learning/*` | **P2** |
| F10 | Evidence is not first-class: `EvidenceObject` is in-memory/JSONB, `GroundedClaim` never emits `CONFLICTED`, `Citation.block_id`/`char_range` never populated, prompt `[Doc: N]` remains the productive main-path citation. No claim/evidence ledger tables. | `src/intelligence/store.py` (trace JSONB); `src/rag/grounding/service.py:87-103`; `src/rag/grounding/citations.py:19-44` | **P2** |
| F11 | Temporal state is partial: `catalog_*` effective dates and `TemporalResolver` exist, but `QueryPlan.date_filters` is orphaned, facts have no persisted validity window, document supersession (`SUPERSEDES`) is domain-only. | `src/intelligence/temporal.py`; `src/rag/query_intelligence/intents.py:210-219`; `src/core/domain/knowledge_v2.py:79-89` | **P2** |
| F12 | `structured_documents.knowledge_base_id` always written `NULL`; `document_type` never set by parsers; `knowledge_usage.corpus_id/source_id` have no FKs; `structured_blocks.parent_id` no FK. | `structured_documents.py:77`; `101_knowledge_usage.py` | **P3** |
| F13 | V2 chunk `metadata` lacks `section_path`, so productive citations have empty `section_path`; `CitationLocator` resolves page/bbox separately by text overlap. | `engine/service.py:490-508`; `grounding/citations.py:19-44` | **P2** |
| F14 | Corpus filter is silently ignored when more than one source is selected in workspace chat; `corpus_id` absent from V2 payload and `structured_documents`. | `src/api/routes/knowledge_workspaces.py:276-283` | **P2** |
| F15 | `MAX(version)+1` without lock in document versioning; `replaced` declared but never produced; `unchanged` rows recorded. | `structured_documents.py:144-157` | **P3** |
| F16 | ADR/code drift: existing ADR still labels `StructuredRetriever` inert and corpus unwired, while deps/orchestrator wire shadow/promote and workspace chat; `structured.py:8` comment stale. | `src/api/deps.py:321-351`, `orchestrator.py:214-315,721`; ADR §8.5 | **P3** |
| F17 | Non-blocking but relevant for Phase 3+: `on_step` never invoked, run timeout/trace/usage surfaces exist, AgentRuntime has no planner/registry injection point; `ToolContext` is frozen and extensible only additively. | `agent_runtime.py:58-72,630-903` | **P2** |
| F18 | `get_documents` (by-id) ACL check covers org + `role=="customer"` visibility only (no `acl_users`/`acl_groups`). Safe today because parents are never indexed (F1); becomes a leak the moment F1 is fixed. | `vector_store.py:750-761` | **P1** (conditional) |

All findings were read directly in code except F6's runtime impact and F14's "silently ignored" behavior, which are code-path reads without a dynamic test; mark both as **needs runtime confirmation** before fixing.

---

## 3. TARGET — Cognitive OS on the existing stack

The brief defines the target. This section maps brief concepts to concrete components and files, preserving the architecture guardrails (`tests/test_architecture.py`): `core` is an island, `infrastructure` implements ports, `rag/agents/platform` use DI.

```
CLIENT (chat, API, workflows, MCP)
   │
   ▼
KnowledgeCognitiveOrchestrator            [Phase 3] src/platform/cognitive/orchestrator.py
   ├─ CognitiveComplexityClassifier (L0–L5) [Phase 3] src/core/domain/cognitive.py
   ├─ CognitiveTaskGraph (DAG, budgets)     [Phase 3]
   ├─ KnowledgeAgentRegistry (declarative)  [Phase 3]
   ├─ EvidenceBlackboard + AgentMessage     [Phase 2/6]
   └─ specialists (Phase 4–5): Librarian, Retrieval Strategist, Document Analyst,
      Data Analyst, Temporal, Conflict, Critic, Fact Checker, Synthesizer
   │
   ▼
EnterpriseQueryPlan → retrieval/data routing   [Phase 4+] src/platform/cognitive/planning.py
   │
   ▼
Knowledge Core (exists): StructuredDocument, Qdrant dense+sparse, RRF, rerank,
   ACL pre-retrieval, catalog, KLE, Postgres graph, intelligence gate
   │
   ▼
GroundedAnswer + Evidence Ledger + Claim Ledger  [Phase 2] new tables + domain
```

Design constraints for every phase:

1. **Deterministic services are not LLMs.** `PermissionGuard`, `ACLFilter`, `VersionResolver`, `BudgetGuard`, `CitationValidator`, `LoopGuard` are code, and they wrap the LLM, not the reverse.
2. **A single agent is the default.** Multi-agent only with a measured win (shadow evaluation, Phase 8) inside the categories of brief §65: parallelism, distinct domains, independent verification, conflicting evidence, multi-modal reasoning, decomposition.
3. **Enterprise modes are explicit.** `ENTERPRISE_ONLY` (default) and `ENTERPRISE_PLUS_APPROVED_TOOLS`; abstention states reuse `AnswerabilityStatus`/`ClaimStatus` vocabularies.
4. **Everything assertable carries evidence.** Evidence and Claim become first-class persisted entities (Phase 2) before any orchestration (Phase 3).
5. **Canonical identity precedes unification.** Phase 1 (this document) creates identity + mapping only; no data movement.

---

## 4. GAPS — brief phase vs code

| Brief phase | Gap today | Blocks |
|---|---|---|
| 0 Architecture audit | This document | — |
| 1 Canonical Knowledge Model | No canonical identity/mapping (F8) | Evidence/claims dedupe, graph joins |
| 2 Evidence + Claim Ledger | In-memory only (F10) | Critic, Fact Checker, auditability |
| 3 CognitiveTaskGraph + Supervisor | Absent (F17) | All multi-agent value |
| 4 First specialists | Only ReAct agent + SQL/retrieval tools | Decomposition |
| 5 Temporal + Conflict intelligence | Partial + unwired (F11, F6) | "What changed / which version" answers |
| 6 Collaboration + challenge protocol | Absent | Contradiction resolution |
| 7 Learning Curator + governed memory | Two partial loops (F9) | Knowledge improvement |
| 8 Shadow evaluation | Single-agent baseline exists; no cognitive comparison | Promotion gate |
| 9 Cognitive UI | Workspace UI exists; no run/evidence/agent inspector | Enterprise UX |
| 10 Hardening | Guards exist for agents; no fan-out budgets/delegation yet | Scale-out |

---

## 5. REUSE — FILES TO KEEP

Do not rewrite any of:

- **Ingestion:** `src/knowledge/engine/service.py`, `connectors/**`, `normalize/**`, `structure/**`, `queue.py`, `storage.py`, `cost/**`, `locate/**`, `summarize/**`
- **Retrieval/grounding:** `src/rag/**` (retrieval, reranking, grounding, query_intelligence, evaluation, chunking, suggestions)
- **Intelligence:** `src/intelligence/**` (engine, answerability, temporal, source_conflict, evidence objects)
- **Catalog/learning:** `src/catalog/**`, `src/platform/knowledge_learning/**`, `src/learning/**`, `src/platform/data_onboarding/**`, `src/platform/studio/**`
- **Agents/tools/MCP:** `src/agents/**`, `src/mcp_server/**`
- **Platform:** tenant middleware, RBAC/ACL (`src/platform/acl/groups.py`, `src/platform/rbac/**`), workspaces, audit, usage, metering, billing, model gateway, model health, tracing, observability
- **Infrastructure:** `src/infrastructure/qdrant/**`, `src/infrastructure/llm/**`, `src/infrastructure/postgres/**`, `redis/**`
- **API:** `src/api/routes/**` (current contracts), deps container, idempotency middleware
- **Workers:** `worker_entry.py`, `src/connectors/sql/worker.py`
- **Migrations `001`–`101` as history** (never squash)
- **Portal:** existing pages/components; 4-pillar e2e stays until its own phase
- **Existing ADR:** `docs/architecture/enterprise-knowledge-refactor.md` (superseded only where this document explicitly says so)

## 6. FILES TO MODIFY

Phase 1 (slice 1):

| File | Change |
|---|---|
| `src/api/deps.py` | Add lazy `get_canonical_repo()` next to `get_corpus_repo()` (no productive callers) |

Later phases (design contracts, not this implementation):

| File | Phase | Change |
|---|---|---|
| `src/knowledge/engine/service.py` | 1.2 | Copy ACL fields into V2 payload; call `delete_for_source`; canonical block/chunk registration |
| `src/rag/retrieval/structured.py` | 1.2 | Persist or fetch parents; fill `section_path` into payload so citations carry locators |
| `src/rag/retrieval/models.py`, `vector_store.py` | 2/3 | Thread `workspace_id` into retrieval; fix ACL on `get_documents` |
| `src/agents/runtime/agent_runtime.py` | 3 | Enforce `tool_allowed` at execution; add supervisor/registry injection points |
| `src/rag/query_intelligence/intents.py` + orchestrator | 4 | Consume `QueryPlan` for retrieval routing (strategist) |
| `src/intelligence/temporal.py`, `source_conflict.py` | 5 | Wire temporal/conflict into cognitive specialists |
| `src/rag/grounding/service.py` | 2 | Emit `CONFLICTED`; bind claims to evidence ledger |
| `src/core/domain/knowledge_v2.py` | 2 | Unify approval law with canonical module |

## 7. FILES TO CREATE

Phase 1 (slice 1, shipped by this implementation):

| File | Responsibility |
|---|---|
| `docs/architecture/knowledge-cognitive-os.md` | This document (Phase 0 + Phase 1 contract) |
| `src/core/domain/canonical.py` | Canonical kinds/systems, deterministic ids, canonical objects/links, natural-key helpers |
| `src/core/ports/canonical.py` | `CanonicalKnowledgeRepository` port (org-scoped) |
| `src/infrastructure/postgres/canonical.py` | Postgres adapter |
| `src/infrastructure/db_init/versions/102_canonical_knowledge.py` | `knowledge_canonical_objects` + `knowledge_canonical_links` |
| `tests/test_canonical_knowledge.py` | Domain invariants + Postgres roundtrip/isolation |

Later phases (contracts only): `src/core/domain/cognitive.py` (TaskGraph, AgentDefinition, AgentMessage, budgets), `src/core/ports/cognitive.py`, `src/platform/cognitive/*` (orchestrator, planner, specialists, critic, consensus), `src/infrastructure/postgres/evidence_ledger.py`, `src/api/routes/cognitive.py`.

## 8. FILES TO DEPRECATE

Later only; nothing is deleted in Phase 0/1.

| Component | Why | Sunset |
|---|---|---|
| `src/platform/knowledgehub/**` + `/api/v1/knowledge-hub` | Parallel source registry, wrong permissions | After Hub sources → `kb_sources` + corpus; keep route as shim |
| Markdown as canonical document | Lossy | Keep as derived view |
| Prompt-only `[Doc: N]` as the only citation | Fragile | After evidence ledger + locators ship |
| `catalog/readiness.py` as user-facing % | Conflicts with Knowledge Score | Keep API, UI shows Score + reasons |
| FASE 25 vs KLE duplicated review surfaces | Two approval models | Unify UX/score, keep both stores until migration is proven |
| `ensure_tables` as schema source of truth | Drift vs Alembic | Alembic-only for new tables |

## 9. TABLES TO KEEP / EVOLVE / CREATE

**Keep (no schema change):** `organizations`, `users`, `roles`, `permissions`, `role_permissions`, `memberships`, `platform_*`, `api_keys`, `workspaces`, `agents`, `agent_runs`, `agent_versions`, `deployments`, `agent_permissions`, `approval_requests`, `audit_logs`, `usage_events`, `pricing_models`, `traces`/`trace_spans`, `catalog_*` (080/084/094 alterations), `knowledge_learning_*` (094–097), `knowledge_business_rules`, `knowledge_questions`, `knowledge_feedback`, FASE 25 tables (081), `document_insights`, `data_onboarding_sessions`, `structured_documents`, `structured_blocks`, `structured_document_versions`, `knowledge_corpora`, `knowledge_usage`, `kb_sources`, `knowledge_bases`, `source_documents`, `catalog_authority`, `verified_queries`, `business_definitions`.

**Evolve (later, additive only):**

| Table | Phase | Additive change |
|---|---|---|
| `structured_documents` | 1.2 | `corpus_id` (currently only on KB/source), `document_type` populated, FKs for `source_id`/`workspace_id` |
| `structured_blocks` | 1.2 | stable canonical refs (`canonical_id` nullable), `section_path` in payloads |
| `knowledge_usage` | 2 | FKs (`corpus_id`, `source_id`, `workspace_id`) |
| Qdrant payload `rag_documents` | 1.2/2 | `corpus_id`, `document_id`, `section_path`, ACL copy (additive; no new collection) |
| `agents`/`agent_runs` | 3 | cognitive run linkage (`cognitive_run_id` nullable), no contract break |

**Create (Phase 1 slice 1):**

- `knowledge_canonical_objects` — canonical identity registry.
- `knowledge_canonical_links` — mapping physical objects (per system/type) to canonical ids.

**Create (Phase 2+):** `evidence_ledger`, `claim_ledger`, `cognitive_runs`, `cognitive_tasks`, `agent_messages`, `knowledge_snapshots` (design in later phases; do not create ahead of their consumers).

### 9.1 Canonical schema (migration 102)

`knowledge_canonical_objects`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | deterministic uuid5 of `(organization_id, kind, natural_key)` |
| `organization_id` | UUID NOT NULL FK organizations CASCADE | tenant guard |
| `workspace_id` | UUID NULL | optional scope |
| `kind` | VARCHAR(32) NOT NULL CHECK | `source, document, section, block, chunk, entity, fact, rule, metric, glossary_term, relationship, question, claim, evidence, artifact` |
| `natural_key` | VARCHAR(768) NOT NULL | stable per kind; unique with org+kind |
| `title` | VARCHAR(512) NOT NULL DEFAULT '' | display |
| `provenance` | VARCHAR(16) NOT NULL CHECK | `OBSERVED/INFERRED/APPROVED/REJECTED/DEPRECATED` |
| `status` | VARCHAR(16) NOT NULL CHECK | `draft/observed/inferred/approved/rejected/archived` |
| `confidence` | DOUBLE PRECISION NULL | `[0,1]` in domain |
| `authority_level` | VARCHAR(32) NULL | future policy-based authority |
| `valid_from`/`valid_to` | TIMESTAMPTZ NULL | temporal validity |
| `metadata` | JSONB NOT NULL DEFAULT '{}' | provenance detail |
| `created_at`/`updated_at` | TIMESTAMPTZ NOT NULL DEFAULT now() | |

Constraints: `UNIQUE (organization_id, kind, natural_key)`; `CHECK ((status <> 'approved') OR provenance = 'APPROVED')` (approval law at the DB); indexes on `(organization_id, kind)` and `(organization_id, updated_at)`.

`knowledge_canonical_links`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK DEFAULT gen_random_uuid() | |
| `canonical_id` | UUID NOT NULL FK objects CASCADE | |
| `organization_id` | UUID NOT NULL FK organizations CASCADE | denormalized tenant guard |
| `workspace_id` | UUID NULL | |
| `system` | VARCHAR(32) NOT NULL CHECK | `v1_knowledge_platform, v1_document_registry, v2_structured, catalog, knowledge_learning, governed_learning, data_onboarding, knowledge_hub, intelligence` |
| `object_type` | VARCHAR(64) NOT NULL | physical table/type name, e.g. `kb_source`, `structured_document`, `catalog_entity`, `document_insight` |
| `object_ref` | VARCHAR(512) NOT NULL | UUID or stable key of the physical row |
| `is_primary` | BOOLEAN NOT NULL DEFAULT false | source of truth for the canonical object |
| `metadata` | JSONB NOT NULL DEFAULT '{}' | |
| `created_at` | TIMESTAMPTZ NOT NULL DEFAULT now() | |

Constraints: `UNIQUE (organization_id, system, object_type, object_ref)` (one physical row → one canonical mapping); partial unique `UNIQUE (canonical_id) WHERE is_primary` (one primary per canonical object).

### 9.2 Canonical kind decisions (dedup, staged)

| Kind | Source of truth (primary) | Other systems mapped later | Dedup rule |
|---|---|---|---|
| `source` | `kb_sources` | `catalog_sources` (overlay), Hub `knowledge_sources` (legacy) | One canonical source per physical origin; Hub migrated last |
| `document` | `structured_documents` when V2 doc exists, else `source_documents` | Hub `documents` | File identity = `(source, external_id)`; canonical survives parser id regeneration |
| `section`/`block`/`chunk` | V2 structure (self) | — | Natural key by document + path/order/content hash, **not** by generated UUID (fixes F7) |
| `entity` | Entity Resolution (future) | `catalog_entities`, inert `EnterpriseEntity`, inert `KnowledgeEntity` | Multiple physical entities may link to one canonical entity; resolution never auto-approves |
| `fact` | `document_insights` (approved) + future persisted V2 facts | V2 `KnowledgeFact` | Canonical natural key `(subject, predicate, object)` |
| `rule` | `knowledge_business_rules` | catalog suggestions (`business_rule`) | Key `rule_key` |
| `metric` | `catalog_metrics` | `business_definitions` bridge | Key `metric_key` |
| `glossary_term` | `business_definitions` | `catalog_abbrev_lexicon` | Key term |
| `relationship` | `catalog_relationships` | inert `KnowledgeRelationship` | Directed endpoints + kind; tenant invariant |
| `question` | `knowledge_questions` | corpus suggestions (derived, not canonical) | Key `question_key` |
| `claim`/`evidence` | Phase 2 ledger (not created yet) | — | Phase 2 |
| `artifact` | Studio artifacts (Phase 9) | — | Phase 9 |

No physical rows are moved, merged, or deleted in Phase 1. Mapping is **additive** and does not affect any productive read path.

## 10. API CHANGES

**Phase 1: none.** No route, response field, or SSE event changes. The repository is injected in `deps` but unused by routes. Phase 2+ contracts (design only): `POST /api/v1/cognitive/runs`, `GET /cognitive/runs/{id}[/tasks|/evidence|/claims|/stream]`, `POST /cognitive/runs/{id}/cancel` — names to be validated against route conventions (`/api/v1/knowledge/...`) before implementation.

## 11. MIGRATION RISKS

| Risk | Mitigation |
|---|---|
| New head collision with a parallel branch (head is `101`) | Migration `102`, single linear chain, pure additive |
| `CHECK` constraints reject legacy provenance strings | Constraint vocabulary matches `CatalogProvenance`/`KnowledgeObjectStatus` exactly |
| Registry drifts from physical rows (no FKs possible to heterogeneous tables) | Slice 1 has no producers; the first mapping script (slice 2) must be idempotent and tenant-scoped |
| Deterministic uuid5 collision across orgs/kind | Namespace includes `organization_id` + `kind` + `natural_key`; test asserts distinctness per org |
| Accidental cross-tenant mapping | Every repo method takes `organization_id`; `find_by_ref` filters by org; tests assert isolation |
| Consumers assume mapping completeness | `find_by_ref` returns `None` for unmapped objects; no backfill claim is made until slice 2 |

## 12. BACKWARD COMPATIBILITY

- No existing table, column, index, or route changes.
- No feature flag needed for inert tables; nothing reads them in productive paths.
- No import cycle risk: `core/domain/canonical.py` imports only `src.core.domain.catalog` (allowed); the adapter imports `core` + `infrastructure` only. `src/api/deps.py` gains one lazy import.
- The approval law is duplicated by design in `canonical.py` (V2 keeps its private helper); a test asserts both laws agree, and unification is a Phase 2 refactor.

## 13. SECURITY RISKS

- **F1/F2/F18** (parent expansion + ACL propagation + `get_documents` check) are the top security debt and must be fixed before V2 promote is enabled in production. Phase 1 makes identity available for that fix but does not enable anything.
- Canonical repository must never return rows across `organization_id` (enforced in SQL + tests).
- `object_ref` is opaque text; no SQL is built from it (parameterized queries only).
- No secrets, prompts, or chain-of-thought are stored in canonical metadata (display/identity only).
- Phase 3+ must re-check `tool_allowed` at execution (F3) before adding delegation: a supervisor compounding a known gap would widen it.

## 14. COST RISKS

- Phase 1 adds two narrow Postgres tables; no LLM, embedding, or Qdrant cost.
- Later phases: classifier must be `FAST_CLASSIFIER` role; multi-agent runs require `max_agents/max_llm_calls/max_tokens/max_cost/max_seconds/max_tool_calls/max_debate_rounds` (brief §54) enforced by the supervisor with the existing `BudgetLimits`/`model_budget_status` primitives.
- L0/L1 queries must not pay for multi-agent; promotion of any multi-agent workflow requires the Phase 8 shadow comparison (correctness, grounding, citations, latency, cost).

---

## 15. PHASE 0 EXIT CRITERIA

- [x] CURRENT / TARGET / GAPS / REUSE / DEPRECATE / RISKS / MIGRATION documented with file:line evidence
- [x] Findings list (F1–F18) with severity and verification status
- [x] FILES TO KEEP / MODIFY / CREATE / DEPRECATE
- [x] TABLES TO KEEP / EVOLVE / CREATE
- [x] API CHANGES (none now; later contracts named)
- [x] MIGRATION RISKS / BACKWARD COMPATIBILITY / SECURITY RISKS / COST RISKS
- [x] Code remains the source of truth; ADR drift flagged (F16)

## 16. PHASE 1 — CANONICAL KNOWLEDGE MODEL (slice 1)

**Goal:** create canonical identity + org-scoped mapping across knowledge silos without moving any data, then use it (slice 2) to resolve duplication incrementally.

**In scope (this implementation):**

1. Domain: `CanonicalKind`, `CanonicalSystem`, `CanonicalRef`, `CanonicalObject`, `CanonicalLink`, deterministic `canonical_uuid()`, natural-key helpers, approval law.
2. Port: `CanonicalKnowledgeRepository`.
3. Migration `102`: two tables as specified in §9.1.
4. Adapter: `PostgresCanonicalKnowledgeRepository` (parameterized SQL, org-scoped).
5. `deps.get_canonical_repo()` (lazy, unused).
6. Tests: domain invariants (no DB) + Postgres roundtrip/isolation (DB).

**Out of scope (slice 2+):**

- Backfill/mapping of existing objects (idempotent script, dry-run first).
- ACL fields on V2 payload / parent persistence (F1/F2/F18).
- Stable canonical refs persisted on `structured_blocks` (F7).
- Evidence/Claim ledgers (Phase 2).
- Any orchestrator/supervisor work (Phase 3+).

**Slice 1 shipped (verification):**

| Deliverable | File |
|---|---|
| Canonical domain | `src/core/domain/canonical.py` |
| Repository port | `src/core/ports/canonical.py` |
| Migration 102 | `src/infrastructure/db_init/versions/102_canonical_knowledge.py` |
| Postgres adapter | `src/infrastructure/postgres/canonical.py` |
| Lazy DI getter | `src/api/deps.py` (`get_canonical_repo`) |
| Tests | `tests/test_canonical_knowledge.py` |

- `pytest tests/test_canonical_knowledge.py` → **11 passed** (deterministic ids, approval law parity with V2, natural keys, Postgres roundtrip, cross-tenant isolation, link upsert, partial-primary uniqueness, DB approval-law CHECK).
- Regression subset `test_architecture.py + test_knowledge_v2_domain.py + test_structured_documents_repo.py + test_knowledge_corpora.py` → **27 passed** (layering guards intact).
- `ruff check` clean on all new/changed files.
- Migration applied locally: `alembic upgrade head` → `101 → 102`. Downgrade drops both tables.

**Test commands:** `pytest tests/test_canonical_knowledge.py -v` (DB tests need the local Postgres from `docker-compose.yml`; conftest already targets it) and `ruff check src tests`.

---

## 17. VERIFICATION PENDING

| Item | How to confirm |
|---|---|
| F6 runtime impact (`strategy=hybrid` + server-side RRF vs 0.1 floor) | Integration test against real Qdrant |
| F14 multi-source corpus filter behavior | Test `/knowledge/workspaces/{id}/chat` with 2+ sources |
| F1/F2 leak potential (ACL on V2 points) | Inspect a V2 point payload for a restricted source with the flag on |
| Canonical mapping coverage after slice 2 | `knowledge_canonical_links` counts vs source/document/entity counts per org |

*End of Phase 0 audit and Phase 1 contract. Next: slice 1 implementation (domain + port + migration + adapter + deps + tests), no productive wiring.*
