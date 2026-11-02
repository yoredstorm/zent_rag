# P19.1-00 — Inventario AS-IS de fuentes, roles y efectos

- **SHA inventariado:** `9791a662404b00f8b80c293a2f94c6e897e38554`
- **Método:** lectura de código, migraciones Alembic, esquema de
  `ops/p19-external` y ejecución de tests locales. No es una auditoría de
  producción ni sustituye `pg_stat_activity`/IAM reales.
- **Regla:** “existe en código” no equivale a “certificado en producción”.

## 1. Fuentes de datos

| Fuente | Implementación | Credencial | Lectura | Escritura | Límites actuales |
|---|---|---|---|---|---|
| `managed_db` | `src/platform/managed_db/service.py` + `_execute_managed_select` | rol query reader del workspace | `get_one`, `list`, `count` | No (transacción read-only) | `max_rows=500`, `timeout<=30s`, `max_bytes<=5 MiB` |
| `connected_db` PostgreSQL | `_execute_connected_select` | Secret Store por `connection_ref` | mismas operaciones | No (`default_transaction_read_only=on`) | engine `pool_size=1`, `max_overflow=0`, dispose por consulta; TLS opcional `require` |
| `inventory` | `_execute_inventory_action` | Secret Store del conector; requiere `config.write=true` | stock/orders/reservations | reserve/commit/release | cantidad `1..max_quantity`, TTL `30..3600s`, row locks, ledger |
| `rest_api` | `_execute_rest` | Secret Store / config | GET | según binding | timeout/allowlist por revisar |
| `marketplace_action` | `_execute_marketplace_action` | capacidad de marketplace | acciones | efecto con ledger | idempotencia por `business_operation_id` |
| `semantic_query` | `_execute_semantic_query` | Managed DB / catálogo | consulta semántica | No | filtros por org/workspace |

Dialectos: solo PostgreSQL está implementado para `connected_db` e
`inventory`. MySQL/SQL Server/Oracle/DB2 no tienen adapter ni certificación.

## 2. Tablas y persistencia

| Objeto | Migración | Campos relevantes | Observación |
|---|---|---|---|
| `workflows` | 063, 088, 170 | `organization_id`, `workspace_id`, `graph`, `workflow_version`, `published_version` | grafo y releases versionados |
| `workflow_runs` | 038, 063, 088 | org/ws, actor, trigger, status, correlation | evidencia de ejecución |
| `workflow_run_steps` | 038, 063, 088 | nodo, intento, idempotency key, status | output puede incluir filas |
| `workflow_instances` | 153 | estado durable, WAIT/RESUME | snapshot de instancia |
| `workflow_signals` | 154 | señal tipada, dedupe | reanudación |
| `workflow_capability_bindings` | 155 | `id`, org, ws, `capability_ref`, provider, `config`, `credential_ref`, `status` | **sin versión ni hash**; unique por org/ws/capability |
| `connectors` | 003, 008, 024, 080 | org, ws, tipo, `config_json`, status | host/usuario en JSON; secreto aparte |
| `workflow_approvals` | 088, 177 | run, nodo, acción, estado, expira | aprobación humana |
| `audit_logs` | 003 | actor, acción, recurso, metadata | no cubre publicación de planes por sí sola |

`workflow_capability_bindings` no tiene columnas `plan_version`,
`canonical_plan_hash`, `superseded_at` ni historial. `upsert_binding` actualiza
la fila existente y la reactiva.

## 3. Roles y permisos relevantes

Sembrados en `src/infrastructure/db_init/versions/088_workflow_graph.py`:

| Permiso | Roles sistema con grant |
|---|---|
| `workflows:read` | owner, admin, member, viewer, ai_engineer, data_engineer, developer, analyst |
| `workflows:create` | owner, admin, member |
| `workflows:update` | owner, admin, member |
| `workflows:delete` | owner, admin, member |
| `workflows:run` | owner, admin, member |
| `workflow_runs:read` | owner, admin, member, viewer, ai_engineer, data_engineer, developer, analyst |
| `integrations:read` | owner, admin, member, viewer, ai_engineer, data_engineer, developer, analyst |
| `integrations:use` | owner, admin, member |
| `external_actions:execute` | owner, admin, member |
| `workflow_secrets:manage` | owner, admin, member |
| `workflow_approvals:approve` | owner, admin |
| `workflow_events:subscribe` | owner, admin, member |
| `connectors:read/write` | catálogo RBAC de 003/023; roles técnicos según migración |

Consecuencia AS-IS: **`member` puede editar un workflow y publicar una consulta
de datos**; no existe permiso `data_queries:*` ni `data_sources:discover`.
`publish_data_query_plan(... permissions=...)` recibe el conjunto pero no lo
usa para autorizar tablas, columnas ni PII.

## 4. Catálogo y caché

- `_CACHE_TTL_SECONDS = 30.0`.
- Clave: `organization_id:workspace_id:plans:<permisos ordenados>` o
  `...:sources:...`.
