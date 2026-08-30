# Autenticación

Todas las rutas de negocio (salvo signup/login/forgot-password/reset-password, planes públicos, embed chat, callback OAuth de Drive y webhooks de billing) exigen:

```
Authorization: Bearer <token>
```

## API keys

- Production: `zent_sk_live_` (default). Development: `zent_sk_test_`.
- Prefijo legado (sigue válido): `rag_live_` / `rag_test_`.
- Se persiste solo el hash SHA-256. El secreto se revela **una vez**.
- `environment` en create/list es additive (`live` | `test`). No hay columna extra: se deriva del prefijo.
- Test y live leen **los mismos datos** de la org. Test añade cabecera `X-Zent-Environment: test` y cuota más baja (30 req/min, 1.000/día). Live: 100 req/min, 10.000/día (`rag:rl:key:{id}`).

Scopes públicos (allowlist; `admin:*` está prohibido al crear keys de organización):

| Scope | Uso |
|---|---|
| `rag:read` | `POST /rag/query` y stream |
| `rag:write` | Ingestión, sources, knowledge bases |
| `knowledge:read` | Fuentes y KBs (`sources:read`, `kbs:read`) + `rag:read` |
| `agents:read` | Listar agentes |
| `agents:execute` | `POST /agents/{id}/run` |
| `connectors:read` | Listar / ver conectores |
| `connectors:write` | Crear / editar conectores |
| `usage:read` | `GET /billing/usage*` |
| `analytics:read` | Alias de `usage:read` |

Aliases de compatibilidad: `rag:query` ≡ `rag:read`, `rag:ingest` ≡ `rag:write`, `billing:read` ≡ `usage:read`. `rag:query` no se rompe.

Crear una key (requiere `Idempotency-Key`):

```bash
curl -X POST http://localhost:8000/api/v1/organizations/api-keys \
  -H "Authorization: Bearer $PORTAL_SESSION" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{"name":"backend","scopes":["rag:read","rag:write"],"environment":"live"}'

# Development (prefijo zent_sk_test_)
#   "environment":"test"
```

## Sesión del portal

Login/signup devuelven `access_token` con prefijo `rag_sess_`. Es una sesión AES-GCM, no una API key. El portal la usa para la UI; para SDKs usa `api_key`.

`POST /api/v1/auth/forgot-password` y `POST /api/v1/auth/reset-password` no enumeran emails (siempre 200 en forgot). El token es de un solo uso y expira. Sin SMTP: en development la respuesta puede incluir `dev_reset_token`. Rotación de secretos: [`docs/platform/SECURITY_RUNBOOK.md`](../platform/SECURITY_RUNBOOK.md). CSRF no aplica a Bearer (sin cookie de sesión).

## Invitaciones de organización

Permiso `users:write`. No hay mailer: el token se revela **una sola vez** en el 201 (igual que las API keys). No se registra el token en claro.

```bash
# Crear
curl -X POST http://localhost:8000/api/v1/organizations/invites \
  -H "Authorization: Bearer $PORTAL_SESSION" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{"email":"teammate@example.com","role":"member"}'

# Listar (sin token)
curl http://localhost:8000/api/v1/organizations/invites \
  -H "Authorization: Bearer $PORTAL_SESSION"

# Aceptar (sesión del invitado cuyo email coincide)
curl -X POST http://localhost:8000/api/v1/organizations/invites/{id}/accept \
  -H "Authorization: Bearer $GUEST_SESSION" \
  -H "Content-Type: application/json" \
  -d '{"token":"..."}'
```

Conflictos: email duplicado pendiente → 409. Límite de usuarios del plan → 409 `plan_limit_reached`. Auditoría: `invite.created` / `invite.accepted`.

## Platform admin (Control Center)

Un **owner de organización no es platform admin**. `POST /api/v1/auth/platform/login` {email, password} emite una sesión `typ=platform` (mismo prefijo `rag_sess_`, `organization_id` nulo). Esa sesión puede llamar `/api/v1/platform/*` y `GET /api/v1/billing/admin/*`.

Las API keys de máquina con scope `admin:*` (seed de desarrollo / automatización; **no** se pueden crear desde el portal tenant) siguen siendo válidas.

`POST /api/v1/platform/organizations/{id}/impersonate` emite una sesión portal corta (TTL ≤ 1h) del org objetivo y escribe auditoría `platform.impersonate` (org objetivo + `actor_user_id` en metadata). Si el audit no se escribe, impersonate falla. `X-Organization-Id` en una sesión platform responde 403: no eleva a tenant.

UI: `/admin/login`, `/admin`, `/admin/customers`, `/admin/plans`. Token en `rag_platform_token`, separado de `rag_portal_token`.

Primer platform admin en prod: proceso manual (`users.is_platform_admin`, email, password bcrypt). `PLATFORM_ADMIN_EMAIL` documenta el correo; la contraseña no va en env.



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
