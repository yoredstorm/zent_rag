# Knowledge OS — Semantic Reconstruction Layer

> Capa arquitectónica obligatoria. Ninguna fuente se convierte en chunks o
> knowledge objects sin comprensión estructural previa.
> Implementación: `src/knowledge/reconstruction/`.

## Principio

El parser extrae información. **Semantic Reconstruction recupera su estructura
y significado.** El Knowledge Compiler convierte ese significado en
conocimiento. Knowledge OS lo organiza y conecta; Cognitive OS lo utiliza.

```
SOURCE
  -> SOURCE ADAPTER
  -> RAW EXTRACTION
  -> SEMANTIC RECONSTRUCTION
  -> SEMANTIC INTERMEDIATE REPRESENTATION
  -> SEMANTIC QUALITY GATE
  -> KNOWLEDGE COMPILER
  -> CANONICAL KNOWLEDGE
  -> KNOWLEDGE OS
  -> COGNITIVE OS
```

No es un parche de PDF. PDF, DOCX, TXT, Markdown, HTML, Excel, CSV, JSON, XML,
base de datos, SQL result sets, APIs, eventos, correos y conversaciones
convergen al mismo modelo semántico. Agregar un formato futuro es registrar un
adapter, no tocar el compilador.

## Parsing vs Reconstruction

- Parsing: "¿qué encontré técnicamente?".
- Semantic Reconstruction: "¿qué estaba intentando representar la fuente?".

Ejemplo: el parser entrega `FOR RECORD 2 – CATEG` + `ORY CONTROL`. La
reconstrucción une la palabra partida porque `CATEGORY` aparece como palabra
completa en la propia fuente (evidencia estructural/contextual). Nunca inventa:
si no hay evidencia, la pieza queda `INCOMPLETE`/`REQUIRES_REPAIR` y jamás pasa
al conocimiento canónico. `Y CONT` aislado no se convierte en entidad.

Reglas duras:

1. No inventar contenido. Solo recombinar caracteres de la fuente (unir, quitar
   guion de corte o agregar un espacio).
2. La reconstrucción exige evidencia: proximidad visual, orden de lectura,
   puntuación, vocabulario observado en la fuente, estructura de tabla o
   contexto de heading.
3. Lo dudoso se conserva y se reporta; no se borra la procedencia.

## Source Adapters

`src/knowledge/reconstruction/adapters/` — todos producen `RawExtraction`
(elementos y tablas) con provenance:

| Fuente | Adapter | Estructura que preserva |
|---|---|---|
| PDF | `PdfSourceAdapter` | layout, columnas, orden de lectura, headers/footers, tablas, captions, cortes de línea |
| DOCX | `DocxSourceAdapter` | headings, párrafos, listas, tablas |
| TXT / Markdown / HTML | `TextSourceAdapter`, `MarkdownSourceAdapter`, `HtmlSourceAdapter` | jerarquía de headings, párrafos, listas, código |
| Excel | `SpreadsheetSourceAdapter` | workbook, sheet, table, header, columna, fila, rango, merged cells, fórmula, tipos |
| CSV/TSV | `CsvSourceAdapter` | idem, una tabla con headers y filas exactas |
| JSON | `JsonSourceAdapter` | objects, arrays, propiedades, tipos, JSONPath |
| XML | `XmlSourceAdapter` | elementos, atributos, jerarquía, XPath |
| Base de datos | `DatabaseSourceAdapter` | schema, tabla, columna, tipo, PK/FK, constraints, relaciones, patrones |
| API/OpenAPI | `ApiSourceAdapter` | servicio, endpoint, método, parámetros, request/response schema, status codes, versión |
| Eventos / correo / conversación | `EventSourceAdapter`, `EmailSourceAdapter`, `ConversationSourceAdapter` | emisor, tiempo, asunto, rol, orden |

Un adapter que no reconoce la carga estructurada cae al adapter de documento;
nunca devuelve contenido sin provenance.

## Semantic Intermediate Representation (IR)

`src/knowledge/reconstruction/contracts.py`. Independiente del formato:

- `SemanticRepresentation` (raíz), `StructuralNode`, `SemanticUnitIR`,
  `SemanticTable`, `SemanticRecord`, `SemanticField`, `Continuation`,
  `Reference`, `SourceProvenance`.
- `ElementKind` cubre documento, jerarquía, tabla, registro, campo, objeto,
  array, propiedad, schema, endpoint, evento, etc.
- La IR se persiste en `StructuredDocument.metadata["semantic_reconstruction"]`
  (schema versionado, unidades compactas, tablas, nodos, continuaciones,
  pendientes y términos rechazados). No se creó una tabla SQL por concepto.

### Provenance inmutable

Cada elemento conserva su conexión con la fuente: PDF (documento, página, bbox,
bloque, hash), spreadsheet (hoja, tabla, fila, columna, celda/rango), base de
datos (conexión, schema, tabla, fila/clave, columna), JSON (JSONPath), XML
(XPath), API (endpoint, método, ruta de response). El bloque absorbido por una
continuación queda `superseded` con `superseded_into`; nunca se elimina.

## Continuidad y fragmentos

`continuity.py` decide si dos elementos separados son la misma unidad lógica:
proximidad (`bbox`), mismo carril horizontal, orden consecutivo, página,
heading, puntuación, conectores, guion de corte, vocabulario real de la fuente
y comparación léxica. `reconstruct_sequence` aplica cadenas de continuación;
los elementos absorbidos mantienen provenance.

