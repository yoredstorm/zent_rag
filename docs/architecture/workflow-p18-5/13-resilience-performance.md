# P18.5-13 — Chaos, rendimiento, recuperación y observabilidad

## Identidad

- Commits: `e23b2ed`, `732e25e`, `7730264`
- Entorno local, sin staging ni producción.

## Ejecutado

| Escenario | Evidencia | Resultado |
|---|---|---|
| Outage de lectura de revocaciones | `test_revocation_store_outage_fails_closed_for_writes` | PASS: fail-closed para escrituras |
| Doble señal / señal concurrente | `test_workflow_durable_instances.py` (suite) | PASS: exactly-one-winner por claim atómico |
| Duplicado webhook/evento | `test_workflow_durable_ingress.py` | PASS: una instancia |
| Doble POST `/run` misma llave | `test_p18_5_effect_idempotency.py` | PASS: un run |
| Cursor inválido / página duplicada | `test_p18_5_execution_timeline.py` | PASS |
| WAIT → resume sin refresh | E2E `p18-5-live-resume` | PASS local |

## NO ejecutado / sin métricas

- Redis no disponible, Postgres failover/bloqueo, worker terminado tras outbox,
  provider 429/503, SSE cortado, deploy/restart durante WAIT: **NOT_RUN**.
- Carga de 100+ pasos/eventos y P95/P99: **NOT_RUN**. No se declara ningún SLO
  como cumplido; los objetivos del documento son propuestas a negociar.
- Dashboard Grafana/Prometheus: no se creó módulo nuevo; no se validaron queries
  de workflow_instance_transitions_total, dedupe, revocaciones denegadas,
  aprobaciones verificadas, replay blocking ni tiempo de resume.
- Aislamiento de carga entre tenants: **NOT_RUN**.

## Observabilidad existente

- Logs estructurados `policy.decision` con `organization_id`, `workspace_id`,
  `actor_type`, `node_id`, `capability_ref`, `allowed`, `code`,
  `policy_version`, `effective_scope_hash`, `approval_required`.
- Logs `approval.verified` con IDs, sin prompt/payload.
- Logs `workflow.agent_snapshot` con estado, fingerprint y versión de agente.
- Métricas Prometheus existentes de runs/nodos; no se añadieron labels con IDs
  de usuario.

## Rollback

- Portal: revertir `7730264`; el backend nuevo ignora campos extra del frontend.
- Backend: revertir `732e25e`/`e23b2ed`; las columnas 177 son nullable y las
  instancias WAIT conservan su JSON. No se probó rollback con tráfico real:
  **NOT_RUN**.
- Migración 177: downgrade elimina columnas/tabla nuevas; no toca datos
  existentes. No ejecutado en base con datos de clientes.

## Decisión

**NOT_RUN** para chaos/rendimiento. El baseline medido no existe; no se declara
capacidad operacional empresarial.
