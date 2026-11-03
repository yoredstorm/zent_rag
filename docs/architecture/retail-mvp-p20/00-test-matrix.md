# P20-00 — Matriz de pruebas y release gates

- **HEAD:** `d71dcfbce1a61b2e36f16b22c68c8d87d2a73544`
- **CI:** run `41585035889`, success.
- **Regla:** PASS solo con ejecución y evidencia; mocks no prueban PostgreSQL
  externo, concurrencia, pago ni usuarios.

## Gates del MVP

| Gate | Riesgo | Evidencia mínima | Estado P20-00/01 |
|---|---|---|---|
| G00 | base/CI | CI verde, invariantes | PASS |
| G01 | fuente SQL única | tests P20-01, dos conectores | PARTIAL |
| G02 | discovery/PII | estados honestos, profiling seguro | PARTIAL |
| G03 | grants/ownership | runtime grants + A/B | PASS backend; UI NOT_RUN P20-04 |
| G04 | tools tipadas | precio/stock backend | PASS P20-05 |
| G05 | 6+ turnos/WAIT | E2E durable | PARTIAL P20-08 (historial); slots/WAIT NOT_RUN |
| G06 | carrito/quote/stock | concurrencia y precio cambiante | PARTIAL P20-10: CAS + precio recalculado; carga concurrente NOT_RUN |
| G07 | checkout simulado | webhook verificado/dedupe | PARTIAL P20-11: manual MVP E2E PASS; Stripe/PSP NOT_IMPLEMENTED |
| G08 | postventa | A/B, identidad | PARTIAL P20-12: ownership por conversación PASS; identidad externa BLOCKED |
| G09 | architect | draft con recursos reales | PARTIAL P20-13: plantilla publicada; draft E2E NOT_RUN |
| G10 | E2E C01-C25 | PostgreSQL externo, Playwright | PARTIAL P20-17: checkout externo manual PASS local; 25 escenarios NOT_RUN |
| G11 | runbooks/rollback | métricas, rollback | PASS documentado P20-18; carga NOT_RUN |

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
| Contexto multi-turno «¿Y el de 5 kg?» | PASS mínimo | Historial textual por `conversation_id`; slots/WAIT P20-08 |
| Slots durables / WAIT-RESUME | NOT_RUN | P20-08 completo |
| Catálogo semántico / manifiesto | PASS | `tests/test_p20_retail_seller.py`, `GET /commerce/catalog/manifest` |
| Crear vendedor backend | PASS unitario | `tests/test_p20_retail_seller.py` |
| Crear vendedor API real | PASS local (fuente P19, 10 tools, 5 grants) | `POST /agents/retail-seller` |
| Crear vendedor UI/wizard | NOT_RUN | P20-06 |
| Prompt retail/grounding | PASS | `RETAIL_SELLER_PROMPT` |
| Grants por agente/capability | PASS backend | `04-data-grants.md` |
| Grant activo limita recursos | PASS (local, runtime real) | idem |
| Sin grant, `PERMISSION_DENIED` | PASS (local, runtime real) | idem |
| `row_scope` falla cerrado | PASS | `tests/test_p20_external_sql_query.py` |
| UI de grants | NOT_RUN | P20-04 |
| `find_products` precio/stock backend | PASS | `tests/test_p20_catalog_tools.py` |
| `get_price_and_stock` total decimal | PASS | idem |
| `NOT_FOUND` sin 500 | PASS | idem |
| Presentación «arroz de 1 kg» | PASS (local, runtime real) | `05-catalog-tools.md` |
| Carrito/quote/checkout | PASS carrito + checkout manual; Stripe NO_IMPLEMENTED | `10-cart-session.md`, `09-checkout-externo.md` |
| Carrito TTL / purga | PASS (local, Postgres real) | `tests/test_p20_cart.py` |
| Carrito CAS / idempotencia | PASS | idem |
| Carrito externo Bodega | PASS en tools (POST HTTP con conversación real) | `10-cart-session.md` |
| Carrito multi-turno HTTP | PASS (local): agrega, cambia, consulta, quita | `tests/test_p20_cart.py` + HTTP |
| Carrito en Workflow Studio / binding | PASS local (plantilla 181 + E2E externo) | `09-checkout-externo.md` |
| Checkout manual E2E externo | PASS local: carrito, orden, proyección, reserva, aprobación, PAID, commit | `ops/p20/e2e_checkout_manual.py` |
| Checkout ZENT interno E2E | PASS | `tests/test_p20_retail_e2e.py` |
| Postventa por conversación | PASS local; número ajeno NOT_FOUND | `tests/test_p20_cart.py`, HTTP |
| Postventa identidad externa | BLOCKED: sin auth de cliente | P20-12 |
| KPI carritos | PASS | `tests/test_p20_cart.py`, portal `SalesFunnelKpis.test.tsx` |
| Aislamiento workspace inventario | PASS | `tests/test_p20_inventory_binding.py` |
| Architect draft E2E | NOT_RUN | P20-13 |
| E2E C01-C25 completo | PARTIAL | P20-17 |
| Nodo pago manual MVP | PASS | `tests/test_p20_manual_payment.py` |
| Pago manual sin aprobación | PASS (pending_approval) | idem |
| Pago manual aprobado | PASS (`provider=manual_mvp`) | idem |
| Pago manual en producción | PASS (bloqueado) | idem |
| Stripe/PSP real | NOT_RUN | P20-11 |
| Postventa con identidad externa | BLOCKED | P20-12 |


## Comandos

```powershell
uv run --frozen --no-sync pytest tests/test_p20_sql_source_integrity.py -q
uv run --frozen --no-sync pytest tests/test_data_onboarding.py::test_database_onboarding_creates_visible_kb_source -q
uv run --frozen --no-sync pytest tests/test_p20_cart.py tests/test_p20_retail_e2e.py tests/test_p20_inventory_binding.py -q
uv run --frozen --no-sync pytest tests/certification/workflows/test_checkout_snapshot.py -q
npx vitest run src/components/commerce/SalesFunnelKpis.test.tsx
uv run --frozen --no-sync python scripts/cert/p20_migrate_sql_sources.py --dry-run
```
