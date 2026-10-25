# P13 — 03 P01: snapshot publicado inmutable

SHA base: `b31b01402a2e10008eb09b77c148e48120af6004`.
Cambios en worktree, sin commit. Migración: `170_workflow_published_pointer.py`.

## 1. Arquitectura

`workflows` sigue siendo el borrador editable. La ejecución productiva resuelve
una única fila `workflow_versions` mediante `workflows.published_version_id`.
No se creó un segundo engine ni un segundo catálogo.

Precedencia explícita (`definition.py`):

| Contexto | Fuente | Uso |
|---|---|---|
| `published` | `workflow_versions.config_snapshot` del puntero | hook, schedule, event, provider, run de workflow activo |
| `draft` | fila `workflows` | pruebas manuales autorizadas; no triggers productivos |
| `instance` | `workflow_instances.definition_snapshot` | WAIT/RESUME y segmentos de instancia |

`run_workflow` recibe `definition_source`; no infiere el modo por ausencia de
`graph_override`. Toda ejecución nueva registra `published_version_id`,
`certificate_id`, `graph_hash`, `policy_version`, `deployment_generation` y
`definition_source`.

## 2. Migración 170 (aditiva)

- `workflows`: `published_version_id`, `published_certificate_id`,
  `published_graph_hash`, `published_at`, `published_by`,
  `deployment_generation`, `draft_revision`.
- `workflow_versions`: `workspace_id`, `graph_hash`, `trigger_hash`,
  `policy_version`, `published_at`, `published_by`, `legacy_baseline`.
- `workflow_certificates`: `binding_fingerprint`, `trigger_hash`.
- `workflow_runs`: columnas de procedencia y policy.
- `workflow_instances`: puntero, certificado, hash y generación.
- `workflow_deployments`: auditoría de publish/activate/promote/restore/
  legacy_baseline/revoke_legacy.
- Índice único parcial `uq_wf_versions_production` (una producción por workflow).
- Backfill: workflows activos sin puntero reciben un snapshot del grafo vivo,
  `legacy_baseline=true`, sin certificado, y `deployment_generation=1`.
  No se certifica nada automáticamente.

## 3. Contrato API

### GET /api/v1/workflows/{id}

Agrega:

```json
{
  "published_version_id": "uuid|null",
  "published_version_number": 3,
  "published_certificate_id": "uuid|null",
  "published_graph_hash": "sha256",
  "published_at": "iso8601",
  "deployment_generation": 4,
  "draft_revision": 7,
  "draft_changed": true
}
```

### PATCH /api/v1/workflows/{id}

Acepta `If-Match: "rev-N"` o `expected_revision`. Conflicto:

```json
{
  "code": "workflow_revision_conflict",
  "message": "revisión del borrador desactualizada",
  "expected_revision": 3,
  "current_revision": 5
}
```

### POST /publish

Respuesta:

```json
{
  "status": "active",
  "published_version_id": "uuid",
  "deployment_generation": 5,
  "version": {"version_number": 4, "status": "production"},
  "release": {"allowed": true}
}
```

### POST /activate

Requiere puntero. Si falta, 409 `published_version_required`. Por
compatibilidad, la primera activación de un workflow con certificado válido
crea el snapshot mediante `publish_workflow`; nunca activa el grafo vivo.

### Errores de definición

`published_version_required`, `published_snapshot_hash_mismatch`,
`certificate_required`, `certificate_expired`, `certificate_revoked`,
`certificate_stale`, `trigger_stale`, `bindings_stale`.

## 4. Acción, fuente y certificado

| Acción | Fuente del grafo | Versión | Certificado |
|---|---|---|---|
| Hook público | `published_version_id` | production | `certificate_id` de la versión |
| Schedule | `published_version_id` | production | idem |
| Event trigger | `published_version_id` | production | idem |
| Run manual de activo | `published_version_id` | production | idem |
| Run manual de draft | fila `workflows` | borrador | no aplica |
| Instancia WAIT/RESUME | `definition_snapshot` | congelada al crear | congelado, sin recertificar |
| Publish | fila viva certificada | nueva production | certificado vigente |
| Promote | snapshot destino | production | certificado del snapshot |
| Restore | snapshot destino | production | certificado del snapshot |

## 5. Secuencia publish

```text
Client          API                 versions.py             Postgres
  | POST publish |                    |                       |
  |------------->| lock workflow      |                       |
  |              |------------------->| SELECT ... FOR UPDATE |
  |              |                    | snapshot + hashes     |
  |              |                    | evaluate_release      |
  |              |                    | INSERT version ready  |
  |              |                    | demote production     |
  |              |                    | UPDATE version prod   |
  |              |                    | UPDATE pointer+gen+1  |
  |              |                    | INSERT deployment     |
  |              |                    | COMMIT                |
  |<-------------| 200 + version      |                       |
```

## 6. Pruebas

Comando:

```powershell
uv run --frozen --no-sync pytest tests/test_workflow_published_snapshot.py -q
```

Resultado: **9 passed**.

Cubre:

- `test_edit_active_workflow_keeps_published_execution`.
- `test_schedule_uses_published_snapshot`.
- `test_patch_rejects_stale_revision`.
- `test_concurrent_patches_are_monotonic` (50 PATCH).
- `test_concurrent_publishes_keep_single_production` (10 publishes).
- `test_restore_active_version_is_atomic_and_certified`.
- `test_trigger_change_invalidates_certificate_for_publish`.
- `test_binding_change_invalidates_certificate_for_publish`.
- `test_legacy_metadata_cannot_self_assign`.

Regresión adicional: `test_workflow_publication_gate.py` **10 passed**;
`test_workflow_studio.py` **12 passed**; `test_workflows.py` **10 passed**;
`test_workflow_durable_instances.py` + `test_workflow_durable_ingress.py`
**34 passed**.

Evidencia: `artifacts/certification/p13/junit-p13-core.xml`.

## 7. Riesgos y límites

- El baseline legacy conserva el comportamiento actual, pero no es evidencia
  de certificación. Su revocación es un script de plataforma.
- Cambiar `trigger_config` o bindings invalida el certificado; requiere
  recertificación.
- Playwright `portal/e2e/workflow-publication.spec.ts` **NOT_VERIFIED** hasta
  levantar API+portal en staging.
- No se activó producción ni `ZENT_GOLD_RELEASE_ENABLED`.

## 8. Rollback

Ver `06-rollback-runbook.md`.
