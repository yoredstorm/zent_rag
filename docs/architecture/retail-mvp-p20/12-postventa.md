# P20-12 — Postventa con ownership por conversación

- **Estado:** IMPLEMENTED para órdenes ZENT del MVP.
- **Tool:** `get_my_order`.
- **Regla:** una orden solo se devuelve si su `conversation_id` coincide con la
  conversación autenticada. Un número ajeno no revela existencia: la tool
  responde `NOT_FOUND`.
- **Órdenes Bodega históricas:** `IDENTITY_REQUIRED`. No se leen sin principal
  verificado; queda para el corte de identidad real.

## Flujo

1. El agente recibe «¿cuál es el estado de mi pedido?».
2. `get_my_order` busca la última orden de `ctx.conversation_id`.
3. Si el cliente da un número, se busca por `order_number` y se compara el
   `conversation_id`; si no coincide, `NOT_FOUND`.
4. La respuesta incluye estado, total, moneda, ítems, `payment_status`,
   `payment_reference` y fechas.
5. La evidencia se registra como `commerce_order`, no como documento.

## Pruebas

- `tests/test_p20_cart.py::test_get_my_order_tool_blocks_other_conversations`.
- HTTP local: la conversación dueña devolvió `PAID` con el pedido real.
- HTTP local: otra conversación con el mismo número devolvió `NOT_FOUND` y no
  expuso datos.

## Límites

- No hay OTP/cuenta de cliente final; la identidad es la conversación.
- No se consultan pedidos históricos de Bodega sin principal.
- No hay devoluciones ni reclamos; solo lectura de estado.
