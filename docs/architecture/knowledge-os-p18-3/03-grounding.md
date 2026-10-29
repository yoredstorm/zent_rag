# P18.3-03 — Grounding, contradicciones, citas y abstenciones

Estado: **corrección aplicada y probada; calidad semántica global: CONDITIONAL**.

## Defecto corregido

Una respuesta podía entregarse con:

```json
{
  "verification": {
    "overall": "blocked",
    "overall_verification": "RESPALDO_CONFIRMADO"
  },
  "answer_gate": {"verdict": "skipped", "provider": "skip", "mode": "on"}
}
```

El `grounded=False` del dataclass del gate skipped se interpretaba como falta
de grounding, aunque el gate nunca hubiera juzgado. Además, el estado global
ignoraba la verificación narrativa cuando la decisión era `NOT_APPLICABLE`.

## Cambios

- `agent_flow.verification_summary` no agrega un check `grounding` cuando el
  gate tiene `provider=skip`.
- `_verification_overall` recibe `narrative_status`:
  - narrativa `VERIFIED` sin decisión aplicable → `verified`;
  - narrativa `PARTIAL` → `partial`;
  - un gate real con `grounding blocked` sigue mandando → `blocked`.
- El agente conserva la respuesta, pero el contrato ya no la declara bloqueada
  si solo faltó el gate.

## Pruebas

`tests/test_p18_3_verification_contract.py`:

- gate skipped no finge `blocked`;
- gate real sin grounding sí bloquea;
- narrativa parcial permanece parcial.

Regresión: `tests/test_narrative_verification_bridge.py`,
`tests/test_agent_flow_v2.py`, `tests/test_traceability.py` y
`tests/test_verification_split.py`. Resultado: **77 passed**.

## Límite

El Answer Gate puede quedar en `provider=skip` si el motor JEV no está
disponible. No se declara que el gate juzgó. La certificación de agente queda
`CONDITIONAL_REAL_PROVIDER` por esa razón y por una verificación parcial.
