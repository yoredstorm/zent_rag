# P16 — Rollback

## Código

No hay migraciones. Rollback de aplicación:

1. Revertir al SHA anterior (`b9e8859`, cierre P15).
2. Rebuild/redeploy de `api`, `ingestion-worker` y `portal`.
3. Los clientes que esperan `draft` siguen funcionando: el nuevo endpoint
   conserva esa clave y agrega campos aditivos.

## Datos

- La generación no persiste: `saved=false` y el usuario debe guardar el agente.
- No se modifican workflows publicados, instancias durables, fuentes ni
  conocimiento.
- Si se guardó un propósito/instrucciones y se desea volver atrás, se puede
  restaurar desde el historial de configuración del agente o reescribir los
  campos; no hay migración que deshacer.

## Seguridad

- Si el proveedor falla, el endpoint devuelve la entrada original con warnings;
  no 503 destructivo ni propósito genérico.
- El RBAC, tenant/workspace y límites de tokens se mantienen.
- `ZENT_GOLD_RELEASE_ENABLED` permanece `false`.
