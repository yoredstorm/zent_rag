# P18.3-00 — Baseline reproducible, mapa de riesgo y congelación de contratos

- Fecha: 2026-10-29
- HEAD verificado: `3c97dfb4149e61a540641a69d86f676be883bee9`
- Rama: `master`
- Árbol al inicio: limpio (`git status --porcelain` vacío)
- Baseline histórico de la auditoría: el mismo SHA (no hay implementaciones P18.3 previas)
- Alcance: Conocimiento → Agente → Workflow. Sin SOÑAR, Dream Engine, reentrenamiento, autoaprendizaje ni promoción autónoma.

## 1. Veredicto

**Baseline verificable. Producción: NO-GO.**

No se encontró código P18.3. El repositorio ya contenía P18.2 y sus artefactos,
pero los pendientes de certificación seguían abiertos. Este baseline congela los
invariantes P0 y reproduce los defectos antes de corregirlos.

| Dimensión | Estado al inicio | Evidencia |
|---|---|---|
| HEAD y árbol | PASS | `3c97dfb`; árbol limpio |
| Migración | PASS | Alembic 174; código y DB alineados |
| Stack local | PASS | API/portal/Postgres/Qdrant/Redis/worker saludables |
| Proveedor LLM | DEGRADADO | Primario `403 NOT_ENOUGH_BALANCE`; fallback real respondió |
| Golden set | DRAFT | 40 preguntas preparadas, sin anotación humana |
| E2E con worker/PDF | NO EJECUTADO al inicio | Se ejecutó después en P18.3-07 |
| Cinco usuarios no técnicos | NOT_RUN | Sin sesiones de usabilidad |
| Paginación de evidencia | FAIL reproducido | Empate y NULL saltados por el cursor |
| Agente pinneado a workflow | FAIL reproducido | `_exec_llm` leía la fila viva del agente |
| Fuente histórica sin corpus | FAIL reproducido | 282 fuentes con `corpus_id IS NULL` |
| Answer Gate | DEGRADADO | `provider=skip` con `mode=on` en trazas reales |

## 2. Entorno reproducible

Comandos ejecutados (sin secretos):

```powershell
git rev-parse HEAD
git status --porcelain=v1
python --version
node --version
docker --version
docker compose version
docker compose ps
docker exec rag-postgres psql -U rag_user -d rag_platform -Atc "SELECT version_num FROM alembic_version;"
```

Valores observados:

- Python local: 3.11.16 (venv del repositorio); Python de contenedor: 3.11.17
- Node: v22.22.1; npm: 11.17.0
- Docker: 29.8.2; Compose: v5.6.0
- Migración inicial: `174`; migraciones nuevas: `175` (índice de paginación) y `176` (journal de backfill)
- Qdrant: colección `rag_documents`, 11.585 puntos, 11.616 vectores, estado `green`
- API: `/health` OK con Postgres, Qdrant, Redis y decision engine
- Worker de ingesta: activo
- Portal: `http://localhost:8080` OK

### Proveedor

Prueba mínima real con timeout corto:

```text
primary  openai/deepseek/deepseek-v4.1-flash  -> 403 NOT_ENOUGH_BALANCE
fallback openai/deepseek-ai/DeepSeek-V4.1-Flash -> ZENT_OK, 15 tokens, 2.698,8 ms
```

No se declara proveedor primario disponible. Las evaluaciones con LLM se
ejecutaron con fallback real y se etiquetan como tales.

### CI

Run `40926693734` de GitHub Actions: `SUCCESS`, 16 jobs verdes, SHA
`3c97dfb4149e61a540641a69d86f676be883bee9`. Un CI verde no cubre los E2E
saltados ni la revisión humana.

## 3. Inventario y contratos

### Rutas y servicios inspeccionados

- `src/api/routes/knowledge_workspaces.py`: corpus, chat acotado, insight, locate, archivo.
- `src/api/routes/sources.py`: upload, resolución de corpus, idempotencia, sesiones.
- `src/api/routes/agent_runs.py`: `/agents/{id}/run` y `/run/stream`.
- `src/api/routes/workflows.py` y `src/platform/workflows/`: definición, publicación, certificados, instancias, políticas y nodos.
- `src/platform/knowledge_sessions/{repository,service}.py`: sello durable y adjuntos idempotentes.
- `src/knowledge/understanding/{genre,passages,explorer}.py`: clasificación y propuestas.
- `src/knowledge/compiler/pipeline.py`: compilador canónico.
- `portal/src/pages/knowledge/{Explorer,Ask}.tsx`, wizard de importación y sesión de aprendizaje.
- `tests/fixtures/p18_2/questions.json`: 40 preguntas, estado `prepared_not_executed`.
- Certificados/artefactos P13–P18.2 y pipelines de `.github/workflows/{ci,nightly}.yml`.

