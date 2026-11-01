# P19 — Workflow Data Orchestration

Programa incremental para consultas estructuradas, rutas por intención y procesos
conversacionales sobre datos reales.

## Estado

| Fase | Estado | Documento |
|---|---|---|
| P19-00 Auditoría y baseline | COMPLETADO | [00-audit-baseline.md](./00-audit-baseline.md) |
| P19-01 Motor declarativo seguro | COMPLETADO (backend) | [01-declarative-query-engine.md](./01-declarative-query-engine.md) |
| P19-02 Catálogo de recursos | COMPLETADO (backend) | [02-data-catalog.md](./02-data-catalog.md) |
| P19-03 Nodo visual | COMPLETADO (backend + editor Simple) | [03-visual-data-query-node.md](./03-visual-data-query-node.md) |
| P19-04 Intención de negocio | PENDIENTE | — |
| P19-05 a P19-14 | No iniciadas | — |

## Artefactos P19-00

- [00-audit-baseline.md](./00-audit-baseline.md): identidad del baseline,
  inventario comprobado, hallazgos P0/P1/P2 y gate.
- [00-adr-query-node.md](./00-adr-query-node.md): decisión `data_query` vs
  `capability_call`, agregados como AST, herencia org-level, identidad, errores,
  pinning y rollback.
- [00-threat-model.md](./00-threat-model.md): amenazas de PII, multiworkspace,
  prompt injection, conectores externos y observabilidad.
- [00-matrix-asis-tobe.md](./00-matrix-asis-tobe.md): matriz antes/después de
  rutas, nodos, API, permisos, contratos, flags y rollback.
- [00-test-evidence.md](./00-test-evidence.md): comandos, resultados, PASS/FAIL/
  NOT_RUN y límites de la evidencia.

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workflow_data_p19_audit.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_workflow_data_p19_query.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_workflow_data_p19_query_integration.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_workflow_data_p19_catalog.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_workflow_data_p19_node.py -q
pnpm --dir portal exec vitest run src/lib/workflowGraph.p19.test.ts
pnpm --dir portal exec vitest run src/components/workflowStudio/DataQueryForm.test.tsx
```

P19-01 convirtió los 8 `xfail` de P19-00 en PASS con rechazo explícito
(`UNEXPECTED_PARAMETER`/`INVALID_PARAMS`), no relajando los asserts. No se
declara PASS de seguridad global ni GO de producción.
