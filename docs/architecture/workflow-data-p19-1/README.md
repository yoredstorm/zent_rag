# P19.1 — Enterprise Data Workflows Hardening

Programa de endurecimiento de los flujos de datos de P19.1. Este directorio
registra baseline, contratos, decisiones, evidencia y gates. **La existencia de
un documento no certifica un control**: solo la fila con evidencia ejecutada y
SHA lo hace.

## Estado

| Prompt | Estado | Documento |
|---|---|---|
| P19.1-00 Baseline, CI rojo, threat model y regresión | DONE (CI run 41362601249 success) | [00-baseline-ci-threat-model.md](./00-baseline-ci-threat-model.md) |
| P19.1-00 Inventario AS-IS | DONE | [00-inventory-asis.md](./00-inventory-asis.md) |
| P19.1-00 Mapa de regresión | DONE | [00-regression-map.md](./00-regression-map.md) |
| P19.1-01 Gobierno de publicación | NOT_STARTED | — |
| P19.1-02 Identidad y ownership | NOT_STARTED | — |
| P19.1-03 Binding pinning/drift | NOT_STARTED | — |
| P19.1-04 Contrato de resultados y errores | NOT_STARTED | — |
| P19.1-05 UX de datos | NOT_STARTED | — |
| P19.1-06 Intención multivuelta durable | NOT_STARTED | — |
| P19.1-07 Inventario | NOT_STARTED | — |
| P19.1-08 Conectores PostgreSQL productivos | NOT_STARTED | — |
| P19.1-09 Certificación GO/NO-GO | NOT_STARTED | — |

## Regla de evidencia

- `PASS`: comando ejecutado en el SHA indicado, con log/JUnit conservado.
- `FAIL`: comando ejecutado y fallo reproducido.
- `NOT_RUN`: no ejecutado o servicio no disponible; incluye comando de
  reproducción. Un mock no convierte `NOT_RUN` en `PASS`.
- `NOT_MEASURED`: métrica sin entorno comparable; no se extrapola del MVP.

## Entorno local de referencia

- Windows, Python 3.11.16, uv 0.12.13, Node 22.22.1, PostgreSQL 16 local.
- `rag-postgres`, `rag-redis`, `rag-qdrant`, `rag-api`, workers y portal en
  Docker; PostgreSQL externo P19 en `127.0.0.1:55432`.
- Los datos de `ops/p19-external` son sintéticos.
