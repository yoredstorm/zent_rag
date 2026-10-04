# Progressive Global Semantic Ingestion + Semantic Fabric + Dynamic Context — AUDITORÍA (Fase 0)

> **Estado:** auditoría sobre runtime real. Sin cambios de código.
> **SHA auditado:** `c2fca454c0d47d44583d2c5d7a02eb4bd8bd877e` (`master`, 2026-10-04).
> **Método:** lectura de runtime (`src/knowledge/**`, `src/rag/**`, `src/runtime/**`, `src/agents/runtime/**`), migraciones `001`–`141`, tests. Los docs se usaron solo como contraste.
> **Regla de esta fase:** no crear sistema paralelo si existe infraestructura reutilizable.

---

## 0. Resumen ejecutivo

ZENT **no es un RAG de chunks planos**. Ya tiene: parsers estructurados, Semantic Reconstruction
determinista, Document Understanding, enrichment con procedencia, Knowledge Compiler canónico
(entidades/hechos/relaciones/reglas/conflictos + evidence ledger), acceptance gate por probes,
Nutrition Score multidimensional, fingerprints de representación con grafo de invalidación,
y en el lado query un motor de long-context adaptativo con requirements, coverage, information
gain, expansión progresiva y empaquetado con MUST_KEEP.

Lo que **no existe** es la capa de comprensión semántica *progresiva y global*:

1. La ingesta parsea la fuente completa, pero **no la comprende por ventanas semánticas**.
   No hay `SemanticWindowResult`, `SemanticState`, `SemanticThread`, `SemanticStitcher`,
   `RegionalSemanticModel`, `GlobalSemanticModel`, ni `SemanticFabric`.
2. El límite real de comprensión por documento es **determinista y por documento**:
   unidades de retrieval de 1200 chars (`SEMANTIC_UNIT_MAX_CHARS`) o chunker fijo 600/50.
   No depende de la capacidad real del modelo ni del tipo/densidad de la fuente.
3. La continuidad entre partes existe **solo a nivel de fragmento físico**
   (`semantic_reconstruction`): merges de página/columna, tablas multipágina, headers repetidos.
   No hay hilos semánticos que se abran en una parte y se resuelvan en otra (apéndice, excepción lejana).
4. El `KnowledgeCompiler` corre **por documento** y no tiene síntesis regional/global ni
   reconciliación cross-source más allá de nombre normalizado/alias.
5. Las relaciones del grafo canónico (`knowledge_edges`) **no participan del retrieval**:
   solo se usan aliases para entity resolution y pins de payload. El grafo es para UI/lineage.
6. `source_coverage = 100%` no es medible hoy: no hay `SourceIngestionManifest`, ni ratio de
   cobertura, ni estado semántico reanudable por ventana. El checkpoint es por record/cursor.

**Conclusión:** la misión es una **evolución por capas sobre infraestructura existente**, no un
rewrite. Chunks se quedan como infraestructura; el cambio es insertar comprensión semántica
progresiva antes de la generación de retrieval units y una capa de activación/expansión en query.

---

## 1. CURRENT INGESTION GRAPH

### 1.1 Entrada y orquestación

```
API (src/api/routes/sources.py, ingestion.py, knowledge_bases.py)
  -> IngestionJob (Postgres, durable: pending/running/completed/failed/dead)
  -> worker_entry.py -> KnowledgeIngestionEngine.execute_job(job_id)
```

- `KnowledgeIngestionEngine`: `src/knowledge/engine/service.py:243`.
  - `execute_job` (`service.py:577`): marca running, observer de learning, `_run`, `_finish_observer`.
  - `_run` (`service.py:686`): `build_connector(source)` → `connector.connect()/validate()` →
    `iter_records(cursor)` (o `sync()` para conectores self-contained).
  - `_run_record_mode` (`service.py:750`): loop de records; checkpoint cada `_CHECKPOINT_EVERY = 10`
    (`service.py:61`) con `cursor_snapshot`; delete detection por `source_documents` +
    `delete_stale_v2_documents`; errores por record se aíslan (excepto rate limit, que reintenta job).
  - Retry: backoff exponencial + 429 con base 60s/cap 900s (`service.py:77-132`); dead letter con
    `ingestion_job_errors` (`_handle_failure`, `service.py:633`).

### 1.2 Pipeline por record (un archivo = un `StructuredDocument`)

`_ingest_record` (`service.py:894`) ejecuta, en orden:

| Paso | Código | Qué produce |
|---|---|---|
| Parse | `_parse_record` (`service.py:1169`) → `src/knowledge/structure/` parsers por formato (`pdf`, `txt`, `md`, `docx`, `html`, `csv`, `xlsx`) | `StructuredDocument` (pages/blocks/sections/tables/figures) |
| Understand | `_apply_document_understanding` (`service.py:1493`) → `src/knowledge/understanding/engine.py:78` | Chrome marking, OCR opcional, reflow, merge de tablas multipágina, **Semantic Reconstruction** obligatoria, semánticas derivadas (definitions, technical_fields, exact_literals, cross_references, relations), neighbors, artifact store (markdown/AST), digests |
| Reconstruct | `src/knowledge/reconstruction/engine.py:108/190` | IR de unidades semánticas físicas, continuations, gate por fragmento, `semantic_reconstruction` payload en metadata |
| Understand→units | `understanding/engine.py:155` → `understanding/units.py:87` | `RetrievalUnit[]` con budget `SEMANTIC_UNIT_MAX_CHARS` (default 1200); SECTION parent + hijas tipadas |
| Enrich | `_apply_enrichment` (`service.py:399`) → `src/knowledge/enrichment/pipeline.py:78` | `SemanticEnrichmentResult`: concepts, aliases, acronyms, identifiers, domain terms, temporal qualifiers, references, possible rules, synthetic questions, semantic types; guard de procedencia; metadata `enrichment` |
| Fingerprint | `_representation_descriptor` (`service.py:421`), `representation/fingerprint.py` | `RepresentationDescriptor` + fingerprint (parser/reconstruction/understanding/enrichment/chunking/embeddings/sparse/parent/compiler) |
| Persistir | `structured_repo.upsert_document` (`service.py:990`), `_register_document` (`service.py:867`) | `structured_documents` + `structured_blocks` + registry `source_documents`; change_kind created/unchanged/updated |
| Tabular | `_persist_tabular` (`service.py:1682`) | workbook/sheets/tables/columns/rows en Postgres + diff incremental por tabla |
| Compile view | `_compiler_view` (`service.py:1204`) → `KnowledgeCompiler.build` (`compiler/pipeline.py:66`) | Vista pura: entities/facts/relationships/rules/conflicts/quality (sin I/O) |
| Index | `_index_chunks` (`service.py:1901`) | Chunks → representaciones → embeddings → Qdrant (una colección `rag_documents`, named dense+sparse) |
| Summaries | `_summarize` (`service.py:2626`) | `SectionSummary`/`DocumentSummary` en modo **shadow**: se calculan y NO se persisten |
| Acceptance | `_run_acceptance` (`service.py:1222`) → `knowledge/acceptance/evaluate.py` | Probes desde enrichment → búsqueda dense real → recall@5, MRR; modo warn/quarantine |
| Nutrition | `_record_nutrition` (`service.py:1328`) → `knowledge/nutrition/score.py` | `NutritionScore` por dimensiones medidas (None ≠ 0) + demand profile + acciones |
| Compile | `_compile` (`service.py:1428`) → `KnowledgeCompiler.compile_document` (`compiler/pipeline.py:178`) | Persistencia canónica: `knowledge_canonical_objects`, `knowledge_assertions`, `knowledge_edges`, `knowledge_conflicts`, `knowledge_entity_aliases`, `evidence_ledger`, `knowledge_compilations`; eventos C8 |
| PASS 2 | `_update_payload_after_compile` (`service.py:1393`) | IDs canónicos de entidad/regla al payload del índice sin re-embedding |

### 1.3 Índice (nivel retrieval)

`_index_chunks` (`service.py:1901-2310`):

- `chunks_for_document` (`understanding/units.py:161`): si hay `metadata["understanding"]` usa
  **semantic retrieval units** (`build_retrieval_units`); si no, cae a `chunk_structured_document`
  (`structure/chunker.py:215`, `ChunkingConfig(child_max_chars=600, child_overlap=50)`).
- Parents = `DOCUMENT_STRUCTURE` (sección); children = `PARENT_CHILD` (unidades tipadas:
  DEFINITION, FIELD_DEFINITION, NOTE, WARNING, EXAMPLE, PROCEDURE, TABLE, PATTERN, CODE_BLOCK…).
- Representaciones (`representation/retrieval.py`, `representation/parent.py`):
  - dense child = **content representation** (sección + texto real);
  - sparse child = `content + retrieval representation` (conceptos/aliases/identificadores/preguntas);
  - parent = **ParentSemanticRepresentation compuesta** (nunca `parent[:N]`), fallback determinista.
