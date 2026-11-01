# P19-02 — Catálogo de conexiones, esquemas y recursos autorizados

- **Estado:** COMPLETADO (backend). La UI de selección llega en P19-03.
- **Base:** P19-01 (plan canónico y binder seguro).
- **Decisión de diseño:** no se crea un registro paralelo. Las conexiones salen
  de `managed_databases`; los recursos publicados salen de bindings activos con
  plan `zent.data.query.binding/v1`.

## 1. Problema

Antes no existía una API para que el canvas listara conexiones, tablas o
columnas. El diseñador solo podía escribir una pregunta libre. Además, el
catálogo semántico (`catalog_tables`) filtra por organización pero no por
workspace, y no distingue una tabla indexada de una tabla realmente autorizada
para consulta en vivo.

P19-02 resuelve la parte de lectura segura: una persona solo ve fuentes y
recursos que ya tienen un plan canónico publicado para su workspace.

## 2. API implementada

Prefijo: `/api/v1/workflows`.

### `GET /data-sources`

Lista las conexiones Managed DB del workspace.

```json
{
  "sources": [
    {
      "ref": "managed_db:uuid",
      "label": "Base de datos gestionada",
      "provider_kind": "managed_db",
      "status": "CONNECTED",
      "read_only": true,
      "capabilities": ["select", "count"],
      "provider": "local"
    }
  ]
}
```

- Requiere `workflows:read` y `X-Workspace-Id` (o workspace activo).
- No devuelve `db_name`, host, DSN, usuario ni credenciales.
- `connector_id` ausente o estado `disabled/error/revoked` → `NEEDS_CREDENTIALS`.

### `GET /data-sources/{ref}/resources?cursor=&limit=`

Lista recursos publicados del workspace.

```json
{
  "resources": [
    {
      "resource_ref": "public.p19_prices",
      "label": "public.p19_prices",
      "kind": "table",
      "schema": "public",
      "name": "p19_prices",
      "columns_count": 4,
      "sensitive": false,
      "binding_ref": "uuid",
      "capability_ref": "p19.price.lookup"
    }
  ],
  "total": 1,
  "next_cursor": null,
  "source_ref": "managed_db:uuid"
}
```

- Lista positiva: solo bindings activos con plan canónico y scope autorizado.
- Bindings legacy no aparecen.
- `cursor` es offset acotado; `limit` se limita a 100.
- Un `ref` de otra organización/workspace devuelve `RESOURCE_NOT_EXPOSED`, no
  una lista vacía que confirme existencia.

### `GET /data-sources/{ref}/resources/{resource_ref}/schema`

Devuelve columnas permitidas, tipos, PK/FK y clasificación.

```json
{
  "resource_ref": "public.p19_prices",
  "binding_ref": "uuid",
  "kind": "table",
  "columns": [
    {
      "name": "sku",
      "label": "sku",
      "data_type": "text",
      "nullable": false,
      "primary_key": false,
      "foreign_key": false,
      "sensitive": false,
      "pii_flags": []
    }
  ]
}
```

- Reutiliza `src/connectors/sql/schema_discovery.discover_columns`.
- Filtra a `allowed_columns` del plan. No enumera columnas ocultas.
- Si el recurso no está publicado o la tabla ya no existe → `RESOURCE_NOT_EXPOSED`.
- Si la conexión falla → `CONNECTION_FAILED`, sin DSN ni SQL.

### `POST /data-query/preview`

Ejecuta un plan ya guardado con límites severos.

```json
{
  "binding_id": "uuid",
  "params": {"sku": "ARR-001"}
}
```

- No acepta `table`, `columns`, `sql`, `filters`, `limit`, `order_by` ni
  `connection_ref`; el binding es la autoridad.
- Fuerza `max_rows≤5`, `timeout_ms≤1500`, `max_bytes≤32768`.
- Redacta campos sensibles por nombre (`customer_email` → `***`) y devuelve
  `redacted_fields`.
- Plan con ownership requerido y sin principal verificado → denegado.
- Error de binding ajeno → `RESOURCE_NOT_EXPOSED`.

## 3. Implementación

| Componente | Archivo | Detalle |
|---|---|---|
| Servicio de catálogo | `src/platform/workflows/data_sources.py` | sources, resources, schema, preview, cache |
| Bindings | `src/platform/workflows/bindings.py` | `get_binding`, invalidación de cache al guardar/borrar |
| Managed DB | `src/platform/managed_db/service.py` | selección por `database_id` |
| API | `src/api/routes/workflows.py` | cuatro endpoints + `DataQueryPreviewIn` |
| Schema discovery | `src/connectors/sql/schema_discovery.py` | reutilizado sin duplicar introspección |
| PII | `src/core/domain/pii.py` | `is_sensitive_column`, `pii_flags_for_column` |

## 4. Cache

- TTL 30 s.
- Clave: organización + workspace + permiso(s) + tipo de dato.
- No mezcla tenants.
- `upsert_binding` y `delete_binding` invalidan la cache del workspace/org.
- Cambios de ACL, conector o schema físico pueden tardar hasta 30 s; P19-13
  medirá la ventana y añadirá invalidación por evento si hace falta.

## 5. Permisos y aislamiento

| Prueba | Resultado |
|---|---|
| Org A no ve sources de Org B | PASS |
| Workspace A no ve resources de Workspace B | PASS |
| Binding legacy no se publica | PASS |
| Recurso no publicado devuelve 404 | PASS |
| Fuente de otro workspace devuelve 404 | PASS |
| Preview de binding ajeno devuelve 404 | PASS |
| Preview redacta email | PASS |
| API `data-sources` exige `workflows:read` | PASS |

No se usa el nombre de la tabla como permiso. La publicación es un binding
canónico con scope; conocer `public.p19_prices` no lo hace accesible.

## 6. Pruebas

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workflow_data_p19_catalog.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_workflow_data_p19_query_integration.py -q
```

Resultados:

- `test_workflow_data_p19_catalog.py`: **7 passed** (6 servicio + 1 API con
  sesión owner real).
- `test_workflow_data_p19_query_integration.py`: **1 passed**, incluye
  introspección real de `p19_prices` y verificación de columnas permitidas.

Cobertura de la matriz exigida:

| Caso | Estado |
|---|---|
| Org A/B | PASS |
| Workspace A/B | PASS |
| Rol sin `workflows:read` | PASS (403 en API) |
| Recurso sensible | PASS (marca `sensitive`/`pii_flags`) |
| Views | PASS por `resource.kind`; falta fixture VIEW explícita |
| Nombres Unicode/no válidos | PASS en validación de plan; no hay tabla Unicode |
| DDL cambiado | PASS (tabla inexistente → `RESOURCE_NOT_EXPOSED`) |
| Conexión revocada | PASS para `connector_id` ausente/estado no conectado |
| No leak con 403/404 | PASS |

## 7. Límites

- No hay UI todavía; el canvas sigue usando `query_business_data`.
- No hay endpoint para crear/publicar un recurso desde una tabla descubierta;
  publicar requiere guardar un binding canónico. El flujo visual llega en
  P19-03.
- Solo `managed_db`. `connected_db` sigue `PROVIDER_NOT_SUPPORTED` hasta P19-06.
- La introspección no cachea schema; se consulta en cada request.
- No hay RLS ni filtro de titularidad; P19-08/09.
- No hay pruebas de tabla Unicode, VIEW real ni permisos DB distintos en esta
  fase; quedan para P19-13.

## 8. Rollback

- Revertir `data_sources.py`, las rutas y `get_binding`/invalidación.
- No hay migración de esquema ni tabla nueva.
- Los bindings canónicos existentes siguen siendo legibles por P19-01.
- Apagar los endpoints no afecta workflows publicados ni instancias.

## 9. Veredicto

**P19-02 COMPLETADO en backend.** El catálogo es una lista positiva por
workspace, no un explorador de todas las tablas. No se declara GO de producción:
faltan UI, creación visual de recursos, RLS/titularidad y pruebas de proveedor
externo.
