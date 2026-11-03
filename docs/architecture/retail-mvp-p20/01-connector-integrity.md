# P20-01 — Integridad de conector y fuente SQL real

- **Estado:** DONE para invariantes de identidad/guardas; PARTIAL para
  snapshot/indexado externo (explícitamente no soportado).
- **HEAD:** `29a66937beed638f511d93e7a1b986687dc59edd`.

## Contrato de fuente

`kb_sources.config_json` para una DB externa:

```json
{
  "connector_id": "uuid",
  "engine": "postgres",
  "host": "host.docker.internal",
  "database": "zent_external_mvp",
  "source_mode": "schema_only",
  "connection_status": "connected",
  "catalog_status": "discovered",
  "snapshot_status": "not_supported",
  "allowed_resources": [],
  "revision": 1
}
```

Nunca contiene password, DSN ni token. El tipo de `kb_source` es `sql` (tipo
soportado por el registry); el motor real está en `config.engine`.

## Cambios

1. `_ensure_database_source()` busca por `config_json.connector_id` y
   workspace. Ya no reconcilia por nombre.
2. `SQLSourceConnector.validate/discover/sync` rechazan fuentes con
   `connector_id` mediante `SOURCE_MODE_UNSUPPORTED`; no tocan Managed DB.
3. `full_refresh` queda prohibido (`FULL_REFRESH_UNSUPPORTED`) antes de
   cualquier borrado. No se puede borrar por organización desde SQL ingestion.
4. `scripts/cert/p20_migrate_sql_sources.py` hace dry-run/apply idempotente:
   normaliza type/config de fuentes con connector_id y reporta legacy sin
   conector para revisión humana. No adjudica nombres.
5. AgentSourcePicker trata tipos DB (`sql`, `postgres`, etc.) como conectados,
   sin botón de indexado documental.

## Pruebas

| Caso | Resultado | Evidencia |
|---|---|---|
| validate externa no toca Managed DB | PASS | `test_p20_sql_source_integrity.py` |
| discover externa bloqueada | PASS | idem |
| sync externa bloqueada | PASS | idem |
| full_refresh no borra org | PASS (fail closed) | idem |
| onboarding crea fuente visible | PASS | `test_data_onboarding.py` |
| picker no indexa DB | PASS | `AgentSourcePicker.test.tsx` |
| migración dry-run | PASS | `p20_migrate_sql_sources.py --dry-run` |
| dos conectores mismo nombre | NOT_RUN | pendiente P20-16 |
| dos DB con mismas tablas | NOT_RUN | pendiente P20-16 |
| refresh concurrente | NOT_RUN | pendiente P20-16 |

## Compatibilidad y rollback

- Aditivo. Fuentes `sql` legacy sin `connector_id` conservan el camino interno,
  pero full_refresh está deshabilitado.
- Rollback de código restaura el comportamiento anterior, que es inseguro; no
  recomendado. El script `--apply` es idempotente y no borra fuentes.
- No hay migración Alembic en este corte; los cambios son de contrato/config y
  guardas de runtime.

## Riesgos residuales

- Snapshot/indexado de una fuente externa no está soportado; el catálogo y las
  consultas en vivo son la ruta válida.
- Falta prueba con dos conectores homónimos y dos workspaces reales; se declara
  NOT_RUN, no PASS.
- La tool del agente para consultar el conector externo ya está implementada
  en P20-02 (`execute_external`); quedan pendientes las tools comerciales
  tipadas de P20-05.
- La autoridad de orden (ZENT commerce vs Bodega) queda ADR, no implementada.
