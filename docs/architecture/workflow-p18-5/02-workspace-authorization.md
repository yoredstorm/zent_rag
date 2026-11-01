# P18.5-02 — Aislamiento real de workspaces en runs, resultados y aprobaciones

## Identidad

- Commit: `e23b2ed`
- Baseline: `e6c42c2579df0e997ef2a0a0d0916f05dc735bef`

## Hallazgo reproducido

`GET /api/v1/workflows/runs/{run_id}` filtraba solo por `organization_id`.
Un usuario del workspace A podía leer el detalle completo de un run del
workspace B conociendo el UUID (incluido `trigger_payload`, pasos y outputs).

## Matriz de rutas

| Ruta | Validación añadida | Resultado ajeno |
|---|---|---|
| `GET /runs/{run_id}` | `assert_run_access` + filtro SQL final | 404 |
| `GET /runs/{run_id}/approvals` | `assert_run_access` | 404 |
| `POST /runs/{run_id}/approvals/{id}/decide` | run + approval scope | 404 |
| `GET /{workflow_id}/runs` | middleware + `list_runs(workspace_id)` | 404 |
| `GET /{workflow_id}/sample-outputs` | `assert_workflow_access` + filtro SQL | 404 |
| `GET /{workflow_id}/data-catalog` | workspace en query y validación | 404 |
| `GET /instances/{id}` y `/timeline` | `require_workspace_scope=True` | 404 |
| `POST /instances/{id}/signal|cancel|suspend|resume` | `require_workspace_scope=True` | 404 |

## Frontera de autoridad

```
run_id ──► workflow_runs ──► workflows
              │                 │
              └─ workspace_id ──┴─ workspace_id (COALESCE)
                       │
              request X-Workspace-Id / workspace activo
                       │
              assert_run_access → 400 (sin workspace) / 404 (ajeno)
```

La autorización de acción (`workflow_runs:read`, `workflows:run`,
`workflow_approvals:approve`) se exige antes del guard de recurso.

## Decisión de producto documentada

ZENT no tiene tabla de membresía por workspace: la política vigente es que un
miembro de la organización puede operar los workspaces de su organización. Por
eso `_workspace_id` valida pertenencia a la organización y el guard valida
pertenencia del recurso al workspace; no se inventa un segundo modelo de
membresía. Recursos con `workspace_id NULL` son globales de la organización
(legacy explícito).

## Pruebas

```text
uv run pytest tests/test_p18_5_workspace_authorization.py -q
2 passed, 1 skipped
```

- A puede leer su run; B recibe 404 y el cuerpo no contiene el UUID.
- Sin header se usa el workspace activo de la membresía (no eleva).
- El helper directo con `workspace_id=None` devuelve 400 `workspace_required`.
- Header de workspace de otra organización → 404.
- `sample-outputs` de B → 404.
- El caso org-global se omitió porque el owner de prueba siempre tiene workspace
  activo; la lógica está cubierta por el helper y por recursos existentes sin
  workspace en la suite de durables.

## Compatibilidad

- Sin migración.
- Respuestas de recursos legítimos conservan campos y formato.
- 404 en lugar de 403 para recursos ajenos evita enumeración.

## Riesgos residuales

- P2: no hay permisos por workspace individuales; si el producto los exige, se
  necesita un modelo aditivo de membresía por workspace.
- P2: recursos legacy sin workspace son visibles para toda la organización por
  diseño.

## Decisión

**PASS** para P18.5-02.

## Próxima fase autorizada

P18.5-03.
