# 01 — Gap register (P00)

Corte auditado: `0cbb494ce4` + WIP descrito en `00-baseline.md`.
Estados: `confirmado_por_codigo` (leído en código), `probado` (test ejecutado),
`hipotesis` (no ejecutado), `no_verificable` (sin entorno), `cerrado` (ya no
aplica). Una brecha solo pasa a `cerrado` con evidencia de código y prueba.

## P0 — estructural

| ID | Síntoma | Causa raíz | Evidencia | Rutas afectadas | Riesgo | Prueba que lo reproduce | Fix scope | Estado |
|---|---|---|---|---|---|---|---|---|
| P0-01 | Publicar activa un workflow sin certificación | `publish_workflow` solo consulta portabilidad/Architect y luego hace `set_workflow_status(active)`; nunca llama al gate de certificación | Cerrado en P01: `release_policy.py` + `versions.py` llaman al gate bajo lock; evidencia `tests/test_workflow_publication_gate.py` | `POST /workflows/{id}/publish`, API E2E | Flujo con efectos externos queda activo sin evidencia | `test_publish_without_certificate_is_denied`, `test_design_certificate_allows_publish_for_internal_flow` | P01 | cerrado: probado |
| P0-02 | Gate de activación y certificado controlados por el cliente | `_gate_required` lee `metadata.mission`/`require_certification`; el certificado se lee de `metadata.certification`; el hash compara el grafo que ya contiene el certificado | Cerrado en P01: metadata reservada ignorada; certificado en `workflow_certificates`; hash recalculado desde el grafo persistido | `POST /workflows/{id}/activate`, PATCH, import | Bypass por omitir metadata o forjar certificado; gate inerte | `test_client_supplied_certificate_metadata_is_ignored`, `test_activate_without_certificate_is_denied` | P01 | cerrado: probado |
| P0-03 | No existe emisión ni persistencia confiable de certificados | `bind_certificate` no tenía caller; no había tabla de certificados | Cerrado en P01: migración 164, `issue_certificate`, `GET/POST /certifications`, `workflow_versions.certificate_id` | publish, activate, tests, UI | No hay fuente de verdad para `SIMULATION_PASSED`/`PROVIDER_VERIFIED` | `test_design_certificate_allows_publish_for_internal_flow`; `test_awaiting_approval_certificate_cannot_publish` | P01 | cerrado: probado |
| P0-04 | Schedule, webhook de arranque y evento ejecutan efímero aunque el grafo tenga WAIT | `run_workflow` no abría instancia | Cerrado en P02: `ingress.py` clasifica y abre instancia durable con inbox idempotente; migraciones 165/166 | schedule, public hook, event trigger, `/run` | Proceso de negocio no sobrevive reinicio; no hay reanudación | `tests/test_workflow_durable_ingress.py` (7 passed); Gold+restart 2 passed | P02 | cerrado: probado |
| P0-05 | Listado y señales no filtran workspace | Cerrado en P05: filtros workspace en instancias/signals; detalle y acciones 404 cross-workspace; creación valida ownership | `instances.py:297-350`, `:1122-1238`; `api/routes/workflows.py`; `tests/test_workflow_workspace_isolation.py` | `/workflows/instances*`, signals | Lectura/escritura cruzada dentro del mismo tenant | `tests/test_workflow_workspace_isolation.py` (3 passed) | P05 | cerrado: probado |
| P0-06 | PEP no transversal; policy de rol es código muerto; nodos sensibles sin permiso | Cerrado en P05: `policy_enforcement.py` en runtime; mapa de nodos internos; rol/autonomía aplicados; traza segura | `policy_enforcement.py`; `nodes.py:43-52`; `runtime.py:494-505`; `tests/test_policy_enforcement.py` | workflows con nodos de acción, agentes, subflujos | Acción sensible sin autorización efectiva; autonomía de rol no limita acciones directas | `tests/test_policy_enforcement.py` (4 passed) | P05 | cerrado: probado |
| P0-07 | El nivel de prueba no gobierna la ejecución ni la certificación | Cerrado en P08: `/test` decide nivel efectivo, persiste reporte con hashes y el panel muestra degradación; no hay `PROVIDER_VERIFIED` falso | `src/platform/workflows/test_studio.py`; migración 169; `WorkflowTestPanel.tsx`; `tests/test_workflow_test_studio.py` | Workflow Test Studio, certificación | Usuario cree que verificó proveedor cuando solo simuló | `tests/test_workflow_test_studio.py`; `WorkflowTestPanel.test.tsx` (13 passed) | P08 | cerrado: probado |
| P0-08 | Bienestar no clínico sin enforcement runtime | Cerrado en P05: guardrail wellness en PEP (clínica/escritura DENY) + rol/autonomía | `policy_enforcement.py`; `tests/test_policy_enforcement.py::test_wellness_never_runs_clinical_capability` | roles, workflows de bienestar, capability_call | Diagnóstico/prescripción o acción clínica no bloqueada | `tests/test_policy_enforcement.py` | P05/P06 | cerrado: probado |

