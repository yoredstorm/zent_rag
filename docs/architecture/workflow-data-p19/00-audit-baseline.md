# P19-00 — Auditoría dirigida, matriz AS-IS/TO-BE y baseline reproducible

- **Estado:** COMPLETADO (auditoría y reproducción; sin cambios de runtime).
- **Fase:** P19-00. No implementa P19-01 ni posteriores.
- **Alcance:** inventario comprobado de rutas ejecutables, binder SQL, Managed DB,
  conectores, catálogo, API, portal, permisos y UX de consulta de datos.
- **Naturaleza:** no es una certificación de producción ni un PASS de seguridad.
  Los hallazgos P0 se reproducen como tests rojos y bloquean P19-01.

## 1. Identidad y reconciliación del baseline

| Dato | Valor |
|---|---|
| Repositorio | `https://github.com/yoredstorm/zent_rag` |
| Baseline solicitado | `47fa8a09fa9f99ab7d77aa9ae555aa3528169253` (master) |
| HEAD observado al iniciar | `9b8641c967cfdb5d04081187d5fa21b23ffcc838` |
| Rama observada | `perf/ci-optimization` |
| Relación | `47fa8a09` es ancestro de `9b8641c9`; 9 commits adelante |
| Diff `47fa8a09..9b8641c9` | 18 archivos, solo CI, docs de CI, `.test_durations`, `scripts/cert/*`, `scripts/ci/*`, tests de evidencia CI y un ajuste de unmount del portal |
| Cambios de runtime de workflows | Ninguno |
| Rama P19 creada | `feat/p19-workflow-data-orchestration` desde `master` (`47fa8a09`) |
| Commits P19-00 | `597df9f` (tests rojos), `face0d0` (documentación) |
| Árbol de trabajo inicial | limpio |
| Fecha de auditoría | 2026-11-01 |

**Reconciliación:** el HEAD de la sesión no era el baseline. Se verificó que el
delta era exclusivamente de optimización de CI y no tocaba `src/platform/workflows`,
`src/connectors`, `src/api/routes/workflows.py` ni el motor. Para evitar mezclar
P19 con una rama de CI no fusionada, P19 se ramifica desde `master` en
`47fa8a09`. El commit de evidencia final debe declarar esta base.

### Estado P18.5 heredado

| Dato | Valor |
|---|---|
| Documento | `docs/architecture/workflow-p18-5/14-final-go-no-go.md` |
| Decisión | `GO_LOCAL_DEV` |
| P0 de P18.5 | Cerrados según sus pruebas (snapshot, workspace, aprobación, revocación, idempotencia local) |
| P1 abiertos | E2E adversarial incompleto, usuario real NOT_RUN, rendimiento/SLO NOT_RUN, suite completa NOT_RUN |
| STOP de expansión | Vigente en el documento: no autoriza orquestación avanzada hasta cerrar P18.5-12/13/14 |

P19-00 es una fase de **auditoría read-only**. No contradice el STOP: no amplía
el producto ni publica workflows. La habilitación de P19-03 en adelante requiere
aceptación explícita de este baseline y de la ADR de P19-01.

### Baseline de CI

| Evidencia | Valor |
|---|---|
| Workflow CI | run `498`, id `41275455559`, commit `47fa8a09`, conclusión `success` |
| Jobs | 16/16 success: `secrets-scan`, `kustomize`, `test (1/4..4/4)`, `test`, `certification`, `portal`, `portal-e2e`, `lint`, `pip-audit`, `build`, `sdk-node`, `sdk-python`, `test-evidence` |
| Nightly | run `20`, id `41279316169`, commit `47fa8a09`, `success` |
| Límite | CI verde no acredita proveedores externos ni datos reales; solo regresión del repositorio |

## 2. Método y ambiente

- Lectura de código y trazas de autoridad, no inferencia por nombres de archivo.
- Pruebas adversariales nuevas en `tests/test_workflow_data_p19_audit.py`.
- Prueba AS-IS del canvas en `portal/src/lib/workflowGraph.p19.test.ts`.
- Consultas de metadatos a PostgreSQL local (solo conteos y catálogo; sin PII).
- Verificación de runs de GitHub Actions vía API pública.

