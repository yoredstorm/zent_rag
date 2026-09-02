# RAG

Chat es el atajo. El recurso RAG expone la consulta completa:

```python
client.rag.query("último producto vendido", top_k=50, retrieval_strategy="hybrid")
```

```ts
await client.rag.query("último producto vendido", { top_k: 50 });
```

Respuesta típica: `answer`, `sources[]` (`document_id`, `content`, `score`, `metadata`), `usage`, `method` (`rag` | `sql`), `latency_ms`.

Filtros: `metadata_filters`, `rerank_top_k`, `score_threshold`, `language`.

Escribir en la base de conocimiento (fuentes, KBs, ingestión) requiere `rag:write`.

## Knowledge Pipeline (PROMPT 03)

### Ciclo de vida de fuentes

`kb_sources.status`: `created → connected → discovering → profiled → ready → ingesting → indexed | error`.

### Data Profiling

- `POST /api/v1/sources/{id}/profile` — perfiliza fuentes SQL: tipos, PK/FK,
  null rates, cardinalidad y candidatos PII/sensibles por heurística de nombre
  (`src/connectors/sql/profiling.py`). Persiste en `source_profiles` y
  transiciona la fuente `discovering → profiled`.
- `GET /api/v1/sources/{id}/profile` — último perfil almacenado.
- Heurísticas PII: email, phone, national_id, secret, payment_card, address,
  birth_date, health; sensibles: cost/revenue/pii_related.

### Index versions

Cada sync completado de una KB registra una fila en `index_versions`
(embedding_model, chunk_size/overlap, vector_count, source_version secuencial).
Ver: `GET /api/v1/knowledge-bases/{id}/index-versions`.

### Training runs

`POST /api/v1/training/runs` crea un run y encola un job durable por fuente de
la KB (`training_run_id` enlazado). El estado se agrega desde los jobs:
`pending → running → completed | failed | partial`, con
`preparation → chunking → embedding → indexing → validation` y progreso en vivo
(`GET /training/runs/{id}` + SSE `GET /training/runs/{id}/stream`).
