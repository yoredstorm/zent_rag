# P17-08 — Validación y release

## Evidencia técnica

| Gate | Estado |
|---|---|
| CI completo (P17-00..06, SHA `db52ebc`) | PASS, run `40465714085` |
| P17-07 tests focalizados | PASS, `51 passed` (Agent Studio + SourceDetail) |
| P0 ACL reader/admin | PASS, `3 passed` |
| Evidence resolver org/workspace | PASS, `4 passed` |
| Ask UI | PASS, cita, evidencia, fuente y feedback |
| Improve inbox | PASS, no evaluado vs sin problemas |
| Baseline PDF real | PASS, 5 citas API; conflicto abierto `NOT_AVAILABLE` |
| A11y smoke Preguntar/Mejorar | PASS local, `knowledge-ux.spec.ts` (axe serias/críticas) |
| A11y de todas las vistas Knowledge | NOT_MEASURED |
| 1/100/1000 fuentes | NOT_MEASURED |
| Bundle/latencia Knowledge | NOT_MEASURED |
| 429/proveedor caído en UX nueva | NOT_TESTED en E2E; cubierto parcialmente por jobs/backend |
| 5 usuarios no técnicos | NOT_STARTED |
| Snapshot de invariantes después | NOT_VERIFIED; el snapshot previo existe |
| Writes por navegación/render | NOT_MEASURED con instrumentación de red |
| Canary por tenant | NOT_AVAILABLE por PK/NOT NULL de `feature_flags` |

CI incluye suite backend, portal, E2E y build; no se omitieron suites.

## Pruebas negativas existentes

- `test_knowledge_workspaces_api.py`: reader no recibe rol admin en retrieval;
  owner sí; cross-tenant en corpus.
- `test_knowledge_evidence_api.py`: 404 cross-org y cross-workspace.
- `test_knowledge_api.py`, `test_model`, `test_authorized_scope`,
  `test_tenant_isolation`: aislamiento de fuentes, jobs y evidencia.
- `test_hybrid_retrieval`/`test_structured_retriever`: ACL pre-LLM.

## Release

- **P17-00..07: GO_STAGING**, con `RAG_KNOWLEDGE_SIMPLE_UX_ENABLED=false` por
  defecto. Activación interna/staging por entorno.
- **GO_CONTROLLED_ROLLOUT: NO_GO** hasta completar 5 usuarios, 1/100/1000,
  axe de todas las vistas, snapshot posterior y medición de red/bundle.
- **Producción: NO_GO.** No se activó ningún flag experimental ni
  `ZENT_GOLD_RELEASE_ENABLED`.
- El rollback es apagar el flag; rutas legacy y APIs siguen disponibles.

## Declaración

NO DREAMING. NO SELF-LEARNING EXPANSION. NO AUTONOMOUS KNOWLEDGE PROMOTION.
NO PRODUCTION MUTATIONS FROM UI-ONLY WORK.