| Herramienta | Versión |
|---|---|
| Python (`.venv`) | 3.11.16 |
| Node | v22.22.1 |
| pnpm | 9.4.0 |
| Docker | 29.8.2 |
| PostgreSQL | 16.15 |
| Servicios | `rag-postgres`, `rag-redis`, `rag-qdrant`, `rag-api` (healthy), `rag-portal` (healthy) |

No se usaron credenciales de clientes, proveedores financieros ni datos reales.
Las sesiones SQL de las pruebas son dobles que solo registran el statement.

## 3. Inventario comprobado

### 3.1 Runtime y nodos

| Componente | Ubicación | Comportamiento comprobado | Clasificación |
|---|---|---|---|
| Registro de nodos | `src/platform/workflows/nodes.py:175` | `NodeRegistry`; tipo desconocido falla en runtime | EXISTE |
| Ejecución de nodo | `src/platform/workflows/runtime.py:401` | resuelve `registry.get(node.type)`, persiste `workflow_run_steps` | EXISTE |
| `query_business_data` | `nodes.py:3007` | pregunta libre → orquestador RAG; devuelve `rows`, `columns`, `sql_query`, `answerability`, `evidence` | EXISTE, semántica distinta a SELECT |
| `capability_call` | `nodes.py:3708` | capacidad lógica → `execute_binding`; `inputs` es un dict libre validado solo por contrato | EXISTE |
| `ai_decision` | `nodes.py:2722` | JEV/decision engine; salida tipada con confianza y `judge_error` | EXISTE |
| `adaptive_route` | `nodes.py:4266` | decisión policy-driven, no ejecuta capacidades | EXISTE |
| `wait_event` | `nodes.py:3407` | WAIT durable con correlación/timeout; reanuda por señal | EXISTE |
| `subworkflow_call` | `nodes.py:4365` | snapshot congelado, idempotencia por efecto | EXISTE |
| Persistencia de pasos | `runtime.py:146` | guarda `input=config` y `output` JSON sin redacción | RIESGO |
| Rol en consulta semántica | `nodes.py:3037`, `bindings.py:610` | fuerza `role="admin"` aunque el actor sea otro | RIESGO P1 |

### 3.2 Binder SQL (`src/platform/workflows/bindings.py`)

| Línea | Comportamiento | Clasificación |
|---|---|---|
| `638` | `_execute_managed_select` es el único executor SQL declarativo | EXISTE |
| `648` | `config = {**binding.config, **payload}`: el payload sobrescribe tabla, columnas, filtros, orden y límite | **P0** |
| `652` | `columns` default `["*"]`; acepta `*` desde config o payload | **P0** |
| `656-671` | filtros solo desde config fusionado; operador desconocido cae a `=` | **P0** |
| `672-680` | `order_by` desde config/payload; identificador validado, columna no autorizada | P1 |
| `682` | límite global 500; no respeta `max_rows` del binding | P1 |
| `685-688` | SQL por concatenación de identificadores validados + bindparams | EXISTE (parametrizado) |
| `689-700` | sesión Managed DB; no hay timeout, dispose ni presupuesto | P1 |
| `408-409` | `connected_db` se despacha a `_execute_managed_select` | **P0** |
| `589-629` | `semantic_query` usa el pipeline RAG y devuelve `sql_query` | EXISTE, no es SELECT directo |
| `292-383` | `execute_binding` resuelve binding vivo, valida contrato y dispatch | EXISTE |
| `194-226` | `resolve_binding`: workspace exacto → fallback org-level sin concesión explícita | **P0** |

No existe `get_one`, `count`, agregación tipada, `MULTIPLE_MATCHES`, `data_as_of`,
`truncated`, `binding_hash`, `source_ref` ni `provenance` en la salida SQL.

### 3.3 Managed DB y descubrimiento

