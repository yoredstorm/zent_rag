# P18.5-05 — Idempotencia de efectos y replay intencional

## Identidad

- Commit: `7730264`
- Componentes: `src/api/routes/workflows.py`, `useWorkflowTestRunner.ts`,
  `IdempotencyMiddleware`, `workflow_ingress_events`.

## Cambios

- `POST /workflows/{id}/run` propaga `Idempotency-Key` a `route_ingress`; el
  evento de ingress conserva la llave y el hash del payload.
- Misma llave + mismo payload → replay de la respuesta (header
  `Idempotency-Replayed: true`), sin segundo run.
- Misma llave + payload distinto → 409 `idempotency_conflict`.
- El frontend genera una llave estable por intención real y la envía en el
  header. La simulación (`/test`) no crea runs reales.
- La confirmación real ya exigía escribir `EJECUTAR`; se conserva.
- Auditoría: `workflow_ingress_events.ingress_key`, `payload_hash`, `run_id`,
  `instance_id`; `workflow_runs.correlation_id` y `actor_id`.

## Pruebas

```text
uv run pytest tests/test_p18_5_effect_idempotency.py -q
2 passed
```

- Doble POST con misma llave → un solo `workflow_runs`.
- Misma llave con payload distinto → 409 y sigue habiendo un run.
- Llaves distintas → dos runs distintos.
- Suite existente: duplicados de webhook/evento y señales concurrentes
  (150 passed, 1 skipped).

## Límites

- No se afirma exactly-once sobre proveedores externos. La garantía local es
  at-most-once para la intención registrada; un proveedor sin idempotencia
  propia puede haber recibido el efecto antes de un timeout.
- El middleware de idempotencia depende de Redis; si Redis no está disponible,
  la request con llave falla cerrada (`idempotency_unavailable`) en lugar de
  ejecutar dos veces.
- Un “reintento” de UI con payload editado debe generar una nueva intención;
  el panel actual no reenvía automáticamente el composer tras un error.

## Compatibilidad

- Sin migración.
- Llamadas sin `Idempotency-Key` siguen funcionando (compatibilidad), pero el
  panel ahora siempre envía una.
- Rollback: revertir `7730264`; los eventos de ingress ya escritos son
  compatibles.

## Decisión

**PASS** para el contrato local de idempotencia. La certificación de efectos
externos queda **NOT_RUN** (no hay proveedor sandbox autorizado en esta fase).

## Próxima fase autorizada

P18.5-06.
