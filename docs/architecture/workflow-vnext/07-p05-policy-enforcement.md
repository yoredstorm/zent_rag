# 07 — P05: Policy Enforcement real

Fecha: `2026-10-23`.
Base: `0cbb494ce4` + P00–P04.

## 1. PEP único

`src/platform/workflows/policy_enforcement.py` es la frontera de autorización de
cada nodo. Combina, sin crear una autoridad paralela:

1. permisos RBAC ya resueltos en `ExecutionContext.permissions`;
2. capacidades declarativas del nodo (`reads_db`, `writes_db`,
   `calls_external`, `calls_agent`, `sends_notification`, `needs_approval`);
3. `RoleProfile` del agente cuando el nodo declara `agent_id`;
4. guardrail de bienestar (no clínico).

La decisión es fail-closed: si falta un permiso, el rol no permite la capacidad,
o el rol es regulated/wellness y la acción es clínica o de escritura, el nodo
termina `denied` y el run falla. No hay efecto lateral silencioso.

`nodes._CAPABILITY_PERMISSION` ahora exige `workflows:run` para nodos internos
(`notify`, `business_result`, `query_business_data`, `state_*`) y mantiene
`external_actions:execute`, `agents:execute` e `integrations:use` para los
nodos externos. Un caller con permisos vacíos ya no puede notificar ni escribir.

## 2. Rol, autonomía y bienestar

- `capability_decision` se consulta en runtime, no solo en el endpoint de
  agentes.
- `allowed_capabilities`, `denied_capabilities`, `allowed_tools` y
  `autonomy_level` recortan; nunca amplían.
- `answer_only`/`propose_actions` no ejecutan escrituras.
- `wellness_companion` no ejecuta `clinical.*`, `medical.*`, diagnóstico,
  prescripción ni escrituras autónomas.
- Cada decisión emite `policy.decision` con tenant, workspace, actor, nodo,
  capacidad, agente, rol, resultado, motivos y correlation_id. No registra
  prompts ni secretos.
- Aprobaciones: el solicitante no puede decidir su propia aprobación. El owner
  conserva un break-glass explícito (`allow_owner_self_approval`) para no
  bloquear organizaciones de un solo operador; queda auditado por la decisión
  y debe revisarse en P11.

## 3. Workspace isolation

- `list_instances` filtra por `workspace_id` cuando el request lo declara.
- Detalle, timeline, señal, cancelar, suspender y reanudar validan el workspace
  de la instancia; un workspace ajeno recibe 404 sin revelar existencia.
- `signal_workflow_instance` valida el workspace antes de insertar la señal; el
  inbox no acepta señales de un proceso ajeno.
- `POST /workflows` rechaza un `workspace_id` que no pertenece a la
  organización.
- Soluciones: la lectura ya filtraba workspace; el flujo normal exige el
  workspace resuelto por request.

## 4. Pinning de rol

Al iniciar una `WorkflowInstance`, `definition_snapshot.policy_snapshot`
congela, por agente LLM, su `role_profile_id` y el payload completo del rol. El
runtime usa ese rol congelado; un cambio de rol en vivo no amplía permisos de
una instancia que ya está en WAIT. La revocación explícita de una capacidad
crítica queda separada del pinning y se operará en P06/P11.

## 5. Pruebas

| Comando | Resultado |
|---|---|
| `pytest tests/test_policy_enforcement.py tests/test_workflow_workspace_isolation.py -q` | **7 passed** |
| `pytest` policy/workspace/approvals/action-plane/RBAC/tenant | **56 passed** (164.73 s) con `junit-p05.xml` |
| `pytest tests/test_workflow_values.py tests/test_workflow_conditions.py tests/test_workflow_join_merge.py tests/test_workflow_context.py tests/test_workflow_node_catalog.py tests/test_workflow_semantic_v2.py tests/test_workflow_cognitive_investigate.py tests/test_workflow_composition.py -q` | **110 passed** |
| `pytest tests/test_workflow_composition.py tests/test_workflow_graph.py tests/test_workflows.py -q` | **41 passed** |
| `pytest tests/test_solution_compiler.py::test_materialized_instance_pins_role_version -q` | **1 passed** |
| `pytest tests/test_workflow_durable_instances.py tests/test_workflow_durable_ingress.py -q` | **33 passed + 1 flaky**; el test de sweep pasó al reintentarse solo (timing) |
| `ruff check` P05 | OK |

Casos cubiertos: notify sin `workflows:run` → DENY; notify con permiso →
simulado; `capability_call` fuera del allowlist del rol → DENY; bienestar con
capacidad clínica → DENY; autoaprobación denegada salvo break-glass explícito
del owner; listado/detalle/señal cross-workspace → 404; creación con workspace
ajeno → 403; instancia durable congela rol y versión.

## 6. Límites

- La memoria (`src/memory`) quedó con workspace/sujeto/consentimiento en P06.
- No hay endpoint de revocación explícita de capacidades críticas todavía.
- El mapa de permisos cubre los nodos del catálogo actual; un nodo nuevo debe
  declarar su capability y añadirse al mapa.
- La política de aprobación humana requiere el flujo existente de approvals;
  P05 no crea un segundo registro de aprobaciones.
- El break-glass del owner permite autoaprobar; no se probó con un segundo
  usuario real porque el helper de tests solo crea al owner. La regla directa
  (`self_approval_denied`) sí está cubierta; el flujo HTTP con dos usuarios
  queda `NOT_VERIFIED` hasta P11.
- No se ejecutó un proveedor real ni una prueba de carga multi-tenant.

## 7. Rollback

1. Revertir `policy_enforcement.py` y el uso en `runtime.py`.
2. Revertir el mapa de permisos de nodos y los filtros workspace.
3. Revertir `policy_snapshot` en instancias; las instancias históricas
   conservan el campo y el runtime vuelve a leer el rol vivo.
4. No hay migración de datos en P05.

## 8. Dictamen

**GO P05 para staging controlado.** Todo nodo sensible pasa por el PEP, el rol y
la autonomía se aplican, y el workspace se valida en lectura/acción. **NO-GO
release:** memoria por workspace (P06), revocación explícita y certificación
horizontal P12 siguen pendientes.