| Componente | Ubicación | Comportamiento | Clasificación |
|---|---|---|---|
| Managed DB | `src/platform/managed_db/service.py:285` | abre sesión con `query_reader_user`, `default_transaction_read_only=on` | EXISTE (positivo) |
| Selección de DB | `service.py:292-301` | filtra organización y, si hay workspace, workspace; si no, toma la última DB de la organización | **RIESGO P0** en runs legacy sin workspace |
| Engine por consulta | `service.py:318-326` | `create_async_engine(pool_size=1)` por llamada, sin `dispose()` ni `statement_timeout` | P1 |
| Descubrimiento | `src/connectors/sql/schema_discovery.py:49` | columnas, PK/FK desde `information_schema` | EXISTE |
| Listado | `schema_discovery.py:101` | denylist de tablas de sistema; `COUNT(*)` por tabla | RIESGO P1/P2 |
| Conectores SQL | `src/connectors/plugin/plugins/sql_optional.py` | MySQL/MSSQL/Oracle/DB2 registrados, drivers no instalados en este entorno | EXISTE-NO-EJECUTABLE |
| PostgreSQL externo | `src/connectors/plugin/plugins/postgres.py` | discovery/ingesta; no hay `ReadOnlyQueryAdapter` de consulta | FALTANTE |
| Credenciales | `src/infrastructure/secrets/...` | Secret Store existente; el binder usa `credential_ref` solo en REST | EXISTE para REST, FALTANTE para SQL externo |

`connected_db` no tiene executor propio. Declararlo soportado hoy sería falso.

### 3.4 Catálogo, recursos y Architect

| Componente | Ubicación | Comportamiento | Clasificación |
|---|---|---|---|
| Capability registry | `capability_registry.py:727` | snapshot tenant/workspace con disponibilidad y hashes | EXISTE |
| Recursos de capacidad | `capability_registry.py:1059` | Managed DB y conectores con `data_schema={}`; sin tablas/columnas | EXISTE-NO-EXPUESTO |
| Resolver de recursos | `business_resources.py:248` | lee `catalog_sources/tables/columns` del catálogo semántico; tablas filtradas solo por organización | EXISTE, RIESGO cross-workspace |
| Data catalog del grafo | `data_catalog.py:24` | campos de salida/samples para Data Picker; no lista conexiones ni tablas | EXISTE, alcance distinto |
| Data mapper | `data_mapper.py:150` | genera SELECT de preview con identificadores validados; sin allowlist de tabla/columnas y sin wiring al runtime | EXISTE-NO-EXPUESTO, RIESGO si se conecta |
| Plan compiler | `plan_compiler.py:95` | valida agentes/KBs/acciones; Managed DB solo como booleano | EXISTE, insuficiente para recursos |
| Architect discovery | `architect_discovery.py:173` | snapshot de capacidades; no entrega schema de tablas | EXISTE |
| Architect compiler | `architect_compiler.py:557` | compila plan a IR validado; no crea recursos | EXISTE |
| Readiness | `readiness.py:38` | checks de trigger/datos/condiciones/agentes/salidas; sin checks de recurso, ACL, pinning o frescura | FALTANTE para P19-12 |

### 3.5 API relevante

| Ruta | Estado | Observación |
|---|---|---|
| `GET /api/v1/workflows/node-schemas` | EXISTE | schemas de negocio; `query_business_data` solo expone `ask` |
| `GET /api/v1/workflows/node-catalog` | EXISTE | catálogo semántico de nodos |
| `GET/PUT/DELETE /capability-bindings` | EXISTE | binding por capacidad; `config` es un dict sin schema de plan |
| `GET /{workflow_id}/data-catalog` | EXISTE | salidas/samples del grafo, no recursos |
| `GET /{workflow_id}/sample-outputs` | EXISTE | samples de runs |
| `GET /api/v1/workflows/data-sources` | **FALTANTE** | no hay listado de conexiones |
| `GET .../data-sources/{ref}/resources` | **FALTANTE** | no hay catálogo de tablas/vistas |
| `GET .../resources/{ref}/schema` | **FALTANTE** | no hay schema autorizado |
| `POST .../data-query/preview` | **FALTANTE** | no hay preview seguro |

`BindingIn.config` acepta cualquier JSON. No hay validación de plan, recurso,
proyección, predicados ni límites al guardar el binding.

### 3.6 Portal

