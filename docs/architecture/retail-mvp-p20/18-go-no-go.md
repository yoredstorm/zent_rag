# P20-18 — GO / NO-GO del MVP retail

- **Fecha:** 2026-11-03
- **Alcance:** vendedor conversacional sobre PostgreSQL externo, carrito
  temporal, checkout manual MVP, postventa por conversación y observabilidad.
- **Decisión:** **GO acotado a demo/sandbox controlado. Producción NO-GO.**

## Gates

| Gate | Criterio | Estado | Evidencia |
|---|---|---|---|
| G00 | Base y CI verdes | PASS | CI del HEAD, lint/test/certification |
| G01 | Fuente SQL externa correcta | PASS parcial | dos conectores homónimos no probados en vivo |
| G02 | Discovery/PII | PARTIAL | schema-only, sin snapshot externo |
| G03 | Grants por agente | PASS backend; UI NOT_RUN | `agent_data_grants` + tools |
| G04 | Tools tipadas de catálogo | PASS | `test_p20_catalog_tools.py` |
| G05 | 6+ turnos / WAIT durable | PARTIAL | historial 6 turnos PASS; slots durables NOT_RUN |
| G06 | Carrito/quote/stock | PASS funcional; carga concurrente NOT_RUN | `test_p20_cart.py` |
| G07 | Checkout sandbox/manual | PASS local; Stripe/PSP NOT_IMPLEMENTED | `e2e_checkout_manual.py` |
| G08 | Postventa con ownership | PASS por conversación; identidad externa BLOCKED | `GetMyOrderTool` |
| G09 | Architect con recursos reales | PARTIAL | plantilla 181 publicada; draft E2E NOT_RUN |
| G10 | E2E C01-C25 | PARTIAL | checkout externo manual PASS local; 25 escenarios NOT_RUN |
| G11 | Runbook/rollback | PARTIAL | este documento + rollback manual |

## Qué está probado

1. Catálogo real desde `bodega.product_catalog_v` con precio/stock backend.
2. Carrito temporal por conversación, TTL configurable, CAS e idempotencia.
3. Cierre de carrito a orden ZENT con precios backend y snapshot de fuente.
4. Proyección idempotente a `bodega.orders`.
5. Reserva batch de stock, commit batch y release batch.
6. Nodo manual `manual_payment_validation`: espera aprobación humana, devuelve
   `provider=manual_mvp`, no cobra y está bloqueado en producción.
7. Checkout E2E local: carrito → orden → proyección → reserva → aprobación →
   `PAID` → commit de stock.
8. Postventa: `get_my_order` solo devuelve órdenes de la misma conversación;
   un número ajeno responde `ORDER_NOT_FOUND`.
9. KPIs de carrito en `/api/v1/commerce/kpis`.
10. Plantilla `retail_checkout_manual` publicada por migración 181.

## Por qué producción sigue NO-GO

- **Pago real:** el único cierre es aprobación humana `manual_mvp`. No hay
  Stripe/PSP real, webhook firmado end-to-end, conciliación ni refunds probados.
- **Identidad:** la postventa usa `conversation_id`; no hay autenticación de
  cliente final (OTP, magic link o cuenta) para órdenes externas históricas.
- **Concurrencia:** no hay prueba de carga con muchos carritos/checkouts
  simultáneos ni de expiración bajo carrera.
- **UI:** grants y checkout se operan por API/Studio; falta pantalla de grants
  y bandeja específica de pagos manuales.
- **E2E completo:** C01-C25 no está cubierto; faltan casos de rechazo,
  expiración, doble aprobación y caos de conectores.

## Rollback

1. Desactivar la plantilla `retail_checkout_manual` en Studio.
2. Revertir la migración 181 si se publicó por error:
   `DELETE FROM workflow_templates WHERE slug='retail_checkout_manual'`.
3. El nodo manual es temporal: quitar `manual_payment_validation` del grafo y
   borrar `src/platform/workflows/manual_payment.py` al integrar Stripe.
4. Los carritos vencen solos; para una purga inmediata:
   `DELETE FROM commerce_cart_sessions WHERE organization_id = :org`.
5. No borrar `commerce_orders` ni movimientos de Bodega sin conciliación.

## Runbook de demo

```powershell
# 1. Fuente externa y bindings P19/P20
python ops/p19-external/seed_tenant.py
# 2. Publicar plantilla
python ops/p20/seed_checkout_manual.py
# 3. Verificar API
curl http://127.0.0.1:8000/health
# 4. Smoke checkout manual (dentro del contenedor API)
docker cp ops/p20/e2e_checkout_manual.py rag-api:/tmp/e2e.py
docker exec rag-api python /tmp/e2e.py
```

Resultado esperado: `run_status=pending_approval`, aprobación aprobada,
`order.status=PAID`, `payment_provider=manual_mvp`.

## Próximo corte para producción

1. Stripe/PSP sandbox con webhook firmado, dedupe y conciliación.
2. Identidad de cliente final y ownership de órdenes externas.
3. Carga/concurrencia y caos de conectores.
4. UI de grants y pagos manuales.
5. Certificación E2E C01-C25 y GO/NO-GO formal.
