# P20-13 — Architect y plantilla de checkout

- **Estado:** PARTIAL. La plantilla está publicada y validada; el draft
  asistido contra recursos reales no se ejecutó en este corte.
- **Plantilla:** `retail_checkout_manual`, migración 181.
- **Snapshot:** `src/infrastructure/db_init/seeds/retail_checkout_manual.json`.
- **Validación:** `validate_graph_from_dict` sobre el grafo vivo y test de
  snapshot congelado.

## Qué queda listo para Architect

- La plantilla aparece en `GET /api/v1/workflows/templates`.
- Se instala con `POST /api/v1/workflows/templates/retail_checkout_manual/install`.
- Declara dependencias reales (`sales.cart.get`, `sales.order.create`,
  `bodega.order.create`, `bodega.stock.reserve_batch`,
  `bodega.stock.commit_batch`, `payments.manual.validate`,
  `conversation.send`).
- El grafo es acíclico y usa nodos registrados.

## Pendiente

- Probar un draft generado por Architect que conecte recursos reales del
  workspace y pase el validador sin intervención manual.
- Añadir la plantilla al catálogo del Marketplace con producto propio si se
  quiere instalar desde la vitrina.