### Contratos congelados

| Contrato | Autoridad | Invariante |
|---|---|---|
| Lectura de corpus | `GET /api/v1/knowledge/workspaces/{corpus_id}` | Solo fuentes de `organization_id + workspace_id + corpus_id` |
| Chat | `POST /api/v1/knowledge/workspaces/{corpus_id}/chat` | Sin fuentes ready no hay respuesta con conocimiento; nunca se cae al workspace completo |
| Insight | `GET .../sources/{source_id}/insight` | La fuente debe pertenecer al corpus y workspace; conteos declaran truncamiento |
| Evidencia | Ledger existente | Extracto, localizador, strength y citation ID de la misma fila |
| Sesión | `knowledge_sessions` | Sesión sellada no acepta fuentes; la carga derivada es explícita e idempotente |
| Agente | Agent Runtime | Identidad, propósito, perfil y fuentes efectivas quedan en la traza |
| Workflow publicado | `workflow_versions` + `workflow_certificates` | El grafo y el agente ejecutado corresponden a la revisión certificada |
| Publicación | `release_policy` | Sin certificado vigente no hay ejecución publicada nueva |
| ACL | RBAC + workspace + corpus + source | Fallar cerrado; un 404 no revela existencia de otro tenant |

## 4. Matriz de cobertura

| Superficie | Estado | Evidencia |
|---|---|---|
| Backend unitario | PASS selectivo | Suites P18.1/P18.2 + P18.3 |
| API integración | PASS | `test_p18_3_evidence_api.py`, `test_knowledge_workspaces_api.py` |
| PostgreSQL real | PASS | Tests de cursor, sesiones, backfill y workflow |
| Qdrant real | PASS para ingesta/retrieval | E2E PDF con worker real |
| Navegador | PASS | Playwright P18.2 y P18.3 |
| Proveedor LLM | PARCIAL | Fallback real; primario sin balance |
| Test humano | NOT_RUN | No hay anotadores ni usuarios reclutados |
| Caos | NOT_RUN | Sin ventana de perturbaciones |
| Seguridad adversarial | PARCIAL | Multi-tenant y ACL en tests; falta batería externa |
| Producción | NOT_RUN | No hay autorización ni ventana |

## 5. Hallazgos y orden causal

### P0 — bloqueantes

**P0-01. El workflow no pinneaba la configuración del agente.**
`_exec_llm` resolvía el agente por ID desde la fila viva. El fingerprint de
release solo guardaba número/estado de versión y rol, no la configuración
ejecutable. Editar el agente después de publicar podía cambiar la ejecución
publicada sin nueva certificación.

Reproducción: `test_published_definition_rejects_agent_edited_after_certification`
falló antes del arreglo (el certificado no exponía `agent_versions` en
`definition._certificate_row`, y el runtime no usaba snapshot). Corrección en
P18.3-09.

**P0-02. El cursor de evidencias omitía filas con empate o NULL.**
El `ORDER BY` era `strength DESC NULLS LAST, created_at DESC, id ASC`, pero el
predicado comparaba `(COALESCE(strength,0), created_at, id) < (...)`. Con tres
evidencias de igual `strength` y `created_at`, la primera página devolvía el ID
menor y la segunda quedaba vacía:

```text
old_page_1 -> 11111111-...-111111111111
old_page_2 -> 0 rows
```

Corrección en P18.3-06; el cursor nuevo es tipado, versionado y usa la
dirección correcta de cada columna.

**P0-03. 282 fuentes históricas no tienen corpus.**
`GET /workspaces/{corpus_id}/sources/{source_id}/insight` devuelve 404 porque
`_sources_for_corpus` filtra por `corpus_id`. Inventario local:

| Clase | Fuentes |
|---|---:|
| `corpus_id IS NULL` | 282 |
| Sin workspace | 83 |
| Con workspace y corpora candidatos | 199 |
| Con vínculo explícito único | 0 |

No se asigna ninguna automáticamente. La herramienta P18.3-04 produce plan,
journal, apply con CAS y rollback. El caso real de un tenant requiere
autorización: `BLOCKED_AUTHORIZATION` hasta que exista.

**P0-04. Respuesta entregada con verificación `blocked`.**
El agente podía entregar una respuesta correcta y, a la vez, publicar
`verification.overall = blocked` porque un Answer Gate skipped aportaba
`grounded=False` como si fuera un juicio. Esto rompía el contrato de lectura y
la confianza en el estado de verificación. Corrección y tests en P18.3-03.

### P1 — importantes

