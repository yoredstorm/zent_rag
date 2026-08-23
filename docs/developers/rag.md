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
