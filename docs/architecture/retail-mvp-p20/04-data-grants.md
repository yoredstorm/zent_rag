# P20-04 — Grants de datos por agente

- **Estado:** PARTIAL. Backend de grants y enforcement en `query_database`
  implementados. UI de Agent Studio, tools tipadas y `execute_binding`
  `source=agent` siguen pendientes.
- **Alcance:** una fuente SQL seleccionada por el agente no concede todas sus
  tablas. Solo los recursos con grant activo llegan al discovery y al SQL.

## Modelo

Tabla aditiva `agent_data_grants`:

```sql
id UUID PRIMARY KEY
organization_id UUID NOT NULL
workspace_id UUID
agent_id UUID NOT NULL
capability_ref VARCHAR(120) NOT NULL
resource_ref VARCHAR(200) NOT NULL
scopes TEXT[] NOT NULL
row_scope JSONB NOT NULL DEFAULT '{}'
active BOOLEAN NOT NULL DEFAULT TRUE
expires_at TIMESTAMPTZ
version INTEGER NOT NULL DEFAULT 1
```

Capacidad inicial: `store.query_database`. Scopes de lectura:
`read`, `aggregate:read`, `*`. `resource_ref` usa nombre calificado
(`bodega.product_catalog_v`).

## Enforcement

1. `QueryDatabaseTool` resuelve agente/org/workspace y exige al menos un grant
   activo y no vencido.
2. `allowed_query_resources()` devuelve solo recursos autorizados.
3. `execute_external()` filtra el discovery a esos recursos antes del prompt
   SQL. Una tabla no concedida no se muestra al LLM y no pasa la allowlist.
4. `row_scope` no vacío se rechaza en la tool genérica:
   `PERMISSION_DENIED` con indicación de usar una tool tipada. No se ignora.
5. Sin `agent_id`, sin grant, grant vencido o sin scope de lectura:
   `PERMISSION_DENIED`.
6. La API `PUT /api/v1/agents/{id}/data-grants` reemplaza grants y escribe
   auditoría `agent.data_grants.replace` sin secretos.

## Prueba real ejecutada

Agente `P19 Prueba ERP`, grant
`store.query_database` sobre `bodega.product_catalog_v`.

- Precio: devuelve `BD-ARROZ-01 4.80 PEN` y `BD-ARROZ-05 22.50 PEN`.
- Estructura: el agente solo ve `bodega.product_catalog_v`; no ve
  `bodega.orders`, `sales.orders` ni `loyalty.loyalty_balances`.
- Pregunta de ventas con tablas no concedidas: no inventa y no consulta otra
  tabla.
- Se revocaron todos los grants por API: la tool respondió
  `PERMISSION_DENIED: el agente no tiene grants de datos`; no ejecutó SQL.
- Se restauró el grant: el precio volvió a responder con datos reales.

## Pruebas automatizadas

`tests/test_p20_external_sql_query.py`:

- grant activo devuelve solo recursos autorizados;
- `row_scope` falla cerrado;
- fuente sin agente falla cerrado;
- tool externa filtra por recursos concedidos.

## Pendiente

- UI «Accesos a datos» en Agent Studio con checkboxes, expiry y prueba
  positiva/negada.
- Grants por capability comercial (`store.price.get`, `store.stock.get`,
  `store.order.status`) y tools tipadas P20-05.
- Enforcement en `execute_binding` cuando `source=agent`; hoy el binding no
  distingue agente/caller.
- Row policies reales para pedidos/fidelidad. Sin identidad verificada no se
  habilita `bodega.orders` ni `loyalty.loyalty_balances`.
- Migración Alembic formal; este corte usa `CREATE TABLE IF NOT EXISTS`
  idempotente al primer uso.
