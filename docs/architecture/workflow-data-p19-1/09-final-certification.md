# P19.1-09 — Certificación integral y decisión GO/NO-GO

- **SHA de código evaluado:** `55143e07bfbdb7ab0dfa80f03fe4cfd23e958886`
- **PR:** https://github.com/yoredstorm/zent_rag/pull/18
- **Fecha:** 2026-11-01
- **Regla:** PASS solo con comando ejecutado y evidencia. Los mocks no
  certifican PostgreSQL externo, concurrencia, TLS real ni usuarios.

## Decisión

**NO-GO para producción general.**
**NO-GO para piloto con datos reales/PII.**
**GO limitado a staging técnico con datos sintéticos**, condicionado a que el
CI del PR 18 cierre verde y a que no se habiliten pagos reales.

Motivos del NO-GO:

- G02 no tiene prueba de revocación viva durante WAIT ni RLS de proveedor.
- G05/G06 no tienen Playwright, axe, usuarios reales ni gold set de 80 casos.
- G07 no tiene 100 reservas concurrentes, doble commit ni multi-ítem atómico.
- G08 no tiene CA inválida/hostname incorrecto, rotación ni carga concurrente.
- G09 no tiene SLO medidos, DR ni soporte operativo certificado.

No se compensa con promedio: cualquier gate crítico `NOT_RUN` bloquea.

## Matriz de gates

| Gate | Riesgo | Prueba ejecutada | Resultado | Evidencia | Bloquea piloto |
|---|---|---|---|---|---|
| G00 | CI/arquitectura | Invariantes + PR CI | PASS (run 41383152164) | `scripts/cert/run_invariants.py`; run del PR | Sí |
| G01 | Publicación/PII | Permisos, allowlist, PII, auditoría, preview stale | PASS local | `test_workflow_data_p19_governance.py` (4) | Sí |
| G02 | Identidad/ownership | Principal, scope, expiración, A/B, sin principal | PASS local; revocación WAIT NOT_RUN | `test_workflow_data_p19_principal.py`, integración PostgreSQL | Sí |
| G03 | Binding drift | Mutar tabla con mismo ID, hash, revisiones, plan stale UI | PASS local; snapshot release PARTIAL | `test_workflow_data_p19_binding_pin.py`; `DataQueryForm` | Sí |
| G04 | Estados/errores | NOT_FOUND, TIMEOUT, DENIED, run failed | PASS local | `test_workflow_data_p19_node.py` (10) | Sí |
| G05 | UX | Cero columnas, sin reload, tipos, política, typecheck | PASS parcial; E2E/a11y/humano NOT_RUN | Vitest `DataQueryForm` + `PublishQueryModal` | Sí para self-service |
| G06 | Conversación | v2, slots, gold set 80, turn limit | PASS unitario + gold set 100%; 4+ turnos E2E NOT_RUN | `test_workflow_data_p19_goldset.py` | Sí para piloto conversacional |
| G07 | Inventario | Adaptador, expiración, batch, 100 ops | PASS local: 100 ops/20 concurrencia, stock 10, 0 negativo; doble commit NOT_RUN | `p19_inventory_concurrency.py` | Sí para escrituras |
| G08 | Conexiones | Red, TLS handshake CA, allowlist, cache, external real | PASS unitario + external; carga 100 NOT_RUN | `test_workflow_data_p19_connector_security.py` (7) | Sí para DB externa |
| G09 | Certificación | E2E, adversarial, humanas, SLO | FAIL / incompleto | este documento | Sí |

## Evidencia ejecutada

| Comando | Resultado |
|---|---|
| `pytest` suites P19 + nuevas | `82 passed, 2 skipped` (skips externos sin env) |
| `pytest` governance/principal/pin/security/node/intent/catalog/query | `70 passed` |
| `pytest` durable/runtime/workflows | `92 passed` |
| PostgreSQL externo real | `2 passed` con `P19_EXTERNAL_*` |
| Invariantes de arquitectura | `407 passed` |
| Vitest `DataQueryForm` | `3 passed` |
| Vitest `PublishQueryModal` | `1 passed` |
| Gold set intención 80 casos | `route_accuracy=1.0`, `slot_f1=1.0`, `false_authorizations=0` |
| Chaos inventario | 100 operaciones, concurrencia 20, stock 10: 10 reserved, 90 conflicts, 0 negativo |
| TLS handshake CA propia | PASS; hostname incorrecto rechazado |
| Cache de engines | PASS; límite 2 respetado |
| `npm run typecheck` | PASS |
| `ruff check src/ tests/ sdk/python` | PASS |
| Migraciones 178/179 | aplicadas localmente |
| CI PR 18 (`41383152164`, SHA `55143e0`) | `test`, 4 shards, portal, portal-e2e, certification, secrets-scan, lint, SDKs y build: success |

## Pruebas obligatorias NOT_RUN

- A. Precio: ≥10 conversaciones E2E, precio cambia entre turnos, quote inválida.
- B. Fidelidad: A≠B, DNI no autentica, agente comercial no lee agregado,
  identidad expirada en WAIT, timing de existencia.
- C. Pedidos: titular, tercero, cancelado, dirección con aprobación.
- D. Bodega: doble commit simultáneo, crash/reboot, reconciliación ledger.
- E. Seguridad: SQLi, override de metadata, replay, cross-org, carga 100 consultas.
- F. Usabilidad: 5 usuarios reales, axe, 390/768/1440.
- Performance/SLO: p50/p95/p99 con hardware/dataset declarados.

## Migraciones y rollback

- `178_data_query_governance`: permisos, políticas, eventos append-only.
- `179_binding_revisions`: versión/hash y revisiones de bindings.
- Ambas aditivas. `downgrade` elimina solo lo nuevo.
- Los bindings/planes creados con 178/179 no se borran al hacer downgrade; el
  preview los trata como legacy y no amplía accesos.
- Rollback de app: volver a `b416da1`. Volver a ejecutar workflows con nodos que
  exigen hash puede dar `PLAN_STALE` (seguro).

## Riesgos residuales aceptados para staging

- Sin UI de administración de allowlists; se usa API.
- Sin RLS de proveedor; ownership es de aplicación.
- Sin TLS real probado; staging debe usar CA de prueba antes de datos reales.
- Sin multi-ítem atómico; no habilitar escrituras de inventario reales.
- Sin métricas de pool/drift; monitoreo básico.

## Firma

- Producto: pendiente de revisión humana.
- Seguridad: NO-GO producción; revisión de los P0 implementados pendiente.
- Operación: NO-GO hasta SLO/DR/soporte.

**Este documento no autoriza producción.** Autoriza únicamente staging técnico
con datos sintéticos si el CI del SHA final está verde.
