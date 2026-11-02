# P20-00 — Matriz de pruebas y release gates

- **HEAD:** `29a66937beed638f511d93e7a1b986687dc59edd`
- **CI:** run `41415711981`, success.
- **Regla:** PASS solo con ejecución y evidencia; mocks no prueban PostgreSQL
  externo, concurrencia, pago ni usuarios.

## Gates del MVP

| Gate | Riesgo | Evidencia mínima | Estado P20-00/01 |
|---|---|---|---|
| G00 | base/CI | CI verde, invariantes | PASS |
| G01 | fuente SQL única | tests P20-01, dos conectores | PARTIAL |
| G02 | discovery/PII | estados honestos, profiling seguro | PARTIAL |
| G03 | grants/ownership | runtime grants + A/B | BLOCKED P20-04 |
| G04 | tools tipadas | precio/stock backend | BLOCKED P20-05 |
| G05 | 6+ turnos/WAIT | E2E durable | NOT_RUN |
| G06 | carrito/quote/stock | concurrencia y precio cambiante | PARTIAL P19.1 |
| G07 | checkout simulado | webhook verificado/dedupe | BLOCKED P20-11 |
| G08 | postventa | A/B, identidad | BLOCKED P20-12 |
| G09 | architect | draft con recursos reales | BLOCKED P20-13 |
| G10 | E2E C01–C25 | PostgreSQL externo, Playwright | NOT_RUN |
| G11 | runbooks/rollback | métricas, rollback | PARTIAL |

## Pruebas P20-01 ejecutadas

| Caso | Resultado | Evidencia |
|---|---|---|
| SQL externo no usa Managed DB | PASS | `test_p20_sql_source_integrity.py` |
| full_refresh no borra org | PASS (fail closed) | idem |
| Onboarding crea fuente visible | PASS | `test_database_onboarding_creates_visible_kb_source` |
| Fuente DB en Agent picker | PASS | `AgentSourcePicker.test.tsx` |
| Migración dry-run | PASS script | `scripts/cert/p20_migrate_sql_sources.py` |
| Dos conectores mismo nombre | NOT_RUN | pendiente integración |
| Dos DB con mismas tablas | NOT_RUN | pendiente P20-16 |
| Refresh concurrente | NOT_RUN | pendiente P20-16 |

## P20-02 — Agente conversacional sobre BD externa

| Caso | Resultado | Evidencia |
|---|---|---|
| `_run_query` usa sesión externa | PASS | `tests/test_p20_external_sql_query.py` |
| `_run_query` sin BD autorizada no usa BD interna | PASS | idem |
| Fuente se resuelve por `connector_id` | PASS | idem |
| Dos conectores distintos fallan cerrado | PASS | idem |
| `query_database` enruta a `execute_external` | PASS | idem |
| Agente DB-only no recibe `search_knowledge` | PASS | idem |
| Precio real `4.80 / 22.50 PEN` | PASS (local, runtime real) | `02-external-sql-agent.md` |
| `¿Qué tablas tienes?` con discovery real | PASS (local, runtime real) | idem |
| Contexto multi-turno «¿Y el de 5 kg?» | PASS (local, runtime real) | idem |
| Grants por agente/capability | NOT_RUN | P20-04 |
| Grant activo limita recursos | PASS (local, runtime real) | `04-data-grants.md` |
| Sin grant, `PERMISSION_DENIED` | PASS (local, runtime real) | idem |
| `row_scope` falla cerrado | PASS | `tests/test_p20_external_sql_query.py` |
| UI de grants | NOT_RUN | P20-04 pendiente |
| Carrito/quote/checkout | NOT_RUN | P20-10/11 |
| Postventa con identidad | NOT_RUN | P20-12 |


## Comandos

```powershell
uv run --frozen --no-sync pytest tests/test_p20_sql_source_integrity.py -q
uv run --frozen --no-sync pytest tests/test_data_onboarding.py::test_database_onboarding_creates_visible_kb_source -q
npx vitest run src/components/agentStudio/AgentSourcePicker.test.tsx
uv run --frozen --no-sync python scripts/cert/p20_migrate_sql_sources.py --dry-run
```
