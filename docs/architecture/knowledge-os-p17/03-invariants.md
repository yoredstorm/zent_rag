# P17-00 — Invariantes y snapshot

## 1. Qué se conserva

La simplificación UX no puede cambiar:

- organización/workspace de fuentes y corpus;
- ACL y visibilidad de evidencia;
- documentos, hashes y versiones de índice;
- jobs, sesiones y estados de ingesta;
- objetos, assertions, edges, conflictos, gaps y compilaciones;
- agentes y workflows publicados.

## 2. Snapshot reproducible

```bash
uv run --frozen --no-sync python scripts/knowledge_ux_snapshot.py \
  --output artifacts/certification/p17/invariants-before.json
```

El script es de solo lectura. Guarda:

- HEAD;
- existencia y conteo por tabla;
- hash determinista de IDs;
- hash de estado para fuentes, assertions, conflictos, gaps, jobs, sesiones y
  workflows.

No guarda contenido documental, prompts, credenciales ni datos personales.

## 3. Baseline local

`artifacts/certification/p17/invariants-before.json` se generó contra la base
local de desarrollo. Los conteos son locales, no producción. Se comparan con el
snapshot posterior de la misma base y flags.

Tablas incluidas: `knowledge_bases`, `kb_sources`, `source_documents`,
`structured_documents`, `ingestion_jobs`, `knowledge_corpora`,
`knowledge_canonical_objects`, `knowledge_assertions`, `knowledge_edges`,
`knowledge_conflicts`, `context_gaps`, `knowledge_learning_sessions`,
`knowledge_compilations`, `evidence_ledger`, `workflows`, `agents`.

## 4. Criterio de no-regresión

Después de cada fase:

1. El conteo/hash de fuentes y documentos no cambia por navegar o renderizar.
2. ACL y workspace no cambian.
3. No aparecen writes nuevos en endpoints de lectura.
4. Workflows publicados y agentes no cambian.
5. Si cambia un conteo esperado (por ejemplo, una fuente nueva creada por un
   test), se documenta la causa y se compara el resto de las tablas.

## 5. Limitación

El script no lee payloads ACL de Qdrant. Esa parte se verifica con las pruebas
negativas de ACL/tenant y con el E2E de cita; no se declara cubierta solo por el
snapshot SQL.
