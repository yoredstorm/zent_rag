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


## Headers anti-spoof

El Bearer es la **unica** autoridad de identidad. `X-Organization-Id` y `X-User-Id` son opcionales: si llegan y no coinciden con el contexto autenticado, la API responde 403. Nunca se usan para elegir tenant o usuario. `X-User-Role` y `body.role` solo pueden degradar el rol RAG (`admin` -> `customer`); nunca elevan.

## Scopes y permisos

| Scope / permiso | Donde aplica |
|---|---|
| `rag:read` (`rag:query`) | Chat RAG |
| `rag:write` (`rag:ingest`) | Ingesta y fuentes |
| `usage:read` (`billing:read`) | Lectura de uso / billing |
| `billing:write` | Mutaciones de billing (owner; no es scope publico de API key) |
| `admin:sql` | Consola SQL admin (no es scope publico de API key) |
| `prompt:read` / `prompt:write` | System prompts |

`admin:sql` y `billing:write` no entran en el allowlist de API keys de desarrollador.

## Modelo de amenazas

| Amenaza | Mitigacion | Residual |
|---|---|---|
| Spoof de `X-Organization-Id` / `X-User-Id` | 403 si difieren del Bearer | Headers ausentes se ignoran |
| Elevacion `body.role` / `X-User-Role` | Degrade-only; el rol sale del token | Keys legacy sin `rag:customer` siguen RAG `admin` |
| SQL Expert / admin SQL cross-tenant | AST SELECT-only + overwrite de `organization_id` + Postgres READ ONLY | Tablas sin columna org no reciben predicado (allowlist + grants) |
| Bypass del parser SQL | Rol `rag_reader` READ ONLY; fail-closed en production sin DSN readonly | CRUD admin de tablas sigue en usuario RW y se apaga en production |
| Coleccion Qdrant compartida | Filtro `organization_id` + assert vs `AuthenticatedContext` | Sin RLS de Qdrant nativo |
| Scope `portal` en sesion | Sigue siendo bypass de `has_scope`; el RBAC de membership aplica | Intencional para el portal |
| Consola admin SQL | `admin:sql` + org-admin + timeout/max rows | Sin RLS de Postgres |
