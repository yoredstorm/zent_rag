# Knowledge Nutrition Pipeline

Estado: implementado (Fases 1-9 del brief Knowledge Nutrition).
Complementa `knowledge-os.md`, `semantic-reconstruction-layer.md`,
`knowledge-quality-gate.md` y `tabular-ingestion.md`. No reemplaza ninguno.

## Principio

La ingesta deja de significar "el archivo está vectorizado" y pasa a
significar: **la información fue comprendida, reconstruida, validada,
enriquecida, conectada, materializada para retrieval, probada y evaluada.**

Pipeline productivo (único camino, sin V1/V2 paralelos):

```
RAW SOURCE
  -> SOURCE PROFILING            (source_profile del understanding)
  -> PHYSICAL PARSING            (src/knowledge/structure)
  -> SEMANTIC RECONSTRUCTION     (src/knowledge/reconstruction, obligatoria)
  -> QUALITY GATE                (src/knowledge/quality + reconstruction)
  -> SEMANTIC ENRICHMENT         (src/knowledge/enrichment)          [NUEVO]
  -> REPRESENTATION FINGERPRINT  (src/knowledge/representation)      [NUEVO]
  -> KNOWLEDGE COMPILER          (src/knowledge/compiler; vista pura ANTES
                                  de indexar, persistencia canónica después)
  -> RETRIEVAL MATERIALIZATION   (chunks + parent representation)    [NUEVO]
  -> INDEX                       (Qdrant: dense + sparse, ACL pre-LLM)
  -> RETRIEVAL ACCEPTANCE        (src/knowledge/acceptance)          [NUEVO]
  -> PUBLISH / NUTRITION         (src/knowledge/nutrition)           [NUEVO]
  -> USER USAGE -> TRACE/FEEDBACK -> NUTRITION ACTION                [NUEVO]
```

## Evidence vs Enrichment

Nada derivado es evidencia. Todo item de enrichment lleva:

- `derived=true`, `canonical=false`
- `source_unit_ids` (block/section/unit reales del documento)
- `derivation_method` (`deterministic|structural|statistical|domain_heuristic|model`)
- `confidence`, `policy_version`

El quality gate de enrichment elimina cualquier item sin provenance real o
que intente declararse canónico. El texto fuente original nunca se modifica.

## Representation Fingerprint

`src/knowledge/representation/fingerprint.py`.

`SHA256(content_hash + parser_version + structure_schema + reconstruction +
understanding + enrichment (+ firma de profile packs) + compiler_representation
+ chunking + contextualization + sparse_encoding + embedding_provider/model/
dimensions + parent_representation_version)`.

Matriz de decisión:

| contenido | representación | decisión |
|---|---|---|
| igual | igual | `SKIP` (no re-embed) |
| igual | distinta | `REINDEX` (re-materializa) |
| distinto | cualquiera | `UPDATE` (flujo normal) |
| sin fingerprint previo | cualquiera | `CREATE` (migración natural) |

El fingerprint usado por el último index exitoso se persiste en
`structured_documents.metadata.indexed_representation_fingerprint` (merge
JSONB) y en el payload de cada punto (`representation_fingerprint`).

## Parent Semantic Representation

Un parent de sección ya no se embebe con `parent_text[:N]`. Se compone con
secciones etiquetadas (las vacías se omiten):

```
Title: ... Section: ... Summary: ... Concepts: ... Aliases: ... Identifiers:
... Entities: ... Rules: ... Key facts: ... Temporal scope: ... Questions: ...
Children: ... Terms: ...
```

El contenido real del parent queda intacto en el payload (evidencia); la
representación es `derived`, versionada (`parent-semantic-1`), con provenance
hacia los children y flag `preliminary=true` cuando el compiler todavía no
corrió (se actualiza después vía PASS 2). Fallback determinista sin enrichment.

## Retrieval Representation Builder

`src/knowledge/representation/retrieval.py`. Cada child tiene DOS
representaciones:

- **content representation**: sección + texto real; es lo que se embebe (dense).
- **retrieval representation**: sección + conceptos + aliases + identificadores
  + entidades + descripción corta + preguntas; alimenta el sparse (BM25) y la
  metadata acotada. El texto de evidencia nunca se contamina.

`VectorStore.upsert_batch(..., sparse_texts=...)` permite que el sparse use la
representación de retrieval sin cambiar el contenido. Los stores que no lo
soportan siguen funcionando (default None).

## PASS 1 / PASS 2 (compiler-aware)

1. **PASS 1**: la ingesta calcula la vista pura del compiler y materializa el
   índice con candidatos (entidades/reglas) + representaciones.
2. **PASS 2**: cuando el compilador persiste, `update_document_payload` lleva
   los ids canónicos (`canonical_entity_ids`, `canonical_rule_ids`) al payload
   del documento **sin re-embedding** (Qdrant `set_payload` con filtro doble
   organización + documento).

## Invalidation Graph

