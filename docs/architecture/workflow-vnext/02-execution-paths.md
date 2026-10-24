# 02 — Mapa de ejecución real

Corte: `0cbb494ce4` + árbol de trabajo con WIP declarado en `00-baseline.md`.
Método: lectura de rutas, servicios, modelos y llamadas; los puntos marcados
`hipótesis` no se ejecutaron en este corte. Los comandos y resultados del
baseline están en `00-baseline.md`.

## 1. Autoridades únicas verificadas

| Dominio | Autoridad | Evidencia |
|---|---|---|
| Grafo y ejecución | `WorkflowGraph` v2 + `execute_graph` | `src/platform/workflows/ir.py:203`, `runtime.py:206` |
| Proceso durable | `workflow_instances` + `WorkflowInstance` | `src/platform/workflows/instances.py:145`, `src/infrastructure/db_init/versions/153_workflow_instances.py:30` |
| Señales | `workflow_signals` (inbox Postgres) | `src/infrastructure/db_init/versions/154_workflow_signals.py:27` |
| Roles | `role_profiles` + versiones | `src/platform/studio/roles.py:32`, migración 163 |
| Soluciones | `studio_solutions` + versiones | `src/platform/studio/solutions.py:25`, migración 163 |
| Agentes | tabla `agents` + `role_profile_id` | `src/platform/studio/roles.py:32-105` |
| Catálogo | `/api/v1/products` | `src/platform/marketplace/` |
| RBAC tenant | `require_permission` | `src/platform/rbac/policy.py` |

No existe un segundo engine, planner, scheduler, tienda ni registro de agentes
en las rutas auditadas.

## 2. Tabla de superficies

| Superficie | Entrada | Servicio | Persiste | Gate de release | Versión | Estado resultante |
|---|---|---|---|---|---|---|
| Proponer rol | `POST /api/v1/studio/roles/propose` `studio.py:142` | `propose_role` `roles.py:227` | Nada | Ninguno | N/A | Borrador en respuesta |
| Crear rol | `POST /api/v1/studio/roles` `studio.py:160` | `create_role` `roles.py:254` | `role_profiles` + versión | Ninguno | semver + revisión | `draft` por defecto |
| Vincular rol | `POST /api/v1/studio/agents/{id}/role` `studio.py:318` | `link_agent_role` `roles.py:583` | UPDATE `agents` | Ninguno | rol activo únicamente | Link |
| Crear solución | `POST /api/v1/studio/solutions` `studio.py:337` | `create_solution` `solutions.py:142` | `studio_solutions` + versión | Ninguno | semver + revisión | `draft` |
| Plan Architect | `POST /api/v1/workflows/architect/plan` `workflows.py:223` | `plan_workflow` `architect.py:891` | Nada | Validación de plan | N/A | Plan + grafo |
| Guardar draft | `POST /api/v1/workflows/architect/draft` `workflows.py:1157` | `save_architect_draft` `architect.py:1073` → `create_workflow` `engine.py:809` | `workflows` | Revalidación Architect | `workflow_version` | `draft` |
| Editar workflow | `PATCH /api/v1/workflows/{id}` `workflows.py:1713` | `update_workflow` `engine.py:957` | `workflows` (grafo + metadata) | Ninguno | sin bump | Conserva estado |
| Publicar | `POST /api/v1/workflows/{id}/publish` `workflows.py:2093` | `publish_workflow` `versions.py:497` + `release_policy` | `workflow_versions` + `workflows.status` | Certificado + readiness + lock de fila | snapshot `production` con `certificate_id` | `active` |
| Activar | `POST /api/v1/workflows/{id}/activate` `workflows.py:1750` | `activate_workflow` `release_policy.py` + lock | `workflows.status` | Certificado + readiness + workspace | N/A | `active` |
| Ejecutar manual | `POST /api/v1/workflows/{id}/run` `workflows.py:1779` | `run_workflow` `engine.py:307` | `workflow_runs` | Solo bloquea `paused` | versión de fila | `succeeded/failed/...` |
| Iniciar durable | `POST /api/v1/workflows/{id}/instances` `workflows.py:1807` | `start_workflow_instance` `instances.py:490` | `workflow_instances` + run | Solo bloquea `paused` | snapshot congelado | `RUNNING/WAITING/...` |
| Schedule | loop `engine.py:1595` | `run_due_scheduled_workflows` `engine.py:1523` → `run_workflow` | `workflow_runs` | `status=active` | versión de fila | Efímero |
| Hook de arranque | `POST /api/v1/public/workflows/{id}/hook` `workflows.py:2417` | `run_workflow_from_hook` `engine.py:1616` | `workflow_runs` | `status=active` + secreto | versión de fila | Efímero |
| Event trigger | consumer `events.py:317` | `dispatch_event_to_workflows` `events.py:187` → `run_workflow` | `workflow_runs` | Solo trigger activo; no exige workflow activo | versión de fila | Efímero |
| Conversación | `conversation_router.py:41` | `signal_workflow_instance` `instances.py:1052` | `workflow_signals` + segmento | Instancia WAITING existente | snapshot de instancia | Reanuda |
| Aprobación humana | `workflows.py:1441` | `decide_approval` `engine.py:1711` | `workflow_approvals` + señal | Permiso `workflow_approvals:approve` | run/instancia | Reanuda/pending |
| Importar paquete | `POST /api/v1/workflows/import` `workflows.py:1680` | `import_workflow_package` `packages.py:516` | `workflows` | Inspección del paquete | `draft` | `draft` |
| Restaurar versión | `POST /api/v1/workflows/{id}/versions/{vid}/restore` `workflows.py:2044` | `restore_version` `versions.py:241` | `workflows` (live) | Ninguno; puede pisar activo | copia snapshot | Estado de la versión |
| Promover versión | `POST /api/v1/workflows/{id}/versions/{vid}/promote` `workflows.py:2025` | `promote_version` `versions.py:197` | `workflow_versions` | Transición de estado | etiqueta `production` | No cambia workflow |

