# Evidencia P08

Base: `0cbb494ce4264077a1e6d4823f4520fbc32928b9` + P00–P07.

| Archivo | Resultado |
|---|---|
| `junit-p08.xml` | 88 passed — Test Studio, simulación, composición, gate, migraciones, architect y plan |

## Estado

- `POST /workflows/{id}/test`: nivel efectivo decidido por servidor.
- `preview` no ejecuta; simulación usa el runner; sandbox/provider se degradan
  con motivo y no emiten `PROVIDER_VERIFIED`.
- Reporte persistido en `workflow_test_reports` (migración 169) con hashes de
  grafo, plan, rol y bindings.
- Escenario humano sin JSON y reporte con timeline/nodos ejecutados.
- Rojo P00 de nivel retirado; 13 tests de panel, 30 de portal.
- Sin adaptador proveedor/sandbox real. Sin downgrade probado.
