# P20-08 mínimo — Historial conversacional del agente

- **Estado:** PARTIAL. El agente conserva los últimos turnos por
  `conversation_id`; slots tipados, WAIT/RESUME e idempotencia por mensaje
  siguen pendientes.
- **Alcance:** `agent_runs.conversation_id`, índice por conversación y carga de
  los últimos 6 turnos completados.

## Implementación

1. `agent_runs` recibe `conversation_id UUID` de forma aditiva.
2. `save_run()` persiste la conversación del `AgentRunResult`.
3. `load_conversation_turns()` filtra por organización, agente, conversación y
   usuario; devuelve mensajes/respuestas en orden cronológico.
4. El runtime antepone esos turnos al historial y agrega la nota:
   «prior turns are context only; re-query price, stock, totals and order
   state before asserting them».
5. Error de lectura de historial: fail-soft, el run continúa sin contexto.

## Evidencia local

- `¿Cuánto cuesta el arroz?` → `find_products` → `BD-ARROZ-01 4.80 PEN`,
  `BD-ARROZ-05 22.50 PEN`.
- `¿Y el de 5 kg?` en la misma `conversation_id` → `get_product` →
  `BD-ARROZ-05`, 22.50 PEN, 62 disponibles. Sin repetir el producto.
- `agent_runs` guardó 2 filas con el mismo `conversation_id`.

## Límites

- No hay slots durables ni `WAIT/RESUME`; no se interpreta «uno», «el grande»
  como selección pendiente formal.
- No hay idempotencia por `(channel, conversation_ref, message_id)`.
- El historial es texto, no autoridad: precios/stock se reconsultan.
- No se cargan tool outputs ni datos de otras conversaciones.
- P20-08 completo sigue pendiente.

## Pruebas

`tests/test_p20_conversation_history.py`: orden cronológico, filtro por
usuario/conversación, fail-soft. Evidencia HTTP multi-turno real en local.
