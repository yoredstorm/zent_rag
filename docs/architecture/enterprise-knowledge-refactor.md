# Enterprise Knowledge Engine — Architecture Refactor (Phase A)

> **Status:** Phase A ADR (audit + contracts). Default runtime remains V1.
> **Date:** 2026-09-11
> **Base:** `master` @ `5269ffe` (Knowledge IA: Resumen · Fuentes · Semántica · Mejora)
> **Scope of this document:** CURRENT → TARGET → GAPS → keep / modify / deprecate → migration → file lists → roadmap A–H.
> **Product lock (Ideas buenas / Tester):** Phase G sources-first workspace (not a pixel-clone of NotebookLM). Phase A does **not** change UI e2e ACs, tenant isolation, or workspace isolation.
> **Out of scope here:** Phases B–H implementation, Phase G UI, V2 ingestion cutover, new vector DB, new LLM gateway, Neo4j.

This is **not** a greenfield MVP. Zent already runs a production RAG stack (FastAPI, Postgres, Qdrant, Redis, LiteLLM/Novita, RBAC, org/workspace isolation, ACL pre-LLM, Knowledge Learning Engine, Knowledge Score, SSE, catalog, audit, usage, observability, evaluation, workers, connectors, hybrid dense+sparse, human-in-the-loop). Phase A records what exists and draws the V2 boundary so later phases evolve that stack instead of replacing it.

---

## 0. Non-negotiables

| Keep | Never in this refactor |
|---|---|
| FastAPI (`src/api/`) | New MVP / rewrite of working systems |
| Postgres (catalog, jobs, scores, audit) | Another vector DB |
| Qdrant (`rag_documents`, named dense+sparse) | Another LLM gateway |
| Redis (queues, SSE pub/sub, conversation TTL) | Neo4j (graph stays in Postgres) |
| LiteLLM / Novita (`src/infrastructure/llm/`) | Auto-promoting `INFERRED` → `APPROVED` |
| RBAC + org/workspace isolation | Changing default ingestion in Phase A |
| ACL filter **before retrieval / pre-LLM** (`visibility` / `acl_users` / `acl_groups`) | Switching portal layout in Phase A (4-pillar IA stays until G) |
| Knowledge Learning Engine (FASE 33) | Migrating all normalizers to V2 in Phase A |
| Knowledge Score (explicable, not “% of embeddings”) | Productive mocks in tests |
| SSE (RAG, jobs, learning, platform realtime) | Changing portal e2e acceptance in Phase A |
| Zent visual identity (tokens, type, chrome) | Pixel-cloning NotebookLM |
| Semantic Catalog + Review Queue | |
| Audit, usage, observability, evaluation | |
| Workers + connectors (SQL + Knowledge Platform) | |
| Hybrid dense + sparse + rerank | |
| Human-in-the-loop: **`INFERRED != APPROVED`** | |

Feature flag for the parallel V2 path:

- Env: `RAG_KNOWLEDGE_V2_ENABLED` (Settings field `KNOWLEDGE_V2_ENABLED`)
- Default: **`false`**
- While off, no request path, worker, or normalizer may call V2 ingestion.

Existing FASE 33 flags keep the accidental double prefix (`RAG_RAG_KNOWLEDGE_*` because the field itself starts with `RAG_`). The V2 flag uses a single `RAG_` prefix on purpose so the name in the brief matches the environment variable.

---

## 1. CURRENT — what exists today

The product already has **several overlapping knowledge systems**, not one engine. They share org isolation and often share CatalogStore / Qdrant / LiteLLM, but they do not share a single document or corpus model.

```
                    ┌─────────────────────────────────────────┐
  Connectors /      │  Data Onboarding wizard                 │
  uploads / SQL  ──►│  src/platform/data_onboarding/          │
                    │  document_facts + document_insights     │
                    └───────────────┬─────────────────────────┘
                                    │ creates kb_sources / catalog_sources
                                    ▼
┌──────────────┐   jobs (Postgres)    ┌─────────────────────────────┐
│ Knowledge    │  Redis wakeup        │ KnowledgeIngestionEngine    │
│ Platform     │ ───────────────────► │ src/knowledge/engine/       │
│ kb_sources   │                      │ normalize → Markdown        │
│ /api/v1/     │                      │ chunk → embed → Qdrant      │
│ sources      │                      └───────────────┬─────────────┘
└──────────────┘                                      │
                                                      ▼
┌──────────────┐   discovery jobs     ┌─────────────────────────────┐
│ Connector    │ ───────────────────► │ Semantic Catalog (FASE 24)  │
│ plugins      │                      │ + SemanticInference         │
│ src/         │                      │ + RelationshipDetector      │
│ connectors/  │                      └───────────────┬─────────────┘
└──────────────┘                                      │
                                                      ▼
                    ┌─────────────────────────────────────────┐
                    │ Knowledge Learning Engine (FASE 33)     │
                    │ CONNECTION→DISCOVERY→PROFILE→SEMANTIC   │
                    │ →RELATIONS→QUESTIONS→SCORE→(eval)       │
                    │ src/platform/knowledge_learning/        │
                    └───────────────┬─────────────────────────┘
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          ▼                         ▼                         ▼
   Qdrant rag_documents      Postgres catalog_*        Intelligence Engine
   + ACL pre-LLM             knowledge_scores          understand→plan→gate
          │                         │                         │
          └────────────► RAGOrchestrator / HybridRetriever ◄──┘
                                    │
                                    ▼
                         Grounded answer + [Doc: N]
                         + SSE /api/v1/rag/query/stream
```

### 1.1 Knowledge Platform (ingestion V1)

**Paths:** `src/knowledge/`

| Piece | Path | Role today |
|---|---|---|
| Engine | `src/knowledge/engine/service.py` | `KnowledgeIngestionEngine`: durable jobs `pending→running→completed\|failed→dead`, retry backoff, `cursor_snapshot` resume, orphan vector delete via `source_documents` |
| Connectors | `src/knowledge/connectors/` | `sql`, `file`, `csv`, `excel`, `web`, `s3`, `api`, `gdrive` via `registry.py` |
| Normalizers | `src/knowledge/normalize/` | Bytes → **flat Markdown** (`pdf`, `docx`, `html`, `txt`/`md`/`json`). Registry in `__init__.py` |
| Queue | `src/knowledge/queue.py` | Redis `RAG_KNOWLEDGE_QUEUE_KEY` (`rag:knowledge:queue`) — wakeup only; Postgres is SoT |
| Storage | `src/knowledge/storage.py` | Safe upload under `UPLOAD_DIR/{org}/` |
| Domain | `src/core/domain/entities.py` | `KnowledgeBase`, `KbSource`, `IngestionJob`, `SourceDocument`, `Workspace` |

