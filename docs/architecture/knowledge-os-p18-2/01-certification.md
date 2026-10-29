# P18.2 — Certificación del Explorador y puertas de release

- Fecha: 2026-10-29
- Rama: `p18.2-knowledge-understanding`
- Baseline: `8a2d7c46907d51faf18a21e0de86c9b6ba411ae9`
- Implementación: `19aa5ebff513c4f0ebf69232c6eacb02076c497b`
- Certificación: `a6a93a88ac9cfe924acb55572a228e0796bfa7ad`
- Release candidate (código): `f0cc145539b592bc83204929ba27accb0ee09d0d`
- Alcance: P18.2-00 a P18.2-10. P18.2-11 es este informe.
- Exclusión respetada: SOÑAR, Dream Engine, memoria paralela, aprendizaje
  autónomo, promoción automática de inferencias.

## 1. Veredicto

**Release A/B/C: CONDITIONAL. Producción: NO-GO.**

Motivo: las puertas P0 están verdes en pruebas reproducibles, pero faltan dos
requisitos de certificación que no se pueden simular:

1. La fuente histórica `el_principito.pdf` **no tiene `corpus_id`**, por lo que
   el endpoint por corpus no la alcanza sin un backfill autorizado. El read
   model se verificó directamente contra la base de staging.
2. No se ejecutó E2E con worker/PDF real ni prueba con cinco usuarios no
   técnicos en este entorno. Se declaran **SKIP**, no PASS.

No se declara GO de producción hasta cerrar esos dos puntos y revisar
humanamente una muestra de propuestas narrativas.

## 2. Matriz PASS / FAIL / SKIP

| Área | Escenario | Resultado | Evidencia |
|---|---|---|---|
| Baseline | Reproducir 110 objetos → 0 visibles → 110 ocultos | PASS | `artifacts/certification/p18-2/baseline.json` |
| Extracción | El PDF no se modifica; 1.045 bloques, 104 páginas, 8 secciones | PASS | consultas SQL en `00-baseline.md` |
| Explorador | Vista documento no dispara listado técnico | PASS | `Explorer.test.tsx` (8 tests) |
| Explorador | Vista técnica etiquetada, ocultos solo con permiso | PASS | `Explorer.test.tsx` |
| Explorador | 110 históricos no reaparecen como temas naturales | PASS | propuestas separadas + `verification_state=proposed` |
| Sesiones | Sesión sellada rechaza `add_source` | PASS | `test_p18_2_session_integrity.py` |
| Sesiones | Carrera seal/attach no deja fuente en lote cerrado | PASS | test de concurrencia real |
| Sesiones | Reintento idempotente no duplica fuente | PASS | `attach_is_idempotent_by_key` |
| Sesiones | Upload a sesión sellada abre lote derivado | PASS | `_open_learning_session` test |
| Read model | 1.001 objetos reporta total 1.001 y truncamiento | PASS | `test_p18_2_read_model.py` |
| Read model | Evidencia más fuerte gana, no la más reciente | PASS | `test_p18_2_read_model.py` |
| Read model | Varios documentos por fuente se cuentan | PASS | `test_p18_2_read_model.py` |
| Género | Narrativa con números/preguntas no es técnico | PASS | matriz 6/6 en `test_p18_2_genre.py` |
| Género | Manual técnico conserva campos/máscaras | PASS | `technical_manual.txt` |
| Género | Documento mixto declara segmentos | PASS | `mixed_policy_technical.txt` |
| Género | OCR ruidoso/vacío → `unknown`, no técnico | PASS | `noisy_pdf_text.txt`, `empty.txt` |
| Pasajes | Personajes con atribución de diálogo y cita | PASS | `test_p18_2_passages.py` |
| Pasajes | Cero personajes inventados en manual técnico | PASS | `test_p18_2_passages.py` |
| Resumen | Documento sin objetos canónicos muestra estructura y pasajes | PASS | `after.json` |
| Resumen | Limitaciones y evaluación no declarada | PASS | `limitations`, `evaluation_state` |
| Grafo | Aristas no verificadas con estilo y estado | PASS | `Explorer.test.tsx` |
| Grafo | Filtro por fuente + ocultos | PASS | `fetchKnowledgeGraph` + API |
| Histórico | Clasificación dry-run por categoría | PASS | `test_p18_2_cleanup.py` |
| Histórico | Shadow reprocess en copia autorizada | SKIP | no se ejecutó en este entorno |
| Histórico | Backfill de `corpus_id` para el caso real | SKIP | requiere decisión/autorización |
| UX | Copy humano, CTA único, responsive CSS | PASS | tests de UI |
| UX | Cinco usuarios no técnicos | SKIP | sin sesiones de usabilidad |
| Métricas | “Comprensión semántica” renombrada | PASS | `test_p18_2_metrics.py` |
| Métricas | Libro narrativo no se castiga por reglas de negocio | PASS | `scoring_profile=narrative`, 37→83 parcial |
| Extracción | Diálogos/secciones de novela no se vuelven entidades | PASS | `test_p18_2_narrative_entities.py` |
| Métricas | 40 consultas preparadas (10/familia) | PASS (fixture) | `questions.json`; no ejecutadas |
| Métricas | Evaluación de comprensión versionada | SKIP | no existe dataset humano |
| Seguridad | Aislamiento org/workspace/corpus | PASS | `test_p18_1_corpus_scope.py` |
| Seguridad | Cross-tenant/ACL/revocación E2E | SKIP | E2E no ejecutado |
| E2E | Flujo real upload → indexado → abrir → preguntar | SKIP | `P18_2_E2E_INGEST` no configurado |
| Docker | Imágenes reconstruidas y API/portal sirviendo código nuevo | PASS | verificación 2026-10-29 |
| Regresión | Suites P18.1/P18.2 backend | PASS | 80 tests |
| Regresión | Suites portal knowledge | PASS | 28 tests |
| TypeScript | `tsc --noEmit` | PASS | sin salida |
| Lint | ESLint archivos tocados | PASS | sin errores |