## 3. Recorridos detallados

### 3.1 Rol

`POST /studio/roles/propose` es una función pura: no abre sesión de BD ni hace
INSERT (`roles.py:227-251`). Devuelve `role` en `draft`, `mission_sheet` y un
`workflow_proposal` textual con `draft_only: true` (`templates.py:205-216`).
No crea rol, agente, workflow, solución ni binding.

`POST /studio/roles` crea una fila en `role_profiles` y su snapshot en
`role_profile_versions` (`roles.py:270-313`). `link_agent_role` solo actualiza
`agents.role_profile_id` (`roles.py:610-613`). El runtime aplica el rol a un
agente en `nodes.py:2004-2008` y en `/agents/{id}/run` (`agent_runs.py:48-53`),
pero no existe PEP equivalente para `capability_call`, `notify`,
`business_result`, `query_business_data`, `state_*` ni subflujos.

### 3.2 Solución

`SolutionV1` es un documento con referencias lógicas; `_relations` valida
coherencia interna, no existencia física (`contracts.py:428-457`).
`create_solution` guarda blueprint + snapshot y hace commit (`solutions.py:142-188`).
P03 agregó la ruta de materialización: `POST /studio/solutions/compile` hace el
dry-run y `POST /studio/solutions/materialize` crea/reutiliza rol, agente y
workflow draft con idempotencia; el estado vive en
`studio_solution_materializations` (migración 167). `GET /install-plan` sigue
siendo solo una proyección del blueprint (`studio.py:478-495`). Detalle en
`05-p03-solution-compiler.md`.

### 3.3 Architect y draft

`plan_workflow` no persiste (`architect.py:904`). `save_architect_draft`
revalida el plan, recompila, exige grafo no bloqueado y llama a
`create_workflow` (`architect.py:1151-1230`). El workflow queda `draft`.
`create_workflow` abre su propia transacción (`engine.py:857-889`); el vínculo
con la design session se guarda en otra transacción (`design_sessions.py:675-690`).
Un nodo `llm` sin agente no bloquea el draft: el validador emite warning
(`architect_validator.py:355-365`) y `design_state` ignora warnings
(`architect_observability.py:175-183`). En runtime ese nodo devuelve eco
(`nodes.py:2050-2065`).

### 3.4 Edición y publicación (actualizado en P01)

`PATCH /workflows/{id}` acepta `graph` y `metadata` del cliente
(`engine.py:1018-1030`), pero la metadata reservada (`certification`,
`require_certification`, `release_certificate`) ya no es evidencia: el gate la
elimina antes de hashear. `publish_workflow` bloquea la fila con
`SELECT ... FOR UPDATE`, consulta portabilidad/Architect y luego llama a
`release_policy.evaluate_release`; solo con ALLOW inserta la versión
`production` con `certificate_id` y activa el workflow
(`versions.py:497-...`, `release_policy.py`).

`activate` usa `activate_workflow`: lock de fila, gate único y UPDATE en la
misma transacción. `promote` a production y `restore` de un workflow activo
evalúan el snapshot destino con `target_graph_decision`. Los certificados se
persisten en `workflow_certificates` (migración 164) y se emiten por
`POST /workflows/{id}/certifications`; el cliente no puede declarar hashes ni
estado. Detalle y límites en `03-p01-release-gate.md`.

### 3.5 Disparadores