**What the engine actually does:** connector `iter_records` → optional KB `metadata_schema` → `get_chunker(fixed\|recursive\|sentence)` → embed batch 32 → Qdrant upsert with payload `{source_id, external_id, content_hash, organization_id, knowledge_base_id}`. There is **no structured document**, **no section/entity index**, **no corpus**. Markdown is the only intermediate.

**APIs:** `src/api/routes/sources.py` (`/api/v1/sources*`), `src/api/routes/knowledge_bases.py`, `src/api/routes/jobs.py`. Cross-tenant access is 404. Workspace via `resolve_workspace`.

**Worker:** `worker_entry.py` → `src/connectors/sql/worker.py` BLPOP on the knowledge queue first, then legacy SQL ingestion queue. Knowledge jobs call `get_knowledge_engine()`.

### 1.2 RAG retrieval, rerank, evaluation

**Paths:** `src/rag/`

| Piece | Path | Role today |
|---|---|---|
| Hybrid | `src/rag/retrieval/hybrid.py` | Classify query → vector / lexical / hybrid; server-side `HybridStore.search_hybrid` or client RRF/weighted; ACL `user_id`/`groups` forwarded |
| Models | `src/rag/retrieval/models.py` | `RetrievalQuery` — FASE 15 identity for **ACL pre-LLM** |
| Fusion | `src/rag/retrieval/fusion.py` | RRF, weighted, dedupe, doc-type priority, threshold |
| Classify | `src/rag/retrieval/classify.py` | Lexical vs semantic vs mixed (ES/EN stopwords) |
| Chunking | `src/rag/chunking/` | `fixed` / `recursive` / `sentence` per KB |
| Rerank | `src/rag/reranking/reranker.py`, `cross_encoder.py` | Optional LLM or cross-encoder; failure falls back to retrieval order |
| Eval | `src/rag/evaluation/` | Golden sets, deterministic metrics + LLM-judge, regression compare |
| Citations | `src/rag/evaluation/metrics.py` | Parses `[Doc: N]`; `citation_accuracy` |

**Query API:** `POST /api/v1/rag/query` and `/rag/query/stream` (`src/api/routes/query.py`) → `RAGOrchestrator` (`src/agents/runtime/orchestrator.py`). SSE events for tokens / completion.

**Federated:** `src/platform/federated/search.py` also applies FASE 15 group ACL before search.

### 1.3 Qdrant + LiteLLM

**Qdrant** (`src/infrastructure/qdrant/vector_store.py`, `bm25.py`):

- Single collection `rag_documents`; **`organization_id` mandatory** on search/upsert.
- Optional filters: `knowledge_base_id`, `workspace_id`.
- Named vectors `dense` + `sparse` (legacy anonymous dense until `migrate_qdrant_hybrid.py`).
- ACL payload: `visibility` (`public`/`admin`) + `acl_users` + `acl_groups`. Empty ACL = org-wide. Filter is applied **in Qdrant, before chunks reach the LLM**.

**LLM** (`src/infrastructure/llm/provider.py`, `router.py`):

- LiteLLM `acompletion` / `aembedding`; Novita/OpenAI/Ollama via `RAG_LITELLM_*`.
- Circuit breaker, token/latency metrics. KLE uses the same provider (`RAG_KNOWLEDGE_LLM_*`).

### 1.4 Semantic Catalog + SemanticInference (FASE 24)

**Paths:** `src/catalog/`, domain `src/core/domain/catalog.py`, docs `docs/intelligence/semantic-catalog.md`

Physical + semantic tables live in Postgres (`catalog_sources`, `catalog_tables`, `catalog_columns`, `catalog_entities`, `catalog_fields`, `catalog_relationships`, `catalog_metrics`, `catalog_authority`, `catalog_suggestions`, `catalog_enum_values`, `catalog_lineage`, …). Store: `src/catalog/store.py` (raw SQL, org-scoped, `ensure_tables` idempotent; created by Alembic `080`).

**`SemanticInference`** (`src/catalog/inference.py`):

- Input: **metadata only** (names, types, comments) — never raw rows, never sensitive columns.
- Output: entities/fields with provenance **`INFERRED`** + Review Queue suggestions.
- Heuristics first (`infer_entity_name` / `infer_field_name` / `catalog/signals.py`); optional LLM enrich; **never auto-APPROVED**.
- FASE 33A split: `run_entities` / `run_fields` as observable KLE stages.

Also: `relationships.py` (FK OBSERVED vs inferred SUGGESTED), `glossary.py`, `metrics.py`, `authority.py`, `readiness.py` (catalog readiness — **a second score**, distinct from Knowledge Score), `studio.py`, `hybrid_search.py`, `jobs.py`.

**API:** `/api/v1/catalog` (`src/api/routes/catalog.py`) — Connector ACL → Discovery ACL → Catalog ACL.

### 1.5 Knowledge Learning Engine — Phase 33 (33A–33H in code)

**Domain:** `src/core/domain/knowledge_learning.py`  
**Runtime:** `src/platform/knowledge_learning/`  
**API:** `/api/v1/knowledge/learning` (`src/api/routes/knowledge_learning.py`)  
**RBAC:** `knowledge:read` / `knowledge:write`  
**Migrations:** `094` runs/steps/events/scores; `095` LLM analysis cache; `096` relationship intelligence; `097` business questions.

Pipeline (orchestrator header):

```
CONNECTION → DISCOVERY → PROFILING → SEMANTIC ANALYSIS → RELATIONSHIPS
  → QUESTIONS / VALIDATION → (chunk/embed/index when flagged)
  → EVALUATION → SCORING → READY
```

