# Self Purge — borrado total de mi rastro

Herramienta de **zona de riesgo** en Ajustes → Workspace: un usuario autorizado
borra **toda la data de su organización** y empieza de cero, sin perder su
cuenta.

---

## 1. Qué borra

Todo lo que tenga `organization_id` en Postgres, descubierto dinámicamente
desde `information_schema` (no hay lista que envejezca), más los almacenes
externos:

| Origen | Qué se elimina |
|---|---|
| Postgres | documentos, KBs, fuentes, conectores y secretos, jobs de ingesta, agentes, workflows, conversaciones, agent runs, Company Graph (entidades, relaciones, authority), descubrimiento (candidatos, runs), memoria, findings y experimentos, Claim Ledger, catálogo, usage, api logs, API keys, invitations, compliance events, audit logs |
| Qdrant | vectores de la organización (`delete_by_organization`) |
| Disco | `UPLOAD_DIR/{org}` y artefactos DSR `data/dsr/{org}` |
| Sesión | la sesión que ejecutó el reset se revoca (sid en Redis) |

Los deletes se ejecutan en **orden topológico de FKs** (hijos antes que
padres), calculado desde `pg_constraint`, con pasadas de reintento para ciclos.
Cada tabla corre en su propia transacción: una tabla que falle se reporta en
`failures[]`, nunca se silencia.

## 2. Qué conserva

`organizations`, `users`, `memberships`, `roles`, `permissions`,
`role_permissions`, `workspaces` y todo lo que empiece con `subscription`,
`billing` o `plan`. La persona sigue entrando con su login y su suscripción
intacta.

## 3. Auditoría

Se borran los `audit_logs` de la organización y se escribe **un único
registro**: `self_purge.executed` con fecha, filas antes/después y número de
fallos. Es la única huella que queda del reset, por decisión de producto.

## 4. Autorización

| Guarda | Detalle |
|---|---|
| Allowlist | `RAG_SELF_PURGE_EMAILS` (CSV, case-insensitive). Vacío = funcionalidad apagada y botón invisible |
| Permiso | `org:read` + rol `owner`/`admin` |
| Confirmación | escribir el email exacto de la cuenta |
| Step-up | `require_tenant_step_up`: MFA reciente o contraseña reciente (`step_up_required` lo maneja el `TenantStepUpModal` del portal) |
| Impersonación | prohibido ejecutar bajo `impersonated_by` |
| Concurrencia | advisory lock por organización (`409 purge_in_progress`) |

## 5. Superficie

| Método | Ruta | Uso |
|---|---|---|
| GET | `/api/v1/self-purge/status` | ¿Este usuario puede? (el panel se oculta si no) |
| GET | `/api/v1/self-purge/preview` | Conteos antes de ejecutar |
| POST | `/api/v1/self-purge/execute` | Ejecuta el borrado |

Idempotente: una segunda corrida reporta `before` en cero y sin fallos.

## 6. Configuración

```bash
# docker-compose (servicio api) o .env
RAG_SELF_PURGE_EMAILS=ppimentel@omnio.pe
```

```bash
docker compose up -d api
```

## 7. Artefactos

| Capa | Archivo |
|---|---|
| Servicio | `src/platform/self_purge/service.py` |
| API | `src/api/routes/self_purge.py` |
| UI | `portal/src/pages/Settings.tsx` (`SelfPurgePanel`) |
| Tests | `tests/test_self_purge.py`, `portal/src/pages/Settings.test.tsx` |