- Point ID determinista: `uuid5(_CHUNK_NS, f"v2:{source_id}:{external_id}:{chunk_index}")`
  (`service.py:135`); tabular usa `point_id_for(point_key)` (`tabular/ids.py`).
- Payload: estructura (document/section/parent/page/chunk_type/chunk_id/chunk_index/prev/next/
  section_path), `representation_fingerprint`, versiones, campos de enrichment acotados,
  vista compilada preliminar (candidatos), canonical ids (PASS 2), ACL (`visibility/acl_users/acl_groups`).
- Fingerprint de representación decide **SKIP / UPDATE / REINDEX** (`representation/fingerprint.py:174`);
  grafo de invalidación por artefacto (`representation/dependencies.py:38-139`).
- Fallo parcial aislado por batch de embeddings; si nada se indexa → `ConnectorError` para reintentar
  el job (`service.py:2278-2302`).

### 1.4 Checkpoints e idempotencia (hoy)

- Job: `cursor_snapshot` cada 10 records (`service.py:787-797`).
- Documento: `structured_documents.upsert` + fingerprint de representación (skip/reindex).
- Tabular: `point_key` determinista + diff por tabla (`_index_tabular_chunks`, `service.py:2381`)
  + `policy_changed` → purga total del documento.
- Compilación: `knowledge_compilations` registra corrida; no hay reanudación intra-documento.
- **No existe checkpoint por ventana semántica ni manifiesto de cobertura de fuente.**

### 1.5 Grafo de datos persistido (Postgres, migraciones)

| Tabla | Contenido | Migración |
|---|---|---|
| `structured_documents` / `structured_blocks` | Árbol canónico V2 (pages/sections/blocks/tables/figures) | `098` |
| `structured_document_versions` | Versiones por content_hash + change_kind | `100` |
| `knowledge_canonical_objects` | Identidad canónica (kind: entity/fact/rule/concept/…, provenance, status, confidence) | `102`, `132` |
| `knowledge_edges` | Relaciones tipadas (subject/predicate/object + evidence JSONB) | `132` |
| `knowledge_assertions` | Hechos/reglas con status, temporalidad, superseded_by | `132`, `135` |
| `knowledge_entity_aliases` | Aliases canónicos con tipo/razón/evidence_ids | `135` |
| `knowledge_conflicts` | Conflictos con clasificación y evidencia | `132`, `135` |
| `claim_ledger` | Claims normalizados S-P-O + status | `103` |
| `evidence_ledger` | Evidencia append-only con locator (page/block/chunk/table/row/cell) | `103`, `132` |
| `knowledge_compilations` | Traza de compilación por documento | `135` |
| `knowledge_ingestion_quality` | Cola de calidad de parsing/extracción | `138` |
| `knowledge_retrieval_probes/evaluations/state/actions` | Acceptance + Nutrition | `139`, `141` |
| `knowledge_learning_sessions/events` | Ingesta como aprendizaje observable (SSE) | `136` |
| `tabular_*` | Representación relacional Excel/CSV con provenance a celda | `118` |
| `knowledge_corpora` | Corpus workspace-scoped (overlay) | `099` |

No hay tabla Postgres de chunks: los chunks viven en Qdrant; Postgres guarda la estructura y el
conocimiento canónico. `evidence_ledger.chunk_id` es una referencia sin FK.

---

## 2. CURRENT SEMANTIC MODEL

### 2.1 Capas reales

1. **Estructural** (`StructuredDocument`): páginas, bloques con bbox/orden, secciones con path,
   tablas, figuras. Persistido y versionado.
2. **Reconstrucción física** (`semantic_reconstruction`): `SemanticUnitIR` por elemento,
   continuations (page/column boundaries), gate (VALID/RECONSTRUCTED/DUPLICATE/…), tablas
   semánticas con records/fields, nodos estructurales, referencias. Todo determinista, misma
   fuente, mismo documento.
3. **Unidades de retrieval** (`RetrievalUnit`): tipadas (DEFINITION/FIELD_DEFINITION/NOTE/TABLE/
   PATTERN/…), con block_ids, page span, bbox, literales exactos, relations, heading.
4. **Enrichment derivado**: conceptos, aliases de retrieval, acrónimos, identificadores,
   términos de dominio, qualifiers temporales, referencias cruzadas, possible rules, preguntas
   sintéticas, semantic types. Todo `derived=true, canonical=false`, con provenance a unidades.
5. **Conocimiento canónico** (compiler, por documento): `EntityCandidate` (+alias), `FactCandidate`
   (S-P-O + temporal + evidence), `RelationshipCandidate`, `RuleCandidate` (modalidad), `ConflictCandidate`
   (taxonomía de 18 clasificaciones, gate de mostrabilidad), `QualityIssue`. Persistencia con
   refuerzo (no duplica), merge con razón y alias, evidencia obligatoria.
6. **Salud de conocimiento**: acceptance (recall de probes), nutrition (10 dimensiones), demand
   profile, acciones no destructivas.

### 2.2 Lo que NO existe como modelo

- `SemanticWindowResult` (concepts/entities/definitions/symbols/claims/rules/conditions/
  exceptions/procedures/temporal statements/references/unresolved/continuation candidates…).
- `SemanticState` (estado compacto por ventana) y `SemanticStateSelector` (carry-forward selectivo).
- `SemanticThread` (OPEN/PARTIAL/RESOLVED/AMBIGUOUS/CONFLICTING/UNRESOLVED por tipo REFERENCE/
  CONTINUATION/DEFINITION/SYMBOL/RULE_DEPENDENCY/TABLE_REFERENCE/EXCEPTION/ALIAS/TEMPORAL/ENTITY).
- `SemanticStitcher` sobre unidades semánticas (el actual `reconstruct_sequence` es stitching
  de fragmentos físicos, no de significado entre ventanas/secciones/fuentes).
- `RegionalSemanticModel` y `GlobalSemanticModel` (síntesis por región y global, no resumen).
- `SemanticFabric` (nodos: Entity/Concept/Definition/Claim/Rule/Condition/Exception/Procedure/
  Event/Metric/Attribute/Symbol/TableSemantic/TemporalAssertion/Reference/Evidence; relaciones:
  DEFINES/MENTIONS/USES/IS_A/PART_OF/HAS_ATTRIBUTE/DEPENDS_ON/APPLIES_TO/CONSTRAINS/
  HAS_CONDITION/HAS_EXCEPTION/REFERENCES/SUPPORTS/CONTRADICTS/SUPERSEDES/DERIVED_FROM/
  ALIAS_OF/SAME_AS/RELATED_TO/VALID_FROM/VALID_TO).
- `SemanticNeighborhood` (semántico) y `KnowledgeAtom` explícito; glossary y symbol table con scope.
- `QueryRequirementGraph` con traversal de dependencias semánticas (hoy hay requirements
  de evidencia a nivel retrieval).
- `SourceIngestionManifest`.

---

## 3. CURRENT CHUNK ROLE

**Qué es un chunk hoy (runtime):**

- storage shard + embedding carrier + retrieval unit + provenance locator;
- generado **después** de estructura, reconstrucción, enrichment y vista compilada;
- denso = representación de contenido; sparse = contenido + representación de retrieval;
- padre = representación semántica compuesta (conceptos, aliases, hechos/reglas compiladas,
  hijos); hijos = evidencia citable;
- payload con candidatos canónicos y, tras PASS 2, IDs canónicos a nivel documento;
- vecindad física: `prev_chunk_id`/`next_chunk_id`/`parent_id`/`section_id`;
- evidencia cruda intacta: `content` del punto + `structured_blocks` en Postgres.

**Dónde el chunk deja de ser boundary:**

- El compiler no razona por chunk: razona por documento (unidades→entidades→hechos→reglas).
- El retrieval adaptativo expande a padres, vecinos de sección, documentos y anchors exactos.

**Dónde el chunk SIGUE siendo boundary duro:**

- `SEMANTIC_UNIT_MAX_CHARS=1200` parte una unidad larga por líneas sin comprensión.
- `ChunkingConfig(child_max_chars=600, child_overlap=50)` es el fallback fijo.
- El contexto final se empaqueta por chunks; no hay "unidades de conocimiento" compiladas como
  nodos recuperables (solo payload names/keys + grafo Postgres no consultado en retrieval).
- El compiler extrae reglas/definiciones de forma determinista; no hay stitching cross-ventana
  de una definición que empieza en A y termina en B si el corte la partió.

---

## 4. CURRENT FAILURE MODES (contra la misión)

