# P18.3-10 — Certificación vertical de agente + conocimiento + workflow

Estado: **NOT_RUN** para el vertical comercial y el de revisión documental.

## Lo que sí está probado

- Ciclo de workflow publicado: snapshot, certificado, bloqueo de publicación
  sin certificado y recuperación durable. Suites P13/P18:
  `tests/test_workflow_published_snapshot.py`,
  `tests/test_workflow_publication_gate.py`,
  `tests/test_workflow_durable_instances.py`,
  `tests/certification/workflows/`.
- Agente con fuentes reales y citas: P18.3-08, CONDITIONAL_REAL_PROVIDER.
- Idempotencia de sesión y adjuntos: P18.2, tests de sello y carrera.
- Snapshot de agente en workflow: P18.3-09.

## Lo que falta para PASS

1. `sales_vertical_e2e.spec.ts`: catálogo CSV/DB autorizado, cinco turnos,
   WAIT MESSAGE/RESUME, carrito persistente, aprobación, sandbox de pedido,
   deduplicación de eventos y reinicio de worker/API.
2. `policy_vertical_e2e.spec.ts`: corpus normativo, obligación/excepción,
   aprobación humana, resumen y seguimiento, sin editar la política original.
3. Sandbox real del proveedor de pedidos o adaptador tipado; no se simula como
   proveedor real.
4. Efecto ledger y replay con `effect_id`.
5. Prueba de revocación durante WAIT y de referencia de aprobación falsa.

No se declara un vertical integral certificado sin ejecutar el flujo completo
con estado durable y recuperación.
