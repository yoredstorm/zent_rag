# Knowledge OS — Gate de calidad semántica y Conflict Engine

> Corrección estructural del pipeline: "texto distinto" no es "conocimiento
> distinto". Este documento registra la causa raíz observada, las barreras
> nuevas y el procedimiento de reproceso.

## Causa raíz (evidencia real)

Los conflictos como `CATEG · also_known_as = "ORD 2 – CATEG"` versus
`"RECORD 2 – CATEG"` (sin fuente) no eran contradicciones: eran basura de
extracción que llegaba hasta la cola de conflictos. Origen verificado contra
la fuente `Rec2_Rules_dapp_C.pdf`:

1. **Parser PDF — tablas con estrategia de texto.** `find_tables()` con
   `vertical_strategy: "text"` parte palabras por la mitad en layouts
   justificados (`DATA AP | PLICA | TION FO | R RECO | RD`). Esas celdas
   fragmentadas se convertían en cabeceras de columna.
2. **Sin reconstrucción semántica.** No había un paso que uniera líneas
   visuales en párrafos lógicos ni que recomponiéra palabras partidas con
   guion. Un corte visual producía una "unidad semántica" como `Y CONT`.
3. **Entity extraction sin control de integridad.** Cualquier etiqueta de
   tabla con 2+ caracteres se volvía entidad: `CATEG`, `CONT`, `ORD 2 –
   CATEG`, `2 – CATEGORY`.
4. **Alias por sufijo sin contexto (R4).** El resolver fusionaba cualquier
   nombre largo que terminara con un nombre corto: `"FOR RECORD 2 – CATEGORY
   CONT"` y `"Y CONT"` quedaban como alias de `CONT`, con confianza 0.72.
5. **Alias convertidos en hechos.** `entity_facts` generaba
   `also_known_as` por cada alias. El Conflict Engine comparaba pares
   `(sujeto, also_known_as)` y trataba dos alias legítimos del mismo canónico
   como valores incompatibles: 318 de 1020 conflictos en la base local.
6. **Detección de conflictos por diferencia bruta.** El motor agrupaba por
   `(sujeto, predicado)` y comparaba valores sin exigir evidencia ni fuentes,
   sin scope, sin temporalidad y sin distinguir identidad de contradicción.
   `belongs_to_table` y `has_position` entre tablas distintas también
   "conflictos": 361 más.
7. **Segundo detector, más crudo, en `knowledge_model`.** Un `JOIN` por
   `subject_label + predicate` con valores distintos insertaba conflictos
   para `field_meaning` y `has_many` sin evidencia, sin fuentes y sin
   clasificación.
8. **Sin cola de calidad de ingesta.** Todo problema terminaba mezclado en la
   cola de conflictos, mostrado como "VALOR A / VALOR B / Sin fuente".

## Pipeline corregido

```
RAW SOURCE
  -> Parsed Source          pdf_parser: celdas reconstruidas desde palabras completas
  -> Structural Model       StructuredDocument
  -> Semantic Reconstruction reflow_wrapped_blocks (wrap + dehyphenation)
  -> Document Understanding layout, tablas, literales, roles
  -> Semantic Units         extract.py + gate de calidad por etiqueta
  -> Fragment Quality       quality/fragments.py (determinista)
  -> Entities (+alias)      entities.py: sin fragmentos, R4 restringido
  -> Facts                  facts.py: sin hechos also_known_as, scope en estructura
  -> Conflict Candidates    conflicts.py: candidato, no conflicto
  -> Semantic Adjudication  taxonomía completa (TRUE_CONFLICT, ALIAS_VARIATION, ...)
  -> Strict Gate            evidencia + fuentes + valores completos => visible
  -> INGESTION_QUALITY_QUEUE para fragmentos y procedencia faltante
  -> Canonical Knowledge    knowledge_canonical_objects / assertions / edges
```

### Gate de procedencia

- Ninguna entidad entra sin `source_id` y al menos una evidencia localizable.
- Ningún hecho entra sin `source_id` y evidencia con locator.
- Sin fuente: `SOURCE_MISSING` o `EVIDENCE_MISSING` en la cola de ingesta;
  nunca un conflicto visible.

### Gate de fragmentos