| Componente | Ubicación | Comportamiento | Clasificación |
|---|---|---|---|
| Librería de nodos | `portal/src/lib/workflowGraph.ts:175` | `query_business_data` con un solo campo `ask` (textarea) | AS-IS insuficiente |
| Nodo «Consultar registros» | — | No existe `data_query` ni equivalente visual | **FALTANTE** |
| Configurador | `portal/src/components/NodeConfigPanel.tsx` | renderiza parámetros del schema; no hay selector de conexión/tabla/columnas | FALTANTE |
| Data Picker | `portal/src/components/workflowStudio/DataPicker.tsx` | selecciona referencias de salida de nodos; no selecciona recursos SQL | EXISTE, alcance distinto |
| Test/Inspector | `WorkflowTestPanel`, `InstanceTimeline` | muestra pasos y salidas; no distingue fuente SQL, frescura ni filas redactadas | PARCIAL |

### 3.7 Baseline de datos locales (solo metadatos)

| Métrica | Valor |
|---|---|
| Workflows | 2 708 (473 activos, 471 con versión publicada) |
| Instancias durables | 123 368 con snapshot; 122 756 en `WAITING` |
| Runs | 173 083 (36 517 succeeded, 12 462 failed, 123 667 waiting) |
| Bindings | 4 742: commerce 3 082, payment 1 105, conversation 221, managed_db 182, rest_api 152 |
| Bindings managed_db | 167 org-level, 15 workspace-level |
| Managed databases | presentes en la DB local; no se leyeron filas ni credenciales |

Estos números describen el entorno local, no producción. La existencia de 122 756
instancias WAITING eleva el riesgo de que un cambio vivo de binding amplíe una
consulta al reanudar.

## 4. Flujo AS-IS

```
mensaje / trigger
  └─ ai_decision | adaptive_route | llm        (no hay contrato de intención de datos)
       └─ capability_call
            ├─ query_business_data → orquestador RAG → texto + rows + sql_query
            └─ managed_db → config = binding.config + payload
                 → SELECT columnas FROM tabla WHERE filtros ORDER BY ... LIMIT ...
                 → filas crudas al output del nodo
```

No hay una entidad «consulta autorizada» intermedia. La autoridad efectiva es el
binding vivo; el payload puede reemplazar sus campos. La intención del usuario no
se valida contra recursos: el LLM o el diseñador eligen una capacidad lógica.

## 5. Matriz AS-IS / TO-BE

