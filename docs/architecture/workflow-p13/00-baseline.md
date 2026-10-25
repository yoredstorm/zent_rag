# P13 — 00 Baseline de realidad

Fecha de corte: `2026-10-25`.
SHA: `b31b01402a2e10008eb09b77c148e48120af6004`.
Rama: `master`.
Árbol: limpio (`git status --porcelain` vacío). `git diff b31b01402a2e..HEAD` vacío.

## 1. Entorno verificado

| Componente | Valor |
|---|---|
| HEAD | `b31b01402a2e10008eb09b77c148e48120af6004` |
| Migración head | `169_workflow_test_reports.py` |
| `ZENT_GOLD_RELEASE_ENABLED` | `false` (`src/core/config.py:202`) |
| Python | 3.11+ (`pyproject.toml`) |
| PostgreSQL/Redis | suite local disponible; estado real por comando |
| Qdrant/LLM/proveedor real | no usados en P00 |

## 2. Autoridades existentes

- `WorkflowGraph` v2: `src/platform/workflows/ir.py`.
- Runtime único: `src/platform/workflows/runtime.py`.
- Engine y ejecución: `src/platform/workflows/engine.py`.
- Instancias durables: `src/platform/workflows/instances.py`.
- Versiones: `src/platform/workflows/versions.py`.
- Gate de release: `src/platform/workflows/release_policy.py`.
- Ingress: `src/platform/workflows/ingress.py`.
- PEP: `src/platform/workflows/policy_enforcement.py`.
- Catálogo canónico: `/api/v1/products`.

No se crea un segundo engine, scheduler, planner, catálogo ni esquema por profesión.

## 3. Hechos de código que originan P13

### 3.1 Snapshot publicado

- `PATCH /api/v1/workflows/{id}` llama `update_workflow` (`routes/workflows.py:1949-1972`).
- `update_workflow` escribe `workflows.graph` sin comprobar publicación (`engine.py:1033-1068`).
- `run_workflow` resuelve el grafo con precedencia `graph_override` > `workflows.graph` > `steps` legacy (`engine.py:443-467`).
- Hook y schedule delegan en `route_ingress`, que lee la fila viva (`ingress.py:303-319`, `engine.py:1583-1597`, `engine.py:1680-1692`).
- `workflow_versions` no tiene puntero en `workflows`; `workflow_versions.status='production'` no lo consulta ningún camino de ejecución (`versions.py:109-127`, migración 109).
- `publish_workflow` bloquea `workflows`, pero relee el grafo con otra sesión (`versions.py:524-536`). Existe ventana TOCTOU con `PATCH`.
- `restore_version` copia el snapshot a la fila viva; `promote` no cambia lo ejecutado (`versions.py:197-357`).

### 3.2 Identidad de eventos

- `normalize_ingress_key` devuelve `webhook:{workflow}:{sha256(payload)}` o `event:{workflow}:{sha256(payload)}` (`ingress.py:106-121`).
- Misma clave con payload distinto devuelve `duplicate:true` sin comparar el hash (`ingress.py:340-352`).
- El inbox no relee `payload`; no hay worker que drene `pending` salvo reintento del cliente (`ingress.py:124-132`, `193-208`).
- No existe outbox: `grep -R "outbox" src/` = 0.
- El scheduler usa `sched:{workflow}:{epoch}` (`engine.py:1592`), no la ocurrencia programada.
- El bus Redis deduplica con TTL 60 s, GET+SET no atómico y sin `event_id` (`events.py:235-252`, `319-333`).

### 3.3 Policy efectiva

- `authorize_node` solo resuelve rol desde `node.config.agent_id` (`policy_enforcement.py:38-41`, `75-85`).
- Sin `agent_id`, el bloque de rol/autonomía/wellness no se ejecuta (`policy_enforcement.py:86-107`).
- `capability_call` y `notify` generados por `solution_compiler` no llevan `agent_id` (`solution_compiler.py:199-222`).
- `SYSTEM_NODE_PERMS` incluye `external_actions:execute`, por lo que esos nodos pasan el PEP con RBAC de sistema (`engine.py:279-287`).
- El snapshot de instancia solo congela agentes `llm`; no hay `EffectiveExecutionPolicy` (`instances.py:707-756`).
- `_run_branch` (for_each) llama `_run_node_once` sin PEP (`runtime.py:765-804`, `949-1000`).
- Los pasos cacheados de resume retornan antes del PEP (`runtime.py:393-403`).

### 3.4 Aislamiento

- `_workspace_id` toma el header sin validar pertenencia (`routes/workflows.py:27-47`; `workspaces/context.py:169-173`).
- Varias rutas por ID filtran solo organización, no workspace (`routes/workflows.py:1937-1983`, `2256-2345`, `2427-2433`).
- `workflow_versions` no tiene `workspace_id` (migración 109).
- `list_certificates` no filtra workspace (`release_policy.py:341-359`).
- Escrituras con `workspace_id` de body/header sin ownership: `architect/draft`, `import`, `templates/install`, `triggers`, `capability-bindings`.

### 3.5 Composer y certificación (P1)

- `compile_solution` elige siempre una de 6 plantillas (`templates.py:254-285`).
- `_build_graph` tiene ramas hardcodeadas y un else genérico (`solution_compiler.py:182-340`).
- `architect.plan_workflow` no está importado por `solution_compiler`.
- `sandbox_ready` se lee de `workflow["metadata"]`, clave que `get_workflow` no devuelve (`test_studio.py:252-256`).
- `provider_ready=False` literal; `issue_certificate` solo acepta design/simulation (`release_policy.py:840-843`).

## 4. Comandos ejecutados

```powershell
uv run --frozen --no-sync pytest tests/red/p13 -q --runxfail
# 7 failed: P01 edición/schedule, P02 identidad/conflicto/outbox, P03 policy.

uv run --frozen --no-sync pytest tests/test_workflow_published_snapshot.py tests/test_workflow_event_identity.py tests/test_workflow_effective_policy.py tests/test_workflow_p13_migrations.py -q
# 23 passed. JUnit: artifacts/certification/p13/junit-p13-core.xml

uv run --frozen --no-sync alembic upgrade head
# 169 -> 170 -> 171 -> 172 OK

uv run --frozen --no-sync python scripts/workflow_p13_audit.py
# active_missing_pointer=0, duplicate_production=0, published_hash_mismatch=0
```

Los archivos rojos se retiraron al pasar; las pruebas viven en las suites
permanentes listadas en `01-gap-register.md`.

## 5. Limitaciones

- No se ejecutó proveedor real, pago real, LLM real masivo, caos de Redis/PostgreSQL ni estudio de usabilidad.
- Playwright `portal/e2e/workflow-publication.spec.ts` queda `NOT_VERIFIED` hasta levantar API/portal.
- Los workflows activos legacy se congelaron en la migración 170; no se certificaron automáticamente.
- SHA después: `b31b01402a2e10008eb09b77c148e48120af6004` (cambios sin commit).
