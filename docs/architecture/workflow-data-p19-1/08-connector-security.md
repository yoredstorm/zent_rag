# P19.1-08 — Conectores PostgreSQL: TLS, SSRF y pooling

- **Estado:** PARTIAL. Política de red/TLS y cache acotado implementados;
  certificación con CA real, rotación y 100 concurrentes pendiente.

## Hallazgo AS-IS

- `_execute_connected_select` creaba un engine por consulta
  (`pool_size=1`, `max_overflow=0`) y hacía `dispose()`.
- `config.ssl=true` se traducía a `ssl="require"` sin verificar CA/hostname.
- No había allowlist de host/puerto ni bloqueo de loopback/metadata/red privada.
- No había timeouts separados de connect/acquire/statement.
- No había health check ni circuit breaker.

## Implementado

`src/platform/workflows/connector_security.py`:

- Production:
  - exige `ssl_mode=verify-full` (o `ssl=true`) con CA y hostname;
  - rechaza `ssl=require` y `disable`;
  - bloquea loopback, link-local, metadata (`169.254.169.254`), multicast,
    reservadas y privadas;
  - allowlist por `RAG_CONNECTOR_ALLOWED_HOSTS` o
    `binding.network_policy.allowed_hosts`.
- Development:
  - permite loopback/privadas solo con `RAG_CONNECTOR_ALLOW_PRIVATE=true`
    (default dev);
  - mantiene bloqueo de metadata y puertos peligrosos.
- Puertos bloqueados: 25, 6379, 9042, 11211, 27017.
- DNS: resuelve y valida todas las IP; IP literal evita DNS.
- Timeouts: `connect`, `command_timeout`, `statement_timeout` y pool timeout.
- Engine cache por loop/org/ws/conector/DSN:
  - `RAG_CONNECTOR_POOL_MAX` (8),
  - `RAG_CONNECTOR_POOL_SIZE` (2),
  - `RAG_CONNECTOR_POOL_OVERFLOW` (1),
  - `RAG_CONNECTOR_POOL_RECYCLE` (300 s),
  - TTL de engine (300 s), evicción LRU.
- `default_transaction_read_only=on` se mantiene.

## Pruebas

| Caso | Resultado | Evidencia |
|---|---|---|
| Producción bloquea loopback | PASS | `test_production_blocks_loopback_and_missing_tls` |
| Producción exige TLS | PASS | idem |
| `ssl=require` rechazado en prod | PASS | `test_production_rejects_ssl_require...` |
| `verify-full` con check_hostname | PASS | `test_verify_full_builds...` |
| Metadata/puerto bloqueado | PASS | `test_metadata_and_forbidden_ports...` |
| Allowlist de host | PASS | `test_host_allowlist_is_enforced` |
| PostgreSQL externo real | PASS | `test_workflow_data_p19_external.py` |
| CA inválida / hostname incorrecto | NOT_RUN | falta servidor TLS de prueba |
| 100 consultas concurrentes | NOT_RUN | falta carga real |
| Rotación de credencial | NOT_RUN | falta integración Secret Store |
| DNS rebinding | PARTIAL | se valida resolución, no se fija IP |

## Rutas

- `_execute_connected_select`.
- `POST /data-query/preview` para conectores.
- Config del conector en `connectors.config_json`.

## Compatibilidad y rollback

- Sin migración. Los conectores sin `ssl_mode` en producción fallarán cerrados;
  es intencional.
- En desarrollo, los conectores loopback siguen funcionando por la bandera dev.
- Rollback restaura `ssl=require` y engine por consulta; no recomendado.

## Riesgos residuales

- TLS verify-full no se probó contra CA privada real ni hostname incorrecto.
- El cache de engines no se comparte entre workers; el límite es por proceso.
- DNS rebinding: entre la resolución y la conexión el DNS podría cambiar. La
  allowlist reduce el riesgo, pero falta pinning de IP/SNI.
- No hay health check programado, circuit breaker ni métricas de pool.
- MySQL/SQL Server/Oracle/DB2 siguen NOT_SUPPORTED.
- No se certifica producción por tests locales.
