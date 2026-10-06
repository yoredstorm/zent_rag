# PDF Parser Knowledge Benchmark — Fase P0

> Pregunta central: después de ingerir exactamente el mismo PDF, ¿qué parser
> permite que ZENT **conozca, conecte, recupere y aplique** más información
> correcta? La métrica principal no es parsing.

Artefactos: `artifacts/pdf-parser-benchmark/summary.json`,
`artifacts/pdf-parser-benchmark/report.md`, `corpus/`, `golden/`,
`visual_debug/`. Golden Sets versionados en `tests/fixtures/pdf_benchmark/golden/`.

## 1. Diseño

- **Pipeline A** y **Pipeline B** idénticos desde `StructuredDocument`:
  Document Understanding, Semantic Reconstruction, Semantic Units, Semantic
  Threads (planner/extractor), Knowledge Compiler y Semantic Rule Compiler.
  Sin DB, sin LLM, sin persistencia.
- **Golden Knowledge Set** por documento: objetos con tipo semántico, meaning,
  páginas, sección, propiedades, relaciones, ejecutabilidad, premisas
  requeridas y formulaciones equivalentes; más queries con respuesta esperada.
- **Matching semántico** determinista por needles (equivalents + properties),
  umbral 0.75. Símbolos puros (`&`) se comparan en crudo.
- **Corpus A-L** generado determinísticamente por código (sin binarios en git):
  manual grande, muchas tablas, contrato, procedimiento, política,
  multi-columna, tagged, fixed-width, reglas distribuidas, ruido
  headers/footers, escaneado (pendiente hybrid/OCR, se reporta skipped),
  fórmulas y ATPCO real de regresión.
- **KCS (Knowledge Completeness Score)**: pesos documentados en
  `src/knowledge/parser_lab/p0/scoring.py`. Positivos suman 1.00; los negativos
  penalizan conocimiento falso más fuerte que el faltante:
  false rules −0.30, contradicciones −0.20, hallucinations −0.20,
  fragmentación −0.10.
- **ZentPdfKnowledgeScore**: prioriza correctness (rule precision 0.30,
  rule recall 0.20, premise coverage 0.15, answer accuracy 0.10, retrieval
  0.10, determinismo 0.05, provenance 0.05, estructura 0.03, performance 0.02).
  Performance tiene gate operativo: > 5 s/página = inviable.
- **Umbral de migración** (§22): si baja knowledge precision o rule precision,
  o suben hallucinations, el verdict es KEEP. Si mejora conocimiento sin
  empeorar precisión y performance es viable, ADOPT. Evidencia mixta =
  NEED_MORE_DATA. Hybrid selectivo = tercera columna opcional.

## 2. Cómo correr

```bash
python -m src.scripts.pdf_knowledge_benchmark \
    --out artifacts/pdf-parser-benchmark \
    --java "$JAVA_HOME/bin/java" \
    --large-pages 120 \
    --consistency-runs 100
# tercera columna (servidor hybrid aparte):
python -m src.scripts.pdf_knowledge_benchmark --out artifacts/pdf-parser-benchmark --hybrid
```

En Docker: `docker compose --profile parser-lab run --rm parser-lab` con el
comando del script P0 (imagen worker con JVM).

## 3. Resultado agregado (13 documentos + manual de 120 páginas, 2026-10-06)

| Score | pdfplumber | OpenDataLoader local |
| --- | ---: | ---: |
| Knowledge Completeness Score | 0.7096 | **0.7493** |
| ZentPdfKnowledgeScore | 0.7116 | **0.7617** |
| Performance viable | sí | sí |

Gana OpenDataLoader (KCS +0.040, ZPKS +0.050), pero el verdict del umbral es
**`D_NEED_MORE_DATA`** por regresiones en métricas operativas críticas.

Métricas donde gana OpenDataLoader:

| Métrica | pdfplumber | ODL |
| --- | ---: | ---: |
| Heading Accuracy | 0.4479 | **0.6042** |
| Semantic Unit Precision | 0.9532 | **1.0000** |
| Exception Recall | 0.0000 | **0.6667** |
| Knowledge Precision | 0.6247 | **0.7542** |
| CanonicalRule Precision | 0.8236 | **0.9167** |
| False Rule Rate | 0.1764 | **0.0833** |
| Recall@K | 0.3889 | **0.4722** |
| MRR | 0.3096 | **0.3517** |
| Irrelevant Evidence Ratio | 0.8961 | **0.8498** |
| Duplicate Rate / Chrome | 0.3077 | **0.0000** |

Métricas donde gana pdfplumber:

| Métrica | pdfplumber | ODL |
| --- | ---: | ---: |
| CanonicalRule Recall | **0.8889** | 0.8611 |
| SUPPORTED Rate | **0.8750** | 0.8472 |
| Answerable With Evidence | **0.9744** | 0.9167 |
| False Abstention Rate | **0.0449** | 0.0833 |
| Formula Recall | **0.5000** | 0.0000 |
| Consistency Rate | **1.0000** | no evaluable |
| Segundos/página (docs chicos) | **0.0689** | 1.1970 |
| Segundos/página (manual 120 pág.) | 0.1221 | **0.0640** |

Ambos en 0: Deterministic Decision Rate, Fact Recall, Relationship Recall,
Cross-page Stitch Accuracy, Cross-page Evidence Recovery, Premise Retrieval
Recall. Eso apunta a brechas **downstream del parser** (Rule Compiler y
stitching), no a una ventaja de un parser sobre el otro.

## 4. Diagnóstico ATPCO (§15)

Premisas requeridas para el patrón `&&&F` con valor `ABCFGEGE`:
`symbol.definition`, `matching.operator`, `length.policy`.

- pdfplumber: 3/3 premisas adquiridas.
- OpenDataLoader: 3/3 premisas adquiridas.
- Ninguno produce una `CanonicalRule` completa y ejecutable que matchee el
  golden posicional; ninguno llega a `DerivedClaim` (deterministic decision
  rate 0.0 en ambos).

Conclusión diagnóstica: la fuente entrega las premisas, pero el Semantic Rule
Compiler todavía no las compila a una regla ejecutable para este caso. Es un
hallazgo de Fase P0, no una excepción de dominio ni un hardcode.

## 5. Documento grande (§23)

Manual de 120 páginas: ODL 7.68 s (0.064 s/página) vs pdfplumber 14.65 s
(0.122 s/página). JSON ODL 370 KB. Provenance mejoró en 120 objetos
(`PROVENANCE_IMPROVED: 120`, 0 regresiones). En documentos chicos la JVM
domina (2.3-4.3 s por documento), por eso el servicio dedicado con pool JVM
sigue siendo la recomendación operativa si se adopta.

## 6. KnowledgeDiff

- `manual_tecnico_grande`: 21 `PROVENANCE_IMPROVED` (ODL), 0 regresiones.
- `manual#large`: 120 `PROVENANCE_IMPROVED`, 0 regresiones.
- `politica`: 3 mejoras de provenance; `contrato`: 2 mejoras y 2 regresiones;
  `fixed_width`: 1 objeto que pdfplumber tiene y ODL no; `distribuidas`/`atpco`:
  4 `ADDED_FALSE` cada uno (objetos producidos que no matchean golden).
- Sin `ADDED_CORRECT` netos: los dos parsers adquieren el mismo conocimiento
  en la mayoría del corpus; la diferencia está en precisión y provenance.

## 7. Limitaciones de esta fase

1. Corpus sintético controlado, no documentos reales de producción.
2. Matching sin LLM: si una formulación no comparte needles, se considera no
   match (los `allowed_formulations` y equivalents lo acotan).
3. Golden Sets son completos para el contenido de conocimiento del corpus
   controlado; en corpus reales habría que ampliarlos.
4. `escaneado` (K) queda pendiente: requiere hybrid/OCR, fuera de la
   comparación local.
5. La consistencia de ODL no es evaluable porque ninguna query ejecutable
   matcheó una regla ejecutable suya; el determinismo real se medirá cuando el
   Rule Compiler cierre esa brecha.
6. Hybrid no se ejecutó (no hay servidor levantado); la columna queda lista.

## 8. Recomendación final (§24)

**D. NEED MORE DATA — no hacer cutover todavía.**

Razones basadas en métricas:

1. ODL mejora conocimiento (KCS/ZPKS), precisión (Knowledge 0.75 vs 0.62,
   CanonicalRule precision 0.92 vs 0.82), retrieval (Recall@K 0.47 vs 0.39) y
   elimina contaminación de chrome/duplicados (0 vs 0.31), sin aumentar
   hallucinations (0.0 ambos).
2. Pero **regresiona** en CanonicalRule Recall (0.861 vs 0.889), false
   abstention (0.083 vs 0.045), answerable-with-evidence (0.917 vs 0.974),
   Formula Recall (0 vs 0.5) y su consistencia no es evaluable.
3. Ninguno de los dos produce decisiones deterministas sobre queries
   ejecutables: el cuello de botella hoy es la compilación de premisas
   (matching posicional, length policy, fórmulas) en el Rule Compiler.

Camino para convertir D en decisión firme:

1. Cerrar la brecha de compilación de premisas (downstream, independiente del
   parser) y volver a correr el benchmark: debería aparecer deterministic
   decision rate > 0 y consistency evaluable.
2. Sumar el corpus ATPCO real multi-página y el PDF escaneado con Hybrid como
   tercera columna (no mezclado con local).
3. Repetir sobre documentos reales de producción (no sintéticos).
4. Recién entonces aplicar el umbral §22. Hoy ODL está mejor posicionado en
   precisión y recuperación, pero la migración no está justificada todavía.