`src/knowledge/representation/dependencies.py`: grafo explícito
SOURCE a PARSED a RECONSTRUCTION a ENRICHMENT a RETRIEVAL_REPRESENTATION a
EMBEDDING a RETRIEVAL_ACCEPTANCE; COMPILATION solo refresca payload.
`invalidation_plan(kind)` devuelve stale transitivo + acciones
(reparse/reconstruct/reenrich/recompile/reindex/refresh_payload/reevaluate).
`change_reason(previous_descriptor, current_descriptor)` traduce el fingerprint
a razón específica (`embedding_model_changed`, `enrichment_version_changed`,
`chunking_changed`, `missing_index`, `manual`, ...) y `plan_for_reason` la
mapea al plan. El descriptor indexado se persiste en
`indexed_representation_descriptor`.

## Acceptance states

`PASS | DEGRADED | FAIL | UNKNOWN`. DEGRADED (evidencia parcial) no tumba el
job; `quarantine` solo actúa con FAIL y `RETRIEVAL_ACCEPTANCE_FAILED` se emite
solo en FAIL. El estado queda en `metrics.state` de la evaluación.

## Demand model

`build_demand_model(evaluations, actions, ...)` agrega evaluaciones
persistidas + acciones de nutrition: `questions_total`, `success_rate`,
`retrieval_failure_rate`, `negative_feedback_rate`, `coverage`, intents por
query_type y conceptos. Alimenta `demand_coverage` del score y se persiste en
`knowledge_nutrition_state.demand_profile`. No conserva texto completo.

## CLI con estimaciones

```
python -m src.scripts.knowledge_reprocess --org <uuid> --invalidate-representation --dry-run
# imprime: documentos afectados, plan de invalidación y estimación
#          (vectors_affected, estimated_embeddings, estimated_tokens,
#           estimated_cost_usd si hay pricing)
python -m src.scripts.knowledge_reprocess --org <uuid> --reevaluate
```

## Enrichment determinista-primero

Orden: estructural -> determinista -> estadístico -> heurística de dominio
(profile packs) -> modelo opcional validado por el mismo guard. Sin provider
LLM configurado, todo se resuelve sin LLM. Topes configurables:
`RAG_KNOWLEDGE_ENRICHMENT_MAX_*`.

Produce: conceptos, aliases de retrieval, acrónimos, identificadores verbatim,
términos de dominio/unidades, qualifiers temporales, referencias, reglas
posibles y preguntas sintéticas. Las preguntas **no** son evidencia, **no** son
facts y **no** se compilan.

## Retrieval Acceptance Gate

Post-index, por documento: probes deterministas con evidencia esperada
(documento/sección/unidad) -> retrieval real con la misma ACL -> métricas
(Recall@1/3/5, MRR, documento/sección/evidencia, lexical/semantic) ->
`accepted` según `RAG_KNOWLEDGE_RETRIEVAL_ACCEPTANCE_MIN_RECALL`.

Modos: `off | observe | warn (default) | quarantine`. No bloquea la ingesta.
Los probes y evaluaciones se persisten (`knowledge_retrieval_probes`,
`knowledge_retrieval_evaluations`) y se pueden re-ejecutar sin re-ingerir:

```
python -m src.scripts.knowledge_reprocess --org <uuid> --reevaluate [--document <uuid>]
```

## Knowledge Nutrition Score

`src/knowledge/nutrition/score.py`. Dimensiones persistidas; las no medidas
quedan `None` (nunca 0). Fórmula versionada `nutrition-score-1`:

```
nutrition_score = Σ(w_i * d_i) / Σ(w_i)   para dimensiones medidas
w: structure .12, reconstruction .14, evidence .16, semantic .12,
   entity_linkage .08, relationship .06, temporal .06, freshness .06,
   retrievability .14, demand_coverage .06
```

## Feedback -> Nutrition

`src/knowledge/nutrition/service.py`. Clasifica fallos con señales reales
(retrieval, scores, evidencia usada, answer gate, feedback, ACL, calidad de
parseo/reconstrucción) en tipos como `RETRIEVAL_MISS`, `BAD_RANK`,
`MISSING_KNOWLEDGE`, `STALE_KNOWLEDGE`, `ACL_FILTERED`, `TEMPORAL_MISMATCH`.
Cada tipo mapea a una acción; **ninguna acción es destructiva** y el feedback
débil solo se registra (`observed`). Reutiliza el feedback/tracing existente.

## Invalidación incremental

| cambia | acción |
|---|---|
| parser | reparse downstream |
| reconstrucción | reconstruct + downstream |
| enrichment (versión o packs) | re-enrich + representación + reindex |
| compiler | recompile (+ metadata de índice) |
| modelo/dimensiones de embeddings | reindex |
| retriever | solo re-ejecutar acceptance |

CLI:

```
python -m src.scripts.knowledge_reprocess --org <uuid> --invalidate-representation [--source <uuid>]
python -m src.scripts.knowledge_reprocess --org <uuid> --reevaluate
```

## API

`src/api/routes/knowledge_nutrition.py`:

