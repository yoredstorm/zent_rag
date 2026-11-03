# P19.1-00 — Mapa de regresión y cobertura por gate

- **SHA base:** `9791a662404b00f8b80c293a2f94c6e897e38554`
- **Objetivo:** que cada gate P19.1 tenga una prueba identificable y un comando
  reproducible. La ausencia de prueba se declara como brecha, no como PASS.

## 1. Gate de arquitectura

| Test | Qué protege | Comando |
|---|---|---|
| `tests/test_architecture.py::test_core_imports_only_core` | `core/` sin frameworks/adapters | incluido en invariantes |
| `test_infrastructure_imports_no_upper_layers` | infraestructura no depende de capas superiores | idem |
| `test_rag_and_agents_do_not_import_adapters` | DI, no adapters directos | idem |
| `test_no_vertical_business_terms_in_generic_layers` | sin vocabulario vertical en `core/rag/agents/platform` | idem; **fallo corregido** |
| `tests/test_suite_hermeticity.py` | suite sin providers reales por defecto | idem |
| `tests/test_openapi_contract.py` | contrato OpenAPI | idem |

Comando único:

```powershell
uv run --frozen --no-sync python scripts/cert/run_invariants.py
```

## 2. Fallo CI y corrección

| Elemento | Valor |
|---|---|
| Run remoto reportado | `41354084398` (master) |
| Job/paso | `test (1/4)` / `Architecture invariants (fast, required)` |
| Test | `tests/test_architecture.py::test_no_vertical_business_terms_in_generic_layers` |
| Commit introductor | `ea294610d4c580e1effcf04af359698fac4e663a` |
| Corrección | `bf8c7b308990701276dec0b90b220321e8ef35f3` (rama `fix/p19-1-data-workflow-hardening`) |
| PR | `https://github.com/yoredstorm/zent_rag/pull/17` |

## 3. Mapa por prompt/gate

| Gate | Riesgo | Pruebas existentes | Brecha / prueba a añadir | Prompt |
|---|---|---|---|---|
| G00 | CI/arquitectura | invariantes, typecheck, Vitest, backend | CI remoto en SHA corregido | 00 |
| G01 | publicación y PII | `test_workflow_data_p19_audit.py`, `test_workflow_data_p19_catalog.py` | `workflows:update` sin `data_queries:publish`; columna PII; allowlist; auditoría; concurrencia | 01 |
| G02 | identidad/ownership | `test_authority_ownership.py`, `test_authorization_matrix.py`, `test_workflow_data_p19_query.py` | A≠B, org≠org, ws≠ws, revocación en WAIT, count/preview/get_one | 02 |
| G03 | binding drift | `test_workflow_data_p19_query.py`, `test_workflow_published_snapshot.py` | mutar plan con mismo `binding_id`; `db_query_count==0`; rollback | 03 |
| G04 | estados/errores | `test_workflow_data_p19_node.py`, `test_failure_taxonomy.py`, `test_reason_codes.py` | timeout/denied no terminal SUCCEEDED; envelope v2; typed ports | 04 |
| G05 | UX | Vitest de `DataQueryForm`, `PublishQueryModal`, `IntentRouteForm`; `test_workflow_studio.py` | sin reload; canvas intacto; tipos; a11y; E2E real | 05 |
| G06 | conversación | `test_workflow_data_p19_intent.py`, `test_workflow_durable_instances.py`, `test_workflow_durable_ingress.py` | gold set ≥80; 4+ turnos; slots; precio entre turnos | 06 |
| G07 | inventario | `test_workflow_effect_verification.py`, tests de bodega/external | 100 concurrentes; doble commit; multi-ítem; job expiración; crash | 07 |
| G08 | conectores | `test_workflow_data_p19_external.py`, `test_ssrf_e2e.py` (script) | CA inválida, hostname, DNS, pool, 100 concurrentes, rotación | 08 |
| G09 | certificación | suites anteriores + Playwright | matriz PASS/FAIL/NOT_RUN, usuarios reales, SLO, rollback | 09 |

## 4. Suites P19 existentes

```powershell
uv run --frozen --no-sync pytest `
  tests/test_workflow_data_p19_audit.py `
  tests/test_workflow_data_p19_catalog.py `
  tests/test_workflow_data_p19_external.py `
  tests/test_workflow_data_p19_intent.py `
  tests/test_workflow_data_p19_node.py `
  tests/test_workflow_data_p19_query_integration.py `
  tests/test_workflow_data_p19_query.py `
  tests/test_workflow_node_catalog.py `
  tests/test_workflow_parameters.py `
  tests/test_workflow_business_schema.py -q
```

Con `P19_EXTERNAL_*` configurado, los 2 tests externos dejan de omitirse.

## 5. Pruebas P18.4/P18.5 que no deben romperse

| Área | Test/archivo |
|---|---|
| draft y canvas | `portal/src/pages/WorkflowNew.test.tsx`, `portal/e2e/studio.spec.ts`, tests de `workflowGraph` |
| Test Studio | `tests/test_workflow_test_studio.py`, `portal/src/components/workflowStudio/WorkflowTestPanel.test.tsx` |
| autorización irreversible | `tests/test_action_plane_authority.py`, `tests/test_workflow_approval_context.py` |
| snapshots de agente | `tests/test_workflow_agent_context.py`, `tests/test_workflow_published_snapshot.py` |
| trazas/UI | `tests/test_observability.py`, `portal/src/components/WorkflowRunInspector.test.tsx` |
| deploy versionado | `tests/test_workflow_publication_gate.py`, `tests/test_workflow_published_snapshot.py` |

Si un archivo no existe en el SHA, se marca brecha y se crea en el prompt
correspondiente; no se inventa cobertura.

## 6. Pruebas negativas transversales (a implementar por prompt)

| Ataque | Prompt | Resultado esperado |
|---|---|---|
| `workflows:update` intenta publicar email/precio | 01 | 403, sin binding creado |
| Columna no permitida / `SELECT *` | 01 | 400/403, cero SQL |
| Tabla de otro workspace/tenant | 01/02 | 403/404 indistinguible, cero SQL |
| PII en `count`, preview, export, trace | 01/02 | denegado o redactado; nunca valor |
| `resource_ref`, columnas u `order_by` en payload | 01/02 | `UNEXPECTED_PARAMETER` |
| Cliente A lee pedido/saldo de B | 02 | 0 filas / denegación; sin side channel |
| `customer_id`/`subject_id` desde LLM o trigger | 02 | ignorado; identidad server-side |
| Binding mutado tras publicar | 03 | `PLAN_STALE`; `db_query_count==0` |
| Edición durante WAIT | 03 | revalidación; denegación o nueva versión |
| Timeout/permiso denegado | 04 | nodo failed; workflow no COMPLETED sin recovery |
| Dos aprobaciones simultáneas | 07 | un solo commit; ledger único |
| 100 reservas con stock limitado | 07 | sin negativo ni sobreventa |
| Host loopback/metadata; TLS falso | 08 | `POLICY_DENIED`/TLS error; sin conexión |
| Credencial rotada/revocada | 08 | bloqueo dentro del SLA; sin fuga |
| Replay/reorder de señales | 02/06 | idempotente; instancia/cliente correctos |

## 7. Criterio de actualización

Cada prompt debe añadir su fila a este mapa con:

- archivo de test nuevo o modificado;
- comando exacto;
- resultado `PASS/FAIL/NOT_RUN`;
- ruta de log/JUnit;
- SHA.

Si un test se vuelve flaky, se investiga; no se elimina ni se marca `xfail`
para cerrar el gate.