## P1 — alto, no bloqueante de P00

| ID | Síntoma | Evidencia | Fix scope | Estado |
|---|---|---|---|---|
| P1-01 | Propuesta de rol no materializa solución, agente ni workflow | Cerrado en P03: `solution_compiler.py` compila y materializa rol+agente+workflow draft; `/solutions/new` y tests | P03: `solution_compiler.py`, migración 167, UI | cerrado: probado (9 passed) |
| P1-02 | Nodo `llm` sin agente devuelve eco silencioso | `nodes.py:2050-2065`; publicador Architect sí bloquea `versions.py:349-354`, pero grafos manuales/importados no | P03/P04 | confirmado_por_codigo |
| P1-03 | Draft puede quedar `DRAFT_READY` con `llm` sin agente | Cerrado en P04: `design_state` trata `plan.agent_needs_selection` como NEEDS_CONFIGURATION | `architect_observability.py:175-191`; `tests/test_architect_design_state.py` | cerrado: probado |
| P1-04 | Restore/promote/import no revalidan certificado ni instancias vivas | Cerrado parcial P01: promote a production y restore de workflow activo usan `target_graph_decision`; import sigue creando draft sin activar | P01/P02: `versions.py:197-350`; `packages.py:516-594` | parcial: probado en gate, falta prueba de versiones con snapshot distinto |
| P1-05 | Event trigger ejecuta workflows `draft` | Cerrado en P02: `route_ingress(require_active=True)` bloquea draft en event | P02: `events.py:229`; `ingress.py` | cerrado: probado (`test_event_trigger_on_draft_does_not_execute`) |
| P1-06 | `create_workflow` acepta `workspace_id` del cliente sin validar pertenencia | Cerrado en P05: la ruta verifica `workspaces.organization_id` antes de crear | `api/routes/workflows.py`; `tests/test_workflow_workspace_isolation.py::test_create_workflow_rejects_foreign_workspace` | cerrado: probado |
| P1-07 | Operations sin retry/resume; filtro de estado es cliente sobre una página | `Operations.tsx:71-74`, `:91-104`; API soporta `status` y acciones `workflows.py:1548/1583/1592` | P11 | confirmado_por_codigo |
| P1-08 | Canvas consume rutas de integraciones contextuales; marketplace canónico es `/products` | `docs/architecture/universal-studio/07-go-no-go.md:23`; auditoría P00 no reejecutó el flujo de instalación | P10 | confirmado_por_codigo |
| P1-09 | Planner universal no alcanza GO; presupuesto/quality no medidos en este corte | `docs/architecture/universal-studio/12-release-gold.md:14-34`; WIP de `planner_*` no ejecutado | P04 | no_verificable |
| P1-10 | Sin presupuesto por instancia durable | `instances.py:145-176` no tiene columnas de coste/tokens/steps; solo timeout/expiración/reaper | P02/P11 | confirmado_por_codigo |
| P1-11 | Event bus Redis pub/sub sin replay ni outbox | `src/platform/realtime/stream.py`; `events.py:317-376`; `grep outbox src/` = 0 | P02/P11 | confirmado_por_codigo |
| P1-12 | Memoria no conectada al ciclo conversacional por workspace | Cerrado en P06: migración 168 (workspace/sujeto/scope/consentimiento), `context_service` por rol, prompt del agente, revocación/borrado y UI | `src/platform/workflows/context_service.py`; `src/memory/service.py`; `src/api/routes/memory.py`; `tests/test_context_service.py`; `tests/test_memory_context_api.py` | cerrado: probado |

## P2 — deuda y consistencia

| ID | Síntoma | Evidencia | Fix scope | Estado |
|---|---|---|---|---|
| P2-01 | Doc de universal-studio cita migración 162; HEAD 163 | `docs/architecture/universal-studio/README.md:10` | docs | confirmado_por_codigo |
| P2-02 | `flags_inventory` no cubre `ZENT_*` ni `WORKFLOW_ARCHITECT_ENABLED` | `src/scripts/flags_inventory.py:23-36`; `tests/test_flags_inventory.py:16` | tooling | confirmado_por_codigo |
| P2-03 | Datos/tipos muertos en portal | `OperationRow.waiting_event_type/started_at/updated_at`; `Proposal.requires_review/publishable`; `STATUS_BADGE` | P09 | confirmado_por_codigo |
| P2-04 | Accesibilidad y usabilidad no medidas | Sin estudio de tareas ni auditoría WCAG en este corte | P09/P12 | no_verificable |
| P2-05 | Segundo motor legacy `trigger_workflow` aún alcanzable por admin de plataforma | `src/platform/workflows/workflows.py:440-452`; `src/api/routes/platform.py:3308` | P11 | confirmado_por_codigo |

