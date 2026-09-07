# Zent Semantic Catalog (FASE 24)

> Representación semántica del negocio construida progresivamente sobre el
> catálogo físico. Toda pieza tiene provenance (OBSERVED / INFERRED /
> APPROVED) y lineage: ¿de dónde salió esto?

## 1. Modelo

```
Physical Catalog          Semantic Catalog
├─ Source                 ├─ Business Entity (Customer)
├─ Database/Schema        ├─ Business Field (customer_id → CUST_ID)
├─ Table (+comment)       ├─ Business Concept / Glossary Term
├─ Column (+comment)      ├─ Business Metric (gobernada)
├─ Index / Key            ├─ Dimension
├─ Relationship           ├─ Relationship (confirmada/inferida)
└─ Profile                ├─ Source of Truth (catalog_authority)
                          └─ Lineage (Enterprise Context Graph)
```

Cada objeto físico mantiene lineage hacia su fuente; cada objeto semántico
registra `provenance`, `confidence`, `evidence` y `approved_by`.

## 2. Business Glossary (`business_definitions` + FASE 24)

Términos con: `name`, `description`, `synonyms`, `owner`, `status`, `version`
(bump automático), `effective_from/to`, `created_by`, `approved_by`,
`provenance`. Los términos aprobados alimentan directamente al Answerability
Gate (`business_definition_status`) — una sola fuente de verdad.

## 3. Business Metrics (`catalog_metrics`)

`metric_key`, `name`, `definition`, `formula` (nunca se ejecuta sin
validación), `semantic_dependencies`, `physical_mappings`, `filters`,
`time_semantics`, `currency_semantics`, `owner`, `status`, `version`.

Al aprobar una métrica:
1. Se sincroniza (idempotente) a `business_definitions`
   (`data_type='metric'`, `expression=formula`) → visible para Answerability.
2. Se registran aristas de lineage: `business_metric DEFINES glossary_term`,
   `business_metric MAPS_TO physical_column` por cada mapping.

## 4. Relaciones

- **Físicas (FK)**: `relation_type=foreign_key`, `status=confirmed`.
- **Inferidas** (sin FK declarada): señales = nombres, tipos, similitud de
  naming, metadata documentada. `status=suggested` + `confidence`.
- Confirmar/rechazar: `POST /catalog/relationships/{id}/confirm|reject`
  (auditado). NUNCA se crean constraints físicos en la base del cliente.

## 5. Enums / códigos desconocidos

Columnas categóricas (cardinalidad ≤ 50) → valores **OBSERVED** en
`catalog_enum_values`. Sin documentación aprobada:
- Gap `UNDEFINED_ENUM` en `context_gaps`.
- Sugerencia `enum_definition` en la Review Queue.
- NUNCA se infiere "A = Active" automáticamente; la aprobación humana
  documenta `documented_meaning`.

## 6. Source Authority (`catalog_authority`)

`domain`, `concept`, `source_name`, `source_type`, `authority_level`,
`priority`, `effective_from/to`. Alimenta al Answerability Gate:
`resolve_authoritative_source(org, concepts)` → `authoritative_source` para
resolver `SOURCE_CONFLICT` sin elegir fuentes arbitrariamente.

## 7. Context Readiness (nunca un % solo)

`GET /api/v1/catalog/sources/{id}/readiness` devuelve composición:

```json
{
  "overall": 82.0,
  "schema_coverage": 100.0,
  "relationship_coverage": 91.0,
  "description_coverage": 64.0,
  "semantic_mapping_coverage": 40.0,
  "metric_coverage": 58.0,
  "glossary_coverage": 71.0,
  "freshness": 99.0,
  "data_quality": 85.0,
  "unknown_code_count": 3,
  "pending_review_count": 5
}
```

## 8. Lineage / Enterprise Context Graph

Aristas `catalog_lineage` (PostgreSQL, sin graph DB):

```
Business Entity   USES        Business Metric
Business Metric   DEPENDS_ON  Business Field
Business Field    MAPS_TO     Physical Column
Document          DEFINES     Business Concept
Source            IS_AUTHORITY_FOR  Business Concept
```

`GET /api/v1/catalog/lineage?object_type=&object_id=` lista upstream/downstream.

## 9. Schema Linking (Text-to-SQL)

El SQL Expert recibe SOLO el subconjunto relevante. Ranking con boosts
semánticos: glossary match + entity mapping + comentarios + queries
históricas exitosas (`sql_audit_logs`) + distancia de relaciones.
`RAG_SQL_SEMANTIC_LINKING_ENABLED=true`; sin catálogo → heurística histórica.
Al completar un scan, `SchemaCache` se invalida.

## 10. Review Queue

Toda sugerencia (INFERRED) requiere acción humana: `APPROVE / REJECT /
EDIT_AND_APPROVE / DEFER`. La aprobación materializa (entidad aprobada,
relación confirmada, enum documentado, métrica/glosario creados) con
provenance APPROVED + lineage + auditoría (`catalog.suggestion.*`).

## 11. Extensibilidad futura

- **Enterprise Context Graph**: `catalog_lineage` ya modela las aristas;
  un grafo dedicado puede leer el mismo modelo.
- **Documentos en el catálogo**: `catalog_authority.source_type='document'`
  ya soporta políticas/documentos como fuentes autoritativas.
- **API/otras fuentes**: `ConnectorPlugin.deep_discover()` es el punto de
  extensión (por defecto deriva del `discover()` sin stats).