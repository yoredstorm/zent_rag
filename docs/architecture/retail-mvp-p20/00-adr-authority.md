# P20-00 — ADR de autoridad por agregado

- **Estado:** propuesto, no certificado.
- **Regla:** un solo store autoritativo por agregado; toda otra copia es
  proyección, cache o snapshot explícito y nunca autoridad de dinero/stock.

## Decisiones

| Agregado | Autoridad MVP | Adapter/lectura | Escritura | Notas |
|---|---|---|---|---|
| Product | Bodega `bodega.products` | discovery + plans P19 | no desde ZENT | catálogo de tienda |
| Variant/Unit | Bodega `products.unit` | mapping semántico | no | “arroz 1 kg” vs 5 kg |
| Price | Bodega `bodega.products.price` / `catalog.product_prices` | plan `get_price` | no | NUMERIC, PEN; valid_from/to si existe |
| Stock | Bodega `bodega.stock` | `available = on_hand - reserved` | reservas vía `inventory_adapter` | row lock/TTL/ledger |
| Cart | ZENT commerce (`commerce_cart_*` temporal) | `sales.cart.*`/commerce store | sí | TTL por sesión; no se escribe en Bodega |
| Quote | ZENT commerce | cálculo server-side | sí | Decimal/centavos, revisión |
| Order | ZENT commerce para venta MVP; Bodega `orders` es histórica/consulta | `order.status` externo solo lectura | una sola autoridad por flujo | no doble escritura |
| Payment | ZENT simulado | provider abstracto | sandbox | nunca cobro real en MVP |
| Loyalty | Bodega `loyalty.loyalty_balances` si existe | plan read-only con ownership | no | sin identidad real: IDENTITY_REQUIRED |
| Knowledge snapshot | catálogo P19 | metadata discovery | no filas por defecto | snapshot explícito sólo si se implementa |

## Reglas de integración

1. `catalog.product_prices` es la vista/plan autorizado para precio; no se
   copia a `commerce` ni se acepta precio del LLM.
2. `bodega.stock` manda para disponibilidad. ZENT puede reservar, pero no
   mantener un segundo stock paralelo.
3. La orden del MVP se crea en ZENT commerce; si en el futuro se proyecta a
   Bodega, será outbox idempotente, no segunda autoridad.
4. La orden histórica de Bodega se consulta read-only para postventa; no se
   modifica desde el agente.
5. Cualquier divergencia stock/orden se bloquea y se reconcilia antes de
   confirmar. Nunca se “arregla” con una escritura silenciosa.

## Consecuencias

- P20-09 debe adaptar el funnel existente, no crear `commerce_orders` y
  `bodega.orders` como dos verdades.
- P20-10 debe usar quote/revisión y reservas existentes.
- P20-11 no puede marcar pago por texto del cliente; solo evento del adapter.
- P20-12 no puede leer pedidos sin principal verificado.