| Module | Path | FASE | Notes |
|---|---|---|---|
| Orchestrator | `orchestrator.py` `KnowledgeLearningEngine` | 33A+ | Reuses Discovery, `SemanticInference`, `RelationshipDetector`, CatalogStore. Durable jobs prefix `knowledge_learning`. Does **not** replace catalog |
| Schema analyzer | `schema_analyzer.py` | 33A | Fingerprint per table for cache |
| Business analyzer | `business_analyzer.py` | 33A | Deterministic business hints |
| LLM Analyzer | `llm_analyzer.py` `LLMAnalyzer` | 33B | 1 LLM call **per table**, JSON/Pydantic, sanitized context, cache `(org, schema_fingerprint, prompt_version, model)`. Flag `RAG_KNOWLEDGE_LLM_ANALYSIS_ENABLED` default **false**. `INFERRED` never stored as truth |
| Relationship Intelligence | `relationship_analyzer.py` | 33C | Signals: FK + types + naming + org convention + LLM. OBSERVED (FK) vs INFERRED. No physical constraints on customer DBs |
| Knowledge Graph | `knowledge_graph.py` | 33C | **Postgres only** (explicitly not Neo4j). Nodes: entity/field/metric/rule/synonym/question/source |
| Questions + HITL | `question_generator.py`, `validation_engine.py` | 33D | Ambiguity → questions; answer/skip/defer. Flag `RAG_KNOWLEDGE_AI_QUESTIONS_ENABLED` default **false** |
| Knowledge Score | `knowledge_score.py` `KnowledgeScoreService` | 33A | Dimensions + weights + reasons + gate `NOT_READY\|LEARNING\|NEEDS_INPUT\|READY\|DEGRADED`. **Not** “how many embeddings” |
| Evaluation | `evaluation.py` | 33G | Synthetic questions from catalog; optional judge. Flag `RAG_KNOWLEDGE_EVALUATION_ENABLED` default **false** |
| Events / SSE | `events.py` | 33E | Durable `knowledge_events` + Redis `rag:events`. `GET .../runs/{id}/stream` with replay |
| Repository | `repository.py` | 33A | Postgres runs/steps/events/scores/settings |

**Knowledge Score dimensions** (defaults in domain):

| Dimension | Weight |
|---|---|
| schema_discovery | 15% |
| semantic_understanding | 20% |
| relationships | 15% |
| human_validation | 15% |
| knowledge_coverage | 15% |
| rag_evaluation | 15% |
| data_freshness | 5% |

READY requires overall ≥ 80, schema ≥ 90, semantic ≥ 70, eval ≥ 75, **zero critical pending questions**. Human validation is a first-class gate, not a tooltip.

**Stages declared but not all executed in Phase 1 of KLE:** `CHUNKING`, `EMBEDDING`, `INDEXING`, `AWAITING_VALIDATION`, `READY` exist on `LearningStage` but `PHASE1_ACTIVE_STAGES` is discovery→questions→scoring (plus LLM when flagged). Indexing of documents still happens in the Knowledge Platform engine, not inside KLE.

### 1.6 Document Insights + Data Onboarding

**Paths:** `src/platform/data_onboarding/`  
**API:** `/api/v1/data-onboarding`  
**Migration:** `083` sessions; `093` `document_insights` + `catalog_suggestions.type='document_fact'`

| Module | Role |
|---|---|
| `service.py` | Wizard orchestration; reuses connectors, catalog, sources, RAG |
| `document_facts.py` | Deterministic extract (dates, amounts, parties, RUT, email, clauses) + optional LLM; LLM never blocks |
| `document_insights.py` | Persist facts with status **`pending`**; human `approved` / `edited` / `rejected`. **Nothing auto-approves** |
| `flows.py`, `questions.py`, `profile.py` | Guided SQL vs document vs file flows |
| `store.py` | Sessions scoped by `organization_id` + optional `workspace_id` |

Portal entry: `/knowledge/add` (and `/knowledge/add/:sessionId`). Overview deep-links resume + `NEEDS_ATTENTION`.

### 1.7 Intelligence (query-time reasoning)

**Paths:** `src/intelligence/`, domain `src/core/domain/intelligence.py` + `semantic.py`  
**API:** `/api/v1/intelligence`  
**Docs:** `docs/intelligence/*`

`IntelligenceEngine` (`engine.py`) composes: **understand → plan → evidence → signals → answerability gate → answer or abstain**. Injected into `RAGOrchestrator`. The LLM is never the only signal.

Includes: `understanding.py` (intent/entities against **approved** `business_definitions`), `answerability.py`, `abstention.py`, `semantic_compiler.py`, `graph_reasoning.py` (over catalog, not Neo4j), `analytical.py`, `temporal.py`, `verified_queries.py`, `source_conflict.py`, `benchmark.py`.

This is **query-time** intelligence. KLE is **learn-time** intelligence. They are not the same pipeline.

### 1.8 Governed Learning (FASE 25) — a third “learning” system

**Paths:** `src/learning/`  
**API:** `/api/v1/learning`  
**Docs:** `docs/intelligence/learning-loop.md`  
**Migration:** `081`

Observation → Inference → Suggestion → Human Review → Approval → Versioned Knowledge → Evaluation Replay → Production.

`improvements.py` (deterministic priority), `gaps.py`, `clustering.py`, `patterns.py`, `advisor.py`, `approvals.py`, `replay.py`, `spider.py`, `analytics.py`. Portal: `/knowledge/improvements`, `/knowledge/review`.

**Do not confuse** with KLE (`/knowledge/learning`). FASE 25 is the post-production improvement loop; FASE 33 is source onboarding/learning.

### 1.9 Knowledge Hub (legacy parallel product)

**Paths:** `src/platform/knowledgehub/hub.py`, `src/api/routes/knowledge_hub.py`  
**Tables:** `knowledge_sources`, `documents` (migration `065`)  
**Portal:** `/knowledge-hub`  
**Refresh loop:** `src/api/main.py` `_knowledge_refresh_loop`

Comment in code: “AI Knowledge Hub v2 — Auto-Discovery & Curation”. This is **not** Enterprise Knowledge V2. It is an older hub with its own source types (`url`, `rss`, `repo`, `s3`, `manual`), signatures, and categories. Permissions today are `billing:read/write` (not `knowledge:*`). Treat as coexistence debt.

### 1.10 Portal Knowledge UI (current IA)

**Routes:** `portal/src/App.tsx`  
**Nav:** `portal/src/lib/knowledgeNav.ts`  
**Layout:** `portal/src/components/KnowledgeLayout.tsx`  
**Pages:** `portal/src/pages/knowledge/`  
**KLE widgets:** `portal/src/components/knowledgeLearning/`

