# P20-10 — Carrito temporal por sesión

- **Estado:** IMPLEMENTED (backend, capacidades y tools del agente).
- **Tablas:** `commerce_cart_sessions`, `commerce_cart_items`,
  `commerce_cart_operations`.
- **Migración:** `180_commerce_cart_sessions.py` (aditiva, revisa 179).
- **Identidad:** `organization_id + workspace_id + cart_key`.
- **TTL:** configurable por workflow (`cart_ttl_seconds`) o por agente
  (`cart_ttl_seconds` / `cart.ttl_seconds`). Default 1 hora; rango 1 s a
  7 días.

## Por qué una tabla temporal y no memoria del proceso

El carrito debe sobrevivir a reinicios y a WAIT/RESUME del workflow, pero no
debe convertirse en una orden. Se guarda en Postgres con `expires_at`:

- cada mutación refresca el TTL (deslizante);
- cada lectura purga los carritos vencidos de la organización;
- un loop de la API (`_commerce_cart_cleanup_loop`) barre vencidos cada 60 s;
- al vencer, la sesión y sus líneas desaparecen por `ON DELETE CASCADE`.

No hay un segundo motor de carrito: se reutilizan las capacidades
`sales.cart.*`, el formato de totales con `Decimal` y el catálogo del tenant.

## Identidad de sesión

`cart_key` se resuelve en este orden:

1. `cart_key` explícito del workflow;
2. `conversation:<conversation_id>` para el agente conversacional;
3. `workflow:<workflow_instance_id>` para un proceso durable.

Las tools del agente usan además
`user:<user_id>:conversation:<conversation_id>`: dos usuarios no comparten
carrito aunque reutilicen el mismo `conversation_id`. El texto del cliente
nunca define la identidad. Sin ninguno de los tres, la operación falla con
`CART_SESSION_REQUIRED`.

## Capacidades

| Capacidad | Efecto | Precio |
|---|---|---|
| `sales.cart.get` | Lee el carrito y su cotización | recalculado |
| `sales.cart.add` | Agrega/incrementa una línea | catálogo backend |
| `sales.cart.set_quantity` | Fija cantidad de una línea existente | catálogo backend |
| `sales.cart.remove` | Quita una línea | n/a |
| `sales.cart.clear` | Vacía líneas sin cerrar sesión | n/a |
| `sales.cart.quote` | Cotiza `items` (sin persistir) o una sesión | catálogo backend |

Entradas relevantes:

```json
{
  "conversation_id": "{{trigger.conversation_id}}",
  "workflow_instance_id": "{{instance.id}}",
  "product_id": "{{nodes.buscar.output.products.0.product_id}}",
  "quantity": 2,
  "ttl_seconds": "{{variables.cart_ttl_seconds}}",
  "expected_revision": 3,
  "idempotency_key": "cart-add:{{instance.id}}:{{nodes.agregar.attempt}}"
}
```

`expected_revision` implementa compare-and-swap: si otro turno modificó el
carrito, la operación falla con `CART_REVISION_CONFLICT` en lugar de pisar
cantidades. `idempotency_key` se guarda en `commerce_cart_operations`; un
retry devuelve el mismo resultado con `idempotent_replay=true`.

## Precio y stock

- Línea interna (`product_id`/SKU del catálogo del tenant): el precio se lee
  de `commerce_products`; un `unit_price` enviado por el llamador se ignora.
- Línea externa (Bodega): solo se acepta con `source_id`, `price_source`
  externo y un precio ya resuelto por el backend autorizado. Las tools del
  agente consultan `bodega.product_catalog_v` en cada lectura; si la fuente no
  responde, fallan cerrado y no muestran total.
- El total se calcula con `Decimal` y se cuantiza a 2 decimales. El LLM nunca
  calcula ni corrige montos.

## Tools del agente

`cart_get`, `cart_add`, `cart_set_quantity`, `cart_remove`, `cart_clear`.

- Usan `ctx.conversation_id` como sesión.
- Comparten los grants de catálogo (`store.products.search`).
- Validan stock real antes de agregar/cambiar y ajustan contra lo que ya está
  en el carrito.
- Requieren `tool:query_database` (mismo permiso que las tools de catálogo).

## Configuración en workflow

`retail_sales_funnel` declara `cart_ttl_seconds` (default 3600) en
`DEFAULT_PARAMETERS` y en `configuration_schema`. En Workflow Studio se puede
sobrescribir por binding o por variable. Ejemplo de nodo:

```json
{
  "capability": "sales.cart.add",
  "inputs": {
    "conversation_id": "{{trigger.conversation_id}}",
    "product_id": "{{nodes.buscar.output.products.0.product_id}}",
    "quantity": "{{trigger.quantity}}",
    "ttl_seconds": "{{variables.cart_ttl_seconds}}"
  }
}
```

## Pruebas

`tests/test_p20_cart.py`:

- TTL acotado y clave de sesión obligatoria;
- suma Decimal (2 × 4.80 = 9.60) y mutaciones;
- vencimiento y purga real en Postgres;
- aislamiento por organización, workspace y conversación;
- recálculo de precio cuando cambia el catálogo (4.80 → 5.10);
- conflicto de revisión (CAS);
- idempotencia sin duplicar líneas;
- línea externa sin fuente autorizada rechazada;
- round-trip por capacidades `sales.cart.*`;
- ejecución real por `execute_binding` (`sales.cart.add`, provider `commerce`)
  con `cart_ttl_seconds=90` y total S/ 6.00.

Evidencia HTTP local con el agente `P19 Prueba ERP` y la fuente externa:

1. «agrega 2 arroz de 1 kg al carrito» → `find_products`, `cart_add` →
   `BD-ARROZ-01`, 2 kg, S/ 9.60.
2. «sube a 3 la cantidad de arroz» → `cart_set_quantity` → 3 kg, S/ 14.40.
3. «¿qué tiene mi carrito?» → `cart_get` → misma línea, total S/ 14.40.
4. «quita el arroz del carrito» → `cart_remove` → carrito vacío, S/ 0.00.
5. «agrega 10000 arroz de 1 kg» → `cart_add` falla con `INSUFFICIENT_STOCK`
   (disponible 53) y no crea sesión.

La sesión quedó en Postgres y fue visible por `conversation_id`; el total y el
stock salieron de `bodega.product_catalog_v`.

## Límites / pendientes

- P20-09 debe reemplazar el carrito en `instance.state.cart.items` del embudo
  por estas capacidades; hoy el embudo conserva su camino certificado.
- La orden (`sales.order.create`) todavía no consume directamente la sesión
  de carrito; P20-11 conecta checkout y cierre.
- No hay UI de carrito; el cliente lo ve por el agente y el operador por el
  workflow.
- La purga periódica corre en la API; si la API está caída, la purga perezosa
  sigue funcionando en la próxima lectura.
