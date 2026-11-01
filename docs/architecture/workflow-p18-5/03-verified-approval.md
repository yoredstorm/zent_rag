# P18.5-03 — Aprobaciones verificables para acciones irreversibles

## Identidad

- Commit: `732e25e`
- Migración: `177_workflow_approval_binding.py` (aditiva)

## Hallazgo reproducido

`authorize_node` solo comprobaba que `node.config.approval_ref` fuera truthy.
Un valor `"approved"` autorizaba un `api_call` POST irreversible sin ninguna
aprobación humana persistida.

## Contrato implementado

```
nodo irreversible
  └─ approval_ref (solo referencia) ──► workflow_approvals
        ├─ organization_id / workspace_id
        ├─ workflow_id / instance_id / run_id
        ├─ workflow_version / graph_hash
        ├─ target_node_id | capability_ref | approval_scope{run,node,capability}
        ├─ status == approved
        ├─ decided_by NOT NULL
        ├─ expires_at > now
        └─ workflow_approval_consumptions (approval_id, run_id, node_id) UNIQUE
```

- La autoridad se resuelve siempre en servidor. `approval_ref` no autoriza por sí
  solo: un string no UUID se rechaza con `policy.approval_invalid`.
- `human_approval` sigue siendo el único mecanismo de solicitud; no se creó un
  sistema paralelo. Al crear la aprobación se guardan instancia, versión,
  `graph_hash`, capability/target y `approval_scope`.
- Si el nodo `human_approval` no declara scope, se usa `scope_type=run`: cubre
  las acciones irreversibles del mismo run/instancia, no de otro tenant.
- `decide_approval` usa `UPDATE ... WHERE status='pending' AND expires_at > now`
  y `RETURNING`; dos decisiones concurrentes no pueden ganar.
- `workflow_approval_consumptions` impide que el mismo nodo consuma la misma
  aprobación dos veces. Es at-most-once por operación, no exactly-once del
  proveedor externo.

## Códigos estables

`approval_required`, `approval_invalid`, `approval_expired`,
`approval_scope_mismatch`, `approval_version_mismatch`,
`approval_already_consumed`, `approval_store_unavailable`.

La UI puede mapearlos sin recibir detalles sensibles. Los logs no incluyen el
contenido del prompt ni el payload completo.

## Pruebas

```text
uv run pytest tests/test_p18_5_verified_approval.py -q
4 passed
```

Cubre: `approval_ref="approved"` denegado; aprobación real consumida una vez;
aprobación expirada; aprobación de otro workflow; aprobación de otra capability.
Las denegaciones ocurren en el PEP antes de ejecutar el nodo; no se llamó a
ningún proveedor externo.

También se ejecutó la suite existente de aprobaciones:

```text
uv run pytest tests/test_workflow_graph.py tests/test_workflow_durable_instances.py
(incluida en 150 passed, 1 skipped)
```

## Compatibilidad y migración

- Migración aditiva: columnas nullable, `approval_scope` con default `'{}'`,
  tabla nueva de consumos. Downgrade elimina solo lo añadido.
- Aprobaciones legacy sin `approval_scope` no autorizan acciones irreversibles:
  deben volver a solicitarse. Es un cambio intencional fail-closed.
- No se modificaron workflows ni nodos inocuos.

## Riesgos residuales

- P1: `scope_type=run` permite que una aprobación cubra varias acciones
  irreversibles distintas del mismo run. Es el comportamiento histórico del
  nodo de aprobación; para acciones distintas se debe declarar
  `target_node_id`/`capability_ref`.
- P2: el `approval_ref` no está firmado criptográficamente; la seguridad
  descansa en la fila persistida, el scope y la sesión autenticada.
- P2: el owner conserva break-glass de autoaprobación auditado
  (`allow_owner_self_approval`), decisión de producto existente.

## Decisión

**PASS** para P18.5-03. P0 de aprobación falsificada cerrado.

## Próxima fase autorizada

P18.5-04.
