# ADR — ZENT Knowledge Operating System (FASE 34)

Estado: aceptado
Fecha: 2026-09-26
Autores: reingeniería del módulo Conocimiento

## Contexto

El módulo Conocimiento estaba construido alrededor del pipeline de aprendizaje
(`LearningRun`, `LearningStep`, SSE, stage progress) y de tablas físicas
(`catalog_*`). La experiencia principal era "Zent está aprendiendo" y el
conocimiento durable (reglas, métricas, procesos, dominios, evidencia,
conflictos) no existía como modelo de primera clase. Además:

- el grafo (`/knowledge/map`) se derivaba de tablas de catálogo, no de un
  modelo canónico;
- "Relaciones descubiertas: 0" se mostraba aunque la lectura fallara;
- `knowledge_canonical_objects` (migración 102) existía sin lectores ni
  escritores productivos;
- `evidence_ledger` (103) solo se llenaba desde grounding de chat/workflows;
- la dimensión no medida del score de readiness contaba como 0.

## Decisiones

### D1 — El objeto canónico es la identidad del conocimiento

Se reutiliza `knowledge_canonical_objects` (102) como registro de objetos de
conocimiento (no se crea una tabla `knowledge_objects` paralela). Se extiende
con `name/display_name/description/domain/source_of_truth/authority_level/
evidence_count/assertion_count/verified_*` y se amplía el CHECK de `kind` y
`status`.

- Estados de negocio: `draft | discovered | inferred | verified | rejected |
  deprecated`. Los valores legados (`observed`, `approved`, `archived`) se
  normalizan en lectura para no romper consumidores existentes.
- Ley de aprobación: `status IN (approved, verified)` exige
  `provenance = APPROVED` (la revisión humana es el único camino de promoción).

Alternativas descartadas: tabla nueva `knowledge_objects` (duplicaba identidad);
Neo4j (no hay justificación medible: los grafos por tenant son pequeños y
PostgreSQL resuelve vecindario y agregados).

### D2 — Assertions y evidencia separadas del objeto

`knowledge_assertions` guarda afirmaciones (sujeto/predicado/objeto) con
`confidence`, `confidence_detail`, `status`, `provenance`, `method` y `source`.
La evidencia se guarda en `evidence_ledger` (103, ya usado por grounding) con
`evidence_type`, `strength`, `locator` y `assertion_id`. Los chunks/documentos
siguen siendo evidencia recuperable; el conocimiento no es el chunk.

### D3 — Confianza explicable, no número del LLM

`compute_confidence` combina señales reales con media geométrica ponderada:
`source_reliability`, `evidence_strength`, `corroboration` (evidencia count),
`semantic_certainty` (método) y `freshness`. Reglas duras:

- sin evidencia: techo 0.6;
- rechazada: 0.0;
- verificada con evidencia: piso 0.9.

`confidence_detail` persiste la composición para que la UI pueda explicar
cada número ("¿Por qué?").

### D4 — El grafo se deriva del modelo

`knowledge_edges` es la única fuente del grafo. El endpoint
`GET /api/v1/knowledge/graph` devuelve vecindario (focus + depth) con límites y
expansión on-demand; no existe un dataset paralelo. La antigua ruta
`/knowledge/map` redirige a `/knowledge/model?view=graph`.

### D5 — Gaps y conflictos reutilizan `context_gaps`

Los gaps accionables viven en `context_gaps` (079/081) extendido con
`title/description/priority/priority_score/object_id/source_id/impact_objects`
y tipos nuevos (`UNSUPPORTED_ASSERTION`, `CONTRADICTION`, `STALE_KNOWLEDGE`,
`LOW_CONFIDENCE`, `MISSING_METRIC_DEFINITION`, ...). La prioridad usa señales
reales (impacto de negocio, retrieval, dependientes, gap de confianza,
ambigüedad) — nunca aleatoriedad. Los conflictos entre fuentes viven en
`knowledge_conflicts`, detectados al materializar y resolubles con decisión
humana auditada.

### D6 — Materialización incremental desde la infraestructura existente

`KnowledgeModelMaterializer` convierte `catalog_sources/tables/columns/
entities/fields/relationships`, `catalog_metrics`, `business_definitions`,
`knowledge_business_rules`, `verified_queries` y `structured_documents` en
objetos/aristas/assertions/evidencia. Es idempotente por `natural_key` y
org-scoped. Corre: (a) al terminar un learning run (best-effort, no bloquea el
run), (b) on-demand al abrir el Command Center si no hay objetos y hay fuentes,
(c) vía `POST /api/v1/knowledge/model/rebuild` (permiso `knowledge:admin`).

No se introdujo fingerprint por artefacto todavía: el materializador es
idempotente y acotado (`RAG_KNOWLEDGE_MODEL_MAX_COLUMNS`), y el impacto se
calcula sobre el grafo. El fingerprint incremental queda como fase 8.

### D7 — Health separa medido de no medido

`KnowledgeHealth` tiene dimensiones con `measured`. El global se calcula solo
sobre dimensiones medidas y expone `measured_dimensions/total_dimensions`. Una
dimensión sin datos se muestra "No medido", nunca 0. El readiness previo
(`knowledge_scores`) sigue existiendo para compatibilidad, pero la UI principal
usa Knowledge Health.

### D8 — JEV no se acopla

No se modificó el decision layer. El materializador usa métodos deterministas y
el contrato `DecisionEngine` existente queda disponible para fases futuras
(aceptación de relaciones, escalado a revisión). Ninguna decisión de
conocimiento depende hoy de JEV.

### D9 — ERROR != ZERO

Los endpoints del Knowledge OS devuelven 503 tipado
(`knowledge_model_unavailable`) cuando la lectura falla; el frontend muestra
estado de error con reintento. Nunca se convierten errores en counts 0.

## Consecuencias

- El módulo Conocimiento ya no depende de un run activo: el modelo persiste.
- Los agentes/workflows pueden consumir los mismos objetos (edges y evidencia)
  en fases posteriores sin una capa semántica paralela.
- Nuevas tablas: `knowledge_edges`, `knowledge_assertions`,
  `knowledge_object_versions`, `knowledge_conflicts` (migración 132). Se
  extienden `knowledge_canonical_objects`, `evidence_ledger` y `context_gaps`.
- Deuda controlada: el mapeo `entity_tables` del materializador usa nombres de
  tabla sin schema (colisión posible en schemas homónimos); la detección de
  procesos/KPIs queda pendiente de la fase 5-6.