## 3. Antes / después medido

| Métrica | Antes | Después | Nota |
|---|---:|---:|---|
| Objetos canónicos | 110 | 110 | Sin borrar ni reescribir |
| Objetos visibles como conocimiento | 0 | 0 | Correcto: no se promueve basura |
| Propuestas desde pasajes | 0 | 22 | 12 personajes + 10 temas |
| Secciones estructuradas mostradas | 0 | 6 | 8 originales; se filtran ruido/duplicados |
| Pasajes abribles disponibles | 215 | 215 | No se alteró la fuente |
| Pasajes seleccionados para UI | 0 | 10 | Acotado |
| Género | `unknown` histórico | `unknown` | Requiere reprocess, no se finge |
| Latencia read model | no medía | p50 78,5 ms / p95 93,3 ms | 5 corridas, sin I/O DB |
| Citas fabricadas | 0 conocidas | 0 | Toda propuesta tiene excerpt textual |

La latencia es una muestra pequeña (n=5) y no incluye la consulta a Postgres.
No se presenta como p95 de producción.

## 4. Comandos ejecutados

```powershell
# Backend
.\.venv\Scripts\python.exe -m pytest `
  tests\test_p18_1_explorer.py tests\test_p18_1_genre.py `
  tests\test_p18_1_candidates.py tests\test_p18_1_cleanup.py `
  tests\test_p18_1_corpus_scope.py tests\test_p18_1_upload_corpus.py `
  tests\test_p18_2_session_integrity.py tests\test_p18_2_read_model.py `
  tests\test_p18_2_genre.py tests\test_p18_2_passages.py `
  tests\test_p18_2_cleanup.py tests\test_p18_2_metrics.py `
  tests\test_knowledge_sessions.py -q
# 80 passed

.\.venv\Scripts\python.exe -m pytest tests\test_p18_2_certification.py -q
# 6 passed

# Portal
cd portal
npx tsc --noEmit
npx vitest run src/pages/knowledge/Explorer.test.tsx `
  src/pages/knowledge/SourceDetail.test.tsx src/pages/knowledge/Ask.test.tsx `
  src/pages/knowledge/Home.test.tsx src/pages/knowledge/Quality.test.tsx `
  src/pages/knowledge/ObjectView.test.tsx src/pages/knowledge/Map.test.tsx
# 28 passed
```

E2E previsto (no ejecutado en este entorno):

```powershell
$env:P18_2_E2E_INGEST="1"
cd portal
npx playwright test e2e/p18-2-explorer.spec.ts
```

## 5. Hallazgos abiertos

### Bloqueante de certificación

1. **Fuente histórica sin corpus.** `kb_sources.corpus_id` es `NULL` para
   `298fdc37-...`. El endpoint `/workspaces/{corpus}/sources/{source}/insight`
   responde 404. El caso se verificó por lectura directa, no por la ruta de UI.
   Requiere backfill autorizado o una ruta de migración no destructiva.
2. **E2E con worker/PDF real no ejecutado.** No se declara PASS.
3. **Prueba de usabilidad con cinco usuarios no ejecutada.** No se declara PASS.

### Limitaciones conocidas

- Las propuestas narrativas son heurísticas (`heuristic-passage-v1`). No se
  evaluó su precisión/recall con anotación humana; por eso se muestran como
  “Propuesta desde pasajes”, nunca como hechos.
- El perfil histórico no tiene `document_genre`; el género sigue `unknown`
  hasta reprocesar en sandbox.
- Los temas propuestos pueden incluir roles secundarios (“Eco”, “Anciano”).
  Son menciones reales, pero su utilidad debe revisarse.
- El resumen sigue empezando con “Solo se identificaron secciones y pasajes”.
  Es correcto: no hay objetos canónicos visibles, solo propuestas.
- El grafo de una narrativa histórica puede quedar vacío si no hay
  `knowledge_edges`; las propuestas no se escriben como aristas canónicas.
- No se añadió LLM de enriquecimiento. Sin evaluación humana no se promete
  semántica profunda.

## 6. Rollback operativo

1. Volver al SHA `8a2d7c46907d51faf18a21e0de86c9b6ba411ae9` (release anterior)
   o revertir los commits de la rama.
