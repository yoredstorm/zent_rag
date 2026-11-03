# P20-15 — Observabilidad de ventas y carrito

- **Estado:** IMPLEMENTED para KPIs de carrito; parcial para trazas de grants.
- **Endpoint:** `GET /api/v1/commerce/kpis`.
- **Datos:** instancias de workflow, órdenes por estado, revenue pagado,
  carritos activos/cerrados, items activos y carritos que expiran en 5 minutos.

## Qué se agregó

`cart_kpis()` en `src/platform/commerce/cart.py` y merge en la ruta de KPIs:

```json
{
  "carts": {
    "active": 1,
    "checked_out": 2,
    "expired": 0,
    "items_active": 3,
    "expiring_soon": 0
  }
}
```

## Trazas existentes

- `agent_runs.steps` registra cada tool (`cart_add`, `get_my_order`, etc.).
- `workflow_runs` y `workflow_approvals` registran el checkout manual y la
  decisión humana.
- `commerce_cart_operations` conserva el ledger de idempotencia.
- Bodega conserva `stock_movements` y `stock_reservations`.

## Límites

- No hay dashboard dedicado de carritos abandonados.
- No hay alerta automática por carritos por vencer; el KPI está disponible.
- No se expone PII de cliente en los KPIs.
- Falta métrica de latencia por tool de carrito.
