# P19.1-04 — Contrato de resultados, errores y estado terminal

- **Estado:** DONE para nodo `data_query`, runtime y preview.
- **Riesgo cerrado:** G04.

## Hallazgo AS-IS

- `_exec_data_query` capturaba `BindingError` y devolvía
  `NodeOutcome(output={"status":"ERROR"})` sin `error`; el runtime podía marcar
  el nodo succeeded y el workflow terminar COMPLETED.
- `NOT_FOUND`, `MULTIPLE_MATCHES`, `FOUND`, `ERROR` y `SIMULATED` no tenían
  categorías ni retryability.
- El runtime descartaba el output seguro del nodo cuando fallaba.
- La UI mostraba JSON crudo; el estado `NOT_FOUND` no era accionable.

## Contrato v2

`zent.workflow.data-query.result/v2`:

```json
{
  "schema": "zent.workflow.data-query.result/v2",
  "status": "FOUND|NOT_FOUND|MULTIPLE_MATCHES|NO_LONGER_VALID|ERROR|SIMULATED",
  "category": "domain|operational|security|contract|configuration|simulation",
  "reason_code": "TIMEOUT",
  "recoverable": false,
  "retryable": true,
  "found": false,
  "record": null,
  "rows": [],
  "count": null,
  "row_count": 0,
  "truncated": false,
  "data_as_of": null,
  "source_ref": "...",
  "binding_ref": "...",
  "binding_hash": "...",
  "duration_ms": 12,
  "correlation_id": "...",
  "provenance": {},
  "safe_message": "La consulta tardó demasiado.",
  "capability": "p19.price"
}
```

Reglas:

- `FOUND`/`NOT_FOUND`/`MULTIPLE_MATCHES` son dominio: nodo succeeded.
- `TIMEOUT`/`CONNECTION_FAILED`/`PROVIDER_UNAVAILABLE`/`SCHEMA_DRIFT` son
  operativos: nodo failed, retryable cuando aplica.
- `PERMISSION_DENIED`/`IDENTITY_REQUIRED`/`PLAN_STALE`/`BINDING_CHANGED` son
  seguridad/contrato: nodo failed, workflow no COMPLETED sin rama de
  recuperación.
- `SIMULATED` nunca es un dato certificado.
- El runtime conserva el output seguro del nodo fallido y añade
  `typed_port`/`error_contract`.
- `safe_message` no incluye `exc.message` crudo, SQL ni PII.

## Rutas

- Nodo `data_query` y `capability_call`.
- Runtime `execute_graph` y ejecución con retries.
- Preview (`result.category`, `safe_message`).
- UI de nodo: tabla de 5 filas, mensaje humano, `aria-live`; JSON solo en
  avanzado.

## Pruebas

| Caso | Resultado | Evidencia |
|---|---|---|
| `NOT_FOUND` sin error de nodo | PASS | `test_data_query_not_found_is_domain_success` |
| `PERMISSION_DENIED` falla y no filtra mensaje | PASS | `test_data_query_maps_binding_error_to_status` |
| `TIMEOUT` operativo/retryable | PASS | `test_data_query_timeout...` |
| Run termina failed, no completed | PASS | `test_data_query_timeout_fails_the_run_not_completed` |
| `BINDING_CHANGED` | PASS | `test_data_query_detects_binding_change` |
| Simulación no ejecuta | PASS | `test_data_query_simulation_does_not_execute` |

## Compatibilidad y rollback

- Se conservan los campos v1 (`status`, `found`, `record`, `rows`, etc.).
- No hay migración.
- Rollback devuelve el comportamiento anterior (ERROR como output sin fallo de
  nodo), que es un riesgo; no se recomienda.

## Riesgos residuales

- El branching tipado usa el mecanismo existente; falta declarar puertos
  `found/not_found/multiple_matches/error` en el catálogo visual para todos los
  casos.
- No se implementó cache/idempotencia de reads (correcto por privacidad, pero
  falta política explícita).
- `data_as_of` depende de que el plan/proveedor lo entregue; hoy suele ser
  `null`.
- Falta prueba E2E de workflow con rama de recuperación exitosa y timeout real
  de PostgreSQL.
