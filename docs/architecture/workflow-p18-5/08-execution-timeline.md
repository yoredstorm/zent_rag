# P18.5-08 — Timeline durable, causal y con permisos

## Identidad

- Commits: `e23b2ed` (datos), `7730264` (integración)
- Archivo: `src/platform/workflows/instances.py::instance_timeline`

## Proyección `execution_timeline/v1`

Cada item incluye:

- `event_id`, `cursor` estable (base64 de `{v:1, seq}`)
- `instance_id`, `run_id`, `node_id`, `instance_seq`
- `kind`, `status`, `occurred_at`, `observed_at`, `duration_ms`
- `summary` redaccionado y `audit_refs` (`policy_code`, `approval_id`,
  `signal_id`, `error_code`)
- `has_more`, `next_cursor`, `limit`

Fuente única: `workflow_runs`, `workflow_signals`, `workflow_run_events`. No se
creó otro event store.

## Causalidad y paginación

- Eventos ordenados por `workflow_run_events.seq` (BIGSERIAL) con cursor
  `seq > after_seq`; no se ordena solo por fecha.
- Runs y señales se incluyen con claves deterministas y orden por timestamp.
- Ya no hay `LIMIT 1000` silencioso: default 200, máximo 500, `has_more` y
  `next_cursor`; cursor inválido → 400 `timeline_cursor_invalid`.
- Señales y payloads se redaccionan (`password`, `token`, `authorization`,
  `api_key`, etc.); strings > 2000 se truncan, listas/dicts se acotan.

## Pruebas

```text
uv run pytest tests/test_p18_5_execution_timeline.py -q
2 passed
```

- Página de 2 eventos con `has_more`/cursor, segunda página sin duplicados.
- Payload sintético con `token` redaccionado y summary truncado.
- Cursor inválido → 400.
- Timeline de instancia en workspace B → 404.

## Rendimiento y límites

- La consulta de eventos está acotada por `instance_id`, `organization_id` y
  `seq` (índices existentes de `workflow_run_events`).
- Runs y señales se repiten en cada página (conjunto pequeño por instancia); si
  una instancia tuviera miles de señales, se deberá paginar también esa tabla en
  una fase posterior. Documentado, no medido con carga real.
- No se exponen dumps de herramientas ni payloads completos.

## Compatibilidad

- Se conservan `runs`, `signals`, `events` para consumidores P18.4.
- `business_timeline` sigue calculándose igual.
- Sin migración.

## Decisión

**PASS** para la proyección y el contrato de lectura. El benchmark de carga queda
**NOT_RUN** (ver P18.5-13).

## Próxima fase autorizada

P18.5-09.