| # | Misión | Falla hoy | Evidencia |
|---|---|---|---|
| 1 | `GLOBAL INGESTION != SINGLE LLM CALL` (§0) | No hay comprensión LLM por ventanas; no hay N ventanas con continuidad. La fuente completa se parsea, pero la comprensión es por documento y determinista | `understanding/engine.py:78-217`; `summarize/service.py` solo shadow |
| 2 | `source_coverage = 100%` medible (§4-5) | No hay manifiesto ni coverage_ratio; checkpoint por cursor/record; un documento enorme es atómico por record | `service.py:750-862`; no existe `SourceIngestionManifest` |
| 3 | Planner dinámico de ventanas (§6) | Presupuesto fijo 1200 chars; no consulta capacidad del modelo, densidad, tablas, código, costo, perfil | `understanding/units.py:540`; `structure/chunker.py:32` |
| 4 | Soft boundaries (§7) | Solo dentro de la unidad (split por líneas, header de tabla repetido); una definición que cruza el budget se parte | `units.py:504-529` |
| 5 | Hard safety limit dinámico (§8) | No existe en ingesta; el único tope real es `RAG_EMBED_MAX_CHARS=6000` (red de seguridad, trunca representaciones) | `service.py:344-363` |
| 6 | Local understanding estructurado (§9) | No hay `SemanticWindowResult`; no se extraen claims/conditions/exceptions/continuations por ventana con LLM/estructura | no existe |
| 7 | SemanticState + selector (§10-11) | No existe carry-forward semántico | no existe |
| 8 | Bi-direccional / threads (§12-13) | Continuidad solo física intra-documento; sin hilos abiertos que se resuelvan después | `reconstruction/continuity.py`; `engine.py:537-558` |
| 9 | SemanticStitcher (§14) | No hay stitcher sobre unidades semánticas; conflictos solo intra-compilación | `compiler/conflicts.py:548` |
| 10 | Unidades semánticas + relaciones (§15-16) | `SemanticUnitIR` existe pero es física; relaciones del compiler no tienen IDs de unidad universales | `reconstruction/contracts.py`; `compiler/facts.py:215` |
| 11 | Regional/Global synthesis (§18-20) | No existen; el compiler es por documento | `compiler/pipeline.py:66` |
| 12 | Semantic Fabric (§21) | No existe; el grafo canónico (`knowledge_edges`) no tiene el vocabulario ni participa en retrieval | `132_knowledge_model.py`; `retrieval/*` |
| 13 | Cross-source semantics (§22) | Identidad cross-source = nombre normalizado/alias en compile; sin evidencia/scope/temporal/authority | `compiler/entities.py:476`; `compiler/store.py:259` |
| 14 | Provenance inmutable (§23) | Fuerte en general; huecos: `chunk_id` sin FK, provenance de reflow/parts parcial | `103/132`; `units.py:302-311` |
| 15 | Knowledge atoms / glossary / symbols (§24-26) | No hay atomización explícita ni glossary/symbol table con scope | no existe |
| 16 | Rule model con dependencias (§27) | `RuleCandidate` no modela `DEPENDS_ON`/condiciones/excepciones | `compiler/rules.py:98` |
| 17 | Neighborhoods (§28-29) | Física sí; semántica no | payload prev/next; sin semantic neighborhood |
| 18 | Nutrient retrieval units heredan significado global (§30) | Heredan enrichment + vista local; no IDs de Fabric ni dependencias | `representation/retrieval.py:194-208` |
| 19 | Contextual / late chunking / multi-representación (§32-34) | Una sola representación densa por child; no concept/question/rule embeddings; sin late chunking | `service.py:2085-2128` |
| 20 | Exact index (§36) | Scan literal acotado + payload de literales; sin índice exacto dedicado | `rag/longcontext/exact_search.py` |
| 21 | Grafo en retrieval (§37) | El grafo canónico no alimenta retrieval ni respuesta: `GraphRunner`/`TemporalRunner` solo observan edges/assertions (no "alimenta la respuesta todavía", `graph_runner.py:4`) y el brief canónico entra al prompt solo en modo limited/active | `orchestrator.py:1506-1546`, `:3784-3798`; planner declara `graph` sin consumidor |
| 22 | QueryRequirementGraph con dependencias (§38-39) | Requirements de evidencia por anchors/entidades; sin traversal regla→definición→excepción | `longcontext/requirements.py:161` |
| 23 | Context compiler estructurado (§43-44) | Empaqueta chunks + evidence state; no compila secciones DEFINITIONS/RULES/EXCEPTIONS/DEPENDENCIES | `longcontext/packager.py`; `package.py:59` |
| 24 | Fingerprints por etapa (§51-52) | Fingerprint de representación + invalidación de representación; sin etapas semánticas | `representation/dependencies.py` |
| 25 | Failure isolation por ventana (§53) | Aislamiento por record y por batch; sin estados de ventana | `service.py:774-785`, `2191-2202` |
| 26 | Semantic completeness / orphans / repair queue (§54-56) | Parcial: acceptance recall + nutrition; sin resolved refs/continuations/orphan rate | `acceptance/evaluate.py`; `nutrition/score.py` |
| 27 | Cross-ingestion learning (§57-58) | Refuerzo y conflicto intra-compile; sin clasificación new/corroboration/alias/dependency/supersession/gap-fill a nivel fabric | `compiler/pipeline.py:399-503` |
| 28 | Retrieval Acceptance V2 / probes / benchmark (§59-60, §67) | Acceptance = recall de chunk; benchmark V2 existe pero no mide dependency/exception/semantic coverage | `acceptance/probes.py`; `rag/evaluation/v2_metrics.py` |
| 29 | Observabilidad Ver flujo (§68) | Hay flow/trace, pero sin windows/threads/regions/fabric/orphans | `rag/flow_store.py`, `traceability.py` |
| 30 | Security/tenant y cost (§69-71) | Tenant/ACL fuertes; falta aislamiento explícito de fabric/threads y costo por ventana semántica | `usage`, `billing`; sin tablas nuevas |
| 31 | Profile modes de ingesta (§72) | Perfiles solo query-time (economy/balanced/quality/maximum_quality) | `longcontext/settings.py` |

---

## 5. REUSABLE COMPONENTS (NO reinventar)

**Ingesta / estructura**
- `src/knowledge/structure/` parsers + `ChunkingConfig` (fallback) + neighbors.
- `src/knowledge/reconstruction/` (adapters por tipo de fuente, continuity, quality gate, IR).
- `src/knowledge/understanding/` (layout, OCR provider, tables, reflow, digests, artifacts).
- `src/knowledge/tabular/` (niveles 0-5, point keys, provenance a celda, diff por tabla).

**Semántica derivada**
- `src/knowledge/enrichment/` completo (concepts/aliases/identifiers/temporal/references/rules/questions)
  con guard de procedencia, profile packs, versionado.
- `src/knowledge/compiler/` (extract, entities+resolver, facts, relationships, rules, conflicts,
  temporal, store Postgres, evidence).
- `src/knowledge/representation/` (content/retrieval/parent representations, fingerprint, invalidation graph).

**Calidad / nutrición / observabilidad**
- `src/knowledge/acceptance/` (probes deterministas, store, evaluate).
- `src/knowledge/nutrition/` (score ponderado por dimensiones medidas, demand, acciones no destructivas).
- `src/knowledge/quality/` (QualityCollector, QualityKind).
- `src/platform/knowledge_model/` (graph, lineage, impact, delta, gaps, conflicts, health).
- `src/knowledge/learning*` / sessions + `KnowledgeSystemEvent` C8 (eventos reales de aprendizaje).
- Metrics Prometheus (`knowledge_*`), billing/usage.

**Query-time (Dynamic Context ya parcial)**
- `src/rag/longcontext/registry.py` → capacidad real del modelo (DeepSeek incluido) reusable por el planner de ingesta.
- `budget.py` → `hard_limit` dinámico = min(modelo, tenant, request, costo) − reservas; tiers soft.
- `views.py` (3 canales exact/lexical/semantic + roles), `requirements.py`, `coverage.py`,
  `information.py`, `expansion.py` (8 estrategias), `packager.py`, `package.py` (generation package).
- `src/rag/adaptive/` (planner, evidence quality, claims, passages, fast path).
- `src/runtime/entity_resolution.py` (menciones→canónico), `evidence_assembly.py`, traces/flows.
- `src/rag/retrieval/hybrid.py` + Qdrant (dense+sparse+exact scan+ACL) + rerank + builders.
- `src/rag/evaluation/` (V2 metrics, runner, regression, golden, snapshot).

**Datos**
- Esquema canónico `102/132/135` (`knowledge_canonical_objects`, `knowledge_edges`,
  `knowledge_assertions`, `knowledge_conflicts`, `knowledge_entity_aliases`, `evidence_ledger`)
  es la base natural del Semantic Fabric: extender, no duplicar.
- `knowledge_ingestion_quality` (138) para cuarentena; `knowledge_retrieval_probes` (139) para probes V2.

---

## 6. ARCHITECTURAL GAPS (mapa target → piezas)

