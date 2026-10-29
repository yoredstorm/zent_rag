# P18.2-00 — Auditoría de causa raíz y baseline de comprensión

- Fecha: 2026-10-29
- Corte auditado: `8a2d7c46907d51faf18a21e0de86c9b6ba411ae9` (master == corte P18.1)
- Rama de trabajo: `p18.2-knowledge-understanding`
- Alcance: modelo de lectura del Explorador, ingesta durable, sesiones, género,
  candidatos y métricas. Sin SOÑAR, sin Dream Engine, sin escritura autónoma.

## 1. Veredicto del baseline

| Dimensión | Estado | Evidencia |
|---|---|---|
| Integridad de la fuente | OK | PDF original inmutable; 104 páginas, 1.045 bloques, 8 secciones |
| Objetos canónicos históricos | 110 | 105 `concept`, 3 `business_rule`, 2 `attribute` |
| Objetos visibles en Explorador | 0 | `build_explorer_insight()` con datos reales |
| Pasajes recuperables | 215 evidencias en 43 páginas | `evidence_ledger`, todas con `excerpt` |
| Clasificación actual | `unknown` | El perfil histórico no contiene `document_genre` |
| `document_type` histórico | `technical_specification` | Etiqueta heredada; no se usa como género |
| Comprensión evaluada | No evaluado | No existe evaluación versionada de comprensión |

El caso real está reproducido: **110 objetos → 0 visibles → 110 ocultos**, y no
es un problema de la fuente ni de los pasajes. Los pasajes están disponibles.

Hallazgo adicional de alcance: la fuente histórica tiene `workspace_id` pero
`corpus_id = NULL`. El endpoint
`/workspaces/{corpus_id}/sources/{source_id}/insight` no puede alcanzarla sin
un backfill autorizado. El baseline se obtuvo por lectura directa del read
model; la ruta de UI queda marcada como pendiente en certificación.

### Distribución de rechazos (ejecución real)

| Razón | Objetos |
|---|---:|
| `SENTENCE_FRAGMENT` | 58 |
| `NON_TERM_LABEL` | 25 |
| `pregunta o diálogo` | 16 |
| `NARRATIVE_CLAUSE` | 5 |
| `encabezado de sección` | 2 |
| `HEADING_OR_INDEX` | 2 |
| `número aislado` | 1 |
| `TRUNCATED_OR_CONCATENATED` | 1 |
| **Total** | **110** |

Lectura: la puerta semántica de P18.1 funciona; lo que falta es (a) una vista
documental útil cuando no hay objetos canónicos y (b) candidatos contextuales
derivados de pasajes, no de etiquetas sueltas.

## 2. Recorridos reales de código

### A. Documento original → parser → StructuredDocument → perfil → compilador

1. `src/api/routes/sources.py` → carga, MIME, `store_upload`, `enqueue_source_sync`.
2. Worker de ingesta → parser → `StructuredDocument` (`structured_documents`,
   `structured_blocks`).
3. `src/knowledge/understanding/views.py::source_profile` calcula
   `document_type`, `document_genre`, `genre_evidence`, `profile_version`.
4. `src/knowledge/compiler/pipeline.py` → `extract_semantic_units` →
   `candidates.py` / `entities.py` / `rules.py` → objetos canónicos y
   `evidence_ledger`.

El perfil histórico de `el_principito.pdf` es anterior a P18.1: no tiene
`document_genre`, pero sí `technical_fields: 3` y `document_type:
technical_specification`. Es decir, la etiqueta errónea es legado, no una
decisión del clasificador actual.

### B. Fuente/corpus → insight → panel

1. `GET /api/v1/knowledge/workspaces/{corpus_id}/sources/{source_id}/insight`
   (`src/api/routes/knowledge_workspaces.py::source_insight`).
2. `list_documents(..., limit=1)`.
3. `SELECT ... FROM knowledge_canonical_objects ... LIMIT 1000`.
4. `SELECT ... FROM evidence_ledger ... ORDER BY created_at DESC LIMIT 1000`.
5. `build_explorer_insight()` (`src/knowledge/understanding/explorer.py`).
6. `portal/src/pages/knowledge/Explorer.tsx::DocumentInsightPanel`.

Defectos de contrato:
- `limit=1` presupone una fuente = un documento sin contrato explícito.
- Los conteos no distinguen total real de filas leídas; 1.001 objetos se
  reportarían como 1.000.
- La "primera evidencia" es la más reciente, no la más fuerte.
- No hay `counts_total`/`counts_returned`/`truncated` ni cursor.
- No hay mapa estructural ni pasajes de respaldo cuando `objects_visible=0`.

