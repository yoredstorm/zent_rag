# 03 — P01: gate único de release y certificados

Fecha: `2026-10-23`.
Base: `0cbb494ce4` + WIP declarado en `00-baseline.md`.
Alcance: publicación/activación/promote/restore y certificados emitidos por el
backend. P02 (ingress durable) no forma parte de este PR.

## 1. Decisión de arquitectura

Una sola autoridad de release: `src/platform/workflows/release_policy.py`.
No hay un segundo engine, planner, scheduler ni tienda.

- `publish_workflow`, `activate`, `promote` y `restore` llaman al mismo servicio.
- El certificado se persiste en `workflow_certificates` (migración 164).
- El grafo y su metadata reservada (`certification`, `require_certification`,
  `release_certificate`) se ignoran como evidencia. El hash se recalcula desde
  el grafo persistido, sin el blob del cliente.
- `publish_workflow` bloquea la fila del workflow con `SELECT ... FOR UPDATE`
  durante el gate y la escritura de la versión, para evitar TOCTOU.
- `activate_workflow` bloquea la fila, evalúa y activa en la misma transacción.
- La política legacy se marca en la fila (`workflows.release_policy='legacy'`)
  con razón y fecha. No hay bypass implícito por metadata ausente.

## 2. Clases de riesgo y niveles

| Clase | Ejemplos | Nivel exigido |
|---|---|---|
| `read_only` | triggers, condiciones, `kb_query`, lectura de datos | `DESIGN_VALID` |
| `internal` | `notify` in-app, `business_result`, `state_*`, `human_approval` | `DESIGN_VALID` |
| `agent` | nodo `llm` con agente activo | `DESIGN_VALID` |
| `external_read` | `capability_call` de catálogo/consulta | `DESIGN_VALID` |
| `external_write` | `capability_call` de escritura, `api_call`, `business_node`, `marketplace_action`, notify email/webhook, subflujo | `SANDBOX_VERIFIED` |
| `regulated` | pagos/financiero/critical | `PROVIDER_VERIFIED` |

Estados del certificado: `DESIGN_VALID`, `SIMULATION_PASSED`,
`SANDBOX_VERIFIED`, `PROVIDER_VERIFIED`, `AWAITING_APPROVAL`, `READY_TO_PUBLISH`,
`BLOCKED`, `STALE`. En P01 solo se emiten `design` y `simulation`; sandbox y
proveedor siguen bloqueados hasta P08. Un flujo `external_write`/`regulated`
no publica con un certificado de simulación.

## 3. Contrato del certificado

Campos persistidos: tenant, workspace, workflow, versión de grafo, hash de
grafo, hash de plan (si existe design session), hash de snapshot de
capacidades, versiones de agentes/roles, versión de política, escenarios,
resultados, nivel, estado, emisor, emisión, expiración, revocación.

Endpoints:

| Método y ruta | Permiso | Uso |
|---|---|---|
| `GET /api/v1/workflows/{id}/release-gate?action=publish` | `workflows:read` | ALLOW/DENY, blockers y mitigaciones |
| `POST /api/v1/workflows/{id}/certifications` | `workflows:activate` | Emite `design`/`simulation`; acota escenarios y expiración |
| `GET /api/v1/workflows/{id}/certifications` | `workflows:read` | Historial auditable |

La metadata forjada por PATCH/import no se lee. El cliente no puede enviar
`graph_hash`, `state`, `publishable` ni `provider`; el backend los calcula.

## 4. Rutas auditadas

| Ruta | Gate | Estado |
|---|---|---|
| `POST /workflows/{id}/publish` | `evaluate_release(action="publish")` + lock | Gate aplicado |
| `POST /workflows/{id}/activate` | `activate_workflow` + lock | Gate aplicado |
| `POST /workflows/{id}/versions/{vid}/promote` a production | `target_graph_decision` sobre el snapshot | Gate aplicado |
| `POST /workflows/{id}/versions/{vid}/restore` con workflow activo | `target_graph_decision` sobre el snapshot destino | Gate aplicado |
| `POST /workflows/import` | crea draft, no activa | Sin activación; publish posterior exige gate |
| `POST /workflows/templates/{slug}/install`, marketplace install | crea draft | Sin activación; publish posterior exige gate |
| Architect draft | crea draft | Sin activación; publish posterior exige gate |
| `/run` | no publica | Permitido para pruebas; no sustituye certificación |
| Scheduler/hook público | exige workflow `active` | La activación ya pasó por gate |
| Event trigger | puede ejecutar un draft | Pendiente P02 (P1-05); no se declara resuelto |

