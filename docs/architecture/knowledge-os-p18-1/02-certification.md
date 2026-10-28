# P18.1-11 — Certificación ejecutada

Fecha: 2026-10-28. Rama: `fix/p18-1-knowledge-integrity-explorer`.
Base: `06415700e7c4a312a938ab9d81375026750b6dd9`.
Último commit de evidencia: `d601b8f`.

## Resultado ejecutivo

**NO-GO para producción en este corte.** La integridad y la UX documental
tienen pruebas reales, pero faltan la medición de usabilidad con cinco personas,
la matriz completa de rendimiento y una corrida CI completa sin timeouts
ajenos. No se fusiona ni se declara PASS.

## Pruebas ejecutadas

| Área | Comando | Resultado |
| --- | --- | --- |
| Backend P18.1 | `pytest tests/test_p18_1_* -q` | 27 passed |
| Backend Knowledge | `pytest tests/test_knowledge_workspaces_api.py tests/test_knowledge_compiler.py tests/test_document_understanding.py tests/test_semantic_reconstruction.py tests/test_knowledge_conflict_quality.py tests/test_knowledge_api.py tests/test_knowledge_corpora.py tests/test_knowledge_model.py` | 129 passed, 1 flaky de orden; aislada pasa |
| Portal unitario | `npm test -- --run` | 814 passed, 2 fallos ajenos |
| E2E P18 existente | `playwright test e2e/knowledge-alive.spec.ts` | 1 passed |
| E2E Explorador P18.1 | `playwright test e2e/p18-1-explorer.spec.ts` | 1 passed, 1366 y 390 |
| E2E Wizard P18.1 | `playwright test e2e/p18-1-wizard.spec.ts` | 1 passed, lote parcial y recarga |
| Cleanup no destructivo | `pytest tests/test_p18_1_cleanup.py` | 1 passed, dry-run + hide + restore |

### Fallos ajenos al cambio

- `pytest -q` completo se detuvo por timeout en una prueba larga no
  relacionada; no se usa como PASS.
- `test_knowledge_api.py::test_sync_creates_job_and_engine_completes` falla
  solo dentro de la suite completa y pasa aislada; el estado `error` proviene
  del acceptance de retrieval previo, no de las rutas P18.1. No se declara PASS
  de esa prueba.
- Portal: `AgentStudio.test.tsx` agotó 20 s y `evaluation.test.tsx` no encontró
  un campo del diálogo. No tocan Knowledge ni P18.1. No se corrigen aquí.

## Evidencia real de datos

Fuente local `el_principito.pdf`, 110 objetos canónicos. El read model
`knowledge_explorer_insight/v1` devolvió:

- `objects_total`: 110
- `objects_visible`: 0
- `objects_hidden`: 110
- `warnings`: `ONLY_LOW_UTILITY`, `HIDDEN_CANDIDATES`, `GENRE_UNKNOWN`
- `summary`: «Solo se identificaron secciones y pasajes; no podemos afirmar
  temas con certeza.»

Esto es correcto para el estado actual: las etiquetas persistidas son
fragmentos narrativos (`planeta?`, `recuerdas?`, `52`, diálogos y títulos). No
se borraron ni se reingirieron. La vista avanzada y el acceso a la fuente
siguen disponibles.

## Matriz GO/NO-GO

| Puerta | Estado | Evidencia |
| --- | --- | --- |
| G0 Baseline reproducible | GO | `artifacts/certification/p18-1/baseline.json` |
| G1 Aislamiento corpus/tenant/workspace | GO parcial | Pruebas unitarias e integración; falta prueba de carga multi-tenant |
| G2 Destino de carga determinista | GO | 3 pruebas de integración, concurrencia no ejecutada |
| G3 Wizard durable | GO | E2E con 3 archivos, duplicado, recarga y lote nuevo |
| G4 Evidencia autenticada | GO parcial | Visor con token; falta E2E de PDF real con cookie y Bearer-only |
| G5 Género y candidatos | GO parcial | Fixtures y matriz; falta corpus anotado humano |
| G6 Explorador explicable | GO parcial | E2E visual 1366/390 y a11y; falta medición con 5 personas |
| G7 CI, rendimiento y rollback | NO-GO | CI completa con timeout ajeno; rendimiento 1000 objetos no medido |

## Rollback

- Explorador visual: `KNOWLEDGE_EXPLORER_V2_ENABLED=false`.
- Wizard: `KNOWLEDGE_IMPORT_WIZARD_V2_ENABLED=false`.
- Cleanup: `action=restore`, `dry_run=false`; probado y verificado en
  `tests/test_p18_1_cleanup.py`.
- Aislamiento de corpus: sin flag de apagado. Rollback = revertir el release.

## Pendiente para GO

1. Corrida CI completa sin timeouts ajenos.
2. Prueba de carga con 1000 objetos y paginación server-side.
3. E2E de PDF real: cookie, Bearer-only, página 7, revocación.
4. Cinco personas no técnicas completando el recorrido, con tiempos y errores.
5. Revisión humana de una muestra de clasificaciones y matriz de confusión por
   género.
