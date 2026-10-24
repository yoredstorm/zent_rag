# 04 — P02: ingress durable e idempotencia

Fecha: `2026-10-23`.
Base: `0cbb494ce4` + P00/P01.
Alcance: manual, schedule, webhook y event triggers; inbox durable; no P03.

## 1. Decisión

Un único `src/platform/workflows/ingress.py` decide efímero vs durable. No hay
un segundo scheduler ni un segundo motor:

- Grafo con `wait_event`, `human_approval` o `loop` → `WorkflowInstance`.
- Grafo sin esas primitivas → `run_workflow` efímero, contrato anterior intacto.
- `route_ingress` es la entrada de `/run`, schedule, hook público y event bus.
- `/instances` sigue siendo el arranque manual explícito; acepta
  `Idempotency-Key` y lo usa como `ingress_key`.

## 2. Inbox y claves

Migraciones 165/166:

- `workflow_instances.ingress_key` + índice único
  `(organization_id, workflow_id, ingress_key)`.
- `workflow_ingress_events`: inbox con estado `pending|processing|processed|failed`,
  intentos, error, payload, `external_event_id`, `business_key` y correlación.
- La deduplicación es por workflow: la misma clave de dos workflows distintos
  no colisiona.
- `ingress_key` identifica el evento de entrada; `business_key` identifica la
  operación de negocio. No se confunden.
- El evento se registra antes de crear la instancia; si la creación falla, queda
  `failed` con error. Un claim huérfano (`processing`, sin instancia, >5 min) se
  devuelve a `pending` en el sweep del scheduler existente.

## 3. Flujos

| Trigger | `require_active` | Clave por defecto | Resultado durable |
|---|---|---|---|
| `/run` manual | No (draft permitido para probar) | `manual:<workflow>:<uuid>` si no hay explícita | Instancia WAITING/RUNNING |
| `/instances` manual | No | `Idempotency-Key` si viene | Idempotente por clave |
| Schedule | Sí | `sched:<workflow>:<epoch>` | Instancia por ocurrencia |
| Hook público | Sí | header `Idempotency-Key`/`X-Zent-Event-Id` o hash del payload por workflow | Duplicado devuelve la misma instancia |
| Event trigger | Sí | `evt:<workflow>:<event_id|ts|fingerprint>` | Duplicado no crea segunda instancia |
| Conversation message | Solo reanuda | señal existente | No inicia desde un workflow no vinculado |

La definición queda congelada en `definition_snapshot`; una edición o publicación
posterior no muta la instancia viva. El snapshot incluye `ingress.trigger`,
`ingress.ingress_key` y `business_key`.

## 4. Rechazos y aislamiento

- Organización distinta → 403, sin cargar la instancia.
- Workspace distinto → 403 cuando el workflow tiene workspace. La cobertura
  completa de listados/signals sigue en P05.
- Workflow pausado → `paused`; inactivo en schedule/hook/event → 409.
- Event trigger sobre workflow draft → no ejecuta (cierra P1-05).
- El hook público conserva la verificación HMAC del secret existente.

## 5. Pruebas

| Comando | Resultado |
|---|---|
| `pytest tests/test_workflow_durable_ingress.py -q` | **7 passed** (94.16 s) con `junit-ingress.xml` |
| `pytest` P02 + durable compat + event triggers | **10 passed** (125.78 s) |
| `pytest tests/test_workflow_durable_instances.py tests/test_workflow_approval_context.py tests/test_workflow_partial_runs.py -q` | **35 passed + 1 fallo corregido**; rerun del approval **1 passed** |
| `pytest tests/test_workflows.py tests/test_workflow_graph.py -q` | **25 passed + 1 fallo corregido**; approval durable rerun **1 passed** |
| `pytest tests/test_workflow_*.py` (440 tests) | **440 passed** (1667 s) con `junit-workflows.xml` |
| `pytest tests/certification/workflows/{gold_sales,durability_restart}` | **2 passed** (779.5 s) con `junit-gold-restart.xml` |
| `pytest tests/test_cognitive_workflows_e2e.py` | **3 passed** (74.89 s) |
| `pytest tests/test_studio_migrations.py tests/test_migrations.py tests/test_architecture.py tests/test_authority_ownership.py` | **29 passed** (76.73 s) |
| `pytest tests/red --runxfail` | **4 failed** (workspace y policy siguen abiertos) |
| `alembic upgrade head` | 163→164→165→166 aplicado en local |

Casos: manual WAIT crea instancia; schedule crea una sola instancia por epoch;
hook duplicado reutiliza instancia; event duplicado no duplica; event en draft no
ejecuta; claim huérfano se reencola; aprobación humana durable reanuda y completa
la instancia.

## 6. Límites

- Redis pub/sub sigue sin replay ni outbox. Para webhooks y schedule la señal ya
  vive en Postgres; un evento publicado mientras el consumer está caído puede
  perderse hasta P11. No se declara exactly-once del bus.
- El inbox cubre el arranque durable; los efectos externos conservan la
  idempotencia del proveedor y la inbox de pagos existente.
- No hay presupuesto por instancia (P1-10) ni política de actualización de
  instancias vivas entre versiones; se congela la definición.
- No se implementó compensación genérica ni outbox de efectos; queda P07/P11.
- P05 cerró workspace en listados/signals (`07-p05-policy-enforcement.md`).

## 7. Rollback

1. Revertir `ingress.py`, sus llamadas y las migraciones 165/166.
2. `alembic downgrade 164` elimina inbox e `ingress_key`; no toca workflows,
   versiones ni instancias históricas.
3. Los workflows existentes siguen ejecutando por `run_workflow` efímero.
4. Mantener `ZENT_GOLD_RELEASE_ENABLED=false`.

## 8. Dictamen

**GO P02 para staging controlado.** Triggers normales ya crean instancias
durables, la idempotencia de entrada vive en Postgres y la suite dirigida pasa.
**NO-GO release:** bus Redis sin replay, presupuesto por instancia y P05
(workspace) siguen abiertos; la suite completa/Playwright no se revalidó.