## 5. Compatibilidad legacy

La migración 164 marca todos los workflows existentes como `legacy` con razón
`política legacy registrada en migración 164` y fecha. Un workflow legacy
publica/activa con estado `LEGACY_EXEMPT` y queda registrado en la respuesta del
gate. Los workflows creados después de la migración usan `standard` y no tienen
exención. La decisión legacy está en base de datos, no en el grafo.

## 6. Pruebas ejecutadas

| Comando | Resultado |
|---|---|
| `pytest tests/test_workflow_publication_gate.py -q` | **10 passed** (98.36 s) con `junit-publication-gate.xml` |
| `pytest tests/test_workflow_studio.py -q` | **12 passed** (128.40 s) |
| `pytest tests/test_workflow_durable_instances.py::test_portable_package_export_inspect_import tests/test_workflows.py::test_crud_and_status` | **2 passed** (47.56 s) |
| `pytest tests/test_workflow_publication_gate.py tests/test_workflow_studio.py -q` | **22 passed** (256.62 s) con `junit-gate-studio.xml` |
| `pytest tests/test_workflow_durable_instances.py tests/test_workflow_architect_canonical.py tests/test_workflows.py tests/test_workflow_graph.py -q` | **67 passed** (717.42 s) con `junit-workflows.xml` |
| `pytest tests/red --runxfail` | **6 failed** (los P0 de P02/P05 siguen abiertos) |
| `pytest` architecture/authority/migrations | **24 passed** (44.24 s) |
| `npm run typecheck` | exit 0 |
| `npm run lint` | exit 0, 0 errores, 22 warnings preexistentes |
| `npm test --` suite dirigida de workflow/studio (7 archivos) | **25 passed** (23.78 s) |
| `npm test` suite completa | **NOT_VERIFIED**: excedió 600 s; no se declara verde |
| `npm run build` | exit 0, built in 28.75 s |
| `alembic upgrade head` | 163 → 164 aplicada en base local |

Casos cubiertos: publish sin certificado → 409; activate sin certificado → 409;
design válido → publish 200; simulación con efecto externo → 409 por nivel
insuficiente; grafo editado → `certificate_stale`; metadata forjada ignorada;
workspace B no reutiliza certificado A; legacy explícito permitido; certificado
`AWAITING_APPROVAL` no publica; carrera publish/edit nunca publica el grafo sin
certificar; UI muestra bloqueos y deshabilita Publicar.

## 7. Limitaciones y riesgos residuales

- `sandbox` y `provider` no se emiten en P01. Todo `external_write`/`regulated`
  queda fail-closed hasta P08. Es intencional: no se etiqueta simulación como
  proveedor.
- El gate de `promote`/`restore` evalúa el snapshot destino; la UI de versiones
  aún no muestra el detalle del gate de cada snapshot.
- La revocación administrativa de un certificado no tiene endpoint todavía;
  se hará en P10/P11. La columna `revoked_at` ya existe.
- No hay prueba de dos publicaciones concurrentes con dos réplicas; la
  protección es el lock de fila y se probó la invalidación por edición.
- Los eventos siguen pudiendo ejecutar un workflow draft (P1-05); P02 debe
  cerrarlo junto con el ingress durable.
- La suite Vitest completa excedió 600 s en esta corrida; la suite dirigida de
  workflow/studio sí pasó. No se declara verde la suite completa.
- `ZENT_GOLD_RELEASE_ENABLED` permanece `false`; no se activó producción.

## 8. Rollback

1. Revertir el PR de P01 (release_policy, integración de versiones/rutas, UI).
2. `alembic downgrade 163` elimina `workflow_certificates`, `certificate_id` y
   las columnas de release_policy. Es reversible y no reescribe workflows. El
   upgrade 163→164 se ejecutó localmente; el downgrade no se ejecutó en esta
   corrida para no borrar la evidencia de certificados.
3. Mantener `ZENT_GOLD_RELEASE_ENABLED=false` y no reactivar publicación manual
   sin el gate.
4. Las versiones y workflows creados durante P01 conservan sus snapshots; no se
   borran históricos.

## 9. Dictamen

**GO P01 para staging controlado.** El gate único está aplicado en publish,
activate, promote y restore; los certificados son del backend, con tenant,
workspace, hashes y expiración. **NO-GO release**: sandbox/proveedor no existen,
event triggers draft siguen abiertos (P02) y la suite completa/Playwright no se
revalidaron en esta fase.