- **P1-01. Answer Gate no observado.** Las trazas reales muestran
  `answer_gate.verdict=skipped`, `provider=skip`, `mode=on`. La configuración
  local tenía `RAG_RUNTIME_JEV_SKIP_PHASES=answer_gate`, combinación marcada
  como peligrosa por `assert_runtime_config`. Se retiró el skip local y se
  documenta que el gate sigue dependiendo de la disponibilidad del motor JEV.
- **P1-02. Gold set sin revisión humana.** 40 casos preparados, 0 aprobados.
  `validate_goldset_v1 --strict-human` devuelve `BLOCKED_HUMAN_REVIEW`.
- **P1-03. Proveedor primario sin balance.** El fallback funciona; no se puede
  certificar el modelo primario.
- **P1-04. E2E de chat/visor PDF incompleto.** La ingesta PDF, sesión durable,
  Explorador, archivo autenticado y responsive pasan. La apertura de la página
  exacta resaltada en el visor y el chat dentro del E2E no se cubrieron en la
  misma prueba.
- **P1-05. Vertical comercial completo no ejecutado.** No hay
  `sales_vertical_e2e.spec.ts` con cinco turnos, WAIT/RESUME, carrito y efecto
  idempotente contra un sandbox.
- **P1-06. Caos y carga no ejecutados.** Sin reinicios de worker, Qdrant caído,
  Redis caído, 429/503 ni 10.001 evidencias en un entorno aprobado.

### P2 — deuda no bloqueante

- Medición de latencia del read model sigue siendo in-process.
- La UI necesita una prueba de usabilidad con cinco participantes.
- El informe de calidad narrativa 83,12 sigue siendo parcial; no mide
  comprensión ni recuperación.
- La documentación de capacidades vendibles debe separar sandbox de proveedor
  real.

## 6. Invariantes P0 congelados

1. Cero fugas entre organización, workspace, corpus, fuente y ACL, incluidas
   respuestas, propuestas, citas, logs y telemetría.
2. Cero efectos duplicados: reintentos, eventos y reanudaciones son idempotentes.
3. Ninguna ejecución de una versión de agente/workflow no autorizada o distinta
   de la certificada.
4. Ninguna cita, página, respuesta o métrica inventada. `NOT_RUN`/`BLOCKED` no
   se convierten en PASS.
5. Ningún dato histórico se pierde en backfill, reproceso o rollback.
6. Toda reversión es comprobable y no pisa cambios concurrentes.

## 7. Runbook mínimo

```powershell
# Estado
docker compose ps
docker exec rag-postgres psql -U rag_user -d rag_platform -Atc "SELECT version_num FROM alembic_version;"

# Tests P18.3
.venv\Scripts\python.exe -m pytest tests/test_p18_3_evidence_paging.py tests/test_p18_3_legacy_backfill.py tests/test_p18_3_agent_pinning.py tests/test_p18_3_goldset.py tests/test_p18_3_eval_harness.py tests/test_p18_3_verification_contract.py -q

# E2E real
$env:P18_3_E2E_INGEST="1"; $env:E2E_EXTERNAL="1"; $env:E2E_BASE_URL="http://localhost:8080"
cd portal; npm run e2e -- e2e/p18-3-e2e.spec.ts

# Backfill: primero plan, nunca apply sin checksum y aprobación
.venv\Scripts\python.exe -m src.scripts.legacy_source_corpus_backfill plan --org <org> --out artifacts/certification/p18-3/legacy_source_plan.jsonl
```

## 8. Artefactos

- `artifacts/certification/p18-3/baseline.json`
- `artifacts/certification/p18-3/flags_inventory.json`
- `artifacts/certification/p18-3/legacy_source_plan.jsonl` y `.sha256`
- `artifacts/certification/p18-3/legacy_source_plan_needs_resolution.jsonl`
- `artifacts/certification/p18-3/agent_certification.json`
- `artifacts/certification/p18-3/e2e/pdf-explorer-{390,1366}.png`
- `tests/fixtures/p18_3/{goldset_v1.jsonl,manifest.json,metamorphic_v1.json,rubric_v1.md,annotation_guide.md}`

## 9. Limitaciones del baseline

- La base local contiene datos de pruebas históricos; los conteos no son de
  producción.
- El caso `el_principito.pdf` local ya tiene `corpus_id`; la reproducción del
  404 se hizo con fuentes históricas sintéticas y con el inventario de las 282
  fuentes nulas.
- El proveedor primario no está disponible; toda métrica LLM es de fallback.
- El gold set está en `draft_not_approved`: no se declara calidad semántica
  certificada.
- La aprobación final requiere revisores humanos, cinco usuarios no técnicos,
  caos/carga y una ventana de producción.
