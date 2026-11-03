# P19 — Merge a master y actualización Docker (2026-11-01)

- **Rama integrada:** `feat/p19-workflow-data-orchestration`
- **Merge commit:** `7a2d6b4` (`--no-ff`)
- **Master remoto:** `7a2d6b4`
- **Fases integradas:** P19-00, P19-01, P19-02, P19-03, P19-04, P19-05.
- **Fases no integradas:** P19-06 a P19-14. No se declaran completas.

## Contenido integrado

| Fase | Entrega |
|---|---|
| P19-00 | Auditoría, modelo de amenazas, ADR, matriz AS-IS/TO-BE, tests rojos |
| P19-01 | Plan `zent.data.query.binding/v1`, binder sin override, `get_one/list/count`, errores tipados, integración PostgreSQL real |
| P19-02 | Catálogo de data sources, recursos publicados, schema y preview redactado |
| P19-03 | Nodo `data_query` y editor Simple «Consultar registros» |
| P19-04 | Nodo `intent_route`, rutas cerradas, entidades y fallback determinista |
| P19-05 | Data Picker de un clic hacia parámetros declarados |

## Pruebas antes del merge

| Suite | Resultado |
|---|---|
| P19 backend (audit, query, integración, catálogo, nodo, intención, node catalog) | `73 passed` |
| Portal completo | `866 passed` en 139 archivos |
| TypeScript | sin errores |
| Ruff | sin errores |
| CI remoto del merge | `8 required status checks are expected` al momento del push; verificar el run de master después |

No se ejecutó la suite backend completa fuera de las suites P19 y de regresión
seleccionada. Se declara **NOT_RUN**, no PASS.

## Docker actualizado

Comando ejecutado:

```powershell
$sha = git rev-parse HEAD
$env:RAG_RUNTIME_BUILD_GIT_SHA = $sha
docker compose build api portal ingestion-worker
docker compose up -d --no-deps api portal ingestion-worker
```

| Elemento | Valor |
|---|---|
| SHA de build | `7a2d6b449dcf4bc8ebc9a702c3b86023923b7526` |
| `rag-api` | healthy; `RAG_GIT_SHA=7a2d6b449dcf...` |
| `rag-portal` | healthy |
| `rag-ingestion-worker` | running |
| `GET /health` | 200 |
| Portal `:8080` | 200 |
| Alembic | `177 (head)`; sin migración P19 nueva |
| Endpoint `GET /data-sources` sin token | 401 (registrado) |
| Endpoint `POST /intent-route/test` sin token | 401 (registrado) |
| Bundle del portal | contiene «No hay consultas publicadas» e «Identificar solicitud» |

No se reiniciaron PostgreSQL, Redis, Qdrant ni servicios de observabilidad. No se
borraron datos ni esquemas.

## Rollback

1. `git revert -m 1 7a2d6b4` y push a master.
2. Reconstruir API/portal/worker con el commit anterior.
3. No hay migración P19 que revertir; Alembic sigue en `177`.
4. Los workflows publicados y las instancias no se reescribieron.
5. Si se revierte el código con grafos `data_query`/`intent_route` guardados,
   desactivar su creación antes del rollback: serían tipos desconocidos.

## Límites de esta entrega

- P19-06 (conectores externos), P19-07/08/09 (plantillas), P19-10 (Architect),
  P19-11 (UX completa), P19-12 (readiness/pinning), P19-13 (adversarial/carga) y
  P19-14 (certificación) no están implementadas.
- No hay proveedor externo certificado, RLS/titularidad ejecutable, pinning de
  binding en WAIT ni E2E Playwright P19.
- El merge no convierte el programa en GO de producción. Es una entrega local
  verificable con Managed DB y tests.
