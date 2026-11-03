# P20-00 — Threat model del MVP retail

| ID | Amenaza | Superficie | Impacto | Control P20 | Estado |
|---|---|---|---|---|---|
| T01 | Fuente SQL externa lee Managed DB interna | `SQLSourceConnector` + sync | fuga interna | guard `SOURCE_MODE_UNSUPPORTED` | mitigado |
| T02 | full_refresh borra vectores de otra fuente/org | sync SQL | pérdida de conocimiento | `FULL_REFRESH_UNSUPPORTED` | mitigado |
| T03 | Dos conectores mismo nombre mezclan fuentes | onboarding | lectura DB equivocada | lookup por connector_id | mitigado |
| T04 | Precio/stock inyectado por LLM o payload | agente/tool | cobro falso | quote server-side + Decimal | mitigado P20-05/10 (carrito temporal) |
| T05 | Pedido de CUST-B leído por CUST-A | postventa | PII/IDOR | ownership pre-SQL + principal | bloqueado P20-12 |
| T06 | “No” interpretado como confirmación | WAIT/carrito | compra no consentida | YES_CONFIRMED explícito | pendiente P20-09 |
| T07 | Doble commit/reserva | checkout/inventory | sobreventa | idempotencia/ledger/TTL | parcial P19.1 |
| T08 | Webhook de pago forjado/duplicado | checkout | venta falsa | firma + dedupe + correlación | pendiente P20-11 |
| T09 | Conector deshabilitado sigue respondiendo | runtime | acceso revocado | revalidar binding/credential | pendiente P20-04 |
| T10 | Cross-tenant por workspace/org | API/planes | fuga | filtros org/ws backend | parcial P19.1 |
| T11 | PII en trace/print | observabilidad | exposición | redacción/cardinalidad | parcial P19.1 |
| T12 | Snapshot externo borra o sustituye datos vivos | sync | datos obsoletos | schema_only/live query | mitigado en P20-01 |
| T13 | Refresh concurrente crea dos fuentes | onboarding | duplicados | unique org+connector / transacción | pendiente prueba |
| T14 | SQL injection por identificadores | planes P19 | lectura no autorizada | allowlist/quote/bind params | parcial |

## Reglas fail-closed

- Fuente sin `connector_id` o con conector inactivo: no consulta.
- Sin principal verificado: `IDENTITY_REQUIRED` para pedidos/puntos.
- Sin grant de agente: `PERMISSION_DENIED`, no fallback al rol del editor.
- Plan/binding cambiado: `PLAN_STALE`, cero SQL.
- Pago no verificado: nunca `PAID`.
