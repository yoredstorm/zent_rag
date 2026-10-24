# Evidencia P05

Base: `0cbb494ce4264077a1e6d4823f4520fbc32928b9` + P00–P04.

| Archivo | Resultado |
|---|---|
| `junit-p05.xml` | 56 passed — PEP, workspace, aprobaciones, action plane, RBAC, tenant y autorización |

## Estado

- PEP común en runtime; nodos internos exigen `workflows:run`.
- Rol/autonomía y guardrail de bienestar aplicados en ejecución.
- Instancias y señales filtran por workspace; creación rechaza workspace ajeno.
- Autoaprobación bloqueada salvo break-glass explícito del owner.
- `policy_snapshot` congela rol por agente al iniciar la instancia.
- Tests directos de grafos: 110/110; core workflow: 41/41.
- Sin migración. Sin proveedor real. Memoria por workspace queda P06.