`src/knowledge/quality/fragments.py` clasifica texto con señales
deterministas: artefactos de layout (`|`, corchetes desbalanceados, viñetas
huérfanas), corte a mitad de palabra contra textos de la misma fuente,
substring extremo, palabra truncada, conector colgante y colas truncadas
(`byte`, `being`). Estados: `LOW_QUALITY_EXTRACTION`,
`FRAGMENT_OF_EXISTING_TEXT`, `LAYOUT_ARTIFACT`, `TRUNCATED_WORD`,
`SENTENCE_FRAGMENT`, `TOO_LONG_FOR_TERM`.

### Alias no es conflicto

- Los alias viven en `knowledge_entity_aliases`; ya no se materializan como
  hechos `also_known_as`.
- R4 solo fusiona nombres calificados (no columnas/tablas/códigos), exige
  límite de palabra real y nombres con estructura.
- Cualquier par `also_known_as` se clasifica `ALIAS_VARIATION` y jamás se
  muestra.

### Conflict Engine con adjudicación

`ConflictCandidate` lleva sujeto, predicado, ambas afirmaciones, evidencia,
fuentes, relación temporal, relación de scope, materialidad, componentes de
confianza y explicación posible. La taxonomía completa:

`TRUE_CONFLICT`, `SAME_MEANING`, `ALIAS_VARIATION`, `PARSER_FRAGMENT`,
`DUPLICATE`, `TEMPORAL_CHANGE`, `VERSION_CHANGE`, `SCOPE_DIFFERENCE`,
`EXCEPTION`, `COMPLEMENTARY_INFORMATION`, `INSUFFICIENT_CONTEXT`,
`SOURCE_QUALITY_PROBLEM`, `UNKNOWN`.

**Gate estricto:** solo `TRUE_CONFLICT`/`SOURCE_CONFLICT` con evidencia y
fuentes en ambos lados, valores semánticamente completos y comparación con
sentido se insertan como conflicto abierto. Todo lo demás se auto-resuelve y
queda auditado.

### Segundo detector

`KnowledgeModelRepository.detect_conflicts` usa la misma adjudicación: exige
`evidence_count > 0`, excluye identidad (`also_known_as`), respeta scope y
solo inserta conflictos que pasan el gate. Las assertions de materialización
(`field_meaning`, `has_many`, `mapped_to_table`) ahora llevan `source_id`.

## Cola de calidad de ingesta

Tabla `knowledge_ingestion_quality` (migración 138). Se expone en:

- `GET /api/v1/knowledge/ingestion-quality?status=open&kind=...`
- Portal: `/knowledge/health?tab=ingestion` ("Calidad de ingesta").

Es un área separada de los conflictos de conocimiento:
fragmentos, baja calidad, fuente/evidencia faltante.

## Reproceso limpio

```bash
python -m src.scripts.knowledge_reprocess --org <uuid> --dry-run
python -m src.scripts.knowledge_reprocess --org <uuid> --source <uuid> --purge
python -m src.scripts.knowledge_reprocess --org <uuid> --requeue --limit 100
# Limpieza de conflictos legacy que no pasan el gate (todas las orgs):
python -m src.scripts.knowledge_reprocess --all-orgs --legacy-conflicts
```

La purga elimina solo filas creadas por el compilador
(`metadata->>'compiled_by' = 'knowledge_compiler'`), más conflictos y cola de
calidad. La reingesta reencola las fuentes con el pipeline corregido.
`--legacy-conflicts` conserva únicamente conflictos con fuentes en ambos lados
y clasificación de conflicto real.

## Métricas

Prometheus: `knowledge_conflict_candidates_total`,
`knowledge_conflicts_visible_total`, `knowledge_conflicts_auto_resolved_total`,
`knowledge_ingestion_quality_total`, `knowledge_extraction_decisions_total`.
La señal de alarma es `conflictos_visibles / objetos` fuera de rango y
`PARSER_FRAGMENT` creciendo.

## Tests de regresión

`tests/test_knowledge_conflict_quality.py` cubre los cinco casos del contrato:

| Caso | Esperado |
|---|---|
| `RECORD 2 – CATEG` vs `ORD 2 – CATEG` | PARSER_FRAGMENT, no conflicto |
| `FOR RECORD 2 – CATEGORY CONT` vs `Y CONT` | PARSER_FRAGMENT, no conflicto |
| `Category 31` vs `CAT 31` | ALIAS_VARIATION, no conflicto |
| `Fee = 100 USD` vs `Fee = 200 USD` (misma vigencia, fuentes distintas) | TRUE_CONFLICT potencial |
| vigencia 2025 vs 2026 | TEMPORAL_CHANGE, no conflicto |
