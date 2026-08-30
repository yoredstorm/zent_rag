# Security runbook — secret rotation

CSRF: las sesiones del portal son Bearer (no cookie). Un formulario cross-site no adjunta el token; no hay cookie de sesión que rotar. No introducir cookies de auth sin un diseño CSRF.

Reset de contraseña v1 no envía email (sin SMTP). En `development` `POST /auth/forgot-password` puede devolver `dev_reset_token`. En producción el token no se revela; documentar SMTP antes de vender enterprise.

## `RAG_PORTAL_SESSION_KEY`

1. Generar `openssl rand -hex 32`.
2. Desplegar el nuevo valor en todos los procesos API a la vez.
3. Las sesiones AES existentes quedan inválidas; los usuarios vuelven a login.
4. No commitear el valor. Rotar si hay sospecha de filtración.

## API keys (`zent_sk_live_`)

Rotar desde el portal (`/keys`) o `POST` rotate existente. La key anterior deja de autenticar. `admin:*` solo se crea por repo/ops, no por el allowlist del portal.

## Stripe (`RAG_BILLING_STRIPE_*`)

Si Fase 04 está activa: rotar secret + webhook signing secret en el dashboard de Stripe y en env. Reenviar webhooks fallidos. `RAG_PAYMENT_PROVIDER=manual` no usa estos secretos.

## Embed (`zent_emb_`)

Revocar desde el builder (`POST /agents/{id}/embed/revoke`) y emitir un token nuevo. El `public_id` anterior deja de responder (401).
