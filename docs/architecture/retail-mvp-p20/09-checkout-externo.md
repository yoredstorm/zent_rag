# P20-09/11 — Checkout externo y pago manual MVP

- **Estado:** IMPLEMENTED y probado E2E en local.
- **Plantilla:** `retail_checkout_manual` (migración 181).
- **Nodo de pago:** `manual_payment_validation` (temporal, bloqueado en
  producción).
- **Autoridad:** ZENT es autoridad de carrito/orden; Bodega es autoridad de
  stock. `bodega.orders` es una proyección idempotente para reservar/commitear.

## Grafo

1. `trigger_webhook` recibe `conversation_id`, `customer_ref` y operación.
2. `sales.cart.get` lee el carrito temporal de la conversación.
3. Si hay items, `sales.order.create` cierra el carrito en una orden ZENT
   `AWAITING_PAYMENT` con precios backend.
4. `bodega.order.create` proyecta la orden a `bodega.orders` y sus items.
5. `bodega.stock.reserve_batch` reserva stock real con TTL.
6. `conversation.send` envía instrucciones de pago manual.
7. `manual_payment_validation` pausa el run y espera aprobación humana.
8. `sales.order.mark_paid` marca la orden ZENT `PAID` con
   `provider=manual_mvp`.
9. `bodega.stock.commit_batch` confirma stock y cierra la proyección.
10. `conversation.send` + `business_result` cierran el flujo.

Si el carrito está vacío, no se crea orden: se responde y termina.

## Acciones de inventario nuevas

`inventory_adapter.py`:

- `create_order`: upsert idempotente de la orden proyectada y sus items.
- `commit_order_stock`: commit atómico de todas las reservas activas.
- `release_order_stock`: release atómico de todas las reservas activas.
- `reserve_stock_batch`: ya existía; ahora tolera `items` serializados como
  JSON string desde el resolver del workflow.

Todas validan `write=true`, conector activo, workspace, límites de cantidad y
recalculan el total con `Decimal`.

## Evidencia E2E local

Ejecutado dentro del contenedor API con PostgreSQL externo real:

```text
run_status=pending_approval
order_status=PAID
payment_provider=manual_mvp
payment_reference=<approval_id>
total=9.60 PEN
stock commit=COMMITTED
```

Comando:

```powershell
docker cp ops/p20/e2e_checkout_manual.py rag-api:/tmp/e2e.py
docker exec rag-api python /tmp/e2e.py
```

## Configuración

Bindings necesarios en el workspace:

- `sales.cart.get`, `sales.order.create`, `sales.order.mark_paid` → `commerce`.
- `bodega.order.create`, `bodega.stock.reserve_batch`,
  `bodega.stock.commit_batch`, `bodega.stock.release_batch` → `inventory`.
- `conversation.send` → `conversation`.

`ops/p19-external/seed_tenant.py` ya crea los bindings de inventario nuevos.
`ops/p20/seed_checkout_manual.py` publica la plantilla sin esperar migración.

## Pendiente para producción

- Reemplazar el nodo manual por Stripe/PSP sandbox con webhook firmado,
  dedupe y conciliación.
- Cancelar/expirar orden y liberar stock si el pago no llega.
- Probar concurrencia de checkout y doble aprobación.
- UI de pagos manuales pendientes.
