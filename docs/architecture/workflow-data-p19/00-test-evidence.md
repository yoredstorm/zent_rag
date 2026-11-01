# P19-00 — Evidencia de pruebas y baseline reproducible

- **Fecha:** 2026-11-01
- **Rama:** `feat/p19-workflow-data-orchestration`
- **Base:** `47fa8a09fa9f99ab7d77aa9ae555aa3528169253` (master)
- **Ambiente:** Windows 11, Python 3.11.16 (`.venv`), Node 22.22.1,
  pnpm 9.4.0, Docker 29.8.2, PostgreSQL 16.15 local.
- **Datos:** PostgreSQL local de desarrollo. No se usaron datos de clientes ni
  proveedores reales.
- **Naturaleza:** P19-00 no implementa controles; los tests rojos documentan el
  baseline. No se declara PASS de seguridad.

## 1. Resumen

| Suite | Comando | Resultado | Clasificación |
|---|---|---|---|
| Auditoría P19 | `pytest tests/test_workflow_data_p19_audit.py -q` | 2 passed, 8 xfailed | DB local + doble SQL |
| Evidencia de fallo real | `... --runxfail` (test de override) | 1 failed como se esperaba | DB local no usada; doble SQL |
| Portal AS-IS | `pnpm --dir portal exec vitest run src/lib/workflowGraph.p19.test.ts` | 3 passed | unitario |
| Data catalog + readiness | `pytest tests/test_workflow_data_catalog.py tests/test_workflow_readiness.py -q` | 10 passed | DB local |
| Effective policy | `pytest tests/test_workflow_effective_policy.py -q` | 7 passed | DB local |
| Workspace isolation | `pytest tests/test_workflow_workspace_isolation.py -q` | 3 passed | API + DB local |
| Published snapshot | `pytest tests/test_workflow_published_snapshot.py -q` | NOT_RUN / cuelgue en el primer test | DB local |
| Suite backend completa | — | NOT_RUN | — |
| E2E Playwright P19 | — | NOT_RUN | no existe flujo P19 |
| Proveedor externo | — | NOT_RUN | no hay driver/DB externa |

## 2. Tests rojos de auditoría

Archivo: `tests/test_workflow_data_p19_audit.py`.

### Ejecución normal

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workflow_data_p19_audit.py -q -p no:cacheprovider
```

Salida:

```
xxxxxxx.x.                                                               [100%]
2 passed, 8 xfailed, 2 warnings in 23.06s
```

Los 8 `xfail(strict=True)` son hallazgos, no pruebas omitidas. Si P19-01 los
corrige sin actualizar la expectativa, el XPASS hará fallar la suite.

| Test | Hallazgo | Estado esperado P19-01 |
|---|---|---|
| `test_p19_00_red_payload_cannot_override_binding_resource` | payload cambia tabla | PASS |
| `test_p19_00_red_payload_cannot_request_star_columns` | `SELECT *` | PASS |
| `test_p19_00_red_payload_cannot_replace_required_predicates` | predicado obligatorio eliminado | PASS |
| `test_p19_00_red_unknown_operator_is_rejected` | operador desconocido → `=` | PASS |
| `test_p19_00_red_payload_cannot_raise_binding_row_limit` | límite del binding ignorado | PASS |
| `test_p19_00_red_payload_cannot_choose_order_by` | orden desde payload | PASS |
| `test_p19_00_red_org_binding_is_not_inherited_without_explicit_grant` | herencia org-level | PASS |
| `test_p19_00_red_connected_db_is_not_routed_to_managed_session` | `connected_db` a Managed DB | PASS en P19-06 |

### Evidencia del override real

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/test_workflow_data_p19_audit.py::test_p19_00_red_payload_cannot_override_binding_resource `
  -q --runxfail -p no:cacheprovider
```

Salida relevante:

```
E  AssertionError: el payload desvió el recurso:
   SELECT customer_id, balance FROM loyalty_balances LIMIT 50
