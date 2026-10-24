# Evidencia P06

Base: `0cbb494ce4264077a1e6d4823f4520fbc32928b9` + P00–P05.

| Archivo | Resultado |
|---|---|
| `junit-p06.xml` | 68 passed — contexto, memoria, roles, migraciones, agente, mapping y solución |

## Estado

- Migración aditiva 168: workspace, sujeto, scope, consentimiento, expiración y borrado.
- `context_service.py`: política única por rol; fail-closed.
- Prompt del agente recibe `context.memory` solo con memoria autorizada.
- Revocación y borrado vía API; workspace isolation en listado/detalle/contexto.
- Drawer “Memoria” en Workflow Studio.
- `GET /workflows/{id}/data-mapping` expone el mapper real.
- Sin proveedor real. Autoservicio del sujeto y P12 quedan pendientes.