`fragments.py` (Fragment Detector) detecta `MID_WORD_START`, `MID_WORD_END`,
`ABRUPT_SENTENCE`, `TINY_ISOLATED_TEXT`, `REPEATED_FRAGMENT`,
`OVERLAPPING_CHUNK`, `TABLE_FRAGMENT`, `HEADER_FOOTER_ARTIFACT`,
`PARTIAL_ENTITY` y `CONTINUATION_FRAGMENT` reutilizando
`src/knowledge/quality/fragments.py`. Un elemento no se valida con su propio
texto: su contenido sale de las referencias antes de decidir.

## Semantic Quality Gate

`quality_gate.py`. Todo elemento termina en uno de estos estados:

`VALID`, `RECONSTRUCTED`, `AMBIGUOUS`, `INCOMPLETE`, `LOW_QUALITY`,
`STRUCTURAL_ARTIFACT`, `DUPLICATE`, `REQUIRES_REPAIR`, `REJECTED`.

Solo `VALID`/`RECONSTRUCTED` con respaldo suficiente pasan al Knowledge
Compiler. El resto:

- deja `index_semantic=False` en el bloque (no se indexa ni se recupera),
- entra a `knowledge_ingestion_quality` como `INGESTION_QUALITY`,
- nunca se convierte en entidad, hecho, relación, conflicto, gap o canónico.

## Confianza multidimensional

`ConfidenceSignals`: `structure_confidence`, `continuity_confidence`,
`semantic_completeness`, `schema_confidence`, `source_quality` y
`reconstruction_confidence` (composición ponderada). Las dimensiones viajan
hasta el Knowledge Compiler; no se colapsan en un número mágico.

## LLM-assisted reconstruction

Escalamiento:

```
deterministic -> heuristics -> semantic model -> LLM
```

Solo corre si `SEMANTIC_RECONSTRUCTION_LLM_ENABLED=true` y existen decisiones
ambiguas (`pending_decisions`). El proveedor devuelve JSON estructurado
(`classification`, `semantic_unit`, `source_elements`, `confidence`,
`ambiguity`, `reason`). Una continuación LLM se aplica solo si el texto es una
recombinación verificable de los fragmentos. **No se almacena
chain-of-thought**: solo resultado y señales de auditoría. Tope por fuente:
`SEMANTIC_RECONSTRUCTION_LLM_MAX_CALLS`.

## Contrato del Knowledge Compiler

`KnowledgeCompiler.build` llama a `ensure_reconstruction` antes de extraer
unidades: ningún documento entra crudo. El compilador recibe:

- documento reconstruido (bloques unidos, artefactos marcados),
- IR + provenance,
- quality status y confianza por unidad,
- `rejected_terms` de la cuarentena,
- metadata de la fuente.

Todo lo producido empieza como **candidate** (entity, fact, relationship, rule,
alias); la validación y el gate de evidencia deciden qué llega a canónico.
Errores de reconstrucción no contaminan Knowledge OS.

## Cross-source understanding

La IR conserva las diferencias de representación (`Carrier Code = AM`,
`Carrier: AM`, `"carrier": "AM"`, `CXRCD = AM`). No hay entity merge dentro de
la reconstrucción: el Knowledge Compiler resuelve identidad con evidencia.

## Observabilidad

Por ingesta se registran: `raw_elements`, `semantic_units`,
`units_reconstructed`, `continuations_detected`, `fragments_rejected`,
`tables_detected`, `schemas_inferred`, `ambiguous_units`, `llm_repairs`,
`deterministic_repairs`, `rejected_units`, distribución de calidad, latencia y
tokens/costo LLM.

- Métricas Prometheus: `knowledge_reconstruction_*`.
- Tech View: `src/knowledge/reconstruction/report.py::tech_view`.
- Live Learning: eventos `SEMANTIC_RECONSTRUCTED`, `CONTINUATIONS_MERGED`,
  `FRAGMENTS_REJECTED`, `SCHEMAS_INFERRED` con mensajes humanos reales
  ("ZENT reconstruyó 18 bloques que estaban divididos por el formato original",
  "Detectó 12 tablas", "Descartó 7 fragmentos incompletos").

## Quality failures

Un problema de reconstrucción se clasifica `INGESTION_QUALITY`. No se convierte
en conflicto, knowledge gap, entidad ni hecho canónico.

## Reproceso

ZENT no está en producción. Después de desplegar esta capa, purgar el
conocimiento del pipeline anterior que contenga artifacts y reingestar:

```bash
python -m src.scripts.knowledge_reprocess --org <uuid> --dry-run
python -m src.scripts.knowledge_reprocess --org <uuid> --source <uuid> --purge
python -m src.scripts.knowledge_reprocess --org <uuid> --requeue --limit 100
```

La reingesta corre el pipeline corregido (reconstrucción obligatoria incluida).

## Performance

Prioridad: procesamiento determinista, algoritmos structure-aware, heurísticas
locales y vocabulario de la propia fuente. El LLM es el último recurso y está
acotado por fuente. La reconstrucción es O(n) sobre elementos, sin llamadas de
red por defecto.

## Tests

`tests/test_semantic_reconstruction.py` cubre PDF multi-columna, tablas PDF,
continuación de línea, palabra partida, headers repetidos, Excel simple,
multi-sheet, merged/formulas, CSV, JSON anidado, XML anidado, schema de base de
datos, OpenAPI, Markdown, DOCX con tablas, texto plano, provenance, calidad y
fragmentación (`RECORD 2 – CATEG` + `ORY CONTROL` se reconstruye; `Y CONT`
aislado queda `INCOMPLETE`/`REJECTED`, nunca canónico).

## Separación de responsabilidades

| Capa | Misión |
|---|---|
| Parser / Source Adapter | extraer la estructura física |
| Semantic Reconstruction | recuperar estructura, continuidad y significado |
| Knowledge Compiler | convertir significado en candidatos de conocimiento |
| Knowledge OS | organizar y conectar conocimiento canónico |
| Cognitive OS | utilizar el conocimiento |
