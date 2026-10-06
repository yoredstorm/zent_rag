# PDF Parser Engine — OpenDataLoader en shadow (Fase 1)

> Estado: **integración paralela, sin cutover**. `pdfplumber` sigue siendo el
> parser productivo por defecto. OpenDataLoader produce `StructuredDocument`
> nativo de ZENT y se evalúa con benchmarks estructurales y de conocimiento.
> Ninguna conclusión de "mejor parser" se toma en esta fase.

## 1. Arquitectura antes / después

Antes (único camino):

```
PDF -> PdfParser (pdfplumber) -> StructuredDocument
    -> Document Understanding -> Semantic Reconstruction -> Semantic Units
    -> Semantic Threads -> Knowledge Compiler -> Semantic Rule Compiler
    -> Canonical Objects -> Semantic Fabric -> Retrieval -> Premise Closure
```

Después (Fase 1, mismo contrato downstream):

```
PDF -> [ PDF Parser Engine ]
         |-- pdfplumber .........-> StructuredDocument (producción, default)
         |-- OpenDataLoader .....-> adapter -> StructuredDocument (evaluación)
         |-- shadow .............-> ambos; solo uno cruza a producción
    -> (cadena Knowledge OS sin cambios)
```

La frontera es `StructuredParser`. El resto de ZENT no importa
`opendataloader_pdf` ni conoce su JSON.

## 2. Componentes

| Ruta | Rol |
| --- | --- |
| `src/knowledge/structure/opendataloader_client.py` | Resolución de Java 11+, flags del CLI, ejecución por documento, JSON crudo + métricas de conversión |
| `src/knowledge/structure/opendataloader_mapping.py` | JSON OpenDataLoader -> `StructuredDocument` (bloques, páginas, secciones, tablas con celdas, figuras, bbox normalizado, provenance) |
| `src/knowledge/structure/opendataloader_parser.py` | `OpenDataLoaderPdfParser(StructuredParser)`; probe de alturas de página y de `StructTreeRoot` |
| `src/knowledge/structure/pdf_engine.py` | Selección de motor (`PDF_PARSER_MODE`) y `ShadowPdfParser` |
| `src/knowledge/parser_lab/comparison.py` | `DocumentParserComparison` (métricas estructurales por lado) |
| `src/knowledge/parser_lab/knowledge_ab.py` | Knowledge A/B offline: misma cadena Knowledge OS, sin persistencia |
| `src/knowledge/parser_lab/quality.py` | Calidad: soporte, duplicación, contradicción, orfandad, provenance, fragmentación, precision/recall vs expectativas |
| `src/knowledge/parser_lab/report.py` | Document Knowledge Coverage Report (brief §15) |
| `src/knowledge/parser_lab/serialize.py` | Artefactos shadow en JSON (documento de evaluación + comparación) |
| `src/scripts/parser_shadow_benchmark.py` | Benchmark CLI end-to-end |

### Provenance preservada

Cada bloque/tabla/página/sección conserva: `document/source identity`, `page`,
`bbox` (normalizado a origen top-left como pdfplumber, más `bbox_native`
bottom-left), `element_type`, `element_id`, `reading_order`, `page_order`,
`section_order`, `heading_path`/`section_path`, `heading_depth`, `table_id`,
`previous_table_id`/`next_table_id`, `parser_engine`, `parser_version`,
`parser_mode`, `structure_source` (`tagged_pdf` | `inferred_layout` | `hybrid` |
`ocr`). Las tablas conservan `headers`, `rows`, `cells` (row/column/span/
`is_header`/bbox/text/element_id), `merged_cells` y `caption`.

### Reading order y checks

Se respeta el orden de OpenDataLoader (XY-Cut++); ZENT no reordena. El adapter
emite warnings en `metadata["parser_warnings"]` para: order duplicado o no
monótono, element ids duplicados, texto repetido (candidato a chrome),
duplicación tabla+párrafo y solapamiento imposible (IoU > 0.9).

## 3. Configuración

```dotenv
# Motor productivo: pdfplumber | opendataloader | shadow
RAG_PDF_PARSER_MODE=pdfplumber

# Solo en shadow: quién continúa a producción (el otro se evalúa offline)
RAG_PDF_SHADOW_PRODUCTION=pdfplumber
RAG_PDF_SHADOW_DIR=            # vacío = <UPLOAD_DIR>/parser_shadow
RAG_PDF_SHADOW_ARTIFACTS=true

# OpenDataLoader
RAG_ODL_JAVA=                  # binario java 11+ (vacío: ODL_JAVA_HOME o PATH)
RAG_ODL_JAVA_HOME=
RAG_ODL_MODE=local             # local (determinista) | hybrid
RAG_ODL_USE_STRUCT_TREE=auto   # auto | always | never
RAG_ODL_TABLE_METHOD=default   # default | cluster
RAG_ODL_READING_ORDER=xycut
RAG_ODL_INCLUDE_HEADER_FOOTER=false
RAG_ODL_THREADS=1
RAG_ODL_TIMEOUT_SECONDS=180
```

