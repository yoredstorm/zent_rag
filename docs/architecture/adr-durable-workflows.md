# ADR — Procesos de negocio durables sobre el motor v2 (FASE Durable)

Estado: aceptado
Fecha: 2026-10-16
Autores: arquitectura de workflows

## Contexto

`execute_graph` + `WorkflowGraph` v2 ejecutan DAGs con retries, timeouts,
aprobaciones y parciales (`run_mode`, `preloaded`). Un run bloqueado en
`pending_approval` ya demuestra la suspensión sin worker. Pero el motor no
representaba **procesos de negocio vivos**: conversaciones de venta por
WhatsApp/chat, pagos, esperas de horas o días, donde el mismo cliente continúa
un proceso y cada mensaje no puede reinterpretarse desde cero.

Problemas observados:

- Un run no congela la definición: un resume relee `workflows.graph` vivo.
- No existe entidad de proceso: `workflow_runs` mezcla ejecución y estado.
- No hay inbox de eventos: un webhook puede llegar antes del wait.
- No hay concepto de estado de negocio portable y durable.
- No hay paquete portable de workflows ni bindings de capacidades por tenant.

## Decisiones

### D1 — WorkflowInstance como entidad durable; el run es un segmento

`workflow_instances` (153) guarda definición congelada (`definition_snapshot` +
`workflow_version`), estado de negocio (`state` JSONB con CAS `state_version`),
checkpoint del wait y expiración. `workflow_runs.instance_id/instance_seq`
(nullable) liga cada segmento. Los runs existentes sin instancia no cambian.

Alternativas descartadas: reutilizar el mismo run para todos los segmentos
(timeline sucio, `completed_at` engañoso, resume clásico acoplado); tabla de
checkpoints separada (el estado de negocio ya es el checkpoint).

### D2 — WAIT es una primitiva; ningún proceso espera

`NodeOutcome.waiting` + control `wait_event`. El runtime persiste
outputs/contexto/checkpoint y termina el segmento (`status="waiting"`).
`human_approval` conserva su control pero se expresa como el mismo WAIT en
instancias (`approval.decided`). Cero `asyncio.sleep` largos, cero polling,
cero procesos vivos.

### D3 — La reanudación reutiliza la ejecución parcial existente

El resume es un segmento nuevo `run_mode=full` con:
`preloaded` = union de steps exitosos de todos los segmentos de la instancia,
`resolve_preload_edges=True` (los edges de preloaded se re-derivan, incluido el
puerto real del wait, persistido en el step) y `graph_override` = snapshot.
El scheduler determinista continúa desde el próximo nodo: **cero
re-ejecución**. Alternativa descartada: `run_mode=node` con `entry_override`
(Fase 3 de Studio) — sirve para debug, pero su filtro de ancestros y su check
de faltantes no cubren forks/joins acumulados.

### D4 — Signals con inbox durable y exactly-one-winner

`workflow_signals` (154) con uniques parciales por `external_event_id` e
`idempotency_key`. El claim `UPDATE ... WHERE status='WAITING' RETURNING`
garantiza un único ganador. Si no hay waiter, el signal queda `pending` y el
wait lo consume al entrar (carrera webhook-antes-de-WAIT). La correlación se
normaliza a `k=v&k2=v2` y se valida también en el camino directo.

### D5 — Un scheduler, un bus

El sweep de timeouts/expiración vive en `workflow_v2_scheduler_loop` (60s). El
consumer de `rag:events` despierta instancias con correlaciones estándar del
payload. No se creó segundo scheduler ni segundo bus.

### D6 — Versión congelada por instancia

Una instancia nace con su versión; publicar v8 no muta procesos v7. La
migración explícita de instancias vivas queda como política futura (fuera de
alcance v1): opciones barajadas para el futuro — re-ejecutar desde checkpoint
con validación de contrato, o clonar la instancia, nunca mutar en caliente.

### D7 — El LLM propone, el workflow aplica

Estado de negocio solo por nodos deterministas (`state_*`, `capability_call`);
nunca prompts como almacenamiento. La respuesta conversacional sale de nodos
(llm/notify) y el runtime la devuelve al caller del segmento.

### D8 — Portabilidad por capacidades + binding por tenant

El paquete (`zent.workflow.package/v1`) declara capacidades/eventos/permisos
sin secretos ni IDs de tenant. El binding (`workflow_capability_bindings`, 155)
resuelve la capacidad al proveedor del tenant. Import en dos fases
(inspect/import) y gate de publicación; el Studio muestra verde/amarillo/rojo
con CTA al Marketplace global.

## Consecuencias

- `execute_graph`/`run_workflow`/`workflow_runs` mantienen contrato: solo
  parámetros opcionales nuevos, default = comportamiento previo.
- `decide_approval` es dual: con instancia → signal; sin instancia → resume
  clásico intacto.
- Deuda declarada: expiración de `workflow_approvals` sin sweeper; retención de
  signals; migración planificada de instancias.
- La API puede reiniciarse en cualquier momento: WAIT es durable y la
  continuación solo necesita la señal (probado en
  `tests/test_workflow_durable_instances.py`).
