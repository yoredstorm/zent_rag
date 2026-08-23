# Autenticación

Todas las rutas de negocio (salvo signup/login, planes públicos y webhooks de billing) exigen:

```
Authorization: Bearer <token>
```

## API keys

- Prefijo nuevo: `zent_sk_live_`
- Prefijo legado (sigue válido): `rag_live_` / `rag_test_`
- Se persiste solo el hash SHA-256. El secreto se revela **una vez**.

Scopes públicos (allowlist; `admin:*` está prohibido al crear keys de organización):

| Scope | Uso |
|---|---|
| `rag:read` | `POST /rag/query` y stream |
| `rag:write` | Ingestión, sources, knowledge bases |
| `agents:execute` | `POST /agents/{id}/run` |
| `connectors:read` | Listar / ver conectores |
| `connectors:write` | Crear / editar conectores |
| `usage:read` | `GET /billing/usage*` |

Aliases de compatibilidad: `rag:query` ≡ `rag:read`, `rag:ingest` ≡ `rag:write`.

Crear una key (requiere `Idempotency-Key`):

```bash
curl -X POST http://localhost:8000/api/v1/organizations/api-keys \
  -H "Authorization: Bearer $PORTAL_SESSION" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{"name":"backend","scopes":["rag:read","rag:write"]}'
```

## Sesión del portal

Login/signup devuelven `access_token` con prefijo `rag_sess_`. Es una sesión AES-GCM, no una API key. El portal la usa para la UI; para SDKs usa `api_key`.