## Cerrado o ya funcional (no reimplementar)

| Capacidad | Evidencia | Nota |
|---|---|---|
| `WorkflowInstance` con snapshot congelado, WAIT y RESUME | `instances.py:490-720`, `:929-991`, `:1382-1479`; `tests/test_workflow_durable_instances.py` | El núcleo durable funciona; el gap es la promoción desde triggers |
| Dedupe de señales por índice único | `154_workflow_signals.py:46-55`; `instances.py:1075-1106` | Evita doble resume del mismo evento |
| Webhook de pagos con inbox | `commerce_provider_events` (`src/platform/commerce/store.py:307-327`); `payments/service.py:776-807` | La única semántica inbox fuerte del repo |
| Clasificación run-level de efectos `NONE/SIMULATED/DECLARED/UNVERIFIED` | `src/platform/workflows/effect_verification.py` (WIP) + tests | No equivale a certificación de proveedor |
| Catálogo canónico `/api/v1/products` | `src/platform/marketplace/` | El canvas aún usa rutas contextuales (P1-08) |
| Baseline de certificación documentado | `docs/architecture/universal-studio/12-release-gold.md` | Sigue NO-GO; no se reescribe en P00 |

## Diferencias con `03-gap-matrix.md`

- Se confirma U-01 (publicación ignora certificación), U-02 (niveles de prueba
  no verificables), U-03 (triggers no crean instancia) y U-06 (bienestar sin
  enforcement).
- U-07 (planner) queda `no_verificable` en P00: no se ejecutó el dataset
  universal en este corte.
- U-26 (suite de certificación) no se declara verde; el resultado real se
  registra en `00-baseline.md`.

## Plan de PRs y gates (sin duplicar autoridades)

Un PR por etapa; se puede dividir si el gate se mantiene íntegro. Ningún PR
crea un segundo engine, planner, scheduler, tienda, registro de agentes,
memoria o conjunto de rutas de publicación.

| Etapa | PR | Reutiliza | Gate de salida |
|---|---|---|---|
| P00 | Auditoría + docs + rojos | `tests/`, docs existentes | Baseline registrado; P0 reproducible; sin cambios de runtime |
| P01 | `release_policy` único + certificados persistidos | `versions.py`, `test_report.py`, `readiness.py`, migración aditiva | Ninguna ruta productiva activa sin certificado vigente; STALE y tenant/workspace denegados |
| P02 | Ingress router durable + inbox/outbox | `engine.py`, `instances.py`, `workflow_signals`, scheduler existente | Trigger con WAIT crea instancia; duplicado/reinicio no duplica efectos |
| P03 | Solution compiler | `studio/{contracts,solutions,roles,templates}.py`, `architect*`, `plan_compiler` | Misión → solución draft con agente, workflow y bindings reales; repetir no duplica |
| P04 | Planner 2.0 | `planner_session.py`, `architect_validator`, `json_output` | ≥95% grafos válidos en casos resolubles con presupuesto declarado; 100% fail-closed |
| P05 | PEP transversal | `studio/policy.py`, `nodes.py`, `runtime.py`, `composition.py` | Toda capacidad sensible denegada sin permiso efectivo; workspace y rol aplicados |
| P06 | Contexto/RAG/memoria | `context_assembler.py`, `data_mapper.py`, `context_store.py`, memoria existente | Continuidad consentida verificable; revocación y borrado; sin fuga cross-tenant |
| P07 | Subflujos y contratos de error | `composition.py`, `nodes.py`, `node_catalog.py`, `ir.py` | Subflujo con snapshot alterado o privilegios elevados = DENY; WAIT durable o bloqueo explícito |
| P08 | Test Studio verificable | `test_report.py`, `workflow_simulation.py`, `design_sessions.py`, portal | Nivel backend real; fake no genera PROVIDER_VERIFIED; v3 no certifica v4 |
| P09 | UX universal | Portal existente | Usuario no técnico completa misión, prueba y corrección sin JSON/UUID |
| P10 | Marketplace único | `/api/v1/products`, `capability_registry`, portal | Instalación solo en marketplace; retorno conserva nodo y revisión |
| P11 | Ops Console | `instances.py`, `operations.py`, `Operations.tsx` | Filtros backend, timeline redactado, retry seguro, sin duplicar pagos |
| P12 | Certificación horizontal | Suite E2E + evidencia | 6/6 Gold en su entorno, invariantes 100%, reinicio real, rollback probado; decisión GO humana |
