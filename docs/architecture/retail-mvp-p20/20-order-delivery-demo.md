# Pedido, cliente y delivery simulado (P20)

- **Usuario:** `ppimentel@omnio.pe`
- **Organización:** `e42d1f42-b87d-4baf-88dc-ec3da1541239`
- **Workspace:** `074a851b-f056-4d16-9ccd-ceaddc387305`
- **Workflow:** `81442b7c-0f87-4903-bd80-1dcfde7477d0`
- **Plantilla:** `retail_order_delivery_demo`
- **Estado:** `draft` (ejecutable manualmente; publicar exige certificación de release)

## Qué hace

Un pedido simulado entra con `customer_ref`, `sku`, `quantity`, `delivery` y
`address`.

Decisiones del flujo:

1. ¿Hay stock suficiente?
2. ¿El cliente tiene pedidos previos?
3. ¿Es delivery o recojo?
4. Si es delivery, ¿hay dirección?
5. ¿Una persona aprueba el pago simulado?

La venta queda en `bodega.orders`. El stock se reserva y se confirma en
`bodega.stock`. El delivery es una rama y un `BusinessResult`; no escribe
`sales.orders` ni usa un courier real.

## Piezas instaladas

### Conectores

- Lector: `ce1eeb5f-b287-4716-809a-61903e63482d` (`p19_reader`).
- Escritor: `1fdf8b76-8115-4b4d-86a0-4c962bd86988` (`p19_writer`).

### Bindings

- `bodega.product.get` (`connected_db`, lector).
- `p19.customer.orders` (`connected_db`, lector).
- `bodega.order.create` (`inventory`, escritor).
- `bodega.stock.reserve_batch` (`inventory`, escritor).
- `bodega.stock.commit_batch` (`inventory`, escritor).
- `bodega.stock.release_batch` (`inventory`, escritor).

### Archivos

- `src/platform/commerce/order_delivery_demo.py`: grafo, plantilla y payload.
- `ops/p19-external/create_order_delivery_workflow.py`: instalación idempotente.
- `tests/test_p20_order_delivery_demo.py`: validación del grafo y del estado durable.

## Cómo ejecutarlo

Abrir `/workflows/81442b7c-0f87-4903-bd80-1dcfde7477d0` y usar **Probar** con:

```json
{
  "customer_ref": "CUST-A",
  "sku": "BD-ARROZ-01",
  "quantity": 2,
  "delivery": true,
  "address": "Av. Demo 123",
  "order_number": "SIM-CUST-A-120024",
  "currency": "PEN"
}
```

`order_number` debe ser único por corrida. El script imprime un payload con
sufijo aleatorio para evitar conflictos.

El flujo se detiene en **Validar pago simulado**. Aprobar en la bandeja de
aprobaciones continúa: confirma stock, elige delivery o recojo y publica el
resultado.

## Evidencia

### Delivery, cliente recurrente

- Instancia: `58d2ee82-1fa5-426f-9360-718e3f07d477`
- Run 1: `894f0bfb-f4d0-1f6e-4516-512865a50c93`
- Aprobación: `1d90d1f8-e7d8-4563-a22b-f1703b451981`
- Pedido: `SIM-CUST-A-120024`
- Total: `9.60 PEN`
- Estado final: `confirmed / paid`
- Stock `BD-ARROZ-01`: `40 -> 38`
- Nodos: `stock_ok`, `recurrente`, `delivery_check`, `address_check`,
  `marcar_delivery`, `crear_pedido`, `reservar`, `aprobacion`, `commit`,
  `entrega_final`, `aviso_delivery`, `resultado`
- BusinessResult: `37a912da-9231-4457-932f-677713ea9831`
  `Pedido SIM-CUST-A-120024 · 9.6 PEN · CUST-A · recurrente · delivery`

### Recojo, cliente nuevo

- Instancia: `95ac0e6b-4a19-4b91-a12d-55c650ae757d`
- Run: `cde87dd0-2ff0-d317-2c77-7cd00b663466`
- Pedido: `SIM-CUST-NEW-120129`
- Total: `4.80 PEN`
- Nodos: `marcar_nuevo`, `marcar_recojo`, `aviso_recojo`
- BusinessResult: `8cd7230b-b03b-43e0-a760-68a687c35e37`
  `Pedido SIM-CUST-NEW-120129 · 4.8 PEN · CUST-NEW · nuevo · pickup`

### Sin stock

- Instancia: `40b8d42f-31dc-4416-a585-04b1789de18a`
- Nodo `sin_stock`; no se creó pedido.

### Delivery sin dirección

- Instancia: `6c8e5ef0-433f-42ab-b85c-38514aabe65f`
- Nodo `sin_direccion`; no se creó pedido.

## Canvas

Los nodos reciben posiciones deterministas en el grafo. Si un workflow importado
o creado por API no trae `position`, el Studio aplica `layoutGraph` antes de
pintar. Sin eso, el canvas calculaba paths SVG con `NaN` y quedaba bloqueado.

## Límites

- No hay cobro real. La aprobación humana es la simulación de pago.
- El delivery no persiste en `sales.orders`; solo rama y resultado de negocio.
- Si se rechaza la aprobación, el run falla y la reserva queda activa hasta su
  TTL (`900` segundos). No hay compensación automática en esta versión.
- El conector escritor tiene permisos de escritura en `bodega.*`. Es un conector
  demo, no de producción.
- Publicar el workflow exige el gate de release; para la demo se ejecuta en
  `draft` con permiso `workflows:run`.
- El run del primer segmento queda en `pending_approval`; la instancia durable
  es la autoridad y queda `COMPLETED` después de aprobar. Los segmentos
  posteriores aparecen como runs `succeeded`.
