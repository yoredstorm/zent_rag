# Knowledge OS — arquitectura canónica

> Reemplaza a `enterprise-knowledge-refactor.md` (ADR del cutover V1→V2, ya cerrado).
> No existe V1 ni V2 en runtime: existe **un** motor de conocimiento.

## Principio

> ZENT no almacena archivos para buscarlos después.
> ZENT transforma información en conocimiento verificable.

Los documentos siguen siendo fundamentales, pero son **fuentes**. El
conocimiento es lo que queda compilado: objetos, hechos, relaciones, reglas,
evidencia y conflictos.

## Pipeline (una sola ruta)

```
RAW SOURCE
  -> Parsed Source            src/knowledge/structure/     (PDF, DOCX, HTML, XLSX, CSV, texto)
  -> Structural Model         src/core/domain/knowledge_v2 (StructuredDocument: pages/blocks/sections/tables)
  -> Source Adapter           src/knowledge/reconstruction/adapters/ (PDF, DOCX, texto, Excel, CSV, JSON, XML, DB, API, eventos)
  -> Raw Extraction
  -> Semantic Reconstruction src/knowledge/reconstruction/ (continuidad, fragment detector, gate)
  -> Semantic IR              metadata["semantic_reconstruction"] (unidades, tablas, nodos, provenance)
  -> Semantic Quality Gate    VALID/RECONSTRUCTED -> compilador; resto -> INGESTION_QUALITY
  -> Document Understanding   src/knowledge/understanding/ (layout, tablas, literales, semánticas, roles)
  -> Semantic Units           src/knowledge/compiler/extract.py
  -> Entities (+alias)        src/knowledge/compiler/entities.py
  -> Facts                    src/knowledge/compiler/facts.py
  -> Relationships            src/knowledge/compiler/facts.py
  -> Rules                    src/knowledge/compiler/rules.py
  -> Temporal Facts           src/knowledge/compiler/temporal.py
  -> Conflict Candidates      src/knowledge/compiler/conflicts.py (adjudicación + gate)
  -> Ingestion Quality Queue  knowledge_ingestion_quality (fragmentos, sin fuente)
  -> Knowledge Objects        knowledge_canonical_objects   (+ knowledge_entity_aliases)
  -> Evidence Links           evidence_ledger
  -> Canonical Knowledge      knowledge_model (assertions/edges/conflicts + /knowledge/*)
```

La Semantic Reconstruction Layer es obligatoria y está documentada en
`semantic-reconstruction-layer.md`: ningún documento entra al Knowledge
Compiler sin pasar por su gate (`KnowledgeCompiler.build` llama a
`ensure_reconstruction`).

El compilador corre al terminar cada ingesta
(`KnowledgeIngestionEngine._compile`), sin intervención humana. Recompilar es
idempotente: la identidad canónica es determinista
(`canonical_uuid(org, kind, natural_key)`), así que el mismo conocimiento se
refuerza en lugar de duplicarse.

El detalle del gate de calidad, la taxonomía de conflictos y el reproceso
limpio están en `knowledge-quality-gate.md`.

## Identidad canónica

- La identidad es **por nombre normalizado**, no por el lugar donde apareció:
  `Record 4` es el mismo objeto si lo define un PDF o si es la cabecera de una
  columna en Excel. El tipo lógico viaja como atributo.
- Las fusiones **solo** ocurren con evidencia y quedan registradas con razón y
  confianza (`EntityMerge`):
  - **R1** igualdad exacta normalizada · confianza 1.0
  - **R2** alias declarado en la fuente (`"Category 31 (Cat 31)"`, "also known as") · ≥ 0.85
  - **R3** sigla que son las iniciales de un nombre del mismo documento · 0.70
  - **R4** nombre calificado del mismo documento (`ATPCO Record 4` frente a `Record 4`; el nombre simple es el canónico) · 0.72
- Nada más se fusiona. La duda es información: queda como entidad separada y se
  reporta.