En shadow, el `StructuredDocument` de evaluación **nunca** se persiste en
`structured_documents`, no se compila y no se indexa: se guarda como JSON en
`RAG_PDF_SHADOW_DIR` y se loguea el resumen de la comparación.

## 4. Cómo correr el benchmark shadow

```powershell
# Requisitos: pip install "opendataloader-pdf>=2.5.12" y Java 11+
$env:ZENT_ODL_JAVA = "C:\ruta\a\java.exe"   # solo para los tests
python -m src.scripts.parser_shadow_benchmark `
    C:\ruta\pdfs `
    --out data\reports\parser_shadow `
    --java "C:\ruta\a\java.exe" `
    --expectations tests\fixtures\parser_lab\atpco_fare_class.expectations.json
```

```bash
python -m src.scripts.parser_shadow_benchmark ./pdfs \
    --out data/reports/parser_shadow \
    --java "$JAVA_HOME/bin/java" \
    --expectations tests/fixtures/parser_lab/atpco_fare_class.expectations.json
```

Salidas: `report.json`, `report.md`, coverage reports por motor impresos y en
el JSON. Flags: `--engines both|pdfplumber|opendataloader`, `--no-knowledge`,
`--limit N`.

Variantes de Fase 2 sin editar `.env`:

```powershell
python -m src.scripts.parser_shadow_benchmark C:\ruta\pdfs --out data\reports\parser_lab_cluster `
    --java "C:\ruta\java.exe" --odl-table-method cluster

python -m src.scripts.parser_shadow_benchmark C:\ruta\pdfs --out data\reports\parser_lab_hybrid `
    --java "C:\ruta\java.exe" --odl-mode hybrid --odl-hybrid-url http://localhost:5002
```

`--odl-use-struct-tree auto|always|never` también disponible. El fingerprint de
la variante queda registrado en `report.json` (`odl_options`).

Tests:

```powershell
# unitarios (sin JVM)
pytest tests/test_opendataloader_adapter.py tests/test_opendataloader_parser.py `
       tests/test_pdf_engine_shadow.py tests/test_parser_lab_comparison.py `
       tests/test_parser_lab_knowledge_ab.py -q

# integración real (se salta sin Java 11+)
$env:ZENT_ODL_JAVA = "...\java.exe"
pytest tests/test_opendataloader_integration.py -q
```

## 5. Métricas iniciales (2 PDFs sintéticos, 1 página cada uno)

Medición local Windows con JRE 17 (la imagen worker usa JRE 21),
`opendataloader-pdf 2.5.12`, 2026-10-06.
Documentos: `fare_class_table.pdf` (título + párrafo + tabla con bordes) y
`manual_operaciones.pdf` (8 secciones numeradas con frases "must ...").

| Documento | Motor | s | s/pág | bloques | tablas | secciones | reglas canónicas | soportadas | threads |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fare_class_table | pdfplumber | 0.06 | 0.06 | 3 | 1 | 0 | 0 | 0 | 2 |
| fare_class_table | opendataloader | 2.83 | 2.83 | 3 | 1 | 1 | 0 | 0 | 2 |
| manual_operaciones | pdfplumber | 0.06 | 0.06 | 1 | 1 | 0 | 1 | 1 | 0 |
| manual_operaciones | opendataloader | 2.83 | 2.83 | 2 | 0 | 1 | 2 | 2 | 0 |

- Comparación estructural: `missing_reference_chars = 0` en ambos motores para
  ambos documentos; bbox coverage 1.0; pdfplumber confundió la página del manual
  con una tabla (`tables=1`, `blocks=1`), OpenDataLoader no (`tables=0`).
- Performance del benchmark completo (2 documentos, ambos parsers + Knowledge
  A/B offline): 6.74 s totales, 17.8 documentos/minuto, JSON de ODL 3.8 KB
  (1 página).
- La JVM domina el tiempo de OpenDataLoader (~2.8 s de startup + conversión por
  documento). `local` procesa rápido después del arranque; el costo por
  documento es casi constante para documentos chicos.
- Memoria medida: pico de allocations Python por parseo (`tracemalloc`). La
  memoria real de la JVM, CPU y concurrencia (`--threads`, pool de workers)
  quedan como medición de Fase 2 con corpus grande: no se optimiza antes de
  medir.

Estos números **no** deciden nada: son la línea base del experimento. La
decisión de Fase 2 requiere el corpus ATPCO real y documentos multi-página.

## 6. Problemas detectados

1. **JVM por documento**: el wrapper oficial lanza un proceso Java por
   `convert()`. Para lotes grandes conviene un proceso/servicio dedicado.
2. **Java 11+ no estaba instalado** en el host de desarrollo (solo Java 8).
   La imagen `worker` de Docker instala `openjdk-21-jre-headless`.
3. **Alturas de página**: el JSON de ODL no trae tamaño de página; el adapter
   abre el PDF con pdfminer (barato) para normalizar bbox. Si falla, conserva
   coordenadas nativas y lo advierte.
4. **Jerarquía de headings en local**: el layout devuelve todos los headings en
   nivel 1; el adapter infiere profundidad por numeración (`5.2`) o
   `level=Doctitle`, igual que pdfplumber. `--heading-hierarchy` es del servidor
   hybrid, no del modo local.
