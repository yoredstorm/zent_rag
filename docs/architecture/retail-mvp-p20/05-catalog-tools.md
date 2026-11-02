# P20-05 — Tools comerciales read-only y contratos tipados

- **Estado:** PARTIAL. `find_products`, `get_product` y
  `get_price_and_stock` implementadas y conectadas al agente. Carrito,
  quote, checkout, pedidos y fidelidad siguen pendientes (P20-10..12).
- **Autoridad:** precio, moneda, stock y total de línea se calculan en
  backend/BD. El LLM solo recibe JSON y redacta.

## Tools

| Tool | Args | Salida |
|---|---|---|
| `find_products` | `query`, `category?`, `unit?`, `max_results?` | lista con `sku`, `name`, `category`, `unit`, `price`, `currency`, `available` |
| `get_product` | `sku` | `FOUND`, `NOT_FOUND` o `MULTIPLE_MATCHES` |
| `get_price_and_stock` | `sku`, `quantity` | `FOUND`, `OUT_OF_STOCK`, `INSUFFICIENT_STOCK`, `NOT_FOUND`; incluye `line_total` decimal |

Las tres leen `bodega.product_catalog_v.available = on_hand - reserved`.
No aceptan SQL, tabla, columna, conexión ni precio desde el texto del
cliente. `find_products` busca por nombre/SKU con términos normalizados
(`arroz de 1 kg` resuelve `BD-ARROZ-01`).

## Grants

Cada tool exige grant P20-04 sobre `bodega.product_catalog_v` con la
capability específica (`store.products.search`, `store.product.get`,
`store.price.get`, `store.stock.get`) o el grant genérico
`store.query_database`. Sin grant: `PERMISSION_DENIED`.

## Evidencia local

- `find_products("arroz")`: `BD-ARROZ-01 4.80 PEN 53`, `BD-ARROZ-05 22.50
  PEN 62`.
- `find_products("arroz de 1 kg")`: solo `BD-ARROZ-01`.
- `get_price_and_stock("BD-ARROZ-01", 2)`: `line_total = 9.60`.
- Stock insuficiente: `INSUFFICIENT_STOCK`, sin inventar disponibilidad.
- Sin grant: `PERMISSION_DENIED`; con grant restaurado: responde datos reales.

## Pruebas

`tests/test_p20_catalog_tools.py`: precio/stock backend, `line_total`
decimal, `NOT_FOUND` sin error 500, `PERMISSION_DENIED`, normalización de
presentación. `tests/test_p20_external_sql_query.py`: grants y aislamiento.

## Pendiente

- `get_cart`, `add_cart_item`, `set_cart_quantity`, `remove_cart_item`,
  `quote_cart`, `get_my_order`, `get_my_loyalty`, `request_checkout`,
  `request_human_handoff`.
- Contratos JSON Schema completos en `ToolResult` (`status`, `data`,
  `provenance`, `binding_hash`, `duration_ms`, `is_fresh`, `disclosure_level`)
  más allá de `output/meta/error` actuales.
- Persistencia de `price_as_of` desde una columna real; hoy se expone
  `observed_at` (momento de consulta) porque la vista no tiene timestamp.
- Idempotencia de tool calls y presupuesto por turno.
