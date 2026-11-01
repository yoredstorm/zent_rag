# P19-10 (previo) — Acceso de agentes a tablas y capacidades

- **Estado:** diseño aprobado para el siguiente incremento. No implementado.
- **Problema:** un agente de eventos de venta no debe consultar ventas totales;
  un agente gerencial sí. El permiso no puede depender del prompt ni del nombre
  del agente.

## Modelo

Cada agente recibe grants explícitos por organización/workspace:

```json
{
  "agent_id": "uuid",
  "capability_ref": "bodega.sales.metrics",
  "resource_ref": "bodega.sales_metrics_v",
  "scopes": ["aggregate:read"],
  "row_scope": {"territory": "assigned"},
  "enabled": true
}
```

Tabla aditiva:

```sql
agent_data_grants (
  id uuid primary key,
  organization_id uuid not null,
  workspace_id uuid,
  agent_id uuid not null,
  capability_ref varchar(120) not null,
  resource_ref varchar(200),
  scopes text[] not null,
  row_scope jsonb not null default '{}',
  enabled boolean not null default true,
  created_by uuid,
  created_at timestamptz default now(),
  unique (organization_id, workspace_id, agent_id, capability_ref)
)
```

No crea un segundo catálogo: referencia `capability_ref` y el binding/plan ya
existentes.

## Enforcement

1. El runtime del agente resuelve `agent_id` desde la fila del agente, no desde
   el mensaje.
2. `ToolContext` ya tiene `agent_permissions`; se completa con los grants.
3. Antes de `execute_binding`, si `source="agent"`, se exige:
   - grant activo para `agent_id` + `capability_ref`;
   - scope compatible (`read`, `aggregate:read`, `write`);
   - workspace del agente igual al de la consulta;
   - row_scope aplicado como predicado obligatorio.
4. Sin grant: `PERMISSION_DENIED`, sin revelar si la tabla existe.
5. El agente no puede ampliar su grant desde el prompt ni desde una tool.

## Agentes de ejemplo

| Agente | Puede | No puede |
|---|---|---|
| `sales_event` | leer pedido, reservar/commit stock, consultar precio | ventas totales, márgenes, otros territorios |
| `manager` | métricas de ventas, pedidos, stock, top productos | credenciales, SQL libre |
| `customer` | precio, stock, su pedido, sus puntos | ventas totales, pedidos ajenos |
| `inventory` | stock y movimientos | ventas, clientes, precios |

## UI

En el detalle del agente, pestaña «Datos»:

- conexiones autorizadas;
- tablas/vistas con checkbox;
- scopes por recurso;
- filtro de fila;
- preview de la pregunta que puede responder;
- botón «Probar acceso» que ejecuta solo el plan autorizado.

El dueño ve la matriz agente → recurso → scope. Un usuario normal no ve planes
de otros agentes.

## Relación con el workflow

El workflow no usa `agent_data_grants`; usa las capacidades del binding y la
política del workflow. Si un workflow invoca un agente, el agente conserva sus
grants. Si un agente invoca una capability de workflow, se aplican ambos:
grant del agente y política del workflow.

## Próximo incremento

1. Migración aditiva `agent_data_grants`.
2. Resolver `agent_id` en ToolContext.
3. Guard en `execute_binding` para `source=agent`.
4. UI de matriz y prueba negativa.
5. Dataset: `sales_event` no puede leer `bodega.sales_metrics_v`; `manager` sí.

No se implementa todavía. No se declara PASS.