Four pillars from **PR #4 / #5** (`KNOWLEDGE_PILLARS` in `knowledgeNav.ts`): **Resumen · Fuentes · Semántica · Mejora**, plus collapsed **Avanzado**. Portal e2e (`portal/e2e/customer.spec.ts`) asserts those four links. **This IA is a temporary bridge.** Phase G replaces it with a sources-first knowledge workspace (see §2.2 / §9 Phase G). Phase A must **not** change those e2e acceptance criteria.

| Pillar (bridge) | Routes today |
|---|---|
| Resumen | `/knowledge` (`Overview.tsx`) — sources, jobs, KBs, vector points, onboarding gate |
| Fuentes | `/knowledge/sources`, `/knowledge/sources/:id`, `/knowledge/add` |
| Semántica | `/knowledge/glossary`, `/understanding`, `/catalog` |
| Mejora | `/knowledge/learning` (KLE studio 33E), `/improvements`, `/map` (33F graph), `/review` |
| Avanzado | jobs, SQL, database builder, collections (KBs), documents, playground, connectors, Knowledge Hub |

This is **operator IA** (catalog + learning studio + jobs). It is **not** yet the sources-first workspace (LEFT Sources · CENTER Chat\|Viewer · RIGHT Studio).

### 1.11 Isolation, ACL, SSE, eval, workers — already in production

| Concern | Where |
|---|---|
| Org isolation | Bearer-only identity; `organization_id` on Qdrant/SQL/Redis/audit; cross-tenant 404 |
| Workspace | `Workspace` entity; `workspace_id` on KB, source, catalog_source, learning runs, Qdrant payload; `085_workspace_isolation.py` |
| RBAC | `owner/admin/member/viewer` → permissions; KLE uses `knowledge:read/write` |
| ACL pre-LLM | `src/platform/acl/groups.py` + Qdrant filter in `vector_store.py` |
| SSE | RAG stream, ingestion jobs, KLE run stream (durable replay), `/api/v1/platform/realtime/stream`, training |
| Audit | `AuditLogService` on source/KLE mutations |
| Usage | LiteLLM tokens + KLE usage events (uuid5 idempotent) |
| Observability | Prometheus knowledge_* metrics, structlog, OTEL |
| Evaluation | `/api/v1/eval` (`src/rag/evaluation`) **and** KLE `evaluation.py` |
| Workers | `worker_entry.py` + SQL worker polling both queues |
| Connectors | `src/connectors/plugin/` (postgres/mysql/mssql/oracle/db2/csv/excel/pdf/rest/graphql/s3) **and** `src/knowledge/connectors/` |

### 1.12 What CURRENT does *not* have

There is **no** `KnowledgeCorpus`, **no** `StructuredDocument` (until Phase A scaffolding), **no** multi-level index (document / section / entity / chunk), **no** org-level knowledge object distinct from “a KB plus a catalog”, **no** single pipeline that runs SOURCE→…→CITATIONS, and **no** sources-first workspace (LEFT Sources · CENTER Chat|Viewer · RIGHT Studio). The 4-pillar IA is a **temporary** operator console. Documents become Markdown blobs; SQL becomes catalog rows; the two meet only at retrieval time and in the KLE score.

---

## 2. TARGET — Enterprise Knowledge Engine

One engine, one mental model, existing infrastructure.

```
SOURCE
  → STRUCTURED          (Structured Document / Table Profile — lossless vs Markdown-only)
  → SEMANTIC            (entities, fields, facts, relations — INFERRED)
  → ORG KNOWLEDGE       (APPROVED glossary, metrics, rules, corpus membership)
  → MULTI-LEVEL INDEX   (document / section / entity / chunk on Qdrant + Postgres)
  → RETRIEVAL           (hybrid dense+sparse + ACL pre-LLM + rerank)
  → REASONING           (IntelligenceEngine: understand → plan → gate)
  → GROUNDED ANSWER     (LLM only over ACL-filtered, scored context)
  → CITATIONS           (stable source/section locators, not just [Doc: N])
  → CONTINUOUS LEARNING (KLE + FASE 25 loop; HITL; Knowledge Score)
```

### 2.1 Corpus / workspace model

| Concept | Meaning in TARGET | Maps from CURRENT |
|---|---|---|
| **Organization** | Tenant boundary (unchanged) | `Organization` |
| **Workspace** | Isolation + UX container (unchanged) | `Workspace` (`024`, `085`) |
| **KnowledgeCorpus** | Queryable body of knowledge inside a workspace: the set of sources a user “asks” | **New.** Optional 1:1 link to existing `KnowledgeBase` during coexistence |
| **Source** | Connector-backed origin (file, SQL, web, …) | `KbSource` (canonical). Hub `knowledge_sources` fold in later |
| **StructuredDocument** | Lossless intermediate (blocks, heading path, page, tables) | New. Today: Markdown string + `source_documents` |
| **KnowledgeBase** | **Index/collection config** (chunking, embedding, retrieval strategy) — not the UX noun | Keep as retrieval profile attached to a corpus |

Rules:

1. A corpus is **workspace-scoped** and **org-scoped**. No corpus without both IDs.
2. A source belongs to at most one primary corpus (can be re-attached with an explicit job).
3. Retrieval default filter: `organization_id` + `workspace_id` + corpus→`knowledge_base_id`(s) + ACL.
4. Catalog / KLE continue to key off `catalog_sources` / `kb_sources`; corpus is an **overlay**, not a third physical source table in Phase A.

### 2.2 Sources-first knowledge workspace (Phase G product — not Phase A UI)

