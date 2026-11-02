# P19.1-01 — Gobierno de publicación y mínimo privilegio

- **Estado:** DONE backend + UI mínima; certificación de producción pendiente.
- **Riesgo cerrado:** G01 (publicación de datos) a nivel de contrato y pruebas
  locales.
- **Migración:** `178_data_query_governance`.

## Hallazgo AS-IS

- `POST /data-query/plans` exigía solo `workflows:update`.
- El rol `member` tiene `workflows:update`, así que podía publicar cualquier
  tabla/columna descubierta de un conector.
- `PublishQueryModal` seleccionaba todas las columnas al elegir tabla.
- No había allowlist de publicación, clasificación PII explícita, propósito ni
  auditoría append-only.
- La introspección física se confundía con autorización.

## Contrato implementado

Permisos nuevos, separados del RBAC de workflows:

| Permiso | Uso |
|---|---|
| `data_sources:discover` | listar fuentes/conectores |
| `data_queries:read` | ver planes publicados |
| `data_queries:preview` | ejecutar preview redactado |
| `data_queries:publish` | publicar plan |
| `data_queries:publish_sensitive` | publicar columnas sensibles con propósito |
| `data_queries:manage` | administrar política y auditoría |

Allowlist por `organization_id + workspace_id + connector_ref`:

```json
{
  "schema": "zent.data.publication.policy/v1",
  "resources": [{
    "schema": "catalog",
    "table": "product_prices",
    "columns": ["sku", "product_name", "price", "currency"],
    "sensitive_columns": [],
    "operations": ["get_one", "list", "count"],
    "max_rows": 5
  }],
  "deny_by_default": true,
  "requires_purpose_for_sensitive": true
}
```

Reglas:

- Sin política: `POLICY_REQUIRED`.
- Tabla fuera de allowlist: `RESOURCE_NOT_ALLOWED`.
- Columna fuera de allowlist: `COLUMN_NOT_ALLOWED`.
- Schema de sistema (`pg_catalog`, `information_schema`, `pg_toast`, `pg_temp`):
  `SYSTEM_SCHEMA_DENIED`.
- Columna sensible sin `data_queries:publish_sensitive` o sin propósito:
  `SENSITIVE_COLUMN_DENIED` / `PURPOSE_REQUIRED`.
- `SELECT *`, proyección vacía o duplicada: `INVALID_PARAMS`.
- `capability_ref` la genera el servidor; un valor del cliente se ignora.
- Cada publicación crea un binding nuevo; nunca reemplaza uno existente.
- Eventos en `data_query_publication_events` (append-only): actor, org, ws,
  conector, binding, recurso, columnas, sensibles, propósito, policy hash,
  plan hash.

## Rutas

- `GET /api/v1/workflows/data-sources` → `data_sources:discover`.
- `GET .../resources`, `.../schema` → `data_queries:read`.
- `GET /api/v1/workflows/data-query/plans` → `data_queries:read`.
- `POST /api/v1/workflows/data-query/plans` → `data_queries:publish`.
- `POST /api/v1/workflows/data-query/preview` → `data_queries:preview`.
- `GET/PUT /api/v1/workflows/data-sources/{ref}/publication-policy`.
- `GET /api/v1/workflows/data-query/publication-events`.

## UI

- `PublishQueryModal.chooseTable` ya no selecciona columnas ni PK.
- El modal envía solo lo que el usuario marcó.
- Publicar refresca el catálogo sin `window.location.reload()` y selecciona el
  plan nuevo.
- El backend es la autoridad: deshabilitar un botón no sustituye un 403.

## Pruebas

| Caso | Resultado | Evidencia |
|---|---|---|
| `workflows:update` sin publish | PASS | `test_publication_is_deny_by_default...` |
| Sin política | PASS | idem |
| Columna sensible sin permiso/propósito | PASS | idem |
| Schema de sistema | PASS | idem |
| Dos publicaciones no colisionan `capability_ref` | PASS | `test_publish_never_overwrites...` |
| Auditoría de 2 eventos | PASS | idem |
| Preview con política stale | PASS | `test_preview_rejects_stale_policy...` |
| UI cero columnas | PASS | `PublishQueryModal.test.tsx` |

Comando:

```powershell
pytest tests/test_workflow_data_p19_governance.py tests/test_workflow_data_p19_catalog.py -q
npx vitest run src/components/workflowStudio/PublishQueryModal.test.tsx
```

## Compatibilidad y rollback

- Migración aditiva; no modifica planes existentes.
- Planes P19 previos quedan en `legacy_plan` controlado: preview con redacción y
  aviso; no se amplían accesos.
- Rollback: bajar 178 elimina tablas/permisos nuevos. Los bindings publicados
  con 178 quedarían sin política y el preview los trataría como legacy; no se
  borran datos.
- No hay feature flag: el modo seguro es el default. Los roles sin permiso
  reciben 403.

## Riesgos residuales

- La política se administra por API; falta UI de administración de allowlists.
- La clasificación PII combina declaración explícita + heurística de nombre;
  una columna sensible con nombre no reconocido debe declararse.
- `count` sigue devolviendo un número; el plan debe declarar ownership/filtros
  obligatorios para no filtrar existencia.
- Falta prueba E2E con dos tenants reales y auditoría de export/historial.