| Capacidad target | Estado | Base reutilizable | Falta |
|---|---|---|---|
| `SourceIngestionManifest` + coverage | ❌ | `structured_documents` metadata, `knowledge_compilations`, jobs | Tabla/manifiesto + contadores de cobertura por etapa |
| `SemanticWindowPlanner` | ❌ | `longcontext/registry.py`, `budget.py`, perfiles | Planner de ingesta (capability + estructura + densidad + costo) |
| `SemanticWindowResult` | ❌ | `understanding` (definitions/fields/literals/relations), LLMProvider | Extractor estructurado por ventana (JSON schema) |
| `SemanticState` + selector | ❌ | enrichment items, requirements/coverage | Estado compacto + selección por relevancia |
| `SemanticThread` + stitcher | Parcial (físico) | `reconstruction/continuity.py`, `compiler/conflicts.py`, entity resolver | Hilos semánticos + stitcher cross-ventana/región |
| `RegionalSemanticModel` | ❌ | compiler build, nutrition scope | Consolidación por región lógica |
| `GlobalSemanticModel` | ❌ | compiler, knowledge_model | Síntesis global estructurada (no resumen) |
| `SemanticFabric` | ❌ (grafo Postgres sin vocabulario target) | `knowledge_canonical_objects/edges/assertions`, evidence ledger | Nodos/relaciones target, IDs estables, retrieval API |
| Nutrient units con fabric ids | Parcial | `representation/retrieval.py`, PASS 2 | `concept_ids/rule_ids/dependency_ids/neighborhood` por unidad |
| Contextual embedding / late chunking | ❌ | `RetrievalRepresentationBuilder` | Multi-representación y contextualización según soporte real del provider |
| Graph-aware retrieval | ❌ | Qdrant hybrid + knowledge_model graph | Activación controlada (spreading) desde seeds |
| QueryRequirementGraph | Parcial | `longcontext/requirements.py`, roles | Dependencias semánticas (regla→def→excepción) y huecos |
| Dynamic ContextCompiler | Parcial | `packager`, `package`, evidence state | Secciones estructuradas + budget dinámico por necesidad |
| Fingerprints por etapa | Parcial | `representation/fingerprint.py` | Fingerprints window/stitch/regional/global/fabric |
| Invalidation graph semántico | Parcial | `representation/dependencies.py` | Nodos semánticos en el grafo |
| Failure isolation por ventana | ❌ | job retry por record | Estados COMPLETE/PARTIAL/RETRYABLE/FAILED/QUARANTINED + reanudar ventana |
| Semantic completeness / orphans | Parcial | acceptance + nutrition | resolved refs/continuations, orphan rate, repair queue |
| Perfiles de ingesta | ❌ | perfiles query | ECONOMY/BALANCED/QUALITY/MAXIMUM_QUALITY en ingesta |
| Observabilidad semántica | Parcial | Ver flujo, learning events | windows/threads/regions/fabric/orphans/expansion en flujo |

### 6.1 Duplicaciones, solapamientos y capacidades implementadas pero no activas

Detectadas en runtime (no en docs):

1. **Dos caminos de ingesta coexisten.** El camino Knowledge Platform (`src/knowledge/engine`) y el
   camino legado SQL (`src/connectors/sql/ingestion.py:1122`, con `_chunk_text` fijo y
   `RAG_CHUNK_OVERLAP`, `:234-295`). El worker atiende ambas colas. La misión debe evolucionar el
   camino Knowledge; el legado no debe recibir lógica nueva (y no es candidato a fabric).
2. **Dos chunkers en el camino Knowledge.** `structure/chunker.py` (600/50) como fallback y
   `understanding/units.py` (1200) como principal. `chunks_for_document` (`units.py:161`) elige por
   presencia de `metadata["understanding"]`. No es código muerto, pero conviene un planner único (Fase 2).
3. **Tres resolutores de entidad** con alcances distintos: `compiler/entities.py:EntityResolver`
   (canónico, por documento), `catalog/entity_resolution.py` (catálogo SQL),
   `company/discovery/resolution.py` (grafo empresa). El Fabric debe pararse sobre el canónico
   (`knowledge_canonical_objects`/`knowledge_entity_aliases`), no crear un cuarto.
4. **Feature dormante: `annotate_chunks`.** `service.py:1952` exige `understanding.get("mode") == "active"`,
   pero el payload que produce `understand_document` (`understanding/engine.py:173-207`) no tiene
   clave `mode`; `public_understanding` agrega `"mode": "active"` solo para la vista de API
   (`views.py:598`). Efecto: durante la ingesta `annotate_chunks` **nunca corre** y la etiqueta
   `chunking_strategy` queda siempre `document_structure+parent_child` (`service.py:2214-2218`).
   Decisión de Fase 2: activar anotación de forma explícita y versionada o eliminar la condición.
5. **Summaries en shadow.** `DocumentSummarizer` calcula y no persiste (`service.py:2626-2672`).
   El GlobalSemanticModel (Fase 7) no debe depender de esto; puede reutilizar su fallback extractivo.
6. **Grafo dormante en retrieval.** Planner declara `graph`; `GraphRunner`/`TemporalRunner` observan
   sin alimentar la respuesta (`runtime/graph_runner.py:4-5`); brief canónico solo en
   `limited/active` (`orchestrator.py:3784-3798`). Fase 11 lo activa con spreading controlado.
7. **`ZentRuntime` dormido** (`src/runtime/engine.py:17`): sin caller productivo. No es base para
   la misión; `RAGOrchestrator` + `AgentRuntime` son los caminos vivos.
8. **`knowledge_canonical_links`** (102) está creada y sin lectura productiva; útil para mapear
   nodos de Fabric a sistemas físicos (Fase 8) sin tabla nueva de mapping.

---

## 7. MIGRATION PLAN (fases, aditiva y flag-gated)

**Reglas de oro del programa**

1. Nada se elimina: chunks, compiler, reconstruction y long-context siguen funcionando.
2. Todo lo nuevo nace detrás de flags (`off` → `shadow` → `canary` → `active`), con métricas.
3. `source_coverage = 100%`: si una parte no se puede comprender semánticamente, se **persiste,
   marca y reanuda**; nunca se descarta.
4. `INFERRED != APPROVED`: el Fabric propone, la evidencia respalda, el humano aprueba.
5. Un concepto puede cruzar boundaries: los límites de ventana son SOFT; el hard limit se deriva
   de la capacidad real del modelo + políticas.
6. No se crea sistema paralelo: se extiende `knowledge_*`, `reconstruction`, `compiler` y `longcontext`.

### Fase 0 — Auditoría (esta)
Entregables: este documento + los 7 artefactos pedidos. ✅

### Fase 1 — Source coverage manifest + checkpoints
- Tabla `knowledge_ingestion_manifests` (org/workspace/source/document, content_hash, source_type,
  bytes, estimated_tokens, structural_units, processed_units, semantic_units, unresolved, failed,
  coverage_ratio, flags parsing/semantic/stitching/global/indexing, versiones, timestamps).
- API/repositorio; integración en `_ingest_record` y `_run_record_mode` (contadores reales por etapa).
- Estados de unidad/ventana (`COMPLETE/PARTIAL/RETRYABLE/FAILED/QUARANTINED`) + reanudación.
- Respuesta a "¿ZENT procesó toda esta fuente?" vía API y Ver flujo.
- Tests: cobertura 100% con fuente truncada simulada; reanudar solo la ventana fallida.

### Fase 2 — SemanticWindowPlanner
- `src/knowledge/semantic/planner.py`: capability (`longcontext/registry`) + perfil + tipo de fuente
  + estructura + densidad + tablas/código/referencias + costo → ventanas (4K…N) con
  **soft boundaries** (preservar unidad completa con headroom) y **hard safety limit** dinámico.
- Reutiliza presupuesto y perfiles existentes; nuevo solo el mapeo ingesta.
- Tests: definición que cruza el budget entra completa; hard limit viene de capability, no de constante.

### Fase 3 — SemanticState
- `SemanticState` compacto (conceptos activos, entidades conocidas, glosario, símbolos, reglas
  activas, refs sin resolver, continuaciones abiertas, topics, temporal, aliases, conflictos).
- Persistencia por ventana (JSONB + fingerprint); `SemanticStateSelector` para carry-forward.

### Fase 4 — SemanticThreads
- `SemanticThread` (tipos y estados de la misión, `source_units`, `target_hint`, `opened_at`,
  `resolved_by`, confidence). Índice de hilos abiertos por fuente; resolución reverse.
- Tests: referencia temprana a apéndice tardío se resuelve al procesar el final.

### Fase 5 — SemanticStitcher
- Sobre `SemanticUnit` (semánticas, no chunks): merge de continuaciones, resolución de refs/símbolos,
  conexión definición↔uso, regla↔excepción, aliases, duplicados/contradicciones/supersession.
- Reutiliza `compiler/conflicts.py` (clasificación) y entity resolver; salida a Fabric.
- Regresión dura: definición partida A/B = una unidad; regla + excepción lejana = dependencia.

### Fase 6 — RegionalSemanticModel
- Regiones lógicas (capítulo/sección/hoja/API group/schema/thread) → consolidación con dependencias
  abiertas. Determinista + LLM opcional para regiones densas.

