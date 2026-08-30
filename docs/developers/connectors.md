# Connectors

```python
client.connectors.list()
client.connectors.create("ERP", "postgres", config={"host": "db.internal"})
```

```ts
await client.connectors.list();
await client.connectors.create("ERP", "postgres", { config: { host: "db.internal" } });
```

HTTP:

- `GET /api/v1/connectors` — `connectors:read`
- `POST /api/v1/connectors` — `connectors:write` + `Idempotency-Key`
- `POST /connectors/{id}/test` · `/discover` · `GET /capabilities` · `GET /types`
- `POST /api/v1/connectors/oauth/drive/start` — `connectors:write` (Google Drive)
- `GET /api/v1/connectors/oauth/drive/callback` — redirect de Google (state firmado)

Los secretos van en `secrets` y **nunca** se devuelven en el JSON de respuesta (`has_secrets: true`).

## Google Drive (`gdrive`)

Conector completo (plugin + ingestion). No hay Notion, SharePoint ni otros SaaS en esta versión.

### OAuth

1. Configura `RAG_GOOGLE_OAUTH_CLIENT_ID`, `RAG_GOOGLE_OAUTH_CLIENT_SECRET` y
   `RAG_GOOGLE_OAUTH_REDIRECT_URI` (debe coincidir con Google Cloud).
2. `POST /api/v1/connectors/oauth/drive/start` con `{ "name", "folder_id" }` crea
   (o reutiliza) un conector `gdrive` y devuelve `authorization_url`.
3. El `state` es HMAC (org + connector + expiry). El callback **no** confía en
   `organization_id` del cliente: solo en el state firmado.
4. Google redirige a `/api/v1/connectors/oauth/drive/callback`. El refresh token
   se guarda en el SecretStore keyed por `connector_id`. Nunca en `config_json`.

Scope: `https://www.googleapis.com/auth/drive.readonly` (solo lectura).
`access_type=offline` + `prompt=consent` para obtener refresh token.

### Sync

Crea una fuente `type=gdrive` con `config: { "folder_id", "connector_id" }`.
Lista archivos de esa carpeta, descarga PDF / Markdown / texto / DOCX / Google Docs
(export texto) y los normaliza con el pipeline `file` existente. Cursor incremental:
`source_sync_state.done_keys`.

### Límites

- Hasta 100 archivos por sync (`max_objects` en config).
- Cuotas de la API de Google (backoff del motor de ingestion si el job falla).
- Shared drives: `supportsAllDrives=true`; el usuario OAuth debe tener acceso.
- Redirect URIs distintos por ambiente (ver producción).

### Qué no hay aún

Notion, SharePoint, Snowflake, BigQuery, Kafka.
