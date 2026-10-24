# Evidencia P07

Base: `0cbb494ce4264077a1e6d4823f4520fbc32928b9` + P00–P06.

| Archivo | Resultado |
|---|---|
| `junit-p07.xml` | 95 passed — subflujos, errores tipados, composición, simulación, planner, architect y policy |

## Estado

- `SubflowDefinition` published/versioned con snapshot y `node_config`.
- Draft/deprecated rechazados; WAIT/LOOP/aprobación bloqueados inline.
- 8 puertos tipados y `error_contract` en runtime/API.
- Router solo sobre allowlist/registry congelados.
- Fan-out hard 20, profundidad hard 8, reintentos hard 5.
- Saga plan en orden inverso con claves idempotentes.
- Biblioteca de subflujos API + drawer del Workflow Studio.
- 17 tests de portal y typecheck/lint OK.
- Sin migración. Sin proveedor real ni instancia hija durable.