### Fase 7 — GlobalSemanticModel + Map→Reduce→Reconcile
- Global síntesis estructurada (glossary/concepts/entities/rules/dependencies/symbols/exceptions/
  unresolved/temporal/reference graph/clusters), nunca solo resumen.

### Fase 8 — Semantic Fabric
- Proyección a nodos/relaciones target reutilizando `knowledge_canonical_objects/edges/assertions`
  (extender kinds/relaciones) + IDs deterministas + provenance + confianza + scope + temporal.
- Cross-source: same identity / likely identity / alias candidate / related concept, sin merge
  irreversible por similitud; evidence + scope + authority + temporal + confidence.

### Fase 9 — Nutrient Retrieval Units desde Fabric
- Retrieval units heredan: concept/entity/rule/dependency/definition/exception ids, neighborhood,
  representation version; raw evidence intacta; dense/sparse siguen existiendo.
- Activación por benchmark; sin reemplazo del índice.

### Fase 10 — Contextual embeddings / late chunking (según provider)
- Abstracción multi-representación (content/semantic/question/concept). Late chunking **solo si el
  provider lo soporta de verdad**; si no, contextual embedding + semantic pooling + parent
  contextualization (sin llamarlo late chunking).

### Fase 11 — Graph-aware retrieval + spreading activation
- Seeds (dense/sparse/exact/structured/graph) → activación por relación/confianza/relevancia/
  hops/gain/costo; límites duros. Fabric consultable por el retriever.

### Fase 12 — QueryRequirementGraph
- Intent/entities/concepts/anchors/valores + dependencias; define huecos reales
  (regla→definición→excepción→evidencia).

### Fase 13 — Dynamic ContextCompiler
- PLAN→SEED→INSPECT→REQUIREMENTS→EXPAND→COVERAGE→GAIN→COMPILE→REASON.
- Salida estructurada: question/user inputs/definitions/rules/conditions/exceptions/evidence/conflicts/
  unresolved/citation map; budget 4K…117K+ según necesidad (headroom real).

### Fase 14 — Retrieval Acceptance V2 + probes
- Métricas: seed recall, dependency recall, definition recall, exception recall, evidence recall,
  semantic coverage (no solo "¿apareció el chunk?").

### Fase 15 — Incremental invalidation
- Fingerprints por etapa (raw/parse/window/stitch/regional/global/fabric/retrieval/embedding) +
  extender `representation/dependencies.py` con nodos semánticos; reprocesar lo mínimo.

### Fase 16 — Benchmark
- BASELINE (nutrient chunks) vs NUEVO (fabric + dynamic context): answer correctness, evidence recall,
  dependency recall, citation precision, abstention precision, context tokens, latency, cost.
  Sin mejora medible no hay promoción.

### Fase 17 — Rollout shadow → canary → active
- Shadow compara en producción sin cambiar respuesta; canary por org; active por defecto para orgs
  nuevas. Eliminar lógica legacy duplicada recién al final.

---

## 8. CURRENT QUERY-SIDE RUNTIME (mapa relevante para Dynamic Context)

### 8.1 Entrada

- `POST /api/v1/rag/query` (`src/api/routes/query.py:322/340`) y `/rag/query/stream`
  (`query.py:525/541`) → `RAGOrchestrator.execute` (`src/agents/runtime/orchestrator.py:1896`).
- Dispatch previo a agente/workflow/tool (`query.py:118-200`, `src/runtime/dispatcher.py:277`);
  agente vía `AgentRuntime.run` (`src/api/deps.py:1225-1252`, `src/agents/runtime/agent_runtime.py:1453`).
- `ZentRuntime` (`src/runtime/engine.py:17`) está dormido: sin composición productiva.

### 8.2 RAGOrchestrator (productivo)

Orden real: cache → query views + source routing → embedding → decision/JEV/adaptive plan →
Intelligence Layer → **retrieval + SQL en paralelo** (`orchestrator.py:2530-2823`) → evaluación de
evidencia + passages → **long-context engine** (`:3016-3249`) → answerability/JEV gate →
prompt (`render_evidence`, `build_generation_package`) → generación → critic/grounding →
citas `[Doc: N]` → trazas (`_build_flow` + `record_flow`, `flow_store.py:20`).

- Retrieval productivo: `StructuredRetriever` con filtro `metadata.v2_chunk=true`
  (`orchestrator.py:1817-1894`), `HybridRetriever` (dense+sparse+RRF+rerank) y scan exacto;
  `ContextBuilder.fit_budget` (`rag/retrieval/builders.py:34`).
- Long-context: `AdaptiveLongContextEngine.run` (`rag/longcontext/engine.py:164`) con
  requirements, coverage, information gain, 8 estrategias de expansión y `ContextPackager`
  (`longcontext/packager.py:135`). **Solo el orchestrator lo invoca**; `AgentRuntime` no.
- `build_evidence_state` (`longcontext/coverage.py:332`) + `build_generation_package`
  (`longcontext/package.py:59`) son la autoridad única de evidencia/decision mode.

### 8.3 Grafo y conocimiento canónico en query-time (estado real)

- El planner declara representación `graph` (`rag/retrieval/planner.py:130-139`) y el plan
  cognitivo `GRAPH_TRAVERSAL` (`runtime/cognitive_plan.py:181-183`), pero el retrieval documental
  productivo **no consulta el grafo**.
- Si `COGNITIVE_OS_ENABLED != off` y hay `knowledge_model` inyectado (`src/api/deps.py:1102`):
  - `resolve_mentions` lee aliases/canónicos (`runtime/entity_resolution.py:109-196`) en
    `orchestrator.py:1506-1514`;
  - `GraphRunner` lee `knowledge_edges` (`runtime/graph_runner.py:31-91`) y `TemporalRunner` lee
    `knowledge_assertions` (`runtime/temporal_runner.py:95-130`), ambos como **observación**
    ("no alimenta la respuesta todavía", `graph_runner.py:4-5`);
  - el brief canónico entra al system prompt **solo en modos limited/active**
    (`orchestrator.py:3784-3798`); en shadow/off no.
- `knowledge_compilations` y `knowledge_conflicts` no tienen lectura en el pipeline de respuesta.
- Conclusión: la lógica del fabric puede construirse sobre `knowledge_model` (edges/assertions/
  aliases) sin tocar el retrieval hasta que el benchmark lo habilite (Fase 11).

### 8.4 Trazas / Ver flujo

- RAG: `rag_flows.flow` JSONB (`123_rag_flows.py`); `traceability.py` schema v2; `flow_story.with_story`
  (`rag/flow_story.py:808`) agrega narrativa, eventos y representación de conocimiento.
- Agente: `agent_runs` + `build_agent_flow` (`runtime/agent_flow.py:865`).
- Hueco: no hay nodos de flow para windows/threads/regiones/fabric/orphans (Fase 1/5/8/14).

### 8.5 Consecuencia para la misión

El "Dynamic Context Engine" de la misión está **parcialmente construido en query-time**
(requirements/coverage/gain/expansión/empaquetado). Lo que falta es que las semillas y la expansión
sean **semánticas y persistentes** (Fabric) en vez de solo chunks, y que el loop de expansión
consulte dependencias regla→definición→excepción. Eso se hace en Fases 11-13 sin reemplazar
`AdaptiveLongContextEngine`; se extienden sus estrategias y su `requirements`.

---

## 9. HARD REGRESSIONS (fixtures mínimas)

| # | Misión | Fixture | Esperado |
|---|---|---|---|
| 1 | §61 | Definición empieza en chunk físico A y termina en B | Una sola `SemanticUnit` + provenance a ambos |
| 2 | §62 | Definición temprana, uso tardío | Relación resuelta en Fabric |
| 3 | §63 | Sección temprana cita apéndice final | `SemanticThread` OPEN → RESOLVED al procesar apéndice |
| 4 | §64 | Regla en una región, excepción lejana | Dependencia `HAS_EXCEPTION` en Fabric |
| 5 | §65 | Usuario aplica regla a valor ausente en fuentes | Valor = input del usuario, no evidencia faltante |
| 6 | §66 | PDF define entidad, Excel usa alias, API usa otro nombre | Fabric propone conexión con confianza + provenance, sin merge automático |

Los tests existentes de long-context, acceptance y tabular golden se reutilizan como base;
las fixtures nuevas van a `tests/` con fakes y Postgres real, igual que `test_knowledge_nutrition_pipeline.py`.

---

## 10. DECISIONES ABIERTAS (antes de Fase 1)

1. **Alcance de la primera entrega:** ✅ resuelto: Fase 1+2 implementadas (ver §12).
2. **Provider LLM para comprensión por ventana:** usar `LLMProvider` configurado (LiteLLM/Novita),
   modelo por perfil, escalado solo cuando el determinista no alcanza (costo).
3. **Persistencia:** Postgres para manifests/estado/hilos/fabric staging (mismo patrón `knowledge_*`);
   Qdrant solo para vectores. Sin nuevo motor.
