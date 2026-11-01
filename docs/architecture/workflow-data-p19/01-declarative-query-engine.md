# P19-01 — Motor declarativo seguro y contrato SQL de solo lectura

- **Estado:** COMPLETADO (backend). Habilita P19-02 y P19-03.
- **Base:** P19-00 aprobada; ADR `00-adr-query-node.md`.
- **Cambio de autoridad:** el plan vive en el servidor; el payload solo envía
  `params`.
- **Sin motor nuevo:** se reutiliza `bindings.py`, Managed DB, runtime,
  `workflow_run_steps`, binding e instancias existentes.

## 1. Diagnóstico que se corrige

Antes:

```python
config = {**binding.get("config"), **payload}
table = config["table"]
columns = config.get("columns") or ["*"]
```

Consecuencias reproducidas en P19-00:

- `payload.table` cambiaba el recurso;
- `payload.columns=["*"]` abría todas las columnas;
- `payload.filters` reemplazaba predicados obligatorios;
- un operador desconocido se degradaba a `=`;
- `payload.limit` superaba el límite del binding;
- `payload.order_by` elegía el orden;
- `connected_db` se ejecutaba contra Managed DB.

## 2. Contrato implementado

Schema: `zent.data.query.binding/v1`.

```json
{
  "schema": "zent.data.query.binding/v1",
  "scope": "workspace",
  "allowed_workspace_ids": [],
  "connection_ref": null,
  "resource": {"schema": "public", "name": "product_prices", "kind": "view"},
  "operation": "get_one",
  "projection": ["sku", "price", "currency"],
  "allowed_columns": ["sku", "price", "currency", "channel"],
  "required_predicates": [
    {"field": "channel", "op": "eq", "source": "binding", "value": "retail"}
  ],
  "parameters": [
    {"name": "sku", "field": "sku", "operator": "eq", "type": "string", "required": true}
  ],
  "order_by": [{"field": "valid_from", "direction": "desc"}],
  "policy": {
    "max_rows": 1,
    "timeout_ms": 3000,
    "read_only": true,
    "pii_class": "internal",
    "max_bytes": 262144
  },
  "ownership": {
    "field": "customer_id",
    "principal_claim": "customer_ref",
    "required": true
  },
  "resource_ref": "resource.catalog.product_prices",
  "column_types": {"sku": "string", "price": "number", "currency": "string"}
}
```

Entrada permitida en ejecución:

```json
{"params": {"sku": "ARR-001"}}
```

Cualquier otra clave (`table`, `columns`, `filters`, `limit`, `order_by`,
`connection_ref`, `workspace_id`, `sql`, `operation`, `policy`, etc.) produce
`UNEXPECTED_PARAMETER` y no ejecuta SQL.

## 3. Implementación

| Cambio | Archivo | Detalle |
|---|---|---|
| Modelos Pydantic `extra=forbid` | `src/platform/workflows/bindings.py` | `DataQueryPlan`, `QueryResource`, `QueryPredicate`, `QueryParameter`, `QueryPolicy`, `QueryOwnership` |
| Parseo del plan | `bindings.parse_data_query_plan` | `None` para legacy; `NEEDS_CONFIGURATION` si el plan es inválido |
| Plan canónico | `bindings._execute_data_query_plan` | Recursos, proyección, predicados, parámetros, ownership y política desde el plan |
| Legacy seguro | `bindings._execute_legacy_select` | Config manda; exige columnas explícitas; rechaza claves de autoridad del payload |
| Dispatch | `bindings._dispatch_binding` | `connected_db` devuelve `PROVIDER_NOT_SUPPORTED`; no toca Managed DB |
| Managed DB | `managed_db/service.py` | `open_managed_query_session(..., database_id=...)` para `connection_ref` |
| Timeout | `bindings._execute_sql` | `SET LOCAL statement_timeout` + `asyncio.wait_for` |
| Salida | `_execute_data_query_plan` | status, found, record, rows, columns, row_count, truncated, data_as_of, source_ref, binding_ref, binding_hash, duration_ms, reason_code, provenance |

## 4. Operaciones

