# Webhooks

Zent recibe webhooks de **billing inbound**. No hay webhooks outbound de cliente en esta versión.

`POST /api/v1/billing/webhooks/{provider}` es público: la protección es la firma HMAC.

Header: `X-Zent-Signature: t=<unix>,v1=<hex>`

El payload se verifica con el secreto del proveedor. Eventos duplicados (`provider`, `event_id`) se ignoran.

No uses `Idempotency-Key` aquí; la idempotencia es la tabla `billing_events`.