4. **Perfil default de ingesta:** `BALANCED` (ventanas medianas, determinista primero), con
   `ECONOMY` y `QUALITY`/`MAXIMUM_QUALITY` configurables por tenant.
5. **Promoción:** shadow primero; ninguna respuesta visible cambia hasta superar benchmark.

---

## 11. DECLARACIÓN DE DONE (mapeo §75)

1. 100% source coverage → Fase 1.
2. Reanudar comprensión semántica → Fases 1/3/15.
3. Concepto cruza chunk boundaries → Fases 5/8 + fixture 1.
4. Información temprana y tardía conecta → Fases 4/5 + fixtures 2/3.
5. Información posterior resuelve unknowns anteriores → Fase 4 + fixture 3.
6. Dependencias semánticas persisten → Fases 5/8.
7. Nutrient chunks heredan significado global → Fase 9.
8. Retrieval navega relaciones → Fase 11.
9. Contexto crece dinámicamente hasta cubrir requirements → Fase 13.
10. Excepciones críticas no se pierden por truncación → Fases 2/5/13.
11. Provenance exacta → reuse `evidence_ledger`; validar en cada fase.
12. Fuentes enormes sin una sola llamada masiva → Fases 2/6/7.
13. Reproceso selectivo → Fase 15.
14. Benchmark demuestra mejora → Fase 16.

---

## 12. ENTREGA FASE 1+2 (implementada sobre este SHA)

### 12.1 Archivos

| Archivo | Rol |
|---|---|
| `src/knowledge/semantic/contracts.py` | `SourceIngestionManifest`, `SemanticWindowPlan/Spec`, etapas/estados, coverage ponderado, versión |
| `src/knowledge/semantic/planner.py` | `SemanticWindowPlanner`: capability real + reservas + perfil + densidad; soft boundaries con headroom; hard limit con split por char offsets |
| `src/knowledge/semantic/store.py` | `PostgresSemanticIngestionStore`: upsert/get/list manifiestos, plan de ventanas, coverage summary, list windows |
| `src/knowledge/semantic/service.py` | `SemanticIngestionService`: off/shadow/active, ciclo begin→parsed→process_windows→indexed→finished/failed, reanudación selectiva |
| `src/knowledge/semantic/extract.py` | Comprensión local determinista por ventana: definición/regla/excepción/símbolo/referencia/claims/relaciones/continuación/topics/notas/conflictos |
| `src/knowledge/semantic/selector.py` | `SemanticStateSelector`: carry-forward relevante con caps y stats |
| `src/knowledge/semantic/state.py` | `SemanticState` merge + resolución hacia atrás de referencias y continuaciones |
| `src/knowledge/semantic/processor.py` | `SemanticWindowProcessor`: checkpoint por ventana (fingerprint + carry), statuses, métricas |
| `src/knowledge/semantic/llm.py` | `LLMWindowProvider` opcional: solo agrega items con quote literal verificado |
| `src/infrastructure/db_init/versions/143_semantic_ingestion.py` | Tablas `knowledge_ingestion_manifests` + `knowledge_semantic_windows` (aditiva) |
| `src/infrastructure/db_init/versions/145_semantic_window_results.py` | Tablas `knowledge_semantic_window_results` + `knowledge_semantic_states` (aditiva) |
| `src/core/config.py` / `.env.example` | Flags de modo/perfil/modelo/ventana/reservas |
| `src/knowledge/engine/service.py` | Integración fail-soft en `_ingest_record` y `_run_record_mode` |
| `src/api/deps.py` | Inyección del servicio en `get_knowledge_engine` |
| `src/api/routes/knowledge_nutrition.py` | Endpoints de manifiesto/cobertura/ventanas |
| `tests/test_semantic_window_planner.py` | 7 tests puros del planner |
| `tests/test_semantic_ingestion_manifest.py` | 6 tests de contratos/servicio/store/engine e2e |
| `tests/test_semantic_window_state.py` | 7 tests de extractor/estado/selector/checkpoint/LLM/store |

### 12.2 Contratos operativos

- **off (default):** comportamiento actual intacto; el servicio ni toca la DB.
- **shadow:** persiste manifiesto + plan de ventanas; no cambia el flujo.
- **active:** además, si `raw_fingerprint` + versiones del pipeline coinciden y
  `pipeline_complete`, la fuente se SALTEA completa (no re-parse, no re-embed).
- `pipeline_complete` exige las etapas requeridas por la versión activa
  (`versions["required_stages"]`). Fase 3 exige `parsing`, `indexing` y
  `semantic_windows`; al activarse Fase 5/7 se agregan `stitching`/`global` e
  invalidan manifiestos viejos una sola vez.
- Endpoints: `GET /api/v1/knowledge/semantic-ingestion/manifests|manifest|coverage|windows`.
- El hard limit se deriva de `resolve_model_capability` (DeepSeek incluido) menos
  reservas (salida/sistema/seguridad) y un techo configurable opcional. Nunca constante.

### 12.3 Verificación

- `pytest tests/test_semantic_window_planner.py tests/test_semantic_ingestion_manifest.py` → 13 passed.
- Regresión: `test_knowledge_ingestion.py`, `test_knowledge_nutrition_pipeline.py`,
  `test_knowledge_nutrition.py`, `test_knowledge_events.py` → 43 passed.
- Migración aplicada localmente (`alembic upgrade 143`).

### 12.4 Fase 3 implementada (comprensión local + estado)

- `extract_window_items` produce `WindowItem` por kind con provenance a bloques:
  concept, entity, definition, symbol, alias, claim, rule, condition, exception,
  procedure, temporal, reference, unresolved_reference, table, relationship,
  continuation, topic, note, conflict. Determinista primero.
- `SemanticWindowResult` expone acceso por kind (`.rules`, `.definitions`, …) y
  `to_dict` auditable; `derived=true`, `canonical=false`.
- `SemanticState` (JSONB por ventana) acumula glosario, símbolos, reglas,
  referencias sin resolver/resueltas, continuaciones abiertas, topics, temporal,
  aliases, relaciones pendientes y conflictos, con caps y `stats.dropped`.
- `SemanticStateSelector` hace carry-forward selectivo: siempre refs sin resolver
  y continuaciones; el resto solo si aparece en la próxima ventana o es adyacente.
- Resolución hacia atrás (§12): una referencia temprana se resuelve cuando una
  ventana posterior define su target (test `test_later_window_resolves_early_reference`).
- Checkpoint por ventana: fingerprint de contenido + carry fingerprint del estado
  seleccionado; ventana sin cambios = SKIP; solo la ventana stale se reprocesa.
- LLM opcional (`RAG_KNOWLEDGE_SEMANTIC_WINDOW_LLM_ENABLED=false`): solo agrega
  items con quote literal verificado; sin quote no hay item; techo de llamadas.
- `versions["required_stages"] = ["parsing","indexing","semantic_windows"]`:
  `pipeline_complete` y `coverage_ratio` exigen la etapa semántica; Fases 5/7
  agregarán `stitching`/`global` (invalida manifiestos viejos una sola vez).
- Endpoints: `GET /semantic-ingestion/window-results` y
  `GET /semantic-ingestion/window-state`.
- Migración `145_semantic_window_results.py` aplicada localmente.

### 12.5 Verificación Fase 3

- `tests/test_semantic_window_state.py` → 7 passed.
- `tests/test_semantic_window_planner.py` + `test_semantic_ingestion_manifest.py`
  → 13 passed (incluye engine e2e con resultados/estados y resume).
- Regresión ingesta/nutrición/eventos → 30 passed.
- Ruff limpio.

### 12.6 Fase 4 implementada (SemanticThreads durables)

- `threads.py`: `SemanticThread` con id determinista por (documento, thread_key),
  tipos REFERENCE/CONTINUATION/DEFINITION/SYMBOL/RULE_DEPENDENCY/TABLE_REFERENCE/
  EXCEPTION/ALIAS/TEMPORAL/ENTITY y estados OPEN/PARTIAL/RESOLVED/AMBIGUOUS/
  CONFLICTING/UNRESOLVED. Campos: source_units, source_windows, target_hint,
  scope, opened_at_window, resolved_at_window, resolved_by_unit, candidates,
  history, confidence.
- Apertura determinista: referencias sin resolver (REFERENCE/TABLE_REFERENCE),
  continuación por sección que sigue (CONTINUATION), símbolo sin definición en
  la ventana (SYMBOL), alias sin canónico (ALIAS), excepción anclada a símbolo
  (EXCEPTION).
- Resolución bidireccional: la ventana N resuelve un thread abierto en la
  ventana 1; un thread AMBIGUOUS se desambigua con información posterior;
  candidato único de baja confianza => PARTIAL; múltiples => AMBIGUOUS con
  candidates auditables.
- Checkpoint + rollback: reprocesar una ventana deshace solo sus efectos
  (`rollback_threads`), re-deriva sus threads y re-resuelve; sin duplicados.