E  assert 'FROM product_prices' in 'SELECT customer_id, balance FROM loyalty_balances LIMIT 50'
1 failed
```

No se ejecutó la consulta contra una base real: la sesión es un doble que registra
el statement y devuelve cero filas. El texto demuestra la construcción SQL, no
una lectura de datos.

### Tests AS-IS verdes

| Test | Qué documenta |
|---|---|
| `test_p19_00_asis_cross_org_binding_is_not_visible` | el lookup no cruza organizaciones (control positivo) |
| `test_p19_00_asis_query_business_data_output_contract` | salida actual con `rows`, `columns`, `sql_query`, `answerability`; sin `structured_output` ni `provenance` |

## 3. Test AS-IS del portal

Archivo: `portal/src/lib/workflowGraph.p19.test.ts`.

```powershell
pnpm --dir portal exec vitest run src/lib/workflowGraph.p19.test.ts
```

Salida:

```
Test Files  1 passed (1)
     Tests  3 passed (3)
  Duration  1.70s
```

Demuestra que:

- no existe `data_query` ni `consultar_registros` en `NODE_LIBRARY`;
- `query_business_data` solo tiene el campo `ask` (textarea);
- no hay selectores de conexión, recurso, columnas ni preview.

No es una prueba de aceptación de UX; es una fotografía del AS-IS. P19-03 debe
actualizarla cuando exista el nodo nuevo.

## 4. Suites de regresión ejecutadas

### Data catalog + readiness

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/test_workflow_data_catalog.py tests/test_workflow_readiness.py `
  -q -p no:cacheprovider --timeout=60
```

```
10 passed, 2 warnings in 102.66s
```

### Effective policy

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workflow_effective_policy.py `
  -q -p no:cacheprovider --timeout=60
```

```
7 passed, 2 warnings in 72.03s
```

### Workspace isolation

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workflow_workspace_isolation.py `
  -q -p no:cacheprovider --timeout=90
```

```
3 passed, 2 warnings in 79.57s
```

### Published snapshot — NOT_RUN

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workflow_published_snapshot.py `
  -v -p no:cacheprovider --timeout=30
```

Resultado: el primer test (`test_edit_active_workflow_keeps_published_execution`)
no termina; pytest-timeout dispara a los 30 s y el proceso sale con código 1. Se
reintentó con 90 s y el comportamiento fue el mismo. **No se declara PASS.** No se
investigó en P19-00 porque no es un cambio de esta fase; queda como riesgo de
baseline para P19-13.

### Suite completa

La suite backend completa no se ejecutó en esta sesión. El CI del baseline sí
ejecutó los 4 shards y certificación (run 498). No se extrapola ese resultado a
esta rama.

## 5. Baseline de CI

| Run | Commit | Resultado | Jobs |
|---|---|---|---|
| CI `498` (`41275455559`) | `47fa8a09` | success | 16/16 |
| Nightly `20` (`41279316169`) | `47fa8a09` | success | — |

Jobs del run 498: `secrets-scan`, `kustomize`, `test (1/4)`, `test (2/4)`,
`test (3/4)`, `test (4/4)`, `test`, `certification`, `portal`, `portal-e2e`,
`lint`, `pip-audit`, `build`, `sdk-node`, `sdk-python`, `test-evidence`.

Límite: el CI verde no prueba conectores externos, RLS, datos reales ni
usabilidad. Es baseline de regresión, no certificación.

## 6. Reproducibilidad mínima

```powershell
# 1. Dependencias
.\.venv\Scripts\python.exe -m pytest --version
pnpm --dir portal exec vitest --version

# 2. Servicios
docker ps --format "{{.Names}} {{.Status}}"

# 3. Tests P19-00
.\.venv\Scripts\python.exe -m pytest tests/test_workflow_data_p19_audit.py -q
pnpm --dir portal exec vitest run src/lib/workflowGraph.p19.test.ts

# 4. Evidencia de fallo (opcional, debe fallar)
.\.venv\Scripts\python.exe -m pytest `
  tests/test_workflow_data_p19_audit.py::test_p19_00_red_payload_cannot_override_binding_resource `
  -q --runxfail
```

## 7. Declaración honesta

- **PASS:** reproducciones adversariales controladas, inventario, ADR propuesta,
  baseline CI, suites de regresión indicadas.
- **FAIL:** el comportamiento AS-IS de las 8 reproducciones (por diseño de la
  auditoría).
- **NOT_RUN:** suite backend completa, published snapshot (cuelgue), E2E P19,
  accesibilidad, carga, proveedor externo, usuario real.
- **Mock:** doble de sesión SQL en los tests de binder; orquestador falso en el
  test AS-IS de `query_business_data`.
- **DB local:** tests de binding, data catalog, readiness, policy y workspace.
- **Sandbox/proveedor real:** no usados.

No se usa un LLM para generar precios ni se declara “dato real” a un fixture.