2. Migración `174_learning_session_attach_idempotency.py`:
   `alembic downgrade 173` elimina `idempotency_key` y su índice. No borra
   fuentes, sesiones ni objetos.
3. Si se ejecutó `explorer-cleanup` en staging, restaurar con:
   `POST /api/v1/knowledge/maintenance/explorer-cleanup`
   `{"dry_run": false, "action": "restore"}`.
   No se ejecutó en este entorno, así que no hay metadatos ocultos por P18.2.
4. El read model es stateless: al volver el código anterior, el Explorador
   recupera la vista previa sin migración de datos.
5. No hay cambios en documentos originales, objetos canónicos, agentes,
   workflows, policies, ACL ni facturación.

## 7. Verificación Docker local

El stack local estaba atrasado: `rag-portal` no contenía `Qué contiene este
documento` y `rag-api` no contenía `build_passage_understanding` ni la
migración `174`. Se reconstruyeron `api`, `ingestion-worker` y `portal`.

Verificación posterior:

```powershell
docker compose build api ingestion-worker portal
docker compose up -d api ingestion-worker portal
docker exec rag-portal sh -lc "grep -Rl 'Qué contiene este documento' /usr/share/nginx/html"
docker exec rag-api sh -lc "grep -Rl 'build_passage_understanding' /app/src"
docker exec rag-postgres psql -U rag_user -d rag_platform -c "\d knowledge_learning_session_sources"
```

Resultado:
- Portal contiene el bundle nuevo.
- API contiene `passages.py` y migración `174`.
- Columna `idempotency_key` existe.
- Flujo real por API: signup, corpus, upload, indexado, `GET .../insight` → 200,
  contrato `knowledge_explorer_insight/v2`, género `technical`,
  `document_type=technical_specification`.
- Bug encontrado y corregido: cursor de objetos con `:cursor IS NULL` producía
  `AmbiguousParameterError` en asyncpg. Fix `f0cc145`, regresión
  `test_p18_2_insight_sql.py`.

## 8. Perfil narrativo y reproceso del libro

El caso reportado (`37/100` en un libro) se reprodujo y corrigió.

Antes:
- 109 objetos canónicos, 108 sin descripción.
- 1 regla, 0 métricas, 0 verificados, 2 relaciones.
- Score 37: promedio de señales de negocio, incluyendo `Reglas y métricas = 0`
  y `Validación humana = 0`, que no aplican a una novela.

Después:
- Se impidió que secciones/diálogos narrativos se promuevan a entidades.
- Reproceso local con purga de conocimiento del compilador y reingesta del PDF.
- Resultado: **0 objetos canónicos basura**, 6 secciones, 10 pasajes,
  22 propuestas (12 personajes + 10 temas).
- Health: `scoring_profile=narrative`, `overall=83.12` **parcial**,
  2 de 11 señales medidas, 5 no aplican.
  - Calidad de extracción: 73.
  - Estructura reconocida: 100.
  - Evidencia canónica: no medida (0 evidencias canónicas).
  - Reglas/métricas, descripciones, relaciones y conflictos: no aplican.
- El PDF original no se modificó. Backup de objetos previos:
  `artifacts/certification/p18-2/principito-before-reprocess.json`.
- Evidencia: `artifacts/certification/p18-2/narrative-quality-after.json`.
- Capturas: `quality-narrative-1366.png` y `quality-narrative-390.png`
  (sin overflow horizontal en 390 px).

Comando ejecutado:

```powershell
.\.venv\Scripts\python.exe -m src.scripts.knowledge_reprocess `
  --org e42d1f42-b87d-4baf-88dc-ec3da1541239 `
  --source da12dc0a-12c9-4a46-95f7-ab19d9c573e7 `
  --purge --requeue
```

El 83 no significa “comprensión 83%”. Es calidad documental parcial:
extracción y estructura. La evidencia canónica y la recuperación siguen
`No medido`.

## 9. Decisión por fase

| Fase | Estado | Condición |
|---|---|---|
| 00 Baseline | GO | — |
| 01 Modos Explorador | PASS | E2E de navegador pendiente |
| 02 Sesión/reintento | PASS | E2E dos pestañas pendiente |
| 03 Read model | PASS | Medir con 10.000 objetos en staging |
| 04 Género | PASS | Matriz 6/6; ampliar corpus anotado |
| 05 Pasajes | CONDITIONAL | Revisión humana de precisión |
| 06 Resumen | CONDITIONAL | Evaluación de fidelidad de citas |
| 07 Grafo | CONDITIONAL | E2E click nodo → PDF |
| 08 Histórico | CONDITIONAL | Backfill corpus + shadow reprocess |
| 09 UX | CONDITIONAL | Cinco usuarios |
| 10 Métricas | CONDITIONAL | Dataset de evaluación versionado |
| 11 Certificación | CONDITIONAL | Cerrar bloqueantes |

**GO de producción: NO.** Mantener NO-GO hasta cerrar los tres bloqueantes y
repetir esta matriz con E2E real, worker y usuarios.
