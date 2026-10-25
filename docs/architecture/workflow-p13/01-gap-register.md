# P13 — 01 Gap register

Corte: `b31b01402a2e10008eb09b77c148e48120af6004`.
Estados: `confirmado_por_codigo`, `probado`, `cerrado`, `no_verificado`.

| ID | Severidad | Síntoma | Causa raíz | Reproducción | Fix | Estado |
|---|---|---|---|---|---|---|
| P13-P0-01 | P0 | Editar un workflow activo cambia la ejecución productiva sin publicar | `PATCH` escribía `workflows.graph`; runtime leía la fila viva; no había puntero publicado | `tests/test_workflow_published_snapshot.py::test_edit_active_workflow_keeps_published_execution` | Migración 170, `definition.py`, publish/activate atómicos, `definition_source` explícito | cerrado: probado (9 passed) |
| P13-P0-02 | P0 | Dos eventos legítimos con payload idéntico se colapsan; evento redelivered no distingue identidad | `normalize_ingress_key` usaba hash del payload; no comparaba hash al duplicar | `tests/test_workflow_event_identity.py` | Migración 171, `event_identity.py`, inbox/outbox, schedule occurrence | cerrado: probado (6 passed) |
| P13-P0-03 | P0 | Nodo sin `agent_id` evita la policy del rol; wellness no aplica | `authorize_node` solo resolvía rol si `node.config.agent_id` | `tests/test_workflow_effective_policy.py` | `EffectiveExecutionPolicy`, PEP en `_run_node_once`, scope congelado | cerrado: probado (7 passed) |
| P13-P0-04 | P0 | Lectura/escritura cross-workspace por ID y header no validado | `_workspace_id` no validaba ownership; versiones/certificados sin workspace | `tests/test_workflow_effective_policy.py::test_workflow_by_id_is_not_visible_from_other_workspace` | Dependencia central, `workflow_versions.workspace_id`, filtros | cerrado: probado |
| P13-P1-05 | P1 | Composer solo elige 6 plantillas; no compone misión nueva | `match_role_template` + `_build_graph`; Architect no conectado | P04 | Contratos y `compile_solution(mode)` | abierto; fuera de esta aprobación |
| P13-P1-06 | P1 | `sandbox_ready` no tiene fuente real; provider nunca se verifica | `workflow["metadata"]` inexistente; `provider_ready=False`; certificado sin adaptador | P05 | `VerificationAdapter` + evidencia inmutable | abierto; fuera de esta aprobación |
| P13-P2-07 | P2 | PATCH sin revisión; publicaciones concurrentes podían violar UNIQUE | Sin `If-Match`; `MAX+1` sin lock | `tests/test_workflow_published_snapshot.py::test_concurrent_publishes_keep_single_production` | `draft_revision`, lock, unique production | cerrado: probado |

## Matriz de dependencias

| Fase | Depende de | No puede cerrar si |
|---|---|---|
| P01 snapshot | Migración 170 | hook/schedule leen grafo vivo; WAIT pierde snapshot |
| P02 identidad | P01 (definición publicada) | dos eventos idénticos siguen colapsando; no hay 409 de conflicto |
| P03 policy | P02 (envelope/instancia) | nodo sin agente evade rol; workspace ajeno visible |
| P04 composer | P03 (policy/scopes) | genera nodos sin agente o capacidades inventadas |
| P05 verificación | P01/P04 | metadata o flag de cliente certifica |
| P06 GO | P01-P05 | algún gate real queda `NOT_VERIFIED` |

## Criterio de cierre

Una brecha solo pasa a `cerrado` con:

1. test que falla contra `b31b01402a2e`;
2. test verde final sin `xfail`, `skip` ni mock de la capa bajo prueba;
3. comando y JUnit en `artifacts/certification/p13/`;
4. `file:line` del cambio;
5. rollback documentado.
