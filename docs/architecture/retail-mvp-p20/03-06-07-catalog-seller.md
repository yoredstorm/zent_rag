# P20-03/06/07 — Catálogo comercial y creación de vendedor

- **Estado:** IMPLEMENTED backend. Wizard UI: PARTIAL (el endpoint existe; la
  pantalla no se trabajó en este corte).

## P20-03 — Manifiesto comercial

`src/platform/commerce/catalog_manifest.py` publica
`GET /api/v1/commerce/catalog/manifest`:

- entidad `product` con clave `sku`;
- campos y tipos (`price` decimal, `available` entero, `unit`);
- autoridad explícita: producto/precio/stock en Bodega, carrito/orden en ZENT;
- reglas de presentación (`1 kg` vs `5 kg`) y prohibiciones:
  precio inventado, stock estimado, total en prompt, pedidos de otra
  conversación;
- capabilities de lectura, carrito y checkout.

No copia datos ni crea tablas: es un contrato revisable y testeable.

## P20-06 — Crear vendedor

`POST /api/v1/agents/retail-seller` crea un agente con:

- tools: catálogo, precio/stock, carrito y postventa;
- prompt retail con reglas de autoridad;
- `source_ids` de la fuente externa;
- `runtime.tool_routing=false`;
- grants explícitos sobre `bodega.product_catalog_v`;
- TTL de carrito configurable.

La fuente se valida contra `catalog_sources` por organización y workspace. Si
no pertenece, responde 422.

## P20-07 — Prompt y grounding

`RETAIL_SELLER_PROMPT` prohíbe inventar precios/stock, obliga a confirmar el
carrito antes de la orden, exige `get_my_order` para postventa y prohíbe leer
otras conversaciones o mostrar SQL/prompts/tokens.

## Pruebas

- `tests/test_p20_retail_seller.py`: manifiesto, grants, prompt, creación con
  repo fake.
- Prueba de API pendiente: `POST /agents/retail-seller` contra una fuente real
  y UI wizard. Se declara NOT_RUN.

## Límites

- No hay pantalla de wizard; el endpoint está listo para conectarla.
- No hay edición posterior del manifiesto desde Studio; el contrato es código
  versionado.
- La aprobación de cambios de manifiesto es organizacional, no UI.
