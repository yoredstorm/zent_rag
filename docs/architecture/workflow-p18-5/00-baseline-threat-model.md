# P18.5-00 — Baseline forense, modelo de amenazas y matriz de gates

## Identidad del baseline

| Dato | Valor |
|---|---|
| Repositorio | https://github.com/yoredstorm/zent_rag |
| Rama creada | `fix/p18-5-security-execution-live-studio` |
| HEAD de trabajo | `e6c42c2579df0e997ef2a0a0d0916f05dc735bef` (= baseline P18.4) |
| Diff contra baseline al iniciar | vacío |
| Estado del árbol | limpio |
| CI del baseline | NOT_RUN en este entorno (no hay `gh` ni credenciales de CI) |
| Entorno local | Windows, Python 3.11.16, Postgres/Redis/Qdrant en Docker, API/portal ya levantados antes de la fase |
| Pruebas base ejecutadas | `tests/test_workflow_test_studio.py`, `tests/test_workflow_test_report.py`, `tests/test_workflow_workspace_isolation.py`, `tests/test_workflow_effective_policy.py` → 20 passed |

El baseline reproduce los defectos descritos abajo. No se declara certificación de
producción: el CI verde histórico no acredita autoridad real ni efectos externos.

## Mapa de autoridad (entrada → efecto)

```
webhook/API/UI
  └─ route_ingress (ingress.py)
      ├─ workflow_runs  ── workflow_versions (published, certificado)
      └─ workflow_instances (definition_snapshot + policy_snapshot)
            └─ run_workflow (engine.py)
                 └─ resolve_effective_policy (effective_policy.py)
                      └─ authorize_node (policy_enforcement.py)
                           ├─ RBAC / scope / rol / revocaciones
                           ├─ aprobación (hoy: config.approval_ref)
                           └─ nodo (_exec_llm, api_call, capability_call…)
```

Frontera de autoridad: **backend**. El payload, `approval_ref`, metadata del LLM
y nombres de nodo nunca son autoridad. La única autoridad es la fila persistida
(workflow, versión, instancia, política, aprobación) resuelta en servidor.

### Dónde se crea y valida una aprobación

| Paso | Archivo | Observación |
|---|---|---|
| Creación | `src/platform/workflows/nodes.py::_create_approval` | Inserta en `workflow_approvals` desde el nodo `human_approval`. |
| Decisión | `src/platform/workflows/engine.py::decide_approval` | Actualiza estado y reanuda por señal. |
| Uso como gate | `src/platform/workflows/policy_enforcement.py::authorize_node` | **Solo comprueba que `node.config.approval_ref` sea truthy**. No resuelve la fila, no valida actor/scope/expiración/estado. |
| Señal de reanudación | `src/platform/workflows/instances.py::_claim_and_resume` | El payload de la señal se publica como salida del nodo WAIT; el run continúa. |

**Hallazgo P0 reproducido:** un `approval_ref="approved"` arbitrario satisface el
gate. El string no tiene vínculo con `workflow_approvals`.

## Traza de agentes (P18.5-01)

`resolve_agent(agent, snapshot)` en `src/platform/deployments/versions.py` usa
verdad booleana (`or`) en lugar de presencia de clave:

```python
system_prompt=snapshot.get("system_prompt") or agent.system_prompt,
tools=list(snapshot.get("tools") or agent.tools or []),
model=snapshot.get("model") or agent.model,
```

Reproducción ejecutada:

```
snapshot: tools=[], system_prompt="", model="pinned"
agente live: tools=["api_call"], system_prompt="LIVE_PROMPT"
resultado actual: tools=['api_call'], prompt='LIVE_PROMPT', model='pinned'
resultado esperado: tools=[], prompt="", model='pinned'
```

Esto permite que una edición viva **amplíe** herramientas y cambie el propósito
de una instancia ya iniciada. El snapshot certificado de `tools=[]` no es
ejecutable como tal.

### `_exec_llm`

`src/platform/workflows/nodes.py::_exec_llm` busca la entrada pinneada en
`instance.policy_snapshot.agents`. Si existe, llama `resolve_agent` (bug arriba).
Si no existe, usa el agente vivo y solo escribe un warning: una instancia legacy
puede ejecutar herramientas vivas sin certificación. No verifica el hash del
snapshot contra la entrada pinneada. El rol se toma de la entrada pinneada si
existe; si no, del rol vivo (el rol solo restringe, pero el snapshot no).

## Traza de revocaciones (P18.5-04)

| Momento | Consulta `workflow_policy_revocations` | Evidencia |
|---|---|---|
| Inicio de instancia | Sí, al construir `resolve_effective_policy` | `instances.py::start_workflow_instance` |
| Reanudación WAIT/RESUME | **No**: `resolve_effective_policy` retorna `instance_policy` sin overlay | `effective_policy.py:306-310` |
| Antes de capacidad sensible | **No**: solo usa `policy.revoked_capabilities` congeladas | `policy_enforcement.py:193-196` |
| Caída de PostgreSQL | **Falla abierto**: `_revocations` captura toda excepción y retorna `set()` | `effective_policy.py:284-286` |

**Hallazgo P0 reproducido por inspección + prueba negativa:** una capability
revocada durante `WAITING` sigue permitida al reanudar. Una caída de la tabla de
revocaciones se interpreta como “sin revocaciones”.

## Aislamiento de workspace (P18.5-02)

| Ruta | Filtro actual | Riesgo |
|---|---|---|
| `GET /api/v1/workflows/runs/{run_id}` | Solo `organization_id` (JOIN workflows) | Lee runs de otro workspace con el UUID. **P0** |
| `GET /api/v1/workflows/runs/{run_id}/approvals` | `organization_id` + run_id; workspace opcional | Con workspace B devuelve 200/lista vacía; no revela contenido, pero no aplica 404 por recurso. |
| `POST /runs/{run_id}/approvals/{id}/decide` | Valida workspace de la aprobación, pero aprobaciones con `workspace_id NULL` pasan | Decisión cruzada en legado. |
| `GET /{workflow_id}/runs` | Middleware `_validate_workflow_workspace` por path | Correcto para workflow; `list_runs` no filtra workspace en SQL. |
| `GET /{workflow_id}/sample-outputs` | Middleware + `workflow_id` en query | El `run_id` se acota al workflow; correcto, pero depende del middleware. |
| `GET /instances/{id}` y `/timeline` | `get_instance(..., workspace_id=...)` | Correcto; `instance_timeline` interno no recibe workspace pero se llama tras validar. |
| `POST /instances/{id}/signal` | `get_instance` con workspace | Correcto. |

`_workspace_id` valida que el workspace exista en la organización, pero **no**
que el actor tenga una relación explícita con ese workspace. ZENT no tiene tabla
de membresía por workspace: la política de producto es que un miembro de la
organización puede operar cualquier workspace de su organización. Se documenta
como decisión explícita; el RBAC de acción sigue siendo obligatorio.

## Semántica de rutas y relaciones

- `workflow_runs.instance_id` → `workflow_instances.id` (segmento durable).
- `workflow_instances.last_run_id` → último segmento.
- `workflow_run_steps` pertenece a un run; `workflow_run_events.seq` es la
  secuencia persistida del timeline.
- `workflow_signals` se consumen al reanudar; `resumed=true` **no** implica que
  la instancia terminó.
- `GET /runs/{run_id}` devuelve el detalle del segmento; no el estado durable.
- `GET /instances/{id}` devuelve estado durable (`RUNNING`, `WAITING`,
  `COMPLETED`, `FAILED`, `SUSPENDED`, `EXPIRED`).
- `POST /instances/{id}/signal` encola/consume una señal; puede devolver
  `resumed=false` si la instancia no estaba esperando.

## Amenazas registradas

| ID | Amenaza | Superficie | Estado inicial |
|---|---|---|---|
| T01 | Snapshot `tools=[]`/`prompt=""` hereda configuración viva | `resolve_agent` | Reproducido (P0) |
| T02 | Edición de agente entre load y ejecución (TOCTOU) | `_exec_llm` | Hipótesis verificada por inspección |
| T03 | Lectura cruzada de run por UUID | `GET /runs/{id}` | Reproducido (P0) |
| T04 | `approval_ref` falsificado autoriza efecto irreversible | PEP | Reproducido (P0) |
| T05 | Revocación durante WAIT no se aplica al reanudar | `resolve_effective_policy` | Reproducido (P0) |
| T06 | Caída de tabla de revocaciones = fail-open | `_revocations` | Reproducido (P0) |
| T07 | Replay/doble clic de run real | `/run` + frontend | Parcial: middleware opcional, frontend genera key nueva por request |
| T08 | Input de test (texto) distinto del payload real (JSON) | `/test` vs `/run` | Documentado; UI avisa, backend no incluye snapshot explícito |
| T09 | Historial atribuye resultados a grafo actual | `WorkflowTestHistory` | Reproducido por inspección: no compara hash |
| T10 | WAIT/RESUME no se observa en vivo | `useWorkflowTestRunner` | Reproducido: un solo GET tras POST |
| T11 | Timeline truncado a 1000 sin cursor | `instance_timeline` | Reproducido por inspección |
| T12 | `flowPreview` presenta orden de almacenamiento como recorrido | `workflowTestPresentation` | Reproducido por inspección |
| T13 | Doble decisión de aprobación / self-approval | `decide_approval` | Parcial: self-approval cubierto, doble decisión devuelve `already` |
| T14 | Rol degradado durante espera | RBAC actor | Parcial: no se reevalúa al reanudar con actor usuario |

## Gates

`gates.json` define el estado inicial. Ningún gate pasa a PASS sin prueba
ejecutada y evidencia. Este documento se actualiza con SHA y resultados reales
al cierre de cada fase.

## Límites del entorno

- No se ejecutaron efectos externos reales, cobros, correos ni webhooks
  productivos.
- Redis/Postgres locales se usaron para pruebas de integración; no equivalen a
  staging.
- No hay aprobación de proveedor ni pentesting en esta fase.
- La UI se validará con build de producción y Playwright local; no se declara
  certificación visual de staging.
