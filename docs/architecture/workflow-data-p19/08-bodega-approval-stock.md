# P19-08/09 — Bodega peruana, aprobación del dueño y descuento de stock

- **Estado:** flujo principal COMPLETADO en local con PostgreSQL externo.
- **Alcance:** 30 productos, stock, pedido, aprobación humana y commit de stock.
- **No incluye:** Stripe/VISA, reserva con expiración, multi-ítem completo,
  certificación de producción.

## 1. Bodega creada

Schema `bodega` en `zent_external_mvp`:

| Tabla | Uso |
|---|---|
| `bodega.products` | 30 productos peruanos |
| `bodega.stock` | `on_hand`, `reserved`, `version` |
| `bodega.stock_movements` | ledger append-only idempotente |
| `bodega.orders` | pedido y estado de pago |
| `bodega.order_items` | ítems del pedido |
| `bodega.product_catalog_v` | vista de precio, stock y disponible |

Productos: arroz, azúcar, aceite, fideos, atún, sardinas, leche, huevos, pan,
harina, sal, ají, ajo, cebolla, papa, camote, tomate, zanahoria, pollo, carne,
pescado, lentejas, frejoles, quinua y avena. Precios en PEN.

Roles:

- `p19_reader`: SELECT sobre todo `bodega`.
- `p19_writer`: SELECT en productos/pedidos; INSERT/UPDATE solo en stock,
  movimientos y pedidos.
- `p19_writer` no puede alterar productos ni schema.

## 2. Flujo ejecutado

```
trigger_webhook (pedido)
  → state_set (order)
  → capability_call bodega.stock.reserve (TTL 900 s)
  → human_approval (dueño)
  → condition approved?
      → commit_stock
      → release_stock si rechaza
  → notify
  → end
```

La reserva se crea antes de la aprobación y descuenta `available`, no `on_hand`.
Si el dueño no aprueba dentro del TTL, la reserva expira y el stock se libera.
La aprobación muestra:

```
Pedido BOD-1001 · SKU BD-ARROZ-01 · cantidad 2
```

El dueño aprueba desde el portal. La reanudación usa la misma instancia durable
y el mismo snapshot. El nodo de commit no recibe SQL: solo
`order_number`, `sku`, `quantity` e `idempotency_key` resueltos del output de la
aprobación.

## 3. Evidencia real

Pedido `BOD-1001`:

- estado inicial: `pending_approval`
- pago: `pending`
- total: `18.50 PEN`
- ítems: 2 arroz + 1 aceite

Aprobación del dueño:

```
approval_id=f020bc53-2572-4de3-bdfa-dfa5df69f617
status=approved
resume=resumed
instance=343c1cbe-f2e6-4bc1-9ac7-efcbcc3bb2b8
```

Resultado:

| Dato | Antes | Después |
|---|---|---|
| `BD-ARROZ-01 on_hand` | 55 | 53 |
| `BOD-1001 status` | `pending_approval` | `confirmed` |
| `payment_status` | `pending` | `approved_manual` |
| Instancia | `WAITING` | `COMPLETED` |
| Movimiento | — | `commit`, 2 unidades, 55 → 53 |

El descuento ocurrió **después** de la aprobación. No al crear el pedido. No hay
descuento automático por pago.

### Reserva tipo cine — BOD-1002

Antes de la aprobación:

| Dato | Valor |
|---|---|
| SKU | `BD-POLLO-01` |
| `on_hand` | 55 |
| `reserved` | 1 |
| Reserva | `active` |
| Expira | 15 minutos |

Después de aprobar:

| Dato | Valor |
|---|---|
| `on_hand` | 54 |
| `reserved` | 0 |
| Reserva | `committed` |
| Pedido | `confirmed` |

### Expiración — BOD-1003

Se reservó 1 unidad de `BD-QUINUA-01` con TTL 30 s. Tras 35 s:

```json
{"status": "RESERVATION_EXPIRED", "order_number": "BOD-1003", "sku": "BD-QUINUA-01"}
```

Resultado:

- `reserved` volvió a 0.
- `on_hand` no cambió.
- la reserva quedó `expired`.
- no se creó movimiento de commit.

La reserva vencida se barre de forma perezosa al iniciar reserve/commit. Para
producción hace falta un job periódico que libere reservas sin esperar una
llamada.

## 4. Idempotencia

La clave del movimiento es:

```
commit:BOD-1001:BD-ARROZ-01
```

`bodega.stock_movements.idempotency_key` es único. Un retry devuelve
`ALREADY_APPLIED` y no vuelve a restar stock. El commit bloquea la fila
`bodega.stock` con `FOR UPDATE` y rechaza `INSUFFICIENT_STOCK` si no alcanza.

Evidencia de reintento: se ejecutó de nuevo el workflow para `BOD-1001`,
se aprobó, y el stock siguió en `53`; `stock_movements` siguió con un solo
movimiento. La instancia quedó `COMPLETED`.

## 5. Seguridad

- El agente no ejecuta `UPDATE stock`.
- El payload solo contiene `order_number`, `sku`, `quantity`,
  `idempotency_key`.
- El binding `inventory` exige `write=true` y un conector de escritura separado.
- El conector de lectura sigue siendo read-only.
- La aprobación es una fila de `workflow_approvals`, no un booleano.
- El dueño que aprueba queda registrado en `decided_by`.
- La UI de aprobaciones existente muestra acción y resumen.

## 6. Reproducción

```powershell
# 1. Crear tablas y 30 productos
docker cp ops/p19-external/bodega.sql p19-external-postgres:/tmp/bodega.sql
docker exec -e PGPASSWORD=p19_admin_dev_2026 p19-external-postgres `
  psql -U p19_admin -d zent_external_mvp -f /tmp/bodega.sql

# 2. Publicar conectores/planes en el tenant demo
$env:ORG_ID="d7cafbf1-5764-41fe-a50e-97c8d97fc834"
$env:WORKSPACE_ID="d28ec9d6-020f-4537-a715-dc4ff34e888d"
$env:P19_EXTERNAL_HOST="host.docker.internal"
$env:P19_EXTERNAL_PORT="55432"
$env:P19_EXTERNAL_USER="p19_reader"
$env:P19_EXTERNAL_PASSWORD="p19_reader_dev_2026"
$env:P19_WRITER_USER="p19_writer"
$env:P19_WRITER_PASSWORD="p19_writer_dev_2026"
.\.venv\Scripts\python.exe ops\p19-external\seed_tenant.py

# 3. Crear y ejecutar el workflow de pedido
.\.venv\Scripts\python.exe ops\p19-external\create_bodega_workflow.py
```

El script imprime el `approval_id`. Aprobarlo en el portal o con
`POST /runs/{run_id}/approvals/{approval_id}/decide`.

## 7. Límites

- Solo commit de un ítem por ejecución; falta iterar `order_items`.
- No hay reserva con expiración; el stock se descuenta al aprobar.
- No hay Stripe/VISA; el pago queda `pending` y la aprobación es manual.
- No hay release ni compensación si el pedido se cancela después.
- No hay notificación externa al dueño; la aprobación vive en el inbox.
- No hay E2E Playwright ni prueba de doble aprobación desde UI.
- No se certifica producción.

## 8. Veredicto

**Flujo bodega local PASS.** Pedido real, aprobación humana, commit idempotente y
stock actualizado en PostgreSQL externo. Es la base correcta para conectar
Stripe/VISA y reservas, sin cambiar el modelo de autoridad.