- `GET  /api/v1/knowledge/nutrition/score?document_id=`
- `GET  /api/v1/knowledge/nutrition/actions`
- `GET  /api/v1/knowledge/retrieval-acceptance`
- `GET  /api/v1/knowledge/retrieval-probes?document_id=`
- `POST /api/v1/knowledge/retrieval-acceptance/reevaluate`
- `POST /api/v1/knowledge/nutrition/feedback`

## Eventos

`SEMANTIC_ENRICHED`, `RETRIEVAL_ACCEPTANCE_FAILED`,
`RETRIEVAL_REPRESENTATION_UPDATED`, `KNOWLEDGE_REINDEXED`,
`KNOWLEDGE_NUTRITION_REQUIRED` (Knowledge Events existente, best-effort).

## Migración

`139_knowledge_nutrition.py`: `knowledge_retrieval_probes`,
`knowledge_retrieval_evaluations`, `knowledge_nutrition_state`,
`knowledge_nutrition_actions`. Aditiva; los documentos existentes sin
fingerprint se re-materializan de forma natural en su próximo sync.
`141_knowledge_nutrition_indexes.py`: índices de consulta para acciones y
probes (crecen con la operación normal).

## Runbook operativo

**¿Por qué se re-indexó este documento?**
`structured_documents.metadata.last_index_reason` + `indexed_representation_descriptor`
(diff de componentes), métrica `knowledge_reindex_reason_total` y log
`Knowledge invalidation plan`.

**¿Por qué falló retrieval acceptance?**
`knowledge_retrieval_evaluations.metrics.state` (PASS/DEGRADED/FAIL),
`failed_probes` con query_type y rank, evento `retrieval_acceptance_failed`.
Re-ejecutable: `POST /api/v1/knowledge/retrieval-acceptance/reevaluate` o
`python -m src.scripts.knowledge_reprocess --org <uuid> --reevaluate`.

**¿Cuánto costó enriquecer/embeber esta fuente?**
`knowledge_usage`/`usage_events` por `source_id` (eventos
`knowledge_ingest_embedding`, `knowledge_ingest_acceptance`). Enrichment es
determinista (sin LLM); reconstruction/summary LLM tienen sus eventos propios.
Retries no doble-cuentan: `request_id` determinista por job/fuente/kind/index.

**¿Qué versión produjo este vector?**
Payload del punto: `representation_fingerprint`, `representation_decision`,
`content_representation_version`, `retrieval_representation_version`,
`parent_representation_version`, `enrichment_version`.

**¿Qué evidencia generó este alias?**
`structured_documents.metadata.enrichment` (payload acotado): cada item lleva
`source_unit_ids`, `confidence`, `derivation_method`, `policy_version`.

**¿Qué feedback originó esta nutrition action?**
`knowledge_nutrition_actions.evidence.classification.signals` (query truncada,
retrieval, scores, gates, feedback) + `policy_version`.

**Retención:** probes y evaluaciones crecen por diseño. Política recomendada:
conservar evaluaciones N días (p. ej. 180) o las últimas M por documento;
probes se conservan mientras el documento exista (son re-ejecutables).

**ACL:** el acceptance corre en contexto de sistema (`role=admin`) scoped por
organización: mide "¿el sistema puede encontrar la evidencia?". El retrieval de
usuario aplica ACL pre-LLM en Qdrant; los probes nunca cruzan tenant.

## Auditoría adversarial (hallazgos corregidos)

- **P0/P1**: el fingerprint se persistía aunque todos los embeddings fallaran,
  ocultando el fallo para siempre. Ahora: cero puntos a excepción explícita;
  índice parcial no persiste fingerprint (reintenta el próximo sync).
- **P1**: PASS 2 escribía ids canónicos en claves top-level invisibles para
  retrieval; ahora hace scroll scoped + merge DENTRO de `metadata` (batch).
- **P1**: `usage_events.event_type` varchar(30) truncaba
  `knowledge_ingest_acceptance_embedding`; el costo de acceptance se perdía en
  silencio. Kind corto `acceptance` + `embedding_tokens` correcto.
- **P1**: conceptos tabulares podían quedar sin provenance; ahora el guard de
  provenance es universal (deterministas + modelo) y las unidades tabulares
  (workbook/sheet/table/column) son provenance válida.
- **P1**: `CAT 31` se expandía a `Category 31` sin evidencia; ahora la
  abreviatura conserva su superficie (`Cat 31`) y solo la forma completa
  canonaliza a `Category`. Acrónimos de ruido (`Y CONT` a `YC`) bloqueados.
- **P1**: prompt injection en reconstruction/summary: política explícita de
  fuente no confiable + tests adversariales (contenido inventado no se mergea).
- **P1**: classifier no distinguía rank malo (rank 15) ni ausencia real de
  fuente; nuevas señales `evidence_rank` y `no_source_match`.
- **P1**: fallo total de registros se declaraba COMPLETED; ahora el job falla y
  reintenta (dead-letter si persiste).
- **P2**: dimensión temporal no aplicable pasa a `None` (no 0); fan-out de
  embeddings de acceptance acotado (batches + presupuesto de retries);
  throughput de embeddings observable; índices de consulta 141.
