# Zent Spider (FASE 25)

> Discovery continuo AUTORIZADO y limitado. No es crawling irrestricto: solo
> fuentes y schemas explícitamente autorizados por la política del tenant.
> NUNCA amplía permisos automáticamente.

## 1. Políticas (`spider_policies`)

```json
{
  "name": "erp-daily",
  "enabled": true,
  "schedule_hours": 24,
  "allowed_source_ids": [],
  "allowed_schemas": ["erp"],
  "excluded_objects": ["TBL_AUDIT"],
  "profiling_level": "standard",
  "max_cost": 500,
  "max_duration_min": 60,
  "sampling_policy": "conservative",
  "pii_policy": "never"
}
```

Reglas de no-ampliación:
- `allowed_source_ids` se intersecta con los `catalog_sources` del tenant.
- `allowed_schemas` se aplica como filtro sobre lo descubierto; vacío =
  todo lo del tenant (nunca más).
- `pii_policy` default `never` (el sampling nunca toca columnas sensibles).

## 2. Ejecución

- Manual: `POST /api/v1/learning/spider/policies/{id}/run`.
- Programada: loop en `main.py` (`_spider_loop`) que encola políticas vencidas
  (`schedule_hours`).
- Job durable `spider:run` → `SpiderService.execute_run`:
  1. carga política + fuentes autorizadas;
  2. filtra schema/objetos excluidos;
  3. `MetadataScanner` (drift, enums) + detección de inconsistencia semántica
     (entidad mapeada a tabla removida);
  4. findings en `spider_runs` + métricas.

## 3. Detecciones

| Hallazgo | Fuente |
|---|---|
| schema drift (tablas/columnas/tipos) | `MetadataScanner` (content_hash) |
| nuevas tablas / tablas obsoletas | drift del scan |
| relaciones nuevas | `RelationshipDetector` |
| enums sin documentar | `EnumDiscovery` → UNDEFINED_ENUM |
| cambios de documentación | column/table comment en cada scan |
| inconsistencias semánticas | entidad ↔ tabla removida |

## 4. Auditoría y observabilidad

- `spider.policy_configured` / `spider.scan_started` en audit_logs.
- `rag_spider_findings_total{kind}` · `rag_spider_scan_duration_seconds`.