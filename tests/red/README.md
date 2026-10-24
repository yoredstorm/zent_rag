# Tests rojos P00

Estos tests describen el comportamiento exigido, no el comportamiento actual.
Cada archivo usa `pytest.mark.xfail(strict=True)` para que la suite normal no
confunda una brecha abierta con un pase:

```powershell
uv run --frozen --no-sync pytest tests/red -q            # xfailed: brecha abierta
uv run --frozen --no-sync pytest tests/red -q --runxfail # falla: prueba real
```

Cuando la brecha se corrige, el test pasa y `strict=True` produce `XPASS`, lo
que rompe la suite y obliga a retirar el `xfail` y convertir el test en verde
permanente. Nunca cambiar el test para que pase sin corregir la causa.

Todos los rojos backend P0 están cerrados y viven como pruebas normales:

- P0-01/P0-02 → `tests/test_workflow_publication_gate.py` (P01).
- P0-04 → `tests/test_workflow_durable_ingress.py` (P02).
- P0-05 → `tests/test_workflow_workspace_isolation.py` (P05).
- P0-06/P0-08 → `tests/test_policy_enforcement.py` (P05).

El rojo de portal de P0-07 se retiró en P08 y su cobertura vive en
`portal/src/components/workflowStudio/WorkflowTestPanel.test.tsx` (13 passed).
El JUnit histórico de los rojos sigue en `artifacts/certification/p00/`.
