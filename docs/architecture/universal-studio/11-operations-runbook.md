# Runbook de procesos durables

La consola vive en `/operations`. Lee `workflow_instances` y `workflow_signals`. No crea estados ni un bus nuevo. El worker sigue siendo `workflow_v2_scheduler_loop`. La señal entra por `workflow_signals`.

Métrica: `zent_workflow_operations_total{event}` con `workflow_start`, `workflow_success`, `workflow_failure`, `workflow_waits`, `workflow_expired`, `workflow_cancelled`. Si Prometheus no está importable, el proceso sigue y la métrica no se finge.

## Qué hacer

| Situación | Qué hace el motor | Qué hacer |
| --- | --- | --- |
| API o worker se reinician con un WAIT | El segmento ya terminó. La instancia queda `WAITING`. El proceso no está en memoria. | No relanzar el run. Esperar la señal o el timeout del scheduler. |
| Redis caído | El inbox de Postgres sigue siendo la fuente de la señal. El bus `rag:events` puede atrasarse. | No marcar el pago como hecho. Recuperar Redis y reinyectar solo con la misma `idempotency_key`. |
| Webhook duplicado | `signal_workflow_instance` responde `duplicate` y no reanuda. | Confirmar el `signal_id` ya consumido. No cobrar otra vez. |
| Señal antes del WAIT | Queda `pending` en el inbox. Al entrar en WAIT, `_consume_pending_for_instance` la toma una vez. | No insertar una segunda señal. |
| DB lenta | El claim `WAITING` a `RUNNING` es el que gana. El otro recibe `already_claimed`. | Reintentar la lectura. No abrir otra instancia con la misma `business_key`. |
| Timeout de pago y callback a la vez | Un solo claim reanuda. El otro no ejecuta el efecto. | Mirar un solo `consumed`. Si no hay proveedor, el ensayo queda `UNVERIFIED`. |
| Última unidad, muchos clientes | El stock lo decide la capacidad de inventario, no el prompt. | No confirmar venta si `inventory.stock.get` no respondió. |
| LLM caído | El nodo de decisión no inventa el pase. | Dejar `FAILED` o `UNVERIFIED`. Escalar a humano con suspender. |

## Acciones

Cancelar, suspender y reanudar exigen `workflows:run` y quedan en el API que ya existía. Reproducir un pago o un mensaje solo vale en sandbox (`sandbox_replay_allowed`). En producción esa acción no está autorizada.

## Rollout

La consola no reescribe `definition_snapshot`. Apagarla es quitar el enlace `/operations`. Las instancias vivas siguen en su versión congelada. No hace falta una migración nueva.

## NO-GO

No cerrar un ensayo de caos como éxito si Redis, la base o el proveedor no respondieron. `chaos_observation` devuelve `UNVERIFIED` y `passed: false`.