- Tope `KNOWLEDGE_SEMANTIC_THREAD_MAX_OPEN` (512): los más viejos pasan a
  UNRESOLVED con history auditable (sin crecimiento infinito).
- Migración `146_semantic_threads.py`: `knowledge_semantic_threads`.
- Endpoint: `GET /semantic-ingestion/threads` (filtros status/type).
- `versions["thread_version"]` agregado: invalida manifiestos viejos una vez.

### 12.7 Verificación Fase 4

- `tests/test_semantic_threads.py` → 7 passed (referencia resuelta, continuación,
  símbolo, ambiguo, cap, rollback+checkpoint, store Postgres).
- Suite semántica completa (planner + manifest + state + threads) → 27 passed.
- Regresión ingesta/nutrición/eventos → 30 passed. Ruff limpio.

### 12.8 Fase 5 implementada (SemanticStitcher)

- `stitcher.py`: unidades semánticas merged (`StitchedUnit`) + relaciones
  tipadas (`StitchRelation`) con evidencia física (block_ids) y ventanas.
  Cadena respetada: PHYSICAL UNIT → SEMANTIC UNIT → RELATION → SEMANTIC UNIT
  → PHYSICAL EVIDENCE.
- Relaciones producidas: DEFINES, USES, HAS_ATTRIBUTE, HAS_CONDITION,
  HAS_EXCEPTION, REFERENCES, ALIAS_OF, SAME_AS, CONTRADICTS, SUPERSEDES,
  PART_OF (vocabulario §21).
- Detecciones: duplicados por texto normalizado (SAME_AS), contradicciones
  entre claims mismo sujeto/predicado con distinto objeto (CONTRADICTS),
  supersession temporal cuando la ventana posterior tiene marcador temporal
  (SUPERSEDES, `requires_review=true`).
- Cierre de threads: los OPEN se resuelven/desambiguan contra las unidades
  cosidas (resolved_by_unit = id de unidad, candidates auditables).
- Persistencia replace-por-documento: `knowledge_semantic_units` +
  `knowledge_semantic_relations` (migración `147_semantic_stitcher.py`).
- `versions["stitch_version"]` y `required_stages` ahora incluye `stitching`;
  `pipeline_complete`/`coverage_ratio` exigen el stitch.
- Endpoints: `GET /semantic-ingestion/units` y `GET /semantic-ingestion/relations`.

### 12.9 Verificación Fase 5

- `tests/test_semantic_stitcher.py` → 5 passed (relaciones core, contradicción +
  supersession, duplicado, cierre de thread, store Postgres idempotente).
- Suite semántica completa (planner + manifest + state + threads + stitcher)
  → 32 passed.
- Regresión ingesta/nutrición/eventos → 30 passed. Ruff limpio.

### 12.10 Fase 6 implementada (RegionalSemanticModel)

- `regional.py`: detección determinista de regiones lógicas por sección de
  primer nivel (capítulo), con "document" para preámbulo sin sección. El mapeo
  usa `parent_section_id` de cada bloque (no solo headings), robusto a ventanas
  que empiezan en un párrafo.
- `RegionalSemanticModel` consolida por región: definitions, rules, concepts,
  entities, exceptions, procedures, conditions, symbols, claims, tables,
  conflicts, relationships y unresolved_dependencies (threads OPEN de la
  región), con unit_key/block_ids/ventanas: la región NO sustituye evidencia.
- Fingerprint determinista; stats con coverage de ventanas procesadas.
- Persistencia replace-por-documento: `knowledge_regional_models`
  (migración `148_regional_models.py`).
- `versions["regional_version"]`; el manifiesto publica
  `details["regional_models"]` (count + ids). No es etapa requerida todavía
  (Fase 7 agregará `global` como requerida).
- Endpoint: `GET /semantic-ingestion/regions`.

### 12.11 Verificación Fase 6

- `tests/test_semantic_regional.py` → 4 passed (split por sección, dependencias
  sin resolver por región, fingerprint determinista, store Postgres idempotente).
- Suite semántica completa (planner + manifest + state + threads + stitcher +
  regional) → 36 passed.
- Regresión ingesta/nutrición/eventos → 30 passed. Ruff limpio.

### 12.12 Fase 7 implementada (GlobalSemanticModel + Map→Reduce→Reconcile)

- `global_model.py`: MAP (ventanas) → REDUCE (regiones) → RECONCILE (links
  globales) → GLOBAL. El modelo global NO es un resumen: glossary, concepts,
  entities, rules, symbols, exceptions, procedures, conditions, claims,
  tables, conflicts, relationships, dependencies, unresolved_items,
  temporal_model, reference_graph y semantic_clusters.
- RECONCILE: regiones por unidad/ventana, relaciones cross-region marcadas,
  clusters por componentes conexas sobre relaciones (union-find, cap 500),
  glossary deduplicado por término.
- Cada item conserva unit_key, regiones, ventanas y block_ids: el global
  tampoco sustituye evidencia.
- `required_stages` ahora incluye `global`: `pipeline_complete` y
  `coverage_ratio` exigen la síntesis global; `global_synthesis_complete`
  queda en el manifiesto.
- Persistencia: `knowledge_global_models` (migración `149_global_model.py`,
  upsert por documento). Endpoint: `GET /semantic-ingestion/global`.
- `versions["global_version"]`; detalles del manifiesto publican
  `details["global_model"]` (glossary/clusters/unresolved/cross-region).

### 12.13 Verificación Fase 7

- `tests/test_semantic_global_model.py` → 5 passed (estructura no-resumen,
  cross-region, unresolved, fingerprint determinista, store Postgres).
- Suite semántica completa (planner + manifest + state + threads + stitcher +
  regional + global) → 41 passed.
- Regresión ingesta/nutrición/eventos → 30 passed. Ruff limpio.

### 12.14 Fase 8 implementada (SemanticFabric)

- `fabric.py`: proyección determinista del modelo global a nodos del
  vocabulario §21 (Entity/Concept/Definition/Claim/Rule/Condition/Exception/
  Procedure/Metric/Attribute/Symbol/TableSemantic/TemporalAssertion/Reference/
  Evidence) y aristas del vocabulario §21.
- Aristas directas desde el stitcher (DEFINES/USES/HAS_ATTRIBUTE/HAS_CONDITION/
  HAS_EXCEPTION/REFERENCES/ALIAS_OF/SAME_AS/CONTRADICTS/SUPERSEDES/PART_OF) más
  derivadas honestas: DEPENDS_ON (de USES/condiciones/excepciones), CONSTRAINS,
  APPLIES_TO (de HAS_ATTRIBUTE), MENTIONS, SUPPORTS, VALID_FROM y DERIVED_FROM
  (nodo → Evidence, provenance exacta a bloque).
- Cross-source sin merges: candidatos de identidad con estado explícito
  (same_identity/likely_identity/alias_candidate/related_concept), evidencia de
  ambos lados, confianza, `temporal_compatible`/`scope_compatible`. El fabric
  NUNCA fusiona por similitud.
- Persistencia: `knowledge_fabric_nodes` + `knowledge_fabric_edges` +
  `knowledge_fabric_identities` (migración `150_semantic_fabric.py`;
  replace por documento e invalidación de identidades stale).
- Endpoints: `GET /semantic-ingestion/fabric/nodes|edges|identities`.
- `versions["fabric_version"]`; `details["fabric"]` publica counts por tipo.

### 12.15 Verificación Fase 8

- `tests/test_semantic_fabric.py` → 3 passed (vocabulario §21 + provenance,
  identidad cross-source sin merge, store Postgres replace/list/find/delete).
- Suite semántica completa (8 archivos) → 44 passed.
- Regresión ingesta/nutrición/eventos → 30 passed. Ruff limpio.

### 12.16 Fase 9 implementada (Nutrient Retrieval Units desde el Fabric)

- `FabricRetrievalContext` (`fabric.py`): indexa nodos/aristas del fabric por
  bloque y por nodo; `chunk_fields(block_ids, unit_key)` produce, por retrieval
  unit: `fabric_node_ids`, `fabric_node_types`, `fabric_labels`, ids por tipo
  (concept/entity/rule/definition/exception/condition/symbol/claim/procedure/
  table/temporal/reference), `fabric_dependency_ids` y `semantic_neighborhood`
  (1 hop, con relación/tipo/label/dirección, cap 12).
- Modos (`RAG_KNOWLEDGE_SEMANTIC_FABRIC_UNITS_MODE`):
  - `off`: sin campos.
  - `shadow` (default): solo payload del índice; los retrievers actuales los
    ignoran (medición sin alterar la respuesta).
  - `active`: además los labels del fabric entran a la pata SPARSE; el dense y
    la evidencia cruda nunca se tocan.
- Invalidación correcta: `FABRIC_REPRESENTATION_VERSION` entra al
  `RepresentationDescriptor`; la razón `fabric_changed` reindexa sin
  reprocesar la fuente (grafo de invalidación actualizado).
