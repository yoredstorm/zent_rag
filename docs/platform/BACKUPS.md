# Backups

## Postgres

- Cadencia sugerida: `pg_dump` (custom format) diario + WAL/PITR del provider managed si existe.
- Incluye el schema de billing, usage_events, eval_runs, api_keys (hashes, no plaintext).
- Retención: 7 diarios + 4 semanales (ajustar al contrato).

```bash
pg_dump -Fc -h "$RAG_POSTGRES_HOST" -U "$RAG_POSTGRES_USER" "$RAG_POSTGRES_DB" > zent-$(date -u +%Y%m%d).dump
```

## Qdrant

- Snapshot por colección (`rag_documents` y las que uses) **después** de un dump PG consistente, o anota el timestamp.
- Qdrant Cloud: snapshots nativos. Self-host: API `/snapshots`.

## Redis

Tratar como **caché**. AOF opcional. Se puede perder: rate-limit counters, idempotency corta, usage storage cache. No es source of truth.

## Object storage

Versionado + lifecycle en el bucket (archivos de ingestión). Un dump de PG sin los blobs deja sources `file` rotos.

## RPO / RTO (best effort)

| | RPO | RTO |
|---|---|---|
| Postgres | 24h (dump) o minutos (PITR managed) | 2–4h restore + migrate |
| Qdrant | alineado al último snapshot (puede desfasar vs PG) | 2–4h |
| Redis | aceptable pérdida total | minutos (vacío) |
| Blobs | versioning del bucket | depende del provider |