| Operación | Comportamiento |
|---|---|
| `get_one` | `LIMIT 2`; 0 → `NOT_FOUND`; 1 → `record`; >1 → `MULTIPLE_MATCHES` sin fila arbitraria |
| `list` | `LIMIT max_rows + 1`; `truncated=true` si hay más; respeta `max_bytes` recortando filas |
| `count` | `SELECT COUNT(*)`; devuelve entero; no filas |

`sum/avg/min/max` no se implementan en P19-01. Quedan para el AST de P19-03,
según ADR-002. No existe SQL libre ni expresiones.

## 5. Invariantes de seguridad

- `SELECT *` prohibido en plan y en legacy.
- Proyección y columnas de filtro/orden deben ser identificadores simples.
- `allowed_columns` es lista positiva; si existe, todo campo usado debe estar en
  ella.
- Predicados obligatorios del plan siempre se agregan; el payload no puede
  quitarlos.
- Parámetros no declarados → `UNEXPECTED_PARAMETER`.
- Tipos validados (`string`, `integer`, `number`, `boolean`, `date`, `datetime`).
- `LIKE`/`ILIKE`: máximo 64 caracteres, sin `%` inicial, máximo 2 `%` y 4 `_`.
- `in`: lista no vacía, máximo 50, sin estructuras anidadas.
- Ownership: si `required=true`, sin principal verificado → `PERMISSION_DENIED`.
- Plan `organization`: solo workspaces en `allowed_workspace_ids`.
- Plan `workspace`: exige binding de workspace; no se hereda silenciosamente.
- `connected_db` no se ejecuta hasta P19-06.
- La sesión Managed DB usa `query_reader_user` y
  `default_transaction_read_only=on`.

## 6. Compatibilidad

| Caso | Comportamiento |
|---|---|
| Binding legacy con `table` + `columns` | Sigue funcionando por `_execute_legacy_select`; config manda |
| Binding legacy sin `columns` | `NEEDS_CONFIGURATION`; ya no hace `SELECT *` |
| Binding legacy sin `table` | `NEEDS_CONFIGURATION` (igual que antes) |
| `capability_call` con inputs planos | Se aceptan solo si coinciden con columnas proyectadas/filtradas; claves de autoridad se rechazan |
| Grafos publicados | No se reescriben |
| Instancias WAIT | No se tocan; el binding sigue siendo vivo hasta P19-12 |
| `query_business_data` | Sin cambio de semántica |
| `connected_db` | Ahora falla explícito; antes leía Managed DB |

## 7. Error mapping implementado

| Código | Uso |
|---|---|
| `NEEDS_CONFIGURATION` | plan inválido, falta tabla/columnas, workspace ausente, DB no disponible |
| `PERMISSION_DENIED` | workspace no concedido, binding de otro workspace, principal ausente |
| `RESOURCE_NOT_EXPOSED` | tabla/columna inexistente o sin permiso en la fuente |
| `INVALID_PARAMS` | falta parámetro, tipo inválido, operador/patrón/lista inválidos |
| `UNEXPECTED_PARAMETER` | payload intenta enviar autoridad o parámetro no declarado |
| `NOT_FOUND` | 0 filas en `get_one` |
| `MULTIPLE_MATCHES` | >1 fila en `get_one` |
| `TIMEOUT` | presupuesto de tiempo agotado |
| `CONNECTION_FAILED` | fallo de conexión |
| `PROVIDER_NOT_SUPPORTED` | `connected_db` sin adaptador certificado |

`STALE_DATA` queda definido para P19-07/12; P19-01 no inventa `data_as_of`.

## 8. Salida (sin SQL)

```json
{
  "status": "FOUND",
  "found": true,
  "record": {"sku": "ARR-001", "price": "5.00", "currency": "PEN"},
  "rows": [],
  "columns": [
    {"name": "sku", "type": "string", "label": "sku"},
    {"name": "price", "type": "number", "label": "price"}
  ],
  "row_count": 1,
  "truncated": false,
  "data_as_of": null,
  "source_ref": "resource.catalog.product_prices",
  "binding_ref": "uuid",
  "binding_hash": "sha256...",
  "duration_ms": 12,
  "reason_code": null,
  "provenance": {"provider_kind": "managed_db", "queried_at": "...", "resource_kind": "view"}
}
```

No incluye `sql_query`, DSN, credenciales ni nombres de columnas no proyectadas.

## 9. Pruebas y evidencia

### Unitarias del plan

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workflow_data_p19_query.py -q
```

Resultado: **17 passed**.

Cubre: autoridad del payload, parámetros declarados, predicados obligatorios,
`SELECT *`, operadores, identificadores, `get_one` 0/1/varios, `list` truncada,
`count`, ownership, `LIKE`, scope workspace/org y legacy sin columnas.

### Regresión P19-00

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workflow_data_p19_audit.py -q
```

Resultado: **10 passed** (antes 2 passed + 8 xfailed). Los 8 hallazgos P0/P1
pasaron a PASS con rechazo explícito, no con relajación de asserts.

### Integración PostgreSQL real

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workflow_data_p19_query_integration.py -q
```

Resultado: **1 passed**. Crea una Managed DB efímera, tabla `p19_prices`, lee
`ARR-001` con `get_one`, prueba un SKU con inyección (`' OR 1=1 --`) y confirma
que la sesión rechaza `INSERT` por read-only. Limpia database y roles.

### Regresión existente

| Suite | Resultado |
|---|---|
| `test_workflow_data_catalog.py` + `test_workflow_readiness.py` | 10 passed |
| `test_managed_db_provisioning.py` | 2 passed |
| `test_workflow_published_snapshot.py` | NOT_RUN (cuelgue preexistente del baseline) |
| Suite completa | NOT_RUN |

## 10. Matriz antes/después de P19-01

| Elemento | Antes | Después |
|---|---|---|
| Recurso | `binding.config + payload` | plan del servidor |
| Columnas | default `*`; payload | `projection` + `allowed_columns` |
| Filtros | dict reemplazable | `required_predicates` + parámetros declarados |
| Operadores | fallback `=` | allowlist; `INVALID_PARAMS` |
| Límite | payload/global 500 | `policy.max_rows` por plan |
| Orden | payload | `order_by` del plan |
| `get_one` | inexistente | 0/1/varios tipados |
| `count` | inexistente | entero |
| Ownership | inexistente | predicado de principal verificado |
| Errores | genéricos | taxonomía P19 |
| Salida | `rows`, `row_count`, `table` | contrato tipado sin SQL |
| `connected_db` | Managed DB | `PROVIDER_NOT_SUPPORTED` |
| Timeout | ninguno | `statement_timeout` + `wait_for` |
| Legacy | inseguro | config manda; columnas explícitas |

## 11. Límites y deuda

- No hay nodo visual `data_query` todavía (P19-03).
- No hay API de catálogo de recursos (P19-02).
- No hay `data_as_of`/freshness SLA (P19-07/12).
- No hay agregados `sum/avg/min/max` (P19-03, ADR-002).
- No hay pinning de binding en WAIT/RESUME (P19-12).
- No hay adaptador externo (P19-06).
- No hay presupuesto de concurrencia/costo por tenant (P19-13).
- No hay redacción de `workflow_run_steps.output` (P19-05/13).
- `resolve_binding` sigue devolviendo bindings org-level legacy por
  compatibilidad; el plan canónico exige `scope` y `allowed_workspace_ids`.

## 12. Rollback

- Revertir los cambios de `bindings.py` y `managed_db/service.py`.
- Los bindings con schema nuevo quedarían ilegibles para el código anterior:
  hacer rollback solo después de desactivar nuevos `data_query` y conservar los
  grafos. No hay migración de esquema.
- Los bindings legacy no se modifican.
- No se publicó ningún workflow ni se alteró una instancia.

## 13. Veredicto

**P19-01 COMPLETADO en backend.** Los P0 de sustitución de recurso, proyección,
predicados, operador, límite, orden y `connected_db` están cerrados por tests.
No se declara GO de producción: faltan catálogo, UI, identidad de cliente,
pinning, pruebas adversariales completas y proveedor externo.