| Área | AS-IS comprobado | Clasificación | TO-BE P19 | Fase |
|---|---|---|---|---|
| Selección de conexión | No existe; solo capacidad lógica | FALTANTE | catálogo de conexiones autorizadas | 02/03 |
| Selección de tabla/vista | `config.table` libre en binding; payload la reemplaza | RIESGO P0 | recurso canónico con snapshot y allowlist | 01/02 |
| Proyección | `columns` libre; default `*` | RIESGO P0 | proyección explícita registrada | 01 |
| Filtros | `filters` libre; payload reemplaza todo el dict | RIESGO P0 | predicados obligatorios + parámetros nombrados | 01 |
| Operadores | allowlist parcial con fallback `=` | RIESGO P0 | allowlist estricta + INVALID_PARAMS | 01 |
| Orden | `order_by` libre desde payload | RIESGO P1 | orden declarado en plan | 01 |
| Límite | global 500; `max_rows` no aplica | RIESGO P1 | límite por binding y por recurso | 01 |
| `get_one` | No existe | FALTANTE | 0 → NOT_FOUND; >1 → MULTIPLE_MATCHES | 01 |
| Agregados | No existe AST | FALTANTE | subset tipado aprobado (count/sum/avg/min/max) | 01/03 |
| Error mapping | `NEEDS_CONFIGURATION`, `PROVIDER_ERROR`, `CONTRACT_INVALID` | PARCIAL | taxonomía P19 estable | 01 |
| Identidad/titularidad | No hay filtro de principal; el payload manda | RIESGO P0 | principal de sesión + ownership server-side | 01/08/09 |
| Cross-workspace | binding org-level heredado sin concesión | RIESGO P0 | concesión explícita o deny | 01/02 |
| Cross-tenant | lookup por `organization_id` | EXISTE (positivo) | mantener + tests | 02/13 |
| Catálogo de recursos | Solo catálogo semántico, sin ACL de lectura | PARCIAL | API paginada, tenant/workspace/role scoped | 02 |
| Nodo visual | Pregunta libre; sin selectores | FALTANTE | «Consultar registros» progresivo | 03 |
| Intención | `ai_decision` genérico; sin rutas de datos tipadas | PARCIAL | contrato `intent.route/v1` | 04 |
| Data Picker | Referencias de salida existentes | EXISTE | tipos, nullabilidad, statuses | 05 |
| Conector externo | `connected_db` cae a Managed DB | RIESGO P0 | `ReadOnlyQueryAdapter` certificado | 06 |
| Plantilla precio | No existe plantilla P19 | FALTANTE | price_lookup con Decimal/moneda/vigencia | 07 |
| Puntos | No existe flujo de titularidad | FALTANTE | loyalty con identidad verificada | 08 |
| Pedido | No existe flujo WAIT de order_status | FALTANTE | order_status + subworkflow de cambio | 09 |
| Architect | Propone capacidades; no recursos con schema | PARCIAL | propuesta tipada con bindings unresolved | 10 |
| UX resultados | Inspector muestra output crudo | PARCIAL | fuente, estado, latencia, redacción | 11 |
| Readiness | Sin checks de datos | FALTANTE | checks P19 + pinning | 12 |
| Observabilidad | `workflow_run_steps` guarda output sin redacción | RIESGO P1 | provenance y redacción por rol | 05/13 |
| Flag reversible | No existe flag P19 | FALTANTE | `ZENT_WORKFLOW_DATA_NODES_ENABLED` | 12 |
| Tests adversariales | Este documento | PARCIAL | matriz P19-13 | 13 |
| Certificación | No existe | FALTANTE | manifiesto P19-14 | 14 |

## 6. Fricción UX medida (canvas actual)

Recorrido real para intentar «consultar precio»:

1. Abrir el canvas.
2. Añadir «Consultar datos de negocio».
3. Escribir una pregunta en texto libre.
4. Guardar.
5. Ejecutar una prueba.

No hay paso para elegir conexión, tabla, operación, columna de búsqueda, campos de
salida ni rutas de no encontrado/error. El usuario no puede saber qué tabla se
consultará ni con qué permisos; el sistema tampoco puede garantizarlo.

| Selector exigido por P19 | Presente |
|---|---|
| Conexión autorizada | 0 |
| Tabla/vista con nombre humano | 0 |
| Operación (buscar/listar/contar/resumir) | 0 |
| Columna y operador de búsqueda | 0 |
| Campos de salida | 0 |
| Preview/Prueba de lectura | 0 |
| Rutas no encontrado/varios/error | 0 |

**Conclusión UX:** el AS-IS no cumple el objetivo de «consultar sin SQL/JSON».
No se aprueba P19-03 por analogía con el editor actual.

## 7. Hallazgos priorizados

### P0 — bloquean P19-01

| ID | Hallazgo | Evidencia |
|---|---|---|
| P19-00-P0-01 | El payload reemplaza `table` y `columns` del binding | test rojo; SQL real `SELECT customer_id, balance FROM loyalty_balances LIMIT 50` |
| P19-00-P0-02 | `columns: ["*"]` produce `SELECT *` | test rojo |
| P19-00-P0-03 | `filters` del payload reemplaza predicados obligatorios | test rojo |
| P19-00-P0-04 | Operador desconocido se degrada a `=` en silencio | test rojo |
| P19-00-P0-05 | Binding org-level se hereda por cualquier workspace sin concesión | test rojo |
| P19-00-P0-06 | Run sin workspace abre la última Managed DB de la organización | inspección `service.py:292-301` |
| P19-00-P0-07 | `connected_db` se ejecuta contra Managed DB | test rojo |

### P1 — bloquean publicación/certificación

