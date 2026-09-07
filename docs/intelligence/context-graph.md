# Zent Enterprise Context Graph (FASE 25)

> Conecta usuarios, agentes, conceptos, métricas, entidades, fuentes,
> documentos, tablas, columnas, APIs, herramientas, consultas, respuestas,
> evaluaciones y gaps. Modelado en PostgreSQL (`catalog_lineage`) — sin graph
> DB (no hay necesidad técnica demostrada).

## 1. Nodos y relaciones

`catalog_lineage` es una tabla de aristas genérica:
`(upstream_type, upstream_id) --relation--> (downstream_type, downstream_id)`.

Relaciones soportadas (CHECK de la migración 081):

```
Business Entity   USES            Business Metric
Business Metric   DEPENDS_ON      Business Field
Business Field    MAPS_TO         Physical Column
Document          DEFINES         Business Concept
Source            IS_AUTHORITY_FOR Business Concept
Agent             AGENT_USES      Source / Metric
Question          QUESTION_REFERENCES Concept
Gap               GAP_AFFECTS     Agent
Evaluation        EVALUATION_TESTS Metric
...               SOURCE_OF / DEFINES / USES / MAPS_TO
```

## 2. Cross-Source Context

Relaciona contextos de distintas fuentes con lineage completo:

```
erp.TBL_CUST ──MAPS_TO──▶ Business Entity Customer ◀──DEFINES── Policy PDF
ERP.ORDER ──MAPS_TO──▶ Order ──USES──▶ CRM.Opportunity (concepto compartido)
```

El `mapped_table_id` de `catalog_entities` + las aristas `MAPS_TO` permiten
navegar entre la representación física y la semántica de cualquier fuente.

## 3. Source of Truth (autoridad por dominio)

`catalog_authority`: `(org, domain, concept, source_name, authority_level,
priority, effective_from/to)`. Flujo ante conflictos:

1. **detectar** conflicto (evidencias numéricas discordantes);
2. **consultar** `catalog_authority` para el concepto;
3. **usar** la autoridad si está inequívocamente configurada;
4. **registrar** el conflicto igualmente (`source_conflicts`);
5. si no existe autoridad → **abstenerse** (`SOURCE_CONFLICT`).

El Answerability Gate ya recibe `authoritative_source` vía
`resolve_authoritative_source(org, concepts)` (FASE 24).

## 4. Source Health

`GET /api/v1/catalog/sources/{id}/health` compone Context Readiness + salud
operacional: connectivity, freshness, schema/semantic/metric coverage,
unknown codes, pending relationships, failed queries 7d.

## 5. Intelligence Readiness por agente

`GET /api/v1/agents/{id}/intelligence-readiness` — 9 dimensiones operativas:
knowledge_coverage, semantic_coverage, source_health, data_freshness,
evaluation_pass_rate, answerability_rate, unsupported_question_rate,
context_gap_count, deployment_health. Caché en `agent_readiness`; overall
HIGH/MEDIUM/LOW según score ponderado.

## 6. Why does Zent know this? / Why couldn't Zent answer?

- `GET /api/v1/intelligence/why/{query_id}`: intent, business concepts +
  versiones, source of truth, physical sources, model, trace, confidence.
- `GET /api/v1/intelligence/why-not/{query_id}`: status, available (catálogo
  real), missing (glosario/enums), recommendation, trace.

Ambos org-scoped y con permisos (`rag:read`).

## 7. Revocación y dependencias

`GET /api/v1/catalog/sources/{id}/dependency-impact` y el DELETE de connector
responden con el impacto: agents, metrics, business_concepts, eval cases,
deployments, documents, tables, columns, relationships, suggestions. La
revocación aplica política (purge/hide/retain-metadata-only), invalida
`SchemaCache` y bloquea sugerencias afectadas
(`rag_knowledge_invalidations_total`).

## 8. Seguridad

- Todas las aristas org-scoped (404 cross-tenant).
- La visibilidad sigue las ACL existentes (connector → discovery → catalog →
  retrieval → answer). Una inferencia nunca revela información que el usuario
  no podía ver originalmente.