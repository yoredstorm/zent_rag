# P19-03b — Autoservicio de conexión y publicación de consultas

- **Estado:** backend y UI Simple COMPLETADOS en local.
- **Objetivo:** un usuario normal conecta su PostgreSQL, descubre tablas y publica
  una consulta sin script, sin SQL y sin JSON.

## Flujo

1. El usuario entra a **Conectores** y crea un conector PostgreSQL.
2. Prueba la conexión.
3. En el workflow, nodo «Consultar registros», pulsa **Publicar una consulta**.
4. Elige el conector.
5. Pulsa **Descubrir tablas**.
6. Elige tabla o vista.
7. Elige operación: buscar uno, listar o contar.
8. Elige columna de búsqueda.
9. Marca columnas que devuelve.
10. Publica.

El plan queda en `workflow_capability_bindings` con
`zent.data.query.binding/v1`. El nodo lo consume en el mismo workspace.

## API

- `POST /api/v1/connectors/{id}/discover`: reutiliza el plugin PostgreSQL para
  listar tablas y columnas.
- `POST /api/v1/workflows/data-query/plans`: valida tabla/columnas y publica el
  plan.
- `GET /api/v1/workflows/data-query/plans`: lista los planes publicados.

Permisos:

- Crear conector: `connectors:write`.
- Descubrir: `connectors:read`.
- Publicar plan: `workflows:update`.
- Usar plan: `workflows:read`.

No se crea un registro paralelo: se reutilizan conectores, plugin discovery,
bindings y catálogo.

## UI

- Modal `PublishQueryModal`.
- Estado vacío de «Consultar registros» ya no dice “pide a un administrador”:
  ofrece **Publicar una consulta**.
- El usuario no escribe SQL ni JSON.
- Las columnas se muestran con tipo técnico; no se inventa semántica.
- No se permite publicar una tabla que el discovery no devolvió.

## Evidencia local

Tenant demo, conector `ERP externo P19`:

```json
{
  "resource_ref": "bodega.product_catalog_v",
  "operation": "get_one",
  "projection": ["sku", "name", "price", "available"],
  "parameter": {"name": "sku", "field": "sku", "operator": "eq", "type": "string"},
  "max_rows": 1
}
```

Respuesta:

```json
{
  "binding_ref": "362f03dc-1904-42d4-8a37-db25d6360f33",
  "capability_ref": "data.bodega.product_catalog_v.get_one.da4f9a41",
  "resource_ref": "Catálogo bodega",
  "operation": "get_one"
}
```

Descubrimiento real:

```json
{"schema":"bodega","name":"product_catalog_v","is_view":true,"columns":9}
```

## Límites

- La pantalla de Conectores sigue usando el formulario existente; no se rediseñó
  en este incremento.
- Solo PostgreSQL externo. MySQL/SQL Server/Oracle/DB2 siguen NOT_SUPPORTED.
- No hay edición/borrado visual del plan; se puede desactivar el binding.
- No hay preview de fila antes de publicar.
- No hay aprobación adicional para publicar; requiere `workflows:update`.
- Ingesta de documentos en Knowledge ya existe; no se modificó en este pase.

## Rollback

- Revertir el endpoint `POST /data-query/plans`, el modal y el enlace del estado
  vacío.
- Los bindings publicados siguen siendo legibles por P19-01; no hay migración.
- No se borran conectores ni tablas.
