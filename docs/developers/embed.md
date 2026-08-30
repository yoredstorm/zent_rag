# Embedded chat

Publica un agente en un sitio de terceros con un token de embed (`zent_emb_…`), no con la API key `zent_sk_live`.

## Requisitos

- Entitlement `embed_widget` del plan (Control Center).
- Orígenes http(s) allowlist. Un `Origin` no listado recibe `403`.
- `public_id` opaco: no es el UUID del agente. `organization_id` del cliente se ignora.

## API

```
POST /api/v1/agents/{id}/embed/token   # 201 { token, public_id, allowed_origins }
GET  /api/v1/agents/{id}/embed         # snippet + iframe_src
POST /api/v1/agents/{id}/embed/revoke
POST /api/v1/embed/{public_id}/chat    # público; body { messages }
```

Snippet:

```html
<script src="https://{host}/embed.js" data-embed="{public_id}"></script>
```

Iframe: `https://{host}/embed/{public_id}` (CSP `frame-ancestors` = orígenes allowlist).

## CSP del cliente

Permite el host de Zent en `script-src` y `frame-src`. El widget v1 no setea cookies de tracking; la conversación vive en memoria del iframe.

Revocar el token corta el chat (`401`).
