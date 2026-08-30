# Webhooks

Zent recibe webhooks de **billing inbound**. No hay webhooks outbound de cliente en esta versión.

`POST /api/v1/billing/webhooks/{provider}` es público: la protección es la firma del provider. Eventos duplicados (`provider`, `event_id`) se ignoran (`billing_events`).

No uses `Idempotency-Key` aquí.

## Manual (`PAYMENT_PROVIDER=manual`)

Header: `X-Zent-Signature: t=<unix>,v1=<hex>`

HMAC-SHA256(`BILLING_WEBHOOK_SECRET`, `"{timestamp}.{body}"`). Ventana de replay: 5 minutos.

## Stripe (`PAYMENT_PROVIDER=stripe`)

Header: `Stripe-Signature: t=<unix>,v1=<hex>`

Misma construcción HMAC que Stripe (`t.{raw_body}`) con `BILLING_STRIPE_WEBHOOK_SECRET`. Firma inválida → 400. Metadata `organization_id` es obligatoria; si no coincide con `client_reference_id` → 400 y no se muta ninguna org.

Eventos aplicados: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`, `invoice.payment_failed`.

Checkout self-service: `POST /api/v1/billing/checkout` `{ "plan_name", "interval" }` (permiso `billing:write`) → `{ checkout_url, session_id }`. El plan **no** cambia hasta el webhook. Enterprise no es self-service.

Tests locales con Stripe CLI no son requisito de CI; las firmas se construyen en pytest.
