# P19 — Workflow Data Orchestration

Programa incremental para consultas estructuradas, rutas por intención y procesos
conversacionales sobre datos reales.

## Estado

| Fase | Estado | Documento |
|---|---|---|
| P19-00 Auditoría y baseline | COMPLETADO | [00-audit-baseline.md](./00-audit-baseline.md) |
| P19-01 Motor declarativo seguro | BLOQUEADO hasta aprobar ADR | [00-adr-query-node.md](./00-adr-query-node.md) |
| P19-02 a P19-14 | No iniciadas | — |

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
pnpm --dir portal exec vitest run src/lib/workflowGraph.p19.test.ts
```

Los 8 casos `xfail(strict=True)` son hallazgos P19-00; deben convertirse en PASS
en P19-01 sin debilitar los asserts. No se declara PASS de seguridad ni GO de
producción.
