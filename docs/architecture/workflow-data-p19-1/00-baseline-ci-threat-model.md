# P19.1-00 — Baseline, CI rojo, threat model y mapa de regresión

- **Estado:** DONE. CI run `41362601249` **success** en el commit
  `bf8c7b308990701276dec0b90b220321e8ef35f3`, rama
  `fix/p19-1-data-workflow-hardening`, PR
  [#17](https://github.com/yoredstorm/zent_rag/pull/17). Incluye
  `Architecture invariants`, los 4 shards de test, portal, portal-e2e,
  secrets-scan, certification y `build`.
- **Baseline de referencia:** `9791a662404b00f8b80c293a2f94c6e897e38554`
  (`master`, 2026-11-01).
- **HEAD local al iniciar:** el mismo SHA; árbol limpio.
- **Run CI reportado:** `41354084398`, fallo en
  `Architecture invariants (fast, required)` del job `test (1/4)`.
- **Alcance de este documento:** reproducir y corregir el gate rojo, registrar
  inventario AS-IS, amenazas y baseline. No implementa P19.1-01..09.

## 1. Baseline verificado

Comandos:

```powershell
git rev-parse HEAD
git status --short
git log --oneline -5
```

Resultado:

```text
9791a662404b00f8b80c293a2f94c6e897e38554
(árbol limpio)
9791a66 docs(p19): record self-service table publication
af4966c fix(p19): make external postgres discovery asyncpg-safe
d7f7e9d feat(p19): self-service table publication for data queries
d068ac4 fix(p19): reject reservations for closed orders
511308d docs(p19): record expiring reservations and agent data grants design
```

El HEAD coincide con el baseline remoto indicado. No se aplicaron
cherry-picks ni se reescribió historia.

El detalle de jobs del run remoto baseline se obtuvo con la API de GitHub y
quedó en `artifacts/certification/9791a662.../ci/ci-run.json`: `test (1/4)`
falló en el paso de invariantes, los otros tres shards, portal, portal-e2e,
lint, secrets-scan, certification, SDKs y `test-evidence` aprobaron; `test`
falló por dependencia y `build` quedó **skipped**. No se declara build PASS
para el baseline.

## 2. Fallo reproducido (causa exacta)

Comando (misma lista que CI, extraída por `scripts/cert/run_invariants.py`):

```powershell
python scripts/cert/run_invariants.py \
  --out-dir artifacts/certification/9791a662/invariants
```

Resultado en baseline:

```text
FAILED tests/test_architecture.py::test_no_vertical_business_terms_in_generic_layers
E AssertionError: Strings verticales en capas genéricas:
E   src\platform\workflows\intent_route.py: contiene 'order_status'
E   src\platform\workflows\node_catalog.py: contiene 'order_status'
E   src\platform\workflows\parameters.py: contiene 'order_status'
1 failed, 406 passed, 7 warnings in 131.14s
```

Evidencia conservada:

- `artifacts/certification/9791a662/invariants/pytest-invariants.log`
- `artifacts/certification/9791a662/invariants/junit-invariants.xml`
- `artifacts/certification/9791a662/invariants/invariants.evidence.json`

### Diagnóstico

- No fue infraestructura ni flaky: es un assert determinista del gate de
  arquitectura.
- El commit `ea294610d4c580e1effcf04af359698fac4e663a`
  (`feat(p19): add typed intent routing and entity extraction`,
  2026-11-01T13:32:37-05:00) introdujo la política vertical demo
  (`price_lookup`, `loyalty_balance`, `order_status`, keywords, extractores)
  directamente en `src/platform/workflows/`.
- `test_no_vertical_business_terms_in_generic_layers` prohíbe términos de
  negocio vertical en `core/`, `rag/`, `agents/` y `platform/`. El assert es
  correcto: el motor genérico no debe conocer rutas de comercio.
- El mismo commit añadió los ids de ruta como texto de ayuda/ejemplo en
  `node_catalog.py` y `parameters.py`.

### Descartado

- No se modificó `tests/test_architecture.py`.
- No se cambió `.github/workflows/ci.yml` ni la lista de invariantes.
- No se añadieron `skip`, `xfail`, `noqa` al assert ni umbrales.
- No se renombró el término para evadir el escaneo.

## 3. Corrección aplicada

Separación motor/política:

| Capa | Responsabilidad |
|---|---|
| `src/platform/workflows/intent_route.py` | Motor genérico: contrato Pydantic, scoring, confianza, seguridad de entrada, validación de rutas contra el pack. Cero vocabulario de negocio. |
| `src/verticals/p19_demo/intent_routes.py` | Pack vertical demo: ids de ruta, keywords, patrones de inyección/ownership, extractores y slots. Es la política de negocio, no el motor. |
| `src/platform/workflows/node_catalog.py` | Ejemplo y ayuda sin ids de negocio; el ejemplo usa el pack configurado por defecto. |
| `src/platform/workflows/parameters.py` | Ayuda genérica de rutas; sin listar rutas de comercio. |

Contrato preservado:

- `classify_intent(config, text, pack=None)` sigue aceptando las mismas
  llamadas. Sin `pack`, carga el pack demo por compatibilidad con workflows
  P19 existentes que no declaran `routes`.
- `parse_intent_config` valida que todo `route.id` pertenezca al pack activo;
  un id inventado sigue devolviendo `IntentConfigError`.
- `default_routes()` se conserva como fachada compatible.
- Los extractores y patrones se movieron sin cambiar su semántica; los tests
  de intención P19 pasan sin modificar sus asserts.

Riesgo residual: el motor todavía importa perezosamente el pack demo como
default. P19.1-06 debe reemplazarlo por rutas declaradas en el workflow y
hacer el pack explícito; hasta entonces se mantiene compatibilidad, no se
declara multi-tenant ni multi-vertical certificado.

## 4. Verificación ejecutada

| Caso | Esperado | Observado | Resultado | Evidencia |
|---|---|---|---|---|
| Gate de invariantes completo | 0 fallos, sin skips nuevos | Local `407 passed`; CI `407 tests, 0 failures, 0 skipped` | PASS | local + `artifacts/certification/bf8c7b3.../ci/junit-invariants.xml` |
| Test rojo exacto | Reproducir y corregir | Falló en baseline; verde tras el fix en CI | PASS | `junit-invariants.xml` baseline y fix |
| Suite P19 (7 archivos + catálogo/parámetros) | Sin regresiones | `120 passed, 2 skipped` local; los 2 externos `2 passed` con env | PASS | ejecución local 2026-11-01 |
| PostgreSQL externo real | Lectura y rechazo de inyección | `2 passed` con `P19_EXTERNAL_*` | PASS | `tests/test_workflow_data_p19_external.py` |
| Frontend typecheck | Sin errores TS | Local `tsc --noEmit` exit 0; CI `portal` success | PASS | ejecución local + CI |
| Frontend lint | 0 errores | Local 0 errores/26 warnings; CI `lint` success | PASS | local + CI |
| Frontend build | Build de producción | Local `vite build` OK; CI `build` success | PASS | local + CI |
| Frontend Vitest (focalizado P19/Workflow) | Sin fallos | `22 files / 123 tests passed` | PASS | `npx vitest run src/components/workflowStudio src/lib/workflowGraph.p19.test.ts` |
| Frontend Vitest (suite completa) | Sin fallos | CI `portal` (incluye `npm run test`) success | PASS (CI) | `ci-run.json` |
| Backend completo (DAG CI) | Sin fallos | CI `6075 tests, 0 failures, 0 errors, 14 skipped`; local abortado por tiempo, 1 flaky aislado PASS | PASS (CI) | `artifacts/certification/bf8c7b3.../ci/junit-tests.xml` |
| Portal E2E | Sin fallos | CI `portal-e2e` success | PASS (CI) | `ci-run.json` |
| Build de imagen | No skipped | CI `build` success | PASS (CI) | `ci-run.json` |
| Secrets scan | Sin secretos | CI `secrets-scan` success | PASS (CI) | `ci-run.json` |

### 4.1 CI completo (autoritativo)

Run `41362601249`, SHA `bf8c7b308990701276dec0b90b220321e8ef35f3`:

| Job | Resultado |
|---|---|
| `test (1/4)` (incluye Architecture invariants) | success |
| `test (2/4)`, `test (3/4)`, `test (4/4)` | success |
| `test-evidence`, `test` | success |
| `portal`, `portal-e2e` | success |
| `certification`, `lint`, `secrets-scan`, `pip-audit` | success |
| `sdk-python`, `sdk-node`, `kustomize` | success |
| `build` | success (no skipped) |

JUnit descargado con `scripts/cert/fetch_ci_evidence.py`:

- Invariantes: `407 tests, 0 failures, 0 errors, 0 skipped`.
- Suite completa: `6075 tests, 0 failures, 0 errors, 14 skipped`.
- Baseline: invariantes `407 tests, 1 failure`; suite fusionada `3764 tests,
  0 failures, 6 skipped` porque el shard 1 no llegó a correr pytest al fallar
  el paso de invariantes. El aumento de skips (6→14) corresponde a los skips
  del shard 1 que ahora sí se ejecuta, no a skips nuevos en invariantes.
- Evidencia: `artifacts/certification/bf8c7b3.../ci/`.

### 4.2 Notas de ejecución local

- La suite backend completa local se abortó al 13% por tiempo (ETA > 2 h en
  Windows). Se observó un fallo en
  `tests/test_api_key_scopes.py::test_test_key_is_rate_limited_per_token_and_watermarked`;
  el rerun aislado dio `1 passed`. El CI de Ubuntu ejecutó los 6075 tests sin
  fallos, por lo que no se atribuye a este cambio.
- La primera corrida local de Vitest completo tuvo un timeout de 60 s en
  `WorkflowPatchPanel.test.tsx` bajo carga concurrente; el rerun aislado dio
  `2/2 PASS` y la corrida focalizada `123/123 PASS`. El job `portal` de CI
  ejecutó la suite completa y aprobó.

### 4.3 Comando de reproducción de seguridad

```powershell
docker run --rm -v "${PWD}:/repo" zricethezav/gitleaks:latest `
  detect --source /repo --config /repo/.gitleaks.toml --no-git
```

En local la imagen no estaba disponible (`NOT_RUN` local); el job
`secrets-scan` de CI aprobó sobre el SHA.

## 5. Inventario AS-IS

Ver [00-inventory-asis.md](./00-inventory-asis.md). Resumen:

- Fuentes: `managed_db`, `connected_db` PostgreSQL externo, `inventory`,
  `rest_api`, `marketplace_action`, `semantic_query`.
- Autoridad de publicación: `POST /data-query/plans` exige solo
  `workflows:update`; el parámetro `permissions` llega a la función pero no se
  usa para autorizar tablas/columnas.
- Autoridad de ejecución: `execute_binding` resuelve por
  `organization_id + capability_ref + workspace_id`; no recibe permisos
  efectivos del actor ni un principal verificado.
- Bindings: tabla única `workflow_capability_bindings`; `upsert_binding` hace
  `ON CONFLICT DO UPDATE` y reactiva `status='active'`.
- Conectores externos: host/puerto/DB/usuario salen de `connectors.config_json`;
  TLS opcional `require`; engine nuevo por consulta (`pool_size=1`).
- Inventario: SQL `bodega.*` embebido en `bindings.py`; TTL con `NOW()` de DB;
  ledger con clave única; sin job periódico de expiración.
- Caché de catálogo: TTL 30 s, clave por org/workspace/permisos; invalidación
  explícita al publicar/deshabilitar.

## 6. Threat model P19.1 (P0/P1/P2)

| ID | Riesgo | Superficie / vector | Prob. | Impacto | Mitigación objetivo | Gate |
|---|---|---|---|---|---|---|
| P0-01 | Publicar acceso a tablas/PII con solo editar workflows | `POST /data-query/plans`; rol `member` tiene `workflows:update`; UI selecciona todas las columnas | Alta | Alto | permisos `data_*` separados, allowlist por conector, deny-by-default, columnas PII explícitas | G01 |
| P0-02 | Lectura sin titular verificado o preview administrativa | `execute_binding` no recibe principal; `_execute_connected_select` no lo propaga; preview con `workflows:read` | Alta | Alto | `VerifiedPrincipal` server-side, ownership antes de SQL, revalidar en WAIT | G02 |
| P0-03 | Binding mutable entre publicación y ejecución | `upsert_binding` sobrescribe mismo `capability_ref`; nodo comprueba `binding_ref` después de ejecutar | Media | Alto | revisión inmutable, hash/version preflight, cero SQL ante drift | G03 |
| P0-04 | Error técnico/seguridad presentado como workflow exitoso | `_exec_data_query` devuelve `output.status=ERROR` sin `NodeOutcome.error` | Alta | Alto | envelope v2, error de nodo, ramas de recuperación obligatorias | G04 |
| P0-05 | SSRF / TLS falso en conector externo | host del conector sin allowlist; `ssl=require` sin CA/hostname; engine por consulta | Media | Alto | egress policy, TLS verify-full, pool acotado, timeouts | G08 |
| P0-06 | Sobreventa o doble commit de inventario | SQL `bodega.*` en core; clave `reserve:order:sku`; multi-ítem no atómico; expiración perezosa | Media | Alto | adaptador inventory, idempotencia por línea/acción, job de expiración, saga | G07 |
| P0-07 | PII en preview, count o trazas | Redacción por heurística de nombre; `count` no redacta; output/trace con filas | Media | Alto | clasificación declarativa, minimización, redacción en runtime/traces, count gobernado | G01/G02 |
| P1-01 | Cross-workspace/tenant por binding org-level o conector compartido | `resolve_binding` cae a org-level; conector sin `workspace_id` | Media | Alto | grant explícito por workspace, RLS, pruebas A≠B | G02 |
| P1-02 | Revocación no respetada tras WAIT/RESUME | snapshot de instancia no revalida permisos/TTL | Media | Alto | revalidar autoridad y principal al reanudar | G02 |
| P1-03 | Fuga por logs/trazas/errores | mensajes con `exc.message`, rows en output, SQL en docs | Media | Medio | redacción, reason codes, sin SQL/PII | G04/G09 |
| P1-04 | Inyección SQL por identificadores/valores | identificadores vienen del plan server-side y se citan; valores son bind params | Baja | Alto | mantener allowlist, tests negativos, no SQL libre | G01 |
| P1-05 | Enumeración de catálogo | `data-sources`, `resources`, `schema` | Media | Medio | filtro por permisos efectivos, respuestas uniformes | G01 |
| P1-06 | Intención no calibrada / multi-intent | reglas con `confidence` heurística; multi-intent va a `other` | Alta | Medio | gold set, calibración, slots durables | G06 |
| P2-01 | UX: reload pierde canvas; columnas preseleccionadas | `DataQueryForm`, `PublishQueryModal` | Alta | Medio | estado sin reload, cero selección inicial | G05 |
| P2-02 | Coste/latencia por pool por consulta | engine `pool_size=1` por query | Alta | Medio | pool acotado por tenant/conector | G08 |
| P2-03 | Documentación P19 desactualizada | docs vs código | Media | Bajo | este programa y checks de docs | G09 |

Pruebas negativas mínimas por amenaza: cross-org, cross-workspace, PII,
`SELECT *`, columna no permitida, tabla fuera de allowlist, binding deshabilitado,
permiso revocado, WAIT con token expirado, SQLi como valor, override de
`connection_ref/table/columns/order_by`, host metadata/loopback, TLS inválido,
replay de señal, doble commit y 100 reservas concurrentes.

## 7. Baseline cuantitativo

| Métrica | Valor | Estado | Nota |
|---|---|---|---|
| Latencia p50/p95/p99 consulta local | — | NOT_MEASURED | Docker local no es entorno comparable; no se extrapola |
| Latencia p50/p95/p99 consulta externa | — | NOT_MEASURED | idem; solo smoke funcional |
| Queries/conexiones por ejecución | 1 query; 1 engine nuevo por consulta externa | OBSERVED (código) | `pool_size=1`, `dispose()` al final |
| Tasa de error de la suite | CI: 0 fallos / 6075 tests (14 skipped) | OBSERVED CI | JUnit CI |
| Cobertura TypeScript | `tsc --noEmit` sin errores; CI `portal` success | OBSERVED CI | no es cobertura de líneas |
| Tiempo UI | — | NOT_MEASURED | requiere Playwright con build real |
| WAIT/RESUME p50/p95 | — | NOT_MEASURED | requiere escenario durable instrumentado |
| Tiempo gate invariantes | 128.79 s (407 tests) | OBSERVED local | Windows, Docker local |
| Suite P19 focalizada | 68.99 s (120 passed, 2 skipped) | OBSERVED local | incluye integración local |

Los valores `OBSERVED` son de desarrollo y no autorizan SLO de producción.

## 8. Compatibilidad, flags y rollback

- **Migraciones:** ninguna. El cambio es de código y organización de módulos.
- **Feature flags:** no se añadió flag; el comportamiento por defecto es el
  mismo pack demo.
- **Workflows existentes:** `intent_route` sin `routes` sigue usando el pack
  demo. `routes` explícitas deben pertenecer al pack; antes también estaban
  limitadas por `Literal`.
- **Instancias en WAIT:** no se tocan; el contrato de resultado no cambió.
- **Rollback:** revertir el commit de corrección restaura el código anterior;
  no hay datos ni esquema que migrar. El rollback vuelve a dejar el gate rojo,
  por lo que no es una salida válida de release.
- **Riesgo residual:** el default demo sigue acoplado por import perezoso;
  P19.1-06 debe eliminarlo.

## 9. Decisión

**DONE para P19.1-00.** Evidencia principal:

1. El fallo exacto del gate se reprodujo localmente y se corrigió sin tocar el
   assert ni el CI.
2. El CI completo del SHA `bf8c7b308990701276dec0b90b220321e8ef35f3`
   (run `41362601249`, PR #17) está **success**, incluidos
   `Architecture invariants`, los 4 shards, `portal`, `portal-e2e`,
   `secrets-scan`, `certification` y `build`.
3. Invariantes: `407 tests, 0 failures, 0 skipped`; suite completa: `6075
   tests, 0 failures, 14 skipped`.

**Se autoriza iniciar P19.1-01** en la misma rama/PR o en una rama derivada,
con la condición de no publicar datos sensibles ni habilitar escrituras hasta
cerrar G01/G02. Los P0 de publicación, identidad, binding drift, errores,
SSRF y bodega siguen abiertos: la autorización es para trabajar en ellos, no
para declarar P19.1 certificado.

No se declara GO de staging, piloto ni producción en este prompt.
