# P20-00 — Auditoría real, fuentes de verdad y plan MVP

- **HEAD auditado:** `29a66937beed638f511d93e7a1b986687dc59edd`
- **CI del HEAD:** run `41415711981`, success (todos los jobs, incluido build).
- **Baseline P19.1:** `docs/architecture/workflow-data-p19-1/09-final-certification.md`
  sigue **NO-GO producción**; P20 no cambia esa decisión.
- **Alcance de este corte:** P20-00 y P20-01. P20-02..18 no implementados.

## 1. Mapa real de dependencias

```text
connectors.id
  -> data_onboarding_sessions.connector_id
  -> catalog_sources.connector_id
  -> catalog_tables / catalog_suggestions
  -> kb_sources.config_json.connector_id   (puente Knowledge/Agent)
  -> workflow_capability_bindings.config.connection_ref
  -> data_query node (binding_ref + binding_hash)
  -> workflow_versions / workflow_instances
  -> commerce cart/quote/order (ZENT)
  -> inventory adapter (Bodega externa, stock)
```

IDs estables y scope:

| ID | Scope | Uso |
|---|---|---|
| `connectors.id` | org + workspace | credencial y host externo |
| `kb_sources.id` | org + workspace | fuente visible en Knowledge/Agent |
| `catalog_sources.id` | org + connector | discovery/profiling |
| `workflow_capability_bindings.id` | org + workspace | plan SQL declarativo |
| `capability_ref` | org + workspace | referencia lógica del workflow |
| `workflow_versions.id` | workflow | release inmutable |
| `workflow_instances.id` | org + workspace | conversación durable |

## 2. AS-IS / TO-BE

| Área | AS-IS | TO-BE MVP | Estado |
|---|---|---|---|
| Onboarding PostgreSQL | crea connector, catalog y kb_source; antes no creaba kb_source | fuente única ligada por `connector_id` | IMPLEMENTED P20-01 |
| Source type | `postgres` rompía el indexer; ahora `sql` | `sql` con `source_mode` y connector ref | IMPLEMENTED P20-01 |
| Indexado externo | `SQLSourceConnector` leía Managed DB interna | rechazo tipado; catálogo/live query | IMPLEMENTED P20-01 |
| full_refresh | borraba vectores de toda la org | prohibido; scoped-only | IMPLEMENTED P20-01 (fail closed) |
| Fuente en Agent picker | se mostraba como documento pendiente | “Base de datos conectada”, sin indexar | IMPLEMENTED |
| Query viva del agente | `query_database` usa SQL Expert/Managed DB | `execute_external` por conector externo; fallback interno bloqueado | IMPLEMENTED P20-02 (read-only) |
| Catálogo semántico | discovery + sugerencias, sin modelo comercial aprobado | modelo/manifest revisable | MISSING P20-03 |
| Grants por agente | P19.1 documenta, no implementa grants específicos | `agent_data_grants` + allowlist de recursos en `query_database` | PARTIAL P20-04 (backend; UI y tools tipadas pendientes) |
| Carrito/quote | commerce existente, no conectado a Bodega | quote server-side con Decimal | PARTIAL P20-10 |
| Sales funnel | 40 nodos existentes, demo interno | adaptar a capacidades externas | PARTIAL P20-09 |
| Checkout | proveedor abstracto, sin sandbox dedicado | checkout simulado verificable | MISSING P20-11 |
| Postventa | órdenes externas disponibles por SQL | identidad + owner filter | BLOCKED P20-12 |
| Observabilidad | métricas/timeline existentes | métricas de venta y grants | PARTIAL P20-15 |

## 3. Hallazgos P0/P1

### P0-01 — Fuente SQL contra la BD equivocada
`SQLSourceConnector` resolvía tablas con `get_async_session()` interno. Un
`kb_source` con `connector_id` externo podía indexar la Managed DB de ZENT.
**Mitigación P20-01:** `_assert_not_external()` en validate/discover/sync;
`source_mode=schema_only`; no snapshot externo.

### P0-02 — Borrado transversal de vectores
`full_refresh` llamaba `delete_by_organization(org)`, borrando todas las
fuentes de la organización. **Mitigación:** `FULL_REFRESH_UNSUPPORTED` antes de
cualquier borrado. No se declara soportado snapshot externo.

### P0-03 — Identidad de fuente por nombre
La reconciliación anterior aceptaba `type='sql' and name=...`. Dos conectores
con el mismo nombre podían colisionar. **Mitigación:** búsqueda solo por
`config_json.connector_id`; nombre duplicado recibe sufijo, no se reutiliza.

### P1-01 — Agente genérico sin query externa
`query_database` usaba `PostgresSqlExpert` sobre Managed DB. El conector
externo P19 ya está cableado a `QueryDatabaseTool` vía
`execute_external()` (P20-02): fuente por `connector_id`, sesión externa
read-only y fallback interno bloqueado. Siguen pendientes las tools
comerciales tipadas y los grants por capability (P20-04/05). No se declara
“agente vendedor” operativo.

### P1-02 — Órdenes y stock con doble autoridad potencial
Bodega tiene `orders/order_items`; commerce ZENT tiene su store. **Decisión
propuesta:** Bodega es autoridad de stock y de la orden histórica de la tienda;
ZENT es autoridad de carrito/quote y de la orden del MVP, con proyección
idempotente a Bodega solo si se implementa adapter. No doble escritura en P20-00/01.

## 4. Matriz de pruebas del corte

| Caso | Resultado | Evidencia |
|---|---|---|
| External SQL source no toca Managed DB | PASS | `tests/test_p20_sql_source_integrity.py` |
| full_refresh no borra org | PASS (fail closed) | mismo test |
| Onboarding crea kb_source visible | PASS | `test_database_onboarding_creates_visible_kb_source` |
| Fuente DB en Agent picker sin “indexar” | PASS | `AgentSourcePicker.test.tsx` |
| Migración dry-run de fuentes existentes | PASS script | `scripts/cert/p20_migrate_sql_sources.py` |
| Dos conectores con mismo nombre | NOT_RUN (integración) | pendiente P20-01 ampliación |
| Dos workspaces / dos DB con tablas iguales | NOT_RUN | pendiente P20-16 |

## 5. Plan mínimo MVP

1. P20-01: congelar contrato de fuente y guardas (este corte).
2. P20-02/03: ficha Knowledge y modelo comercial revisable.
3. P20-04/05: grants por agente y tools comerciales tipadas (la query
   externa read-only ya está en P20-02).
4. P20-06/07: wizard “Crear vendedor” y prompt/grounding.
5. P20-08/09: intent v2 + sales funnel adaptado.
6. P20-10/11: carrito/quote/checkout simulado.
7. P20-12..18: postventa, architect, UX, observabilidad, E2E y GO/NO-GO.

No se avanza a P20-02 hasta cerrar la integración de fuente de P20-01 en un
entorno con dos conectores y dos workspaces.
