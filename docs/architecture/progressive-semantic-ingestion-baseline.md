# Baseline — Progressive Global Semantic Ingestion (Fase 0 de la implementación)

> Registro de línea base ANTES de la implementación incremental fases 0-33.
> No es un documento de arquitectura: es la foto del runtime para comparar.

## Git

- Repo: `https://github.com/yoredstorm/zent_rag`
- Rama: `master`
- SHA base: `56926ff` (CI verde; incluye fases 1-17 previas + fixes de env/catálogo)
- Migración head: `150`

## Tests baseline (suites ejecutadas y verdes en el SHA base)

| Suite | Archivos | Tests |
|---|---|---|
| Semántica (planner, manifest, state, threads, stitcher, regional, global, fabric, fabric_units, embeddings) | 10 | 54 |
| Fases 11-17 (graph activation, requirement graph, context compiler, acceptance v2, invalidation, benchmark, rollout) | 7 | 29 |
| Long-context (engine, structural, orchestrator, exact, adaptive, budget, roles, critical question) | 8 | 96 |
| Ingesta/nutrición/acceptance/compiler/eventos | 6 | 106 |

## Config activa (defaults)

| Clave | Default | Efecto |
|---|---|---|
| `RAG_KNOWLEDGE_SEMANTIC_INGESTION_MODE` | `off` | pipeline semántico apagado |
| `RAG_KNOWLEDGE_SEMANTIC_INGESTION_PROFILE` | `balanced` | perfil de ventana |
| `RAG_KNOWLEDGE_SEMANTIC_FABRIC_UNITS_MODE` | `shadow` | ids/vecindad al payload |
| `RAG_EMBEDDING_DENSE_REPRESENTATION` | `content` | dense = representación de contenido |
| `RAG_EMBEDDING_LATE_CHUNKING` | `auto` | late chunking solo con capacidad real |
| `RAG_KNOWLEDGE_RETRIEVAL_ACCEPTANCE_MODE` | `warn` | acceptance post-index |
| `RAG_LONG_CONTEXT_MODE` | `off` | expansión adaptativa apagada |

## Providers

| Rol | Config | Default |
|---|---|---|
| LLM | `LITELLM_DEFAULT_MODEL` (LiteLLM `acompletion`) | `gpt-4o-mini` |
| Embeddings | `EMBEDDING_MODEL` (LiteLLM `aembedding`) | `openai/baai/bge-m3` |
| Vector dimension | `VECTOR_DIMENSION` | 1024 |
| Reranker | `RAG_RERANKER` | `""` (passthrough) |

## Ingestion path (runtime)

```
API (/api/v1/sources*, ingestion, knowledge-bases)
  -> IngestionJob (Postgres durable) -> worker_entry.py
  -> KnowledgeIngestionEngine.execute_job            src/knowledge/engine/service.py
  -> connector.iter_records (file/pdf/docx/xlsx/csv/web/s3/gdrive/api/sql)
  -> _parse_record -> StructuredDocument             src/knowledge/structure/
  -> _apply_document_understanding                   src/knowledge/understanding/
     (layout, OCR opcional, reflow, tablas, Semantic Reconstruction)
  -> semantic.parsed (plan de ventanas, si mode != off)
  -> _apply_enrichment                               src/knowledge/enrichment/
  -> fingerprint de representación                   src/knowledge/representation/
  -> structured_repo.upsert_document + registry      Postgres
  -> _compiler_view (candidatos)                     src/knowledge/compiler/
  -> semantic.process_windows (ventana->resultado->estado->threads->
     stitch->regional->global->fabric, si mode != off)
  -> _index_chunks (chunks, representaciones, embeddings, Qdrant)
  -> summarize (shadow), acceptance, nutrition, compile canónico, PASS 2
```

## Retrieval path (runtime)

```
POST /api/v1/rag/query -> RAGOrchestrator.execute     src/agents/runtime/orchestrator.py
  -> query views + source routing + embedding
  -> HybridRetriever (dense+sparse+RRF) + ExactRetriever + rerank
  -> AdaptiveLongContextEngine.run (si mode != off)   src/rag/longcontext/engine.py
     requirements -> coverage -> expansions (incl. fabric_activation)
     -> ContextPackager -> generation package
  -> LLM (LiteLLM) -> citas -> flow/trace
```

## Diagrama runtime (runtime real)

```
SOURCE ─► PARSE ─► UNDERSTAND ─► [SEMANTIC WINDOWS] ─► ENRICH ─► FINGERPRINT
                                        │
                                        ▼
                       WINDOW RESULT ─► STATE ─► THREADS ─► STITCH
                                        │                    │
                                        ▼                    ▼
                                    REGIONAL ─► GLOBAL ─► FABRIC
                                        │                    │
                                        ▼                    ▼
                                    CHUNKS/REPRESENTACIONES ─► QDRANT
                                        │
                                        ▼
                              COMPILER CANÓNICO + ACCEPTANCE + NUTRITION
                                        │
QUERY ─► SEED RETRIEVAL ─► FABRIC ACTIVATION ─► COVERAGE/GAIN ─► CONTEXT
```

## Hard chunk boundaries identificados (SHA base)

| Frontera | Valor | Ubicación |
|---|---|---|
| Semantic unit budget | 1200 chars (`SEMANTIC_UNIT_MAX_CHARS`) | `understanding/units.py:540` |
| Chunker fallback | 600 chars + 50 overlap (`ChunkingConfig`) | `structure/chunker.py:32` |
| Embed safety truncation | 6000 chars (`RAG_EMBED_MAX_CHARS`) | `engine/service.py:344` |
| Tabular row groups | `KNOWLEDGE_TABULAR_ROW_GROUP_SIZE`/`_OVERLAP` | `knowledge/tabular/` |
| Ventanas semánticas | dinámicas (capability + perfil + reservas) | `semantic/planner.py` |

## Objetivo de este turno

Cerrar las fases 0-33 de la lista de implementación con tests por fase,
sin romper las suites baseline y sin introducir anti-patrones (overlap fijo,
top_k ciego, una llamada LLM por chunk, estado/grafo sin límites).