5. **Headers/footers**: por defecto ODL los filtra. El adapter puede pedirlos
   (`RAG_ODL_INCLUDE_HEADER_FOOTER=true`) para que el chrome detection de ZENT
   los vea y los marque; hoy el default usa el filtrado nativo.
6. **OCR**: el JSON no distingue si el texto vino de OCR; `RAG_ODL_FORCE_OCR`
   es una etiqueta operativa (`structure_source=ocr`) que el operador debe
   mantener en sincronía con el servidor hybrid.
7. **API con worker in-process**: si `RAG_BACKGROUND_INGESTION=true` y el modo
   PDF no es `pdfplumber`, la imagen de la API necesita `--target worker`
   (con JVM). Documentado en `Dockerfile.api`.
8. **`uv.lock`**: el extra `pdf-odl` se agregó a `pyproject.toml`; regenerar
   con `uv lock` en CI si el pipeline lo verifica.

## 7. Fase 2 en Docker

Todo el experimento corre en contenedores; nada depende del host.

**Imágenes**

- `Dockerfile.api --target api` (default): API sin JVM. Es lo que se construye
  si no se especifica target.
- `Dockerfile.api --target worker`: `openjdk-21-jre-headless` +
  `opendataloader-pdf`. Es la imagen de `ingestion-worker` y de `parser-lab`.
- Compose ya fija los targets: `api` para el servicio `api`, `worker` para
  `ingestion-worker` y `parser-lab`.

**Benchmark shadow one-shot**

```bash
# dev
docker compose --profile parser-lab run --rm parser-lab

# corpus propio y reportes propios
PARSER_LAB_CORPUS=/srv/corpus/atpco \
PARSER_LAB_REPORTS=/srv/reports/parser_shadow \
docker compose --profile parser-lab run --rm parser-lab

# prod
docker compose -f docker-compose.prod.yml --profile parser-lab run --rm parser-lab
```

El servicio monta el corpus en `/corpus:ro` y escribe `report.json`/`report.md`
en `/reports`. No toca Postgres, Qdrant ni Redis. El heap de la JVM se acota
con `PARSER_LAB_JAVA_OPTS` (default `-Xmx1g`); subirlo recién después de medir
documentos grandes.

Verificado en este repo (2026-10-06): `docker build --target worker` OK; dentro
del contenedor `java 21` y `opendataloader-pdf 2.5.12` disponibles; benchmark
in-container con los mismos números que el host; `docker compose --profile
parser-lab run --rm parser-lab` escribe `report.json` y `report.md`.

**Parser como componente dedicado (si se adopta ODL)**

Hoy: ODL corre dentro del worker, un proceso JVM por documento (~2.8 s de
startup). Si la Fase 2 adopta OpenDataLoader, el camino es reusar la imagen
`worker` como servicio dedicado de parsing (cola interna + pool de procesos
JVM o un servidor que mantenga la JVM caliente) para amortizar el arranque.
No se implementa en Fase 1 porque todavía no hay cutover.

**Hybrid (variable separada, no activada)**

El servidor hybrid es un componente aparte (`pip install "opendataloader-pdf[hybrid]"`,
`opendataloader-pdf-hybrid --port 5002`). Queda fuera del stack default: cuando
la Fase 2 lo evalúe, se agrega como servicio propio con perfil
`odl-hybrid` y se apunta el worker con `RAG_ODL_MODE=hybrid` +
`RAG_ODL_HYBRID_URL`. No se instala ahora para no inflar las imágenes
(dependencias de modelos/OCR).

**Kubernetes**

La imagen del worker se construye con `--target worker` (anotación
`zent.io/dockerfile-target` en `deploy/k8s/deployment-worker.yaml`). El mismo
target sirve para un Job de benchmark montando el corpus y un PVC de reportes.

## 8. Recomendaciones para la Fase 2

1. Correr el benchmark sobre el corpus ATPCO real completo (multi-página,
   tablas sin bordes, continuaciones, notas al pie) con `--expectations`
   por documento.
2. Decidir con las métricas de **conocimiento** (reglas soportadas/ejecutables,
   provenance, contradicciones, fragmentación) y no solo con extracción de
   texto.
3. Evaluar `cluster` para tablas sin bordes y hybrid (`docling-fast`) como
   segunda variable separada del modo local.
4. Si se adopta ODL, mover el parsing a un componente dedicado (pool de JVMs o
   servicio) para evitar el costo de startup por documento.
5. Recién entonces: cutover con `RAG_PDF_PARSER_MODE=opendataloader` y
   `pdfplumber` como rollback.

## 9. Fase P0 (benchmark de conocimiento)

La comparación científica por conocimiento (Golden Sets, KCS,
ZentPdfKnowledgeScore, umbral de migración, KnowledgeDiff, visual debug)
está en `docs/architecture/pdf-parser-benchmark-p0.md`. Resultado actual:
`D_NEED_MORE_DATA` (sin cutover). Artefactos en
`artifacts/pdf-parser-benchmark/`.
