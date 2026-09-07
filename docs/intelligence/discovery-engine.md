# Zent Discovery Engine (FASE 24)

> Cuando una organización conecta una fuente autorizada, Zent NO espera
> pasivamente preguntas: explora de forma segura la metadata y construye
> progresivamente una representación semántica del negocio.
> NO entrena el LLM con los datos y NUNCA trata una inferencia de IA como verdad.

## 1. Pipeline

```
Source
  ↓ Discovery Adapter (ConnectorPlugin)
  ↓ Metadata Scanner (read-only, incremental, presupuestado)
  ↓ Profiler (null_ratio/cardinalidad/muestras seguras)
  ↓ Relationship Detector (FKs físicas + candidatos inferidos)
  ↓ Semantic Inference (OBSERVED / INFERRED, nunca auto-aprobado)
  ↓ Catalog (físico + semántico) + Review Queue
```

Reutiliza la Connector Platform existente: `ConnectorPlugin.discover()` /
`deep_discover()` con `POST /api/v1/connectors/{id}/discover` intacto.

## 2. Prioridades SQL

| Motor | discover | deep_discover (comentarios/FKs/stats) |
|---|---|---|
| PostgreSQL | completo (índices, `reltuples`, `pg_stats`) | completo |
| MySQL | tablas/columnas | comentarios + FKs |
| SQL Server | tablas/columnas | FKs |
| Oracle | tablas/columnas (all_tables/all_tab_columns) | comentarios + FKs |
| DB2 | tablas/columnas (syscat) | comentarios + FKs |

Los perfiles de Postgres provienen de `pg_stats` (OBSERVED, cero acceso a
datos). El muestreo de valores distintos (`sample_distinct_values`) es
acotado (`LIMIT`), solo para columnas NO sensibles y con presupuesto.

## 3. Presupuestos (modo conservador)

`RAG_CATALOG_MAX_TABLES_PER_SCAN=200` · `MAX_COLUMNS_PER_TABLE=200` ·
`MAX_SAMPLES=50` · `MAX_QUERY_SECONDS=10` · `MAX_SCAN_COST=500` ·
`MAX_PARALLELISM=3`. `ScanBudget` corta el scan en PARTIAL cuando se agota
el presupuesto; `cursor_snapshot` permite resumir.

## 4. Seguridad del profiling

- **Read-only**: solo catálogos de sistema + `SELECT DISTINCT ... LIMIT n`.
- **PII nunca se muestrea**: `core/domain/pii.py` (email, phone, national_id,
  salary, secret, health, financial...) → `sample_disabled=true`.
- **Incremental**: `content_signature` por scan; drift detectado
  (table_added/removed, column_added/removed, type_changed).
- **Cancelable/resumable**: jobs durables con cancelación existente.
- **Rate limited y tenant isolated**: jobs org-scoped; Redis rate limits.

## 5. Jobs

`job_type=catalog_discovery:scan` sobre `ingestion_jobs` (estados existentes
+ `partial` añadido). El worker despacha por prefijo al
`CatalogDiscoveryEngine`. Fases en `catalog_sources.phase`:

```
QUEUED → SCANNING → PROFILING → INFERRING → WAITING_REVIEW
       → COMPLETED | PARTIAL | FAILED | CANCELLED
```

Rescan: `POST /api/v1/catalog/discovery` (initial), `POST /catalog/sources/{id}/rescan`
(manual), o programado (`scan_interval_hours` + loop en `main.py`).

## 6. Estados del catálogo semántico

OBSERVED (verificable en la fuente) · INFERRED (heurística/LLM) · APPROVED
(validación humana) · REJECTED · DEPRECATED. Nunca se promueve
INFERRED → APPROVED automáticamente: toda aprobación pasa por la
**Review Queue** (`catalog_suggestions`) y se audita.

## 7. Revisión humana (Review Queue)

Sugerencias: `entity_identification`, `table_identification`,
`relationship_candidate`, `enum_definition`, `field_mapping`,
`metric_proposal`, `glossary_term`. Acciones: `APPROVE` / `REJECT` /
`EDIT_AND_APPROVE` / `DEFER` — cada acción materializa el conocimiento con
`provenance=APPROVED` + aristas de lineage + auditoría.

## 8. Observabilidad

`rag_discovery_jobs_total` · `rag_discovery_duration_seconds` ·
`rag_catalog_objects_total` · `rag_inferred_relationships_total` ·
`rag_approved_relationships_total` · `rag_unknown_codes_total` ·
`rag_semantic_suggestions_total` · `rag_semantic_suggestions_approved_total` ·
`rag_context_readiness` (Gauge).

## 9. API

| Método | Path | Permiso |
|---|---|---|
| POST | `/api/v1/catalog/discovery` | connectors:read + catalog:write |
| GET | `/api/v1/catalog/sources` · `/{id}` | catalog:read |
| GET | `/api/v1/catalog/sources/{id}/readiness` | catalog:read |
| GET | `/api/v1/catalog/sources/{id}/scans` | catalog:read |
| POST | `/api/v1/catalog/sources/{id}/rescan` | catalog:write |
| GET | `/api/v1/catalog/sources/{id}/tables` · `/tables/{id}` | catalog:read |
| GET/POST | `/api/v1/catalog/entities` (+fields) | catalog:read/write |
| GET/POST | `/api/v1/catalog/glossary` + `/{concept}/approve` | catalog:read/write |
| GET/POST | `/api/v1/catalog/metrics` + `/{id}/approve` | catalog:read/write |
| GET | `/api/v1/catalog/relationships` + confirm/reject | catalog:read/write |
| GET/POST | `/api/v1/catalog/authority` | catalog:read/write |
| GET | `/api/v1/catalog/suggestions` + approve/reject/defer/edit-approve | catalog:read/write |
| GET | `/api/v1/catalog/enums` · `/lineage` | catalog:read |

Todos org-scoped (404 cross-tenant). Permisos nuevos: `catalog:read` (051),
`catalog:write` (052) — grants owner/admin/member (+ viewer read).

## 10. Seguridad y ACL

`Connector ACL → Discovery ACL → Catalog ACL → Retrieval ACL → Answer ACL`.
Discovery solo sobre connectors que el tenant puede leer. Identidad solo del
Bearer; sin filtrado cross-tenant en ningún endpoint.