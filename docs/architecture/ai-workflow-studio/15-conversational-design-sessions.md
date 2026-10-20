# 15 — Sesiones conversacionales de diseño (Prompt 07)

## Objetivo

Convertir el diseño de workflows en una conversación persistente sin crear un segundo
motor, scheduler, cola o runtime. La sesión de diseño describe y versiona el **plan**; la
ejecución sigue viviendo en `WorkflowInstance`, `execute_graph()` y `run_workflow()`.

## Separación de estados

| Estado | Dónde vive | Uso |
|---|---|---|
| Sesión de diseño | `workflow_design_sessions` | Requerimiento, mensajes, plan, grafo, readiness y revisiones |
| Revisión de diseño | `workflow_design_revisions` | Snapshot inmutable del plan/grafo/validación por cambio |
| Mensaje | `workflow_design_messages` | Conversación del usuario con Zent |
| Workflow borrador | `workflows` + `workflow_versions` | Resultado de “Guardar borrador” |
| Instancia en ejecución | `workflow_instances` | Ejecución durable; nunca se muta al editar el diseño |

Una sesión cerrada no acepta mensajes, simulación ni guardado. Se puede reabrir sin
perder mensajes ni revisiones.

## Persistencia y concurrencia

Cada sesión conserva:

- `organization_id`, `workspace_id`, `user_id` y `original_prompt`;
- `revision` monotónica;
- `plan`, `graph`, `plan_hash` y `capability_snapshot_hash`;
- `state_json` con requisitos, decisiones, clarificaciones, supuestos, recursos,
  capacidades, validación, readiness y el último `proposal`;
- mensajes y revisiones separados.

Toda mutación usa `expected_revision`. Si otra pestaña ya guardó, el backend responde
`409 DESIGN_SESSION_CONFLICT` con `current_revision`; el portal recarga la sesión en vez
de sobrescribirla. Restaurar una revisión crea una **nueva** revisión (`kind=restore`), no
reescribe el historial.

## API

| Método | Ruta | Efecto |
|---|---|---|
| `POST` | `/api/v1/workflows/architect/sessions` | Crea sesión y ejecuta el planner inicial |
| `GET` | `/api/v1/workflows/architect/sessions` | Lista sesiones del usuario/workspace |
| `GET` | `/api/v1/workflows/architect/sessions/{id}` | Detalle, mensajes y revisiones |
| `POST` | `/api/v1/workflows/architect/sessions/{id}/messages` | Corrección conversacional directa (compatibilidad) |
| `POST` | `/api/v1/workflows/architect/sessions/{id}/patch-preview` | Genera y valida el diff sin persistirlo |
| `POST` | `/api/v1/workflows/architect/sessions/{id}/patch-apply` | Aplica el diff confirmado sin volver a llamar al LLM |
| `POST` | `/api/v1/workflows/architect/sessions/{id}/restore` | Restaura una revisión como revisión nueva |
| `POST` | `/api/v1/workflows/architect/sessions/{id}/close` | Cierra la sesión |
| `POST` | `/api/v1/workflows/architect/sessions/{id}/reopen` | Reabre la sesión |
| `POST` | `/api/v1/workflows/architect/sessions/{id}/simulate` | Certifica con escenarios reales del backend |
| `POST` | `/api/v1/workflows/architect/sessions/{id}/draft` | Re-valida y guarda un workflow borrador |

Los endpoints de sesión siguen usando las rutas canónicas del Architect; no hay planner,
validador ni compilador paralelo.

## Patch semántico

El patch se aplica sobre `SemanticPlan`, nunca sobre el Canvas. Operaciones soportadas:

- `set_param`, `set_trigger`, `set_schedule`;
- `set_condition` (`when`: paso + outcome);
- `set_policy` (`retries`, `timeout_seconds`, `on_error`, `idempotency`);
- `set_outputs`;
- `replace_agent`;
- `replace_capability` (capacidad lógica + inputs; sin credenciales ni ids físicos);
- `remove_step` con reescritura de dependencias;
- `add_step` (incluye `wait`, `loop`, `human_approval`, `capability_call`).

La UI usa `patch-preview` para mostrar el diff semántico (`added`, `removed`, `modified`,
campos antes/después) y re-ejecutar validación estática y compilación sin persistir. Solo
después de “Confirmar y aplicar” llama a `patch-apply`, que vuelve a validar el mismo patch
contra la revisión esperada; el LLM no participa en la confirmación. Un
`SensitivePatchError` rechaza cualquier intento de escribir credenciales, secretos,
permisos, roles, providers o bindings físicos. Esos cambios se resuelven en
Integraciones/Mapping Studio.

## Interfaz

`ArchitectAskZent` usa la misma sesión y el mismo estado canónico en tres modos:

- **Simple**: conversación, resumen del proceso, aclaraciones y resultado.
- **Guiado**: capacidades, recursos, requisitos, readiness y revisiones.
- **Avanzado**: plan JSON, flujo compilado y acceso al Canvas existente.

La conversación muestra mensajes persistidos. “Corregir por conversación” envía un patch;
“Mis diseños” permite cerrar y reabrir una sesión. “Guardar borrador” y “Abrir en el
Canvas” llaman al backend; publicar y activar siguen siendo acciones explícitas separadas.

## Simulación

La sesión usa `simulate_semantic_plan()` y `execute_graph(simulate=True)`. El resultado se
persiste en la revisión de simulación. El modo avanzado permite enviar escenarios JSON y
ejecutar la simulación; la UI solo muestra el estado y los resultados devueltos por el
backend. Un resultado parcial o con nodos externos no verificados nunca es publicable. La
simulación no escribe en DB ni dispara efectos externos reales.

## Evidencia

- `tests/test_workflow_design_sessions.py`: persistencia, conflicto optimista, preview sin
  persistir, aplicación confirmada, restauración, cierre/reapertura, simulación, guardado y
  API conversacional.
- `tests/test_workflow_architect_patch.py`: patch de condición, política, salidas,
  capacidad, `wait`/`loop`, rechazo de credenciales/permisos y diff semántico.
- `ArchitectAskZent.test.tsx`: sesión conversacional, preview + confirmación de patch,
  certificación de simulación y guardado con revisión esperada.

## Límites conocidos

- No se ejecutó un LLM real ni un proveedor externo real en esta fase.
- Cambiar un proveedor físico concreto requiere el binding/credencial del tenant en
  Mapping Studio/Integraciones; el plan portable no almacena secretos. El patch rechaza
  `provider`, credenciales, permisos y bindings, y muestra la configuración pendiente.
- “Solicitar aprobación”, “Publicar” y “Activar” siguen en el WorkflowStudio sobre el
  workflow ya guardado; no se ejecutan desde la conversación ni después de una respuesta
  del LLM.
- El gate de publicación de workflows existentes todavía no consume automáticamente la
  certificación de la sesión; el borrador y la certificación están persistidos, pero la
  integración con el gate queda como siguiente paso.
- No hay presencia colaborativa en tiempo real; la concurrencia se resuelve por revisión.