## Multi-representación

| Representación | Dónde vive | Para qué |
|---|---|---|
| Vectorial | Qdrant `rag_documents` (dense + sparse) | similitud semántica |
| Estructurada | `tabular_*`, `structured_blocks` | datos exactos (lookup, agregación, filtro) |
| Grafo | `knowledge_canonical_objects` + `knowledge_edges` | entidades y relaciones |
| Léxica/exacta | sparse BM25 + canales exactos del índice | códigos, bytes, identificadores |
| Temporal | `knowledge_assertions.valid_from/valid_to/observed_at` | vigencias y cambios |
| Evidencia | `evidence_ledger` | provenance hasta documento/página/bloque/tabla/fila/celda |

El retrieval lo decide el **planner** (`src/rag/retrieval/planner.py`):
representaciones + razones explícitas, visibles en la traza.

## Leyes del compilador

1. **Evidence first**: ningún candidato sin evidencia localizable.
2. **La procedencia es un dato**: `SourceLocator` guarda documento, página,
   sección, bloque, tabla, fila, celda y hash de contenido.
3. **Corroboración, no duplicación**: un hecho sostenido por varias fuentes
   independientes sube su respaldo (`evidence_sources`), no se duplica.
4. **El conflicto no se resuelve solo**: se clasifica con la taxonomía
   semántica (`TRUE_CONFLICT`, `ALIAS_VARIATION`, `PARSER_FRAGMENT`,
   `DUPLICATE`, `TEMPORAL_CHANGE`, `VERSION_CHANGE`, `SCOPE_DIFFERENCE`,
   `EXCEPTION`, `COMPLEMENTARY_INFORMATION`, `INSUFFICIENT_CONTEXT`, ...) y
   solo pasa a la cola de conflictos si tiene evidencia y fuentes en ambos
   lados. Todo lo demás se auto-resuelve y queda auditado.
5. **La ingesta se separa del conocimiento**: fragmentos, parsing dudoso y
   procedencia faltante van a `knowledge_ingestion_quality`. Un problema de
   parsing no es un conflicto de conocimiento.
6. **Sin fuente no hay conocimiento**: entidad, hecho o conflicto sin
   `source_id` y evidencia localizable se rechaza hacia la cola de ingesta.
5. **La ingesta nunca se cae por el conocimiento**: un fallo del compilador se
   registra en `knowledge_compilations` y se reintenta en la próxima
   recompilación; el documento y su índice quedan intactos.
6. **Sin embargo, un fallo del proveedor sí es del job**: 429/cuota reintenta
   con backoff largo, no marca el record como fallido.

## Observabilidad

- `GET /api/v1/knowledge/compilations` — trazas del compilador por fuente.
- `GET /api/v1/knowledge/health` — salud del conocimiento (dimensiones medidas;
  lo no medido no cuenta como 0).
- `GET /api/v1/knowledge/quality` — problemas operables (gaps, conflictos,
  huérfanos, sin evidencia).
- Métricas Prometheus: `knowledge_ingest_*`, `knowledge_parse_*`,
  `knowledge_tabular_*`, `knowledge_model_materializations_total`.

## Flags eliminados

Estos interruptores existían para mantener dos arquitecturas en paralelo. Ya no
existen: `RAG_KNOWLEDGE_V2_ENABLED`, `RAG_KNOWLEDGE_V2_SHADOW`,
`RAG_KNOWLEDGE_V2_PROMOTE`, `RAG_DOCUMENT_UNDERSTANDING_ENABLED`,
`RAG_DOCUMENT_UNDERSTANDING_SHADOW`, `RAG_KNOWLEDGE_SUMMARY_MODE`,
`RAG_KNOWLEDGE_TABULAR_ENABLED`, `RAG_KNOWLEDGE_TABULAR_SUPERSEDE_V1` y el
paquete `src/knowledge/cutover/`.