| Disparador | Función | ¿Abre instancia durable? | Evidencia |
|---|---|---|---|
| Manual `/run` | `route_ingress` → instancia si WAIT/approval/loop; si no `run_workflow` | Sí cuando el grafo lo exige | `ingress.py`, `workflows.py:1779-1829` |
| Manual `/instances` | `start_workflow_instance` | Sí | `workflows.py:1832-1870`, `instances.py:490` |
| Schedule | `route_ingress(trigger="schedule")` | Sí cuando el grafo lo exige; inbox por epoch | `engine.py:1523-1596` |
| Hook de arranque | `route_ingress(trigger="webhook")` | Sí; duplicado por clave reutiliza instancia | `engine.py:1637-1665` |
| Event trigger | `route_ingress(trigger="event")` | Sí; requiere workflow activo | `events.py:255-287` |
| Conversación | `signal_workflow_instance` | Solo reanuda | `conversation_router.py:41-81` |
| Pago | `signal_workflow_instance` | Solo reanuda | `payments/service.py:961-987` |
| Aprobación | señal o `run_workflow(resume=True)` | Reanuda si hay instancia | `engine.py:1781-1835` |

El ingress durable se implementó en P02. Un grafo sin WAIT/approval/loop sigue
ejecutando efímero y conserva el contrato anterior. Dentro de una instancia,
`wait_event` suspende el worker y `human_approval` queda WAITING hasta la señal.
Detalle en `04-p02-durable-ingress.md`.

### 3.6 Instancia durable, WAIT y RESUME

`start_workflow_instance` congela `definition_snapshot` (grafo, versión,
trigger, editor state) e inserta `RUNNING` (`instances.py:561-599`). El registro
de `workflow_runs` queda ligado por `instance_id`/`instance_seq`. `_enter_wait`
cambia a `WAITING`, guarda correlación, deadline y `wait_seq`
(`instances.py:929-991`). `signal_workflow_instance` deduplica por índices
únicos (`instances.py:1075-1097`), reclama la instancia con UPDATE condicional
(`:1402`) y ejecuta el siguiente segmento con el snapshot congelado
(`:1465-1472`). `sweep_waiting_instances` maneja timeout, expiración, reaper y
retención (`:1893-2035`).

Límites conocidos: no hay presupuesto por instancia; un segmento `RUNNING`
interrumpido no se adopta, el reaper lo marca `FAILED`; el evento Redis
`rag:events` es pub/sub sin replay; no hay outbox.

### 3.7 Import, restore, promote y plantillas

`import_workflow_package` crea un `draft` copiando el grafo y su metadata del
paquete (`packages.py:559`); no activa, y publicar después exige gate.
`restore_version` de un workflow activo exige certificado del snapshot destino
(`target_graph_decision`). `promote_version` a `production` también lo exige.
Ninguna de estas rutas crea un certificado por sí sola ni reescribe instancias
vivas: la instancia mantiene su snapshot congelado.

## 4. Efectos externos y rollback

| Efecto | Punto | Idempotencia | Rollback |
|---|---|---|---|
| `api_call` | `nodes.py:1404` | clave de nodo + correlación; depende del proveedor | compensación no automática |
| `capability_call` | `nodes.py:3513` | binding/proveedor | no hay saga general |
| `marketplace_action` | `nodes.py:3734` | proveedor | no hay saga general |
| Pago | `payments/service.py` | inbox `commerce_provider_events` + `workflow_signals` | conciliación manual |
| Notificación | `nodes.py:2711` | no | no aplica |
| Resultado de negocio | `nodes.py:3931` | no | no aplica |

No se declara `exactly once` universal. La única zona con semántica de inbox
fuerte es el webhook de pagos (`commerce_provider_events`, dedupe por proveedor
y evento).

## 5. Diferencias con la documentación previa

- `docs/architecture/universal-studio/README.md` cita la migración 162; el HEAD
  tiene 163.
- `docs/architecture/ai-workflow-studio/14-workflow-simulation.md:202-213`
  declara que la certificación no se persiste ni se integra al gate; sigue
  siendo cierto en este corte.
- `docs/architecture/universal-studio/03-gap-matrix.md` marca avance parcial de
  `effect_verification` a nivel run; se confirma en el WIP, pero no cambia el
  gate de publicación.

## 6. Hipótesis no ejecutadas en P00

- La carrera exacta entre timeout y callback en producción no se reprodujo en
  este corte.
- La pérdida de eventos durante caída de Redis se deduce del pub/sub sin
  replay; no se ejecutó un chaos test.
- El comportamiento de dos réplicas del scheduler no se ejecutó; no hay
  advisory lock en `run_due_scheduled_workflows`.
