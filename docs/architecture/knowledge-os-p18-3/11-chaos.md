# P18.3-11 — Caos, carga, observabilidad y coste

Estado: **NOT_RUN**. No se ejecutó una ventana de perturbaciones ni una carga
representativa.

## Matriz planificada

| Perturbación | Qué verificar |
|---|---|
| Reiniciar ingestion-worker durante parsing y al indexar | job reanudado o fallo explícito; sin pérdida de archivo |
| Qdrant caído y restaurado | fallback honesto, sin respuesta inventada |
| Reiniciar API durante SSE | reconexión por `since_seq`, sin duplicar eventos |
| Redis no disponible / evento reentregado | consumidor único, deduplicación |
| Postgres lento / pool agotado / 429-503 del LLM | timeout, retry y estado visible |
| Token de proveedor agotado antes de RESUME | fail closed |
| 1.001 y 10.001 objetos/evidencias | paginación, memoria, p95 |
| Lotes de 5–20 archivos | cuota por tenant/workspace/job |

## Métricas que se deben reportar

- ingest-to-ready, query-to-first-token, respuesta total, reanudación;
- fallos, recuperación, backlog, retries, deduplicación;
- CPU/RAM, profundidad de cola y coste por documento/consulta/ejecución;
- p50, p95, máximo y n por familia y escenario.

No se reutiliza el p95 in-process de 78–93 ms (n=5, sin DB) como latencia de
usuario.

## Evidencia existente

- E2E real de ingesta con worker: PASS.
- Tests de idempotencia de sesión y workflow: PASS.
- Paginación de 10.001 evidencias: PASS en test de integración.
- No hay dashboard de esta corrida ni runbook on-call firmado.