| ID | Hallazgo |
|---|---|
| P19-00-P1-01 | `max_rows` del binding no se respeta; solo el techo global 500 |
| P19-00-P1-02 | `order_by` elegido por payload |
| P19-00-P1-03 | Sin `get_one`, `NOT_FOUND`, `MULTIPLE_MATCHES`, `truncated`, `data_as_of`, `binding_hash`, `source_ref`, `provenance` |
| P19-00-P1-04 | Cross-tenant y capacidad inexistente colapsan en `NEEDS_CONFIGURATION`; no hay razón interna auditable |
| P19-00-P1-05 | Sin `statement_timeout`, sin dispose del engine, sin presupuesto de costo/concurrencia |
| P19-00-P1-06 | `query_business_data` y `semantic_query` fuerzan rol admin |
| P19-00-P1-07 | El binding no está pinneado en la instancia; un cambio vivo afecta WAIT/RESUME |
| P19-00-P1-08 | `workflow_run_steps` persiste output sin redacción; `sql_query` se propaga |
| P19-00-P1-09 | `business_resources` lista tablas del catálogo solo por organización, sin workspace en `catalog_tables` |
| P19-00-P1-10 | `data_mapper.declarative_select` es un segundo generador SQL sin allowlist ni wiring |
| P19-00-P1-11 | `schema_discovery` usa denylist y `COUNT(*)` por tabla; no es un catálogo de recursos expuestos |
| P19-00-P1-12 | No hay API de data sources/resources/schema/preview |

### P2 — deuda planificada

- Identificadores Unicode o con mayúsculas rechazados por `_IDENT_RE`; el catálogo
  debe mostrar nombre humano y nombre técnico sin inventar semántica.
- Sin cursor/paginación en consultas de datos.
- Sin presupuesto de tokens/costo por consulta.
- Sin prueba de accesibilidad del configurador (no existe todavía).
- Sin prueba de concurrencia 1/10/50.

## 8. Gate P19-00

| Criterio | Resultado | Evidencia |
|---|---|---|
| Reproducciones adversariales | PASS (como tests rojos controlados) | 2 passed, 8 xfailed |
| Lista de componentes reales | PASS | secciones 3.1–3.6 |
| ADR firmada | PASS (propuesta, pendiente aprobación humana) | `00-adr-query-node.md` |
| Baseline de CI | PASS | run `498`, 16/16 jobs |
| Cero cambios de runtime | PASS | solo docs y tests |
| Publicaciones/instancias modificadas | 0 | sin migraciones ni escrituras |

**Veredicto:** P19-00 COMPLETADO. **P19-01 queda BLOQUEADO** hasta que una persona
apruebe la ADR y acepte que los P0 anteriores son el alcance de cierre. No se
declara PASS de seguridad ni GO de producción.

> **Actualización posterior:** la ADR fue aprobada. P19-01 quedó COMPLETADO en
> backend y convirtió los 8 `xfail` en PASS. Ver
> `01-declarative-query-engine.md`.

## 9. Superficie de cambio y rollback

Archivos añadidos por P19-00:

- `docs/architecture/workflow-data-p19/00-audit-baseline.md`
- `docs/architecture/workflow-data-p19/00-adr-query-node.md`
- `docs/architecture/workflow-data-p19/00-threat-model.md`
- `docs/architecture/workflow-data-p19/00-matrix-asis-tobe.md`
- `docs/architecture/workflow-data-p19/00-test-evidence.md`
- `tests/test_workflow_data_p19_audit.py`
- `portal/src/lib/workflowGraph.p19.test.ts`

Rollback: revertir estos archivos. No hay migración, flag, schema, binding,
workflow publicado ni instancia tocada. Los tests rojos son `xfail(strict=True)`;
si P19-01 los arregla sin actualizarlos, el XPASS fallará y obligará a convertir
la expectativa en PASS.

## 10. Criterios de entrada a P19-01

1. ADR aprobada: nodo `data_query` vs extensión de `capability_call`.
2. Contrato de plan `zent.data.query.binding/v1` congelado.
3. Decisión de herencia org-level: default deny + concesión explícita.
4. Decisión de agregados: subset tipado, no SQL libre.
5. Aceptación de que P19-01 debe convertir los 8 xfail en PASS sin relajar
   ninguno de los asserts de seguridad.
