# Aislamiento multi-tenant con contenido idéntico (Parte H)

Evidencia: `artifacts/certification/edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8/battery/tenant.json`.

| Dato | Valor |
|---|---|
| SHA | `edeeb61` |
| Fecha | 2026-10-14 |
| Entorno | DB scratch `rag_cert_battery` + Redis real + Qdrant real (`v1.13.4`) |
| Comando | `python -m src.scripts.certification_battery --suite tenant` |
| Resultado | **6/6 escenarios PASS · 49 tests · 0 fail** (190,3 s) |

No son dos tests unitarios: las organizaciones A y B se crean con datos
**deliberadamente parecidos** y se verifica que el boundary aguanta aunque el
contenido coincida.

| # | Escenario (A/B con datos idénticos) | Qué se verifica | Test |
|---|---|---|---|
| H01 | mismo texto de documento + mismo `filename` en dos orgs, misma colección Qdrant | la búsqueda de A devuelve **1** chunk (el suyo) y una org sin datos devuelve 0 | `test_vector_search_isolates_tenants_with_identical_documents` |
| H02 | misma query, mismo rol, misma etiqueta de conversación, mismo fingerprint de conocimiento | la clave de caché difiere por tenant; B no lee la respuesta de A; otra conversación de A tampoco; sin fingerprint la clave cambia (fail-closed) | `test_response_cache_key_isolates_tenants_with_identical_query` |
| H03 | mismos tokens y mismo costo en dos orgs | `reconcile` por org devuelve solo la fila propia (requests/tokens/costo) | `test_usage_and_billing_are_tenant_scoped` |
| H04 | scopes de conocimiento disjuntos | `narrow(scopeA, scopeB)` no amplía nunca | `test_knowledge_scope_never_widens_across_tenants` |
| H05 | misma KB id en dos orgs | los vectores no se mezclan (filtro org+kb) | `test_knowledge_base_vectors_scoped_to_organization` |
| H06 | conversaciones distintas del mismo tenant | 0 hits cruzados ×100 corridas adversariales | `test_conversation_isolation.py` (8 tests) |

## Contratos duros que respaldan esto (no solo tests)

| Boundary | Código |
|---|---|
| Retrieval | `src/infrastructure/qdrant/vector_store.py` (rechaza búsqueda sin `organization_id`; filtro por org en vector y sparse) |
| Caché de respuestas | `src/infrastructure/redis/cache.py` (`_hash_query` embebe tenant + conversación + fingerprint + versión de política) |
| Scope de conocimiento | `src/core/domain/knowledge_scope.py`, `src/runtime/authorized_scope.py` |
| Usage/billing | `usage_events.organization_id` + `reconcile(org)`; `invoices` por org |
| Tools | `ToolContext` construido desde la request autenticada (`agent_runtime`), nunca desde argumentos del modelo |
| Memoria | `tests/test_zent_runtime.py` / memoria por org (fuera de la batería; cubierto por la suite) |

## Límites declarados

- El test H01 requiere Qdrant real (se saltea fuera de `development`); en CI hay
  Qdrant como service.
- Traces/agent_runs se validan por suite (no en la batería); su aislamiento por
  `organization_id` está cubierto en `tests/test_traces.py`.
- No se probó aislamiento entre regiones/workspaces cruzados en esta batería
  (`tests/test_workspace_isolation.py` corre en la suite completa).