- Invalidación al publicar/deshabilitar binding.
- El catálogo publica solo bindings `managed_db`/`connected_db` con plan
  canónico; filtra `scope=organization` por `allowed_workspace_ids`.
- La introspección física muestra tablas/columnas disponibles del conector;
  **no hay allowlist de publicación** separada del descubrimiento.

## 5. Ejecución de consultas

Ruta real:

```text
data_query node
  -> execute_binding(organization_id, capability_ref, {"params": ...},
                     workspace_id, actor_id, workflow_id, run_id, instance_id, node_id)
  -> resolve_binding(org, capability_ref, workspace)
  -> validate_contract(payload)
  -> _dispatch_binding(kind)
  -> _execute_connected_select / _execute_managed_select
  -> _execute_data_query_plan(principal=None en connected_db)
```

Hechos verificados:

- `execute_binding` no recibe `permissions` ni `VerifiedPrincipal`.
- `_execute_connected_select` llama `_execute_data_query_plan(...)` sin
  `principal`.
- `_execute_data_query_plan` sí sabe aplicar `ownership.required` si recibe
  `principal`, pero la ruta real no lo alimenta.
- El nodo comprueba `binding_ref` **después** de ejecutar; la consulta ya
  ocurrió.
- El payload acepta solo `params`; tabla, columnas, `connection_ref`, filtros y
  `order_by` no son overrideables desde el payload. La autoridad está en el
  plan persistido, pero ese plan puede ser reemplazado por `upsert_binding`.
- `max_rows` y `max_bytes` se aplican en memoria después de `fetchall()`; no
  hay `LIMIT` de bytes ni streaming.
- `count` no devuelve filas, pero tampoco exige ownership si el plan no lo
  declara.

## 6. Conectores externos

- `connectors.type` acepta PostgreSQL; `config_json` contiene host, puerto, DB,
  usuario y `ssl` booleano.
- `get_secret_store()` usa Vault si está disponible; fallback
  `EncryptedPostgresSecretStore`.
- `_execute_connected_select` crea un engine nuevo por consulta, con
  `pool_size=1`, `max_overflow=0`, `pool_pre_ping=True`, y `dispose()` al final.
- `ssl=true` se traduce a `ssl="require"`; no hay `verify-full`, CA bundle ni
  validación de hostname.
- No hay allowlist de host/puerto, bloqueo de loopback/link-local/metadata ni
  revalidación DNS.
- Timeout: `statement_timeout` derivado de `plan.policy.timeout_ms`; no hay
  timeout separado de connect/acquire.
- No hay health check programado ni circuit breaker en esta ruta.

## 7. Inventario y efectos

- `inventory` exige `config.write=true` y resuelve conector/credencial.
- Operaciones: `reserve_stock`, `commit_stock`, `release_stock`.
- Usa `SELECT ... FOR UPDATE` sobre orden y stock; TTL con `NOW()` de la DB.
- Barrido de reservas expiradas: dentro de cada operación (lazy); no hay job
  periódico.
- Ledger `bodega.stock_movements` con `idempotency_key UNIQUE`.
- Clave de reserva actual: `reserve:<order_number>:<sku>`; no incluye
  `quantity`, línea ni versión de acción.
- Multi-ítem: no hay operación atómica de varias líneas; cada llamada es
  independiente.
- `effect_ledger` cubre `rest_api`, `marketplace_action` e `inventory` cuando
  hay `workflow_id` + `node_id`; no cubre `data_query` de lectura (correcto)
  ni sustituye la idempotencia transaccional del adaptador.
- `payment_status` y `order.status` son estados separados; no hay pasarela de
  pago real conectada.

## 8. Observabilidad y datos expuestos

- Output de `data_query` incluye `status`, `found`, `record`, `rows`,
  `columns`, `binding_ref`, `binding_hash`, `duration_ms`, `provenance`.
- `_exec_data_query` añade `message` con `exc.message` en errores.
- No hay redacción sistemática de filas/PII en la ruta de ejecución; preview
  redacta por heurística de nombre (`is_sensitive_column`) y solo
  `record`/`rows`, no `count`.
- Trazas/logs pueden recibir el output del nodo; no hay un redactor central
  probado para datos de negocio.
- Métricas de binding drift/plan stale no existen todavía.

## 9. Límites y licencias

- PostgreSQL 16 (imagen oficial) y `pgvector/pgvector:pg16`; licencia
  PostgreSQL.
- Redis 7, Qdrant 1.13.4, Grafana/Prometheus/Loki/Alertmanager en el stack
  local. No se certifican licencias de terceros en este documento.
- El PostgreSQL externo P19 es un contenedor separado en
  `ops/p19-external/docker-compose.yml`, con volumen propio.

## 10. Diferencias documentación vs código

- La documentación P19 describe ownership como implementado en el ejecutor,
  pero la ruta `connected_db` no propaga principal.
- `06-external-postgres.md` declara “CERTIFIED LOCAL” para lectura; eso no
  cubre TLS verificado, SSRF, pooling ni producción.
- `08-bodega-approval-stock.md` puede describir barrido/job que el código aún
  no tiene. Manda el código y el SHA, no la narrativa.