- El engine calcula el contexto tras `process_windows` y lo pasa a
  `_index_chunks` (texto y tabular). Sin fabric persistido no hay cambios.
- `details["fabric"]` ya publica counts; el enriquecimiento es aditivo.

### 12.17 Verificación Fase 9

- `tests/test_semantic_fabric_units.py` → 3 passed (mapeo ids/vecindad,
  off/shadow/active, fingerprint + `fabric_changed`).
- Engine e2e: payloads de Qdrant con `fabric_version`, `fabric_node_ids` y
  `fabric_labels`; suite semántica completa (9 archivos) → 47 passed.
- Regresión ingesta/nutrición/eventos → 30 passed. Ruff limpio.

### 12.18 Fase 10 implementada (Contextual embedding + late chunking real)

- `src/rag/embeddings/registry.py`: `EmbeddingCapability` — nunca se asume
  late chunking. Config (`RAG_EMBEDDING_LATE_CHUNKING_MODELS`) gana; builtin
  conservador (jina-v3/v4, voyage-context-3); default sin soporte.
- `src/rag/embeddings/representations.py`: `EmbeddingTextPlanner` con
  representaciones content (default, comportamiento actual), semantic
  (contextual embedding real: contenido + labels/definiciones del Fabric),
  concept y question (preparadas para benchmark, no activadas).
- `src/rag/embeddings/late_chunking.py`: late chunking SOLO si el provider
  expone `embed_late_chunking` (método nuevo en el port, default
  NotImplementedError) y la capacidad del modelo está declarada. Los chunks
  del mismo padre viajan juntos; un fallo cae a contextual embedding sin
  romper la ingesta. `LateChunkingBatch` audita textos/fingerprint.
- LiteLLM provider implementa `embed_late_chunking` con `late_chunking=True`
  (Jina-style); jamás se simula ni se renombra la técnica.
- `RAG_EMBEDDING_DENSE_REPRESENTATION` (content|semantic|concept|question) y
  `RAG_EMBEDDING_LATE_CHUNKING` (off|auto|on). La representación entra al
  `RepresentationDescriptor`; `embedding_representation_changed` invalida SOLO
  el embedding (reindex) vía grafo de invalidación.
- Engine: planner por documento; batches mixtos (late vectors + embeddings
  normales); vector faltante no se indexa y no marca fingerprint completo.

### 12.19 Verificación Fase 10

- `tests/test_embedding_representations.py` → 6 passed (capability, método
  real del provider, builders, batches + fallback, fingerprint).
- Engine e2e: representación `semantic` embebe "Semantic context:" y los
  payloads declaran `embedding_representation=semantic`.
- Suite semántica completa (10 archivos) → 54 passed.
- Regresión ingesta/nutrición/eventos → 30 passed. Ruff limpio.

### 12.20 Fase 11 implementada (Graph-aware retrieval + spreading activation)

- `src/rag/longcontext/graph_activation.py`: activación desde seeds
  (payload `fabric_node_ids`) por relaciones del fabric con límites duros
  (relación, confianza, hops, decay, nodos, aristas). `FabricActivationExpansion`
  consulta aristas y chunks vecinos vía store (`list_fabric_edges_for_nodes`,
  `get_chunks_by_fabric_nodes` en Qdrant con MatchAny + ACL/tenant), y cae a
  activación in-set si no hay fetch. `default_strategies` la incluye.
- El engine ahora deduplica expansiones por identidad de chunk
  (documento+chunk_id), no por documento: los vecinos del MISMO documento
  entran al contexto.

### 12.21 Fase 12 implementada (QueryRequirementGraph)

- `src/rag/longcontext/requirement_graph.py`: grafo pregunta→requisitos
  (Rule/Definition/Symbol/Entity/Exception/Condition/Evidence) desde
  requirements + payload fabric + `semantic_neighborhood`; estados
  FOUND/PARTIAL/MISSING/CONFLICTING; aristas DEPENDS_ON/HAS_EXCEPTION/
  HAS_CONDITION/USES/...; `dependency_coverage`, `missing` y fingerprint.
- `LongContextResult.requirement_graph` + `to_public_dict` para Ver flujo.

### 12.22 Fase 13 implementada (Dynamic ContextCompiler)

- `src/rag/longcontext/context_compiler.py`: secciones estructuradas
  (QUESTION, USER INPUTS, DEFINITIONS, RULES, CONDITIONS, EXCEPTIONS,
  RELATED EVIDENCE, CONFLICTS, UNRESOLVED REQUIREMENTS, CITATION MAP) con
  citation map estable; recorte por prioridad (reglas/excepciones antes que
  evidencia genérica) contando lo omitido; `render_compiled_context_block`.
- `LongContextResult.compiled_context`; `build_generation_package` acepta y
  expone `compiled_context` (aditivo, shadow-safe).

### 12.23 Fase 14 implementada (Retrieval Acceptance V2)

- `src/knowledge/semantic/acceptance_v2.py`: probes V2 desde el fabric
  (nodos por tipo + dependencias) y métricas definition/rule/exception/symbol/
  dependency recall, evidence_recall, semantic_coverage, orphans.
- Nuevos `query_type` en el contrato de probes y evento
  `RETRIEVAL_ACCEPTANCE_V2`; el engine evalúa los probes V2 post-index y
  persiste métricas en la evaluación (`update_knowledge_metrics`).

### 12.24 Fase 15 implementada (Invalidación incremental por etapa)

- `ArtifactKind` extendido: SEMANTIC_WINDOWS→STITCH→REGIONAL→GLOBAL→FABRIC→
  RETRIEVAL_REPRESENTATION→EMBEDDING→RETRIEVAL_ACCEPTANCE, con acciones
  `reprocess_windows/restitch/recompute_regions/resynthesize/reproject` y
  razones `*_changed`. Cambiar una etapa no reprocesa la fuente.
- `manifest.details["stage_fingerprints"]`: windows/stitch/regional/global/
  fabric (deterministas) para invalidación selectiva auditable.

### 12.25 Fase 16 implementada (Benchmark BASELINE vs NUEVO)

- `src/rag/evaluation/semantic_benchmark.py`: casos con expectativas de
  evidencia/dependencias/citas/abstention; métricas answer correctness,
  evidence recall, dependency recall, citation precision, abstention
  precision, tokens, latencia y costo; deltas por caso, `promotion_ready`
  (mejora de conocimiento sin degradar >50% tokens/latencia) y reporte
  markdown/JSON.

### 12.26 Fase 17 implementada (Rollout shadow/canary + métricas)

- Modo `canary` con `RAG_KNOWLEDGE_SEMANTIC_INGESTION_CANARY_PERCENTAGE`
  (selección determinista por org+source+external_id); `should_process` gatea
  el pipeline en el engine. shadow/active procesan siempre; active reanuda.
- Métricas Prometheus: `knowledge_semantic_windows_total`,
  `knowledge_semantic_threads_total`, `knowledge_semantic_fabric_nodes_total`
  (best-effort).

### 12.27 Verificación final (fases 1-17)

- Suite semántica (10 archivos): 54 passed.
- Fases 11-17 (7 archivos nuevos): 29 passed.
- Long-context (8 archivos): 96 passed.
- Ingesta/nutrición/acceptance/compiler/eventos: 62+44 passed.
- Ruff limpio en todo lo tocado. Migraciones 143-150 aplicadas localmente.

### 12.28 Definition of Done (§75) — estado

1. 100% source coverage: manifiesto + coverage ponderado por etapas
   requeridas (parsing/indexing/semantic_windows/stitching/global). ✅
2. Comprensión reanudable: checkpoints por record y por ventana; rollback de
   threads al reprocesar. ✅
3. Concepto cruza chunk boundaries: unidades semánticas + stitcher + fixtures. ✅
4. Temprano y tardío conectan: threads + stitcher + global. ✅
5. Info posterior resuelve unknowns: resolución bidireccional de referencias
   (Fase 3/4) + cierre por unidades (Fase 5). ✅
6. Dependencias persisten: relations + fabric + requirement graph. ✅
7. Nutrient chunks heredan significado: payload fabric + representación
   semántica/late chunking opcional. ✅
8. Retrieval navega relaciones: spreading activation + Qdrant MatchAny. ✅
9. Contexto crece hasta cubrir requirements: long-context engine + compiler. ✅
10. Excepciones críticas no se pierden: secciones/prioridad de recorte +
    HAS_EXCEPTION/DEPENDS_ON. ✅
11. Provenance exacta: evidence ledger + block_ids en todas las capas. ✅
12. Fuentes enormes sin una sola llamada masiva: ventanas + map/reduce/
    reconcile. ✅
13. Reproceso selectivo: fingerprints por etapa + grafo de invalidación. ✅
14. Benchmark demuestra mejora: módulo listo; promoción requiere correrlo con
    corpus real (`promotion_ready`). ⏳ operacional.
