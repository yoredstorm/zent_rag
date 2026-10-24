# 10 — P08: Workflow Test Studio verificable

Fecha: `2026-10-23`. Base: `0cbb494ce4` + P00–P07.

## 1. Nivel decidido por el servidor

`POST /api/v1/workflows/{id}/test` recibe un escenario humano y un nivel
solicitado. El servidor decide el nivel efectivo:

- `preview`: no ejecuta nodos; resultado `PREVIEW`, nunca `PASSED`;
- `simulation`: ejecuta el runner determinista existente sobre el grafo;
- `sandbox`: si no hay adaptador sandbox real, baja a `simulation` con
  `capped_reason=sandbox_adapter_unavailable`;
- `provider`: sin adaptador real baja a `simulation` con
  `capped_reason=provider_adapter_unavailable` y resultado `UNVERIFIED`.

`provider_verified` siempre es `false` en este corte. No se emite
`PROVIDER_VERIFIED` ni un certificado de proveedor por un fake.

## 2. Reporte persistido

Migración aditiva **169** crea `workflow_test_reports` con:

- `requested_level`, `effective_level`, `result`;
- `graph_hash`, `plan_hash`, `role_hash`, `binding_hash`;
- escenario enmascarado y reporte completo;
- tenant, workspace, workflow, actor y fecha.

`GET /workflows/{id}/test-reports` devuelve el historial. Un cambio de grafo
produce otro `graph_hash`; el gate P01 (`publication_blockers`) sigue marcando
`certificate_stale`. El reporte de test no sustituye el certificado.

## 3. Escenario sin JSON

`draft_to_scenario` acepta mensajes, eventos, respuestas simuladas, estado
esperado, efectos permitidos/prohibidos y presupuesto. El panel usa ese
contrato; no exige escribir JSON. La respuesta incluye `executed_nodes` y
`timeline`, y el panel proyecta esos pasos en el overlay del lienzo.

## 4. UI

El dock de prueba:

- conserva los cuatro niveles visibles;
- muestra el nivel solicitado, el efectivo y el motivo de degradación;
- muestra hashes, nodos ejecutados y timeline;
- para `provider`/`sandbox` avisa que no acredita proveedor real;
- “Ejecutar de verdad” sigue usando `/run`; “Probar” usa `/test`.

El rojo P00 de nivel de prueba quedó retirado y reemplazado por pruebas
permanentes.

## 5. Pruebas

| Comando | Resultado |
|---|---|
| Suite P08 backend (test studio, simulación, composición, gate, errores, migraciones, architect, plan) | **88 passed** (`junit-p08.xml`) |
| Portal `WorkflowTestPanel` + memoria + subflujos + tipos | **30 passed** |
| `ruff check` P08 | OK |
| Portal `npm run typecheck` | OK |
| Portal `npm run lint` | 0 errores |

Cubre: preview sin ejecución, simulación, degradación sandbox/provider,
`UNVERIFIED`, hashes, persistencia, escenario sin JSON, workspace isolation,
certificado stale y que un fake no produzca `PROVIDER_VERIFIED`.

## 6. Límites

- No existe adaptador sandbox ni proveedor real conectado; el nivel efectivo se
  degrada y se declara.
- El overlay de test usa los `executed_nodes` del reporte, no un `workflow_run`
  real; el reporte persistido es la evidencia.
- La UI sigue mostrando el aviso de niveles no conectados; el servidor es la
  autoridad.
- No se probó carga concurrente ni un proveedor real.
- El downgrade 169→168 no se ejecutó.

## 7. Rollback

1. Revertir panel, endpoints, `test_studio.py`.
2. `alembic downgrade 168` elimina solo `workflow_test_reports`.
3. El resto de runs y certificados no se toca.

## 8. Dictamen

**GO P08 para staging controlado.** El nivel es del servidor, el reporte es
persistido y trazable, y un fake no certifica proveedor. **NO-GO release:** falta
adaptador sandbox/provider real y certificación horizontal P12.