**Bridge:** the current 4-pillar IA (PR #4 / #5: Resumen · Fuentes · Semántica · Mejora) stays in production through Phases A–F. Phase G **replaces** that chrome with a sources-first workspace. Do not pixel-clone NotebookLM: keep **Zent visual identity** (existing portal tokens, type, density, RBAC chrome).

**Home (Phase G):** a list of **knowledge workspaces** (org-isolated, `workspace_id` unchanged). Each card shows **coverage** (Knowledge Score / source coverage) and **conflicts** (reuse `src/intelligence/source_conflict.py` + catalog authority — not a new conflict engine). Opening a workspace is the product, not “open the catalog”.

**Workspace chrome — three panes + tabs:**

```
┌──────────────────────────────────────────────────────────────┐
│  Tabs:  Chat  |  Sources  |  Studio  |  Advanced             │
├──────────────┬─────────────────────────────┬─────────────────┤
│ LEFT         │ CENTER                      │ RIGHT           │
│ Sources      │ Chat  ⟷  Viewer             │ Studio          │
│ (corpus      │ (ask the corpus)            │ (artifacts)     │
│  list)       │ (highlight cited span)      │                 │
└──────────────┴─────────────────────────────┴─────────────────┘
```

| Region | Role | Maps from CURRENT (do not rewrite in A) |
|---|---|---|
| **LEFT · Sources** | Corpus source list; add/sync; select to open viewer | `/knowledge/sources`, `SourceDetail.tsx` |
| **CENTER · Chat \| Viewer** | Ask the corpus **or** read the selected source. Clicking an inline citation `[1]` **highlights** the span/page/block in the viewer | Chat + `/knowledge/playground` + structured locators from Phase F |
| **RIGHT · Studio** | Generated artifacts over the **same corpus** (HITL: INFERRED until approved) | KLE studio widgets + `portal/src/pages/knowledge/studio/panels.tsx` + map |
| **Advanced** | Operator surfaces that do not belong on the happy path | Today’s Avanzado + Semántica/Mejora leftovers (glossary, catalog, review, jobs, SQL, Hub shim) |

**Tabs:** `Chat` / `Sources` / `Studio` (+ `Advanced`). The 4 pillars are **not** the Phase G tabs.

Phase A **does not** change `KnowledgeLayout`, `knowledgeNav.ts`, or `portal/e2e/*`.

### 2.3 Phase G must-have product (Ideas buenas / Tester)

Ship these in Phase G. Audio/video studio and a NotebookLM lookalike are **out**.

| Must-have | Meaning | Reuse |
|---|---|---|
| **Inline citations `[1]` → highlight in viewer** | Grounded answer emits numbered cites; click selects LEFT source + scrolls/highlights the block/page in CENTER Viewer. Not only a footnote list. Compat: keep `[Doc: N]` in eval until metrics move | Phase F locators; `src/rag/evaluation/metrics.py` today parses `[Doc: N]` |
| **Learning events reales in the workspace** | Activity in the workspace is `knowledge_events` / SSE (`src/platform/knowledge_learning/events.py`) — no fake timers or simulated stages | KLE event bus; `LearningActivityFeed` |
| **Studio MVP first** | **Summary, FAQ, Timeline, Comparison, Key Facts, Risks, Map.** Each artifact is INFERRED until Review/approve. **Audio / video later** (not G) | Document insights + KLE graph (`/knowledge/map`) + IntelligenceEngine; do not invent a second LLM stack |
| **Suggested questions from corpus** | Questions justified by catalog / approved facts / KLE `question_generator` + eval synthetics — not a random FAQ | `src/platform/knowledge_learning/question_generator.py`, `evaluation.generate_synthetic_questions` |
| **Source details = coverage + Open / Relearn** | Source row/detail shows coverage (Score dimensions / last learned) and two actions: **Open** (viewer) and **Relearn** (KLE start / re-sync). Internals stay in Advanced | `SourceDetail.tsx`, `POST /api/v1/knowledge/learning/start`, Knowledge Score |

**Hard constraints (all phases, including G):**

1. **`INFERRED != APPROVED`** — Studio artifacts, suggested questions, and facts never auto-promote.
2. **ACL pre-retrieval** — viewer, chat, studio, and suggested questions only see chunks/sources that already passed Qdrant ACL (`visibility` / `acl_users` / `acl_groups`) + org/workspace filters. No “show then hide”.
3. **Zent look, not a clone** — layout *pattern* (sources / chat+viewer / studio) is the product constraint; visual system stays Zent.

### 2.4 Provenance (unchanged law)

`OBSERVED` (measurable) / `INFERRED` (hypothesis) / `APPROVED` (human) / `REJECTED`.

- LLM Analyzer, SemanticInference, document facts, relationship hypotheses: **INFERRED or OBSERVED**.
- Review Queue, KLE questions, Document Insights review, FASE 25 approvals: the **only** promotion path.
- Retrieval may use INFERRED for ranking hints; **answers that assert business truth** must cite APPROVED or OBSERVED evidence, else IntelligenceEngine abstains / asks.

### 2.5 Multi-level index (later)

| Level | Store | Built from |
|---|---|---|
| Document | Postgres (`source_documents` evolved) + Qdrant payload | StructuredDocument |
| Section / block | Qdrant point + heading_path | StructuredBlock |
| Entity / fact | catalog_* + document_insights (approved) | SEMANTIC + ORG KNOWLEDGE |
| Chunk | Existing chunkers, but **over structured text**, not raw Markdown flatten | Same `src/rag/chunking/` |

Still **one Qdrant collection**, same named vectors, same ACL fields.

---

## 3. GAPS

| Gap | Evidence | Risk if ignored |
|---|---|---|
| No Structured Document | Normalizers return `str`; engine chunks `record.content` | Loss of tables, headings, page numbers; weak citations |
| No KnowledgeCorpus | KB = vector config; “collections” in portal = KB list | Users cannot say “this project’s knowledge” without mixing indexes |
| Three source registries | `kb_sources`, `knowledge_sources`, `catalog_sources` | Split UX (Hub vs Platform vs Catalog); inconsistent ACL |
| Two learning systems | `src/learning` vs `src/platform/knowledge_learning` | Duplicate Review / Improvements / questions |
| Two readiness scores | `catalog/readiness.py` vs `knowledge_score.py` | Conflicting “82% ready” |
| Two evaluation stacks | `src/rag/evaluation` vs KLE `evaluation.py` | Divergent citation/faithfulness numbers |
| KLE does not index documents | Stages CHUNKING/INDEXING declared; Phase 1 skips them | SQL sources get semantics; PDFs only get Markdown chunks |
| Document insights isolated | `document_insights` not in Knowledge Score / graph | Contracts never become Org Knowledge |
| Citations are prompt-level | `[Doc: N]` over retrieved chunks, not stable source locators | Cannot jump to page/section; eval only checks index in context |
| Hub permissions | Knowledge Hub uses `billing:read/write` | Wrong ACL surface |
| Portal is operator-first (temporary) | 4 pillars PR #4/#5; e2e locks Resumen/Fuentes/Semántica/Mejora | Phase G must replace chrome — but Phase A must **not** change those e2e ACs |
| No workspace home with coverage/conflicts | Overview is jobs + KB counts | Users cannot pick “which knowledge to work in” |
| Citations do not highlight the source | `[Doc: N]` is prompt-level | Cannot click `[1]` into the viewer |
| Studio is not corpus-native | KLE Learning + Map + `studio/panels.tsx` (lexicon) are separate pages | No Summary/FAQ/Timeline/Comparison/Key Facts/Risks/Map pane |
| Suggested questions not corpus-scoped | KLE questions are SQL-ambiguity HITL | Chat has no “ask these next” from the corpus |
| Double env prefix on KLE flags | Field `RAG_KNOWLEDGE_*` + prefix `RAG_` | Ops confusion (`RAG_RAG_KNOWLEDGE_*`) |
| `ensure_tables` + Alembic | Catalog/insights/KLE recreate schema in code | Drift vs `097` head |
| Markdown-only V1 path | Recursive chunker *wants* headings that PDF flatten often loses | Hybrid retrieval quality ceiling |

These gaps are **why** V2 exists. They are **not** Phase A implementation work.

---

## 4. COMPONENTS TO KEEP

Reuse as-is (call them; do not reimplement):

- **API shell:** FastAPI, versioning `/api/v1`, idempotency, tenant middleware.
- **Identity / RBAC / workspaces / audit / usage / billing.**
- **Qdrant adapter + BM25 + ACL filter + workspace delete.**
- **LiteLLM provider + router + circuit breaker.**
- **HybridRetriever + fusion + classify + rerank + context budget.**
- **Chunker registry** (will consume structured text later).
- **RAG evaluation + regression CLI** (`src/scripts/eval_engine.py`).
- **KnowledgeIngestionEngine job machine** (retry/resume/dead letter).
- **Knowledge Platform connectors + plugin connectors.**
- **Semantic Catalog store + SemanticInference + Review Queue.**
- **KLE orchestrator, LLMAnalyzer, RelationshipAnalyzer, KnowledgeGraph (Postgres), Knowledge Score, questions, SSE events.**
- **Document Insights HITL + data onboarding flows.**
- **IntelligenceEngine** (answerability / abstention).
- **FASE 25 learning loop** (improvements, replay, spider).
- **Portal 4-pillar IA and KLE studio widgets** through Phase F (bridge). Phase G **replaces the chrome**, not the widgets’ data (Score, events, graph, review).
- **Workers** (`worker_entry.py` / SQL worker dual-queue).

---

## 5. COMPONENTS TO MODIFY (later phases, not this PR’s behavior)

| Component | When | Change |
|---|---|---|
| `src/knowledge/normalize/*` | B | Emit `StructuredDocument` **in parallel**; keep Markdown `normalize()` for V1 |
| `src/knowledge/engine/service.py` | B/E | If flag on: persist structured blocks; index multiple levels; still upsert V1 chunks until cutover |
| `KbSource` / sources API | D | `corpus_id`; keep `knowledge_base_id` |
| `KnowledgeBase` | D | Become retrieval profile of a corpus |
| Qdrant payload | E | `corpus_id`, `document_id`, `block_id`, `heading_path`, `page` — additive |
| `RAGOrchestrator` / query schema | F/G | Filter by corpus; emit numbered cites `[1]` with locators |
| `src/rag/evaluation/metrics.py` | G | Citation = source+locator; keep `[Doc: N]` compat during dual-read |
| KLE orchestrator | C/H | Ingest approved document insights; run doc stages for file sources |
| Knowledge Score | C/H | Add document-coverage dimension (do not drop existing seven); feed workspace home |
| IntelligenceEngine | F | Prefer structured locators + approved org knowledge; conflicts on home |
| Portal `KnowledgeLayout` / `knowledgeNav.ts` / Overview | G | Replace 4 pillars with workspace home + Chat/Sources/Studio/Advanced; LEFT/CENTER/RIGHT panes. **Update e2e ACs in G, not A** |
| `SourceDetail.tsx` | G | Coverage + **Open** / **Relearn**; extras stay Advanced |
| KLE events + `LearningActivityFeed` | G | Real events visible **inside** the workspace (not only `/knowledge/learning`) |
| Studio pages / `studio/panels.tsx` | G | Studio MVP: Summary, FAQ, Timeline, Comparison, Key Facts, Risks, Map |
| Knowledge Hub routes | H | Proxy or redirect onto `kb_sources` + corpus |
| Settings | A (stub only) | `KNOWLEDGE_V2_ENABLED` |

---

## 6. COMPONENTS TO DEPRECATE (later; do not delete in Phase A)

| Component | Why | Sunset rule |
|---|---|---|
| `src/platform/knowledgehub/` + `/api/v1/knowledge-hub` | Parallel source/document model | After Hub sources migrate to `kb_sources` + corpus; keep route as shim |
| Portal `/knowledge-hub` and `/knowledge/documents` if they only wrap Hub | Duplicate of Fuentes | Redirect |
| Catalog-only readiness as the **user-facing** % | Conflicts with Knowledge Score | Keep API; UI shows Score + reasons |
| Markdown as the **canonical** document | Lossy | Keep as derived view (`StructuredDocument.as_markdown()`) |
| Prompt-only `[Doc: N]` as the only citation | Fragile | Compat layer in eval; Phase G UI uses `[1]` + highlight |
| 4-pillar nav as the **product** IA | Operator-first bridge (PR #4/#5) | Phase G; keep routes as Advanced/shims; **do not change e2e in Phase A** |
| `ensure_tables` as schema source of truth | Drift | Alembic-only after V2 tables exist |
| Field names `RAG_KNOWLEDGE_*` (double prefix) | Ops hazard | New flags without the extra `RAG_` in the field name |

**Never deprecate in this program:** Qdrant, LiteLLM, HybridRetriever, KLE HITL, ACL pre-LLM, Knowledge Score idea, Catalog provenance, FASE 25 approval records.

---

## 7. MIGRATION STRATEGY

### 7.1 V2 parallel, not replace

```
                 ┌──────────── V1 (default) ────────────┐
  Source ───────►│ Markdown → chunk → Qdrant            │──► RAG
                 └──────────────────────────────────────┘
                         │
                         │ if RAG_KNOWLEDGE_V2_ENABLED
                         ▼
                 ┌──────────── V2 (parallel) ───────────┐
                 │ StructuredDocument → (shadow index)  │──► logs / score / optional shadow retrieve
                 └──────────────────────────────────────┘
```

- **Phase A:** types + flag only. V1 is the only productive path.
- **Phase B+:** V2 writers run beside V1 when flag is on; readers stay V1 until shadow metrics pass.
- **Cutover (H):** default flag on for new orgs; old orgs opt-in; Hub/shim last.

### 7.2 `RAG_KNOWLEDGE_V2_ENABLED`

| Value | Behavior |
|---|---|
| `false` (default) | V2 types may exist in process; **no** engine/API/portal branch |
| `true` | Later phases may write structured docs / shadow index. Still no API contract break without a versioned field |

Shadow mode (Phase B+): for a sample of queries, run V2 retrieval **after** ACL, compare overlap with V1, log; **do not** change the user-visible answer until a separate promote flag (not invented in Phase A).

### 7.3 Data movement (future)

1. Backfill `KnowledgeCorpus` 1:1 from workspace default KB (or “Default corpus”).
2. Attach existing `kb_sources` to that corpus (`corpus_id` nullable first).
3. Re-normalize files to StructuredDocument without deleting V1 points.
4. Dual-write chunks with new payload fields.
5. Migrate Hub `knowledge_sources` → `kb_sources` (type mapping `url/rss/repo`).
6. Only then stop writing V1-only payloads.

No Alembic in Phase A. First V2 tables land in Phase B/D under a new revision after `097`.

---

## 8. Phase A — explicit file lists

Phase A **lands this document** and **may** land additive, flag-off domain types. It does **not** switch ingestion, APIs, or portal.

### 8.1 FILES TO KEEP (do not rewrite)

All of:

- `src/knowledge/engine/service.py`, `connectors/**`, `normalize/**`, `queue.py`, `storage.py`
- `src/rag/**`
- `src/catalog/**`
- `src/intelligence/**`
- `src/learning/**`
- `src/platform/knowledge_learning/**`
- `src/platform/data_onboarding/**`
- `src/platform/acl/groups.py`
- `src/infrastructure/qdrant/**`, `src/infrastructure/llm/**`
- `src/api/routes/query.py`, `sources.py`, `knowledge_bases.py`, `knowledge_learning.py`, `catalog.py`, `data_onboarding.py`, `evaluation.py`, `learning.py`
- `portal/src/pages/knowledge/**`, `portal/src/components/KnowledgeLayout.tsx`, `knowledgeLearning/**`
- `portal/e2e/customer.spec.ts` and other knowledge e2e ACs (4-pillar assertions — **do not edit in Phase A**)
- Tenant / workspace isolation: `src/api` tenant middleware, `src/platform/workspaces/`, `src/platform/acl/groups.py`, Qdrant org/workspace filters
- Alembic `001`–`097` as history (do not squash)

### 8.2 FILES TO MODIFY (Phase A only)

| File | Change |
|---|---|
| `src/core/config.py` | Add `KNOWLEDGE_V2_ENABLED: bool = False` |
| `.env.example` | Document `RAG_KNOWLEDGE_V2_ENABLED=false` |
| `src/core/domain/__init__.py` | Optional re-export (keep package a leaf) |
| `README.md` §16 | Link this ADR (optional, one row) |

### 8.3 FILES TO CREATE (Phase A)

| File | Responsibility |
|---|---|
| `docs/architecture/enterprise-knowledge-refactor.md` | This ADR (primary artifact) |
| `src/core/domain/knowledge_v2.py` | `StructuredDocument`, `StructuredBlock`, `KnowledgeCorpus` — pure domain, no I/O |
| `src/knowledge/v2/__init__.py` | Re-export domain types; **not** wired into the engine |
| `tests/test_knowledge_v2_domain.py` | Flag default + provenance / corpus invariants (no mocks of prod services) |

### 8.4 FILES TO DEPRECATE (Phase A)

**None.** Deprecation is documented in §6 only. Do not delete Hub, Documents page, or catalog readiness.

### 8.5 DATABASE MIGRATIONS (Phase A)

**None.** Head remains `097_knowledge_questions.py`.

Later (not this PR):

| Phase | Likely tables / columns |
|---|---|
| B | `structured_documents`, `structured_blocks` (org + workspace + source + content_hash) |
| D | `knowledge_corpora`; `kb_sources.corpus_id`; `knowledge_bases.corpus_id` |
| E | Qdrant payload backfill (script, like `migrate_qdrant_hybrid.py`) — not a new collection |
| H | Drop or archive `knowledge_sources` / Hub `documents` after migrate |

### 8.6 COMPATIBILITY RISKS (Phase A)

| Risk | Mitigation |
|---|---|
| Settings `extra=forbid` | New field must exist or process dies on unknown env — add the field, default false |
| Double-prefix confusion | Field name is `KNOWLEDGE_V2_ENABLED` so env is `RAG_KNOWLEDGE_V2_ENABLED` (not `RAG_RAG_…`) |
| Importing V2 from the engine by accident | Engine must not import `src.knowledge.v2` in Phase A; test that default path is unchanged |
| Treating Hub “v2” as this V2 | This ADR names it **Knowledge Hub (legacy)** vs **Knowledge V2 (corpus)** |
| Portal / API / e2e drift | No route, React, or `portal/e2e/*` AC changes in Phase A (Tester: 4-pillar e2e stays) |
| Tenant / workspace isolation | Phase A must not touch `TenantMiddleware`, `resolve_workspace`, Qdrant `organization_id` / `workspace_id` filters, or ACL groups |
| Test suite using fake LLM/Qdrant as “product” | Domain tests are pure dataclasses + Settings; no stubbed RAG answers |
| Future flag-on without ACL | V2 payload **must** copy `visibility` / `acl_*` / `organization_id` (Phase E checklist). Chat/viewer/studio in G are **post-ACL** only |

### 8.7 Phase A Tester contract

Phase A is **docs + inert types**. Tester acceptance is **not** a new UI e2e:

| Check | Pass if |
|---|---|
| CI | Existing workflow stays green (lint, pytest, portal, e2e). This PR does not add/change knowledge e2e ACs |
| Isolation | No edits under tenant middleware, workspace resolver, ACL groups, or Qdrant `organization_id` / `workspace_id` filters |
| Portal | `KnowledgeLayout` / `knowledgeNav.ts` / `portal/e2e/customer.spec.ts` unchanged (4 pillars still asserted) |
| Runtime | `RAG_KNOWLEDGE_V2_ENABLED` default false; V1 ingestion and `/rag/query` unchanged |

---

## 9. Roadmap A–H (summarized)

Aligned to SOURCE→…→CONTINUOUS LEARNING. Each phase is a PR train, not a rewrite.

| Phase | Name | Pipeline slice | What ships | What does **not** |
|---|---|---|---|---|
| **A** | Architecture + contracts | — | This ADR (incl. Phase G product lock); optional domain types; `RAG_KNOWLEDGE_V2_ENABLED=false` | Ingestion/API/portal/e2e behavior; isolation changes |
| **B** | Structured sources | SOURCE → STRUCTURED | Parallel normalizers → `StructuredDocument`; persist when flag on; V1 Markdown still default | Cutover; all formats at once |
| **C** | Semantic unification | STRUCTURED → SEMANTIC | File facts + SQL inference share provenance APIs; insights feed Review Queue / KLE | New LLM vendor |
| **D** | Org Knowledge + corpus | SEMANTIC → ORG KNOWLEDGE | `KnowledgeCorpus` persisted; workspace default corpus; attach sources; KB = profile | Force-migrate all orgs |
| **E** | Multi-level index | ORG KNOWLEDGE → INDEX | Additive Qdrant payload; section/entity points; same collection + ACL | Second vector DB |
| **F** | Retrieval + reasoning | INDEX → RETRIEVAL → REASONING | Hybrid + IntelligenceEngine consume locators / corpus filter; shadow compare | Change default answers or portal chrome |
| **G** | Grounded workspace UX | REASONING → ANSWER → CITATIONS | See §2.2–2.3: home = workspaces (coverage/conflicts); LEFT Sources · CENTER Chat\|Viewer · RIGHT Studio; tabs Chat/Sources/Studio + Advanced; `[1]`→highlight; real learning events; Studio MVP (Summary/FAQ/Timeline/Comparison/Key Facts/Risks/Map); suggested questions; source coverage + Open/Relearn. **Then** update portal e2e ACs | Pixel-clone NotebookLM; audio/video studio; auto-APPROVED artifacts |
| **H** | Continuous learning + cutover | CITATIONS → LEARNING | Unify Score + FASE 25 + KLE events; Hub shim; flag default true for **new** orgs; deprecations | Neo4j; drop V1 overnight |

**Phase A exit criteria (this PR) — Tester cares about these:**

- [x] ADR at `docs/architecture/enterprise-knowledge-refactor.md` with CURRENT / TARGET / GAPS / keep-modify-deprecate / migration / file lists / A–H **and** Phase G product lock
- [x] V2 types do not alter `/api/v1/sources`, `/rag/query`, or portal routes
- [x] Flag off by default
- [x] **CI intact** (lint + existing tests); no productive mocks
- [x] **Tenant / workspace isolation untouched** (no middleware, ACL, or Qdrant filter edits)
- [x] **No portal e2e AC changes** (`portal/e2e/customer.spec.ts` 4-pillar assertions stay)

---

## 10. ADR decisions (Phase A lock)

1. **Evolve, do not replace.** V2 is a parallel model on the same Postgres/Qdrant/LiteLLM/Redis.
2. **Corpus ≠ KB ≠ Workspace.** Workspace isolates; corpus groups sources; KB configures retrieval.
3. **StructuredDocument is the canonical file representation**; Markdown is a derived view.
4. **Postgres remains the knowledge graph.** `KnowledgeGraphService` stays. No Neo4j.
5. **ACL stays pre-retrieval** (Qdrant filter before chunks exist for Chat, Viewer, Studio, or suggested questions). V2 points inherit the same payload contract.
6. **HITL stays.** Any V2 semantic object — including Studio MVP artifacts — starts `OBSERVED`/`INFERRED`.
7. **KLE and FASE 25 both stay**; Phase H unifies UX/score, not a deletion of either in A–G.
8. **Knowledge Hub is legacy**, not “V2”.
9. **Phase A code is inert** unless someone imports types in new tests or later phases.
10. **4-pillar IA is a temporary bridge (PR #4/#5).** Phase G replaces it with the workspace chrome in §2.2. Phase A does not change e2e ACs.
11. **Zent visual identity** over any NotebookLM pixel clone. The product constraint is the **layout pattern** (Sources / Chat+Viewer / Studio), not the look.

---

## 11. Pointers (audit index)

| Area | Start here |
|---|---|
| Ingestion V1 | `src/knowledge/engine/service.py` |
| Normalizers | `src/knowledge/normalize/base.py` |
| Hybrid + ACL query | `src/rag/retrieval/hybrid.py`, `models.py` |
| Qdrant ACL | `src/infrastructure/qdrant/vector_store.py` (~L247–295, L583–594) |
| LiteLLM | `src/infrastructure/llm/provider.py` |
| Catalog + inference | `src/catalog/inference.py`, `store.py` |
| KLE | `src/platform/knowledge_learning/orchestrator.py` |
| LLMAnalyzer | `src/platform/knowledge_learning/llm_analyzer.py` |
| Knowledge Score | `src/platform/knowledge_learning/knowledge_score.py` |
| Relationships / graph | `relationship_analyzer.py`, `knowledge_graph.py` |
| Document Insights | `src/platform/data_onboarding/document_insights.py`, `document_facts.py` |
| Intelligence | `src/intelligence/engine.py` |
| FASE 25 | `src/learning/improvements.py` |
| Hub (legacy) | `src/platform/knowledgehub/hub.py` |
| Portal IA (bridge) | `portal/src/lib/knowledgeNav.ts`, `KnowledgeLayout.tsx`, `portal/e2e/customer.spec.ts` |
| Source conflicts | `src/intelligence/source_conflict.py` |
| Flags | `src/core/config.py` (FASE 33 block), `.env.example` L149–172 |
| Migrations | `src/infrastructure/db_init/versions/080`, `083`, `093`–`097` |

---

*Zent Enterprise Knowledge Engine — Phase A ADR. Product chrome for Phase G is locked in §2.2–2.3 (Ideas buenas / Tester). Next implementer: Phase B only after this document is accepted; do not implement Phase G UI in A–F; do not enable `RAG_KNOWLEDGE_V2_ENABLED` in production until Phase F shadow metrics exist.*