### C. Lista técnica → `knowledge_model.list_objects`

- `fetchKnowledgeObjects()` → `GET /api/v1/knowledge/objects` →
  `KnowledgeModelService.list_objects` → `repository.list_objects`.
- El endpoint no excluye objetos con `metadata.explorer_visibility=hidden`.
  La vista natural debe filtrar; la API técnica heredada no se reescribe.
- `Explorer.tsx` ejecuta `loadObjects()` incluso en `mode=document` y además
  renderiza `DocumentInsightPanel`; luego cae al listado si `showTopics` es
  falso. Es una superposición real, no solo visual.

### D. Subida/reintento → sesión → sellado → consulta

1. `KnowledgeImportWizard.uploadAll()` abre sesión (`POST /knowledge/sessions`).
2. Cada archivo va a `POST /api/v1/sources/files/upload-batch?session_id=...`.
3. `_open_learning_session()` devuelve la sesión existente **sin comprobar
   `sealed_at`**.
4. `_session_attach_hook()` → `KnowledgeSessionService.attach_source()` →
   `repository.add_source()`, que inserta sin condición de estado.
5. `enqueue_source_sync()` absorbe cualquier error del hook (`try/except`) y
   encola igualmente.
6. `uploadAll()` sella al final; `retry()` reenvía con `force=true` y el mismo
   `sessionId`.

Consecuencia demostrada: una sesión sellada puede recibir fuentes nuevas y el
reintento crea otra fuente aunque el archivo ya exista. `force=true` no debe
ser un bypass de estado.

Además, `askFirstQuestion()` usa `createdItems` como respaldo de
`readySourceIds`: un HTTP 201 habilita preguntar antes de que la fuente sea
consultable. El gate de readiness debe ser el estado durable, no la respuesta
de subida.

## 3. Causa raíz por capa

| Capa | Causa | ¿Requiere reprocess? |
|---|---|---|
| Extracción histórica | Etiquetas de diálogo/pregunta convertidas en conceptos por el pipeline previo a P18.1 | Sí, en sandbox/copia |
| Clasificación histórica | Perfil sin `document_genre`; `document_type` legado | Sí (metadatos), no toca el PDF |
| Read model | `LIMIT 1` / 1.000 sin conteos ni truncamiento; sin fallback estructural | No |
| Evidencia | Primera evidencia por fecha, no por fuerza; sin batch lookup | No |
| UI | Modos no excluyentes; listado técnico se dispara en vista documental | No |
| Wizard | `add_source` no valida `sealed_at`; hook fail-soft; retry re-sube | No |
| Readiness | `createdItems` habilita preguntar sin fuente consultable | No |
| Métricas | "Comprensión semántica" = objetos con descripción | No |

## 4. Fixtures y evaluación

Se reutilizan los fixtures P18.1 (`tests/fixtures/p18_1/`) y se añade un relato
sintético original (sin texto con copyright) con diálogos, números, secciones y
personajes. Familias:

1. Narrativa: diálogo, preguntas, números, páginas.
2. Técnico: ATPCO sintético con campos, máscaras y reglas.
3. Política/contrato: obligación, excepción, opinión.
4. Tabular: CSV/Excel con celdas y columnas.

El corpus humano anotado debe incluir 10–20 preguntas por familia, incluidas
preguntas sin evidencia y contradicciones. **No se usan respuestas del propio
modelo como verdad de referencia.**

## 5. Umbrales

Los umbrales de producto no están aprobados todavía. Este paquete usa puertas
internas verificables, no porcentajes presentados como certificación:

- Cero fugas entre organización/workspace/corpus/fuente/ACL.
- Cero citas fabricadas: todo claim sustentado abre un pasaje existente.
- Cero `technical_specification` en los fixtures narrativos anotados.
- Cero objetos de diálogo/pregunta en la vista natural de narrativa.
- Cero fuentes adjuntadas a sesiones selladas.
- `truncated=true` siempre que la lectura no cubra el total.
- Si no hay evaluación versionada, la comprensión se muestra **No evaluado**.

Las métricas de exactitud, cobertura, latencia y coste se registran antes de
fijar umbrales; no se ajustan para que las pruebas pasen.

## 6. Decisión

- Baseline: **GO** para P18.2-01.
- Comprensión en producción: **NO-GO** hasta completar fases P1 y certificar
  con corpus humano.
- Reparación histórica: **CONDITIONAL**; solo en copia/sandbox y con revisión
  humana. No se modifica el PDF ni se borran objetos canónicos.
