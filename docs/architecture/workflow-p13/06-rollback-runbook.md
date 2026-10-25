# P13 — 06 Runbook de cutover y rollback

## 1. Preflight

```powershell
git rev-parse HEAD
uv run --frozen --no-sync alembic current
uv run --frozen --no-sync python scripts/workflow_p13_audit.py
```

El audit debe devolver `active_missing_pointer=0`, `duplicate_production=0`,
`published_hash_mismatch=0`. `legacy_baselines` es informativo.

## 2. Cutover P01

1. Backup de PostgreSQL y de `workflow_versions`.
2. `alembic upgrade head` (170, 171, 172).
3. Ejecutar `scripts/workflow_p13_audit.py`; debe salir 0.
4. Canary de una réplica API. Verificar:
   - hook y schedule ejecutan `definition_source=published`;
   - WAIT/RESUME conserva el snapshot de la instancia;
   - `ZENT_GOLD_RELEASE_ENABLED=false`.
5. Extender a todas las réplicas.

## 3. Rollback de código

Antes de desplegar el SHA anterior:

```powershell
# Dry-run: muestra qué workflows se alinearían
uv run --frozen --no-sync python scripts/workflow_p13_rollback.py

# Aplicar: copia el snapshot publicado a la fila viva
uv run --frozen --no-sync python scripts/workflow_p13_rollback.py --apply --confirm-restore
```

El script preserva `hook_secret_hash` y escribe
`workflow_deployments(action='rollback_live_restore')`. Después se despliega el
SHA anterior. No ejecutar `alembic downgrade` hasta verificar que ningún
workflow activo depende solo del puntero.

## 4. Rollback de migraciones

Solo en base de prueba o con backup verificado:

```powershell
uv run --frozen --no-sync alembic downgrade 169
```

Antes, exportar `workflow_outbox`, `workflow_ingress_events` y
`workflow_policy_revocations` a `artifacts/certification/p13/`. Las tablas
aditivas se eliminan; los snapshots históricos permanecen.

## 5. Revocación legacy

Solo operador de plataforma, nunca tenant:

```powershell
uv run --frozen --no-sync python scripts/workflow_p13_revoke_legacy.py <workflow_id> `
  --reason "revisión de seguridad" --confirm-revoke
```

Marca `release_policy='standard'`, quita `legacy_baseline` y audita
`revoke_legacy`. Los nuevos runs quedan bloqueados hasta certificar.

## 6. Recuperación operativa

- **Inbox**: revisar `status='failed'`, `dead_letter_at`, `last_error`.
  Reencolar es `UPDATE status='pending', next_attempt_at=NOW()` solo tras
  revisar el error; no borrar filas.
- **Outbox**: `outbox.backlog()`; si el bus estuvo caído, `dispatch_pending()`
  reintenta. No marcar `delivered_at` manualmente sin evidencia.
- **Instancias**: WAIT/RESUME usa `definition_snapshot`; no editar el snapshot
  de una instancia viva.
- **Certificados**: si `certificate_expired`/`*_stale`, recertificar el snapshot
  exacto y volver a publicar; no forzar el puntero.

## 7. Señales de abortar el cutover

- `active_missing_pointer > 0`.
- `published_hash_mismatch > 0`.
- Hook/schedule ejecutan un hash distinto al publicado.
- Errores `published_snapshot_hash_mismatch` repetidos.
- Aumento de `policy.denied` por `policy.invalid_policy` o `workspace_mismatch`.
