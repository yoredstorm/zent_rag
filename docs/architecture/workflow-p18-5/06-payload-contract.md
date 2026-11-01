# P18.5-06 — Contratos de payload entre /test y /run

## Identidad

- Commit: `7730264`
- Archivos: `src/platform/workflows/test_studio.py`,
  `WorkflowTestTechnical.tsx`, `WorkflowTestComposer.tsx`.

## Contrato actual

| Nivel | Entrada | Ejecuta nodos | Certifica proveedor |
|---|---|---|---|
| preview | `scenario.messages` (texto) | No | No |
| simulation | `scenario.messages` (texto) | Simulación | No |
| sandbox / provider | `scenario.messages` + readiness | Verificación controlada | Solo si backend devuelve `provider_verified=true` |
| `/run` real | `payload` JSON estructurado | Sí | No aplica |

Un objeto JSON escrito en el composer se envía como **texto del escenario** al
test y como **objeto estructurado** al run real. La UI ya lo advertía; ahora el
backend devuelve `input_snapshot` para que el reporte conserve exactamente lo
que consumió.

## Cambios

- `execute_workflow_test` valida `scenario.messages` como lista de strings
  (máximo 50) y devuelve 400 si el contrato no se cumple.
- Todos los reportes (BLOCKED, PREVIEW, simulación, verificación) incluyen
  `input_snapshot`:
  - `kind: scenario.messages`
  - `contract: test_text_vs_run_payload`
  - `scenario` redaccionado
  - `messages_preview`, `message_count`
  - nota explícita de que el run real usa el payload estructurado.
- La UI muestra el snapshot en “Detalles técnicos del reporte”; no vuelca
  secretos.
- No se cambió el schema de `/test` ni el de `/run`.

## Pruebas

```text
uv run pytest tests/test_p18_5_payload_contract.py -q
2 passed
```

- Reporte conserva el texto exacto enviado, incluido JSON como string.
- `messages` con objetos → 400 con mensaje de validación.
- La suite P18.4 de Test Studio sigue verde (20 passed en el baseline; el panel
  completo se ejecutó después en 112 tests de UI).

## Riesgos residuales

- P2: no se compilan variables obligatorias del trigger contra el escenario; el
  compilador existente valida el grafo, no un payload de negocio arbitrario.
- P2: un JSON inválido se trata como texto y la UI lo indica; no se inventa un
  parseo alternativo.

## Decisión

**PASS** para el contrato y la trazabilidad del input. La equivalencia semántica
completa test↔run sigue siendo una limitación documentada.

## Próxima fase autorizada

P18.5-07.
