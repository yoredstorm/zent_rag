# ZENT — Baseline de rendimiento del CI/CD

Fecha de medición: 2026-11-01 (UTC).
Repositorio: `yoredstorm/zent_rag`.
Alcance: workflow `CI` (`.github/workflows/ci.yml`) y su cadena de evidencia/certificación.

> Documento de línea base. No declara mejoras: las mejoras se miden en
> `docs/ci-optimization-results.md` después de ejecutar el pipeline optimizado.

## 1. Método y evidencia

Se usaron exclusivamente datos de GitHub Actions y de los artifacts JUnit del
repositorio:

| Fuente | Uso |
|---|---|
| Run `#456` (id `40465714085`, SHA `db52ebc`, push, 2026-10-27) | Línea base monolítica: un solo job `test`. Es la ejecución de ~50 min solicitada. |
| Run `#497` (id `41274066260`, SHA `1bbe4b4`, push, 2026-11-01) | Línea base actual con 4 shards. Es la ejecución #497 solicitada. |
| Runs `#498`, `#495`, `#487`, `#480` | Variabilidad reciente del mismo diseño. |
| Artifacts de `#497`: `junit-ci`, `junit-ci-shard-1..4`, `junit-certification` | Conteos y duración real por test; 6.016 testcases en la suite principal y 41 en certificación. |
| Logs de `#497` | Totales de pytest por shard, algoritmo de split, tiempos de E2E. |
| `.test_durations` (5.936 entradas antes de esta fase) | Distribución histórica usada por `pytest-split`. |
| `gh api .../branches/master/protection` | Checks realmente obligatorios en `master`. |

Aclaración importante sobre la premisa: **#497 no duró ~50 minutos; duró
15,10 minutos**. La ejecución de ~50 minutos es **#456 (53,02 min)**, anterior a
la introducción de shards. Ambas se usan como antes/después parcial.

## 2. Duración total y runner-minutes

GitHub factura por job y redondea hacia arriba al minuto. “Runner-minutes” de la
tabla es esa suma facturable; “suma de jobs” es la duración real acumulada.

| Run | Diseño | Wall-clock | Suma de jobs | Runner-minutes facturables |
|---|---|---:|---:|---:|
| `#456` | 1 job `test` (suite completa + invariantes + certificación) | **53,02 min** | 62,83 min | **69** |
| `#497` | 4 shards + certificación y E2E en paralelo | **15,10 min** | 72,03 min | **83** |
| `#498` | 4 shards | 13,78 min | — | — |
| `#495` | 4 shards | 13,25 min | — | — |
| `#487` | 4 shards | 13,98 min | — | — |
| `#480` | 4 shards | 16,70 min | — | — |

Lectura: el sharding redujo el wall-clock un 71,5 % (53,02 → 15,10 min) a cambio
de +20,3 % de runner-minutes (69 → 83). El costo extra es preparación redundante
de 4 runners (contenedores, DB, dependencias), no trabajo de tests.

Trabajo real de tests en `#497`: la suma de tiempos JUnit es **2.389,8 s (39,8
min)**; la suma de los pasos `Run tests` es **2.508,5 s (41,8 min)**; la
diferencia (118,7 s) es colección, fixtures de sesión y teardown.

## 3. Ranking de jobs y pasos

### 3.1 Jobs de `#497` (duración real)

| Job | Duración | Runner-min facturables | ¿Ruta crítica? |
|---|---:|---:|---|
| `test (1/4)` | 13,27 min | 14 | **Sí** |
| `test (2/4)` | 12,02 min | 13 | No |
| `test (3/4)` | 11,93 min | 12 | No |
| `portal-e2e` | 10,47 min | 11 | No (pero close) |
| `test (4/4)` | 8,67 min | 9 | No |
| `certification` | 7,03 min | 8 | No |
| `portal` | 5,13 min | 6 | No |
| `build` | 1,43 min | 2 | **Sí, al final** |
| `pip-audit` | 0,93 min | 1 | No |
| `sdk-node` | 0,28 min | 1 | No |
| `lint` | 0,22 min | 1 | No |
| `sdk-python` | 0,18 min | 1 | No |
| `test-evidence` | 0,17 min | 1 | **Sí** |
| `kustomize` | 0,13 min | 1 | No |
| `secrets-scan` | 0,12 min | 1 | No |
| `test` (gate) | 0,05 min | 1 | **Sí** |

### 3.2 Pasos más lentos de `#497`

| # | Paso | Job | Duración |
|---:|---|---|---:|
| 1 | `Run tests (shard 1/4)` | `test (1/4)` | 11,85 min |
| 2 | `Run tests (shard 2/4)` | `test (2/4)` | 11,33 min |
| 3 | `Run tests (shard 3/4)` | `test (3/4)` | 11,12 min |
| 4 | `Run E2E (smoke + axe)` | `portal-e2e` | 8,53 min |
| 5 | `Run tests (shard 4/4)` | `test (4/4)` | 7,87 min |
| 6 | `Certification — Gold Workflow` | `certification` | 6,35 min |
| 7 | `Run npm run test` | `portal` | 2,78 min |
| 8 | `Portal deps + browsers` | `portal-e2e` | 0,95 min |
| 9 | `docker/build-push-action` | `build` | 0,92 min |
| 10 | `Audit prod extras (HIGH+)` | `pip-audit` | 0,83 min |
| 11 | `Run npm run lint` | `portal` | 0,77 min |
| 12 | `Run npm ci` | `portal` | 0,73 min |
| 13 | `Architecture invariants` | `test (1/4)` | 0,63 min |
| 14 | `Run npm run typecheck` | `portal` | 0,43 min |
| 15 | `Initialize containers` | cada job con services | 0,27–0,35 min |

### 3.3 Preparación, dependencias y servicios

| Operación | Duración observada | Comentario |
|---|---:|---|
| `Set up job` | 0,02 min | Runner ya asignado. |
| Cola hasta el primer job | ~0,05 min | Run creado 04:41:32; jobs a 04:41:35. |
| `Initialize containers` (Postgres/Redis/Qdrant) | 0,27–0,35 min | Se repite en cada job con `services`. |
| `actions/checkout` | 0,03–0,05 min | — |
| `actions/setup-python` | 0,00 min | Python 3.11 ya presente en el runner. |
| `Init DB schema` | 0,15–0,18 min | Incluye `apt-get update/install postgresql-client` en el diseño anterior. |
| `Seed dev key` | 0,00 min | — |
| `Install deps (uv sync --frozen)` | 0,05–0,08 min | `Prepared 155 packages in 2.31s`, `Installed 155 packages in 315ms`. Caché uv no aporta. |
| `Apply Alembic migrations` | 0,07 min | — |
| `npm ci` (portal) | 0,73 min | `setup-node` ya cachea npm. |
| `npx playwright install --with-deps chromium` | 0,95 min | Descarga de Chromium + shell headless + dependencias apt. |
| `Merge shard JUnit` | <0,01 min | Script Python; no es cuello de botella. |

## 4. Ruta crítica del DAG actual

```
runner start
  └─ Initialize containers (0,30)
      └─ checkout + setup-python (0,05)
          └─ Init DB schema (0,18)
              └─ deps + alembic (0,12)
                  └─ Architecture invariants (0,63)
                      └─ Run tests shard 1 (11,85)   ← cuello de botella
                          └─ upload JUnit (0,02)
                              └─ test-evidence (0,17)
                                  └─ gate test (0,05)
                                      └─ build + SBOM (1,43)
```

Total: ~15,1 min.

Trabajos que corren en paralelo y **no** contribuyen a la duración total
mientras el shard 1 sea el máximo: shards 2–4, `certification`, `portal`,
`portal-e2e`, `pip-audit`, `lint`, `secrets-scan`, `sdk-python`, `sdk-node`,
`kustomize`. `build` sí está en la ruta crítica porque `needs: [lint, test,
sdk-python, sdk-node, portal]` lo obliga a esperar al gate, aunque la imagen no
depende de ningún artefacto de tests.

## 5. Balance de los 4 shards actuales

Algoritmo efectivo: `pytest-split 0.11.0` con el default
`duration_based_chunks`. Ese algoritmo recorre los tests en el orden de
colección y corta cuando el acumulado supera `total / splits`; **no reordena ni
empaqueta por duración**. Con un `.test_durations` sesgado, los bloques quedan
desbalanceados.

| Shard | Tests | Passed | Skipped | Tiempo JUnit | Paso `Run tests` | Estimado por split | Desvío |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2.302 | 2.294 | 8 | 680,3 s | 707,2 s (11,85 min) | 642,66 s | **+10,0 %** |
| 2 | 973 | 973 | 0 | 640,3 s | 672,4 s (11,33 min) | 643,98 s | +4,4 % |
| 3 | 2.016 | 2.012 | 4 | 629,5 s | 662,4 s (11,12 min) | 642,97 s | +3,0 % |
| 4 | 725 | 725 | 0 | 439,7 s | 466,6 s (7,87 min) | 640,13 s | **−27,1 %** |
| **Total** | **6.016** | **6.004** | **12** | **2.389,8 s** | **2.508,6 s** | **2.569,7 s** | — |

Desequilibrio actual: `max/min = 707,2 / 466,6 = 1,52`; spread = 240,6 s.
El shard 4 termina 3,98 min antes que el shard 1 y sus runners quedan ociosos.

### 5.1 Por qué `.test_durations` está sesgado

El archivo se generó desde un JUnit de suite monolítica. En ese diseño los
tests del final de la colección corrían con la base de datos más “sucia” y más
grande; sus duraciones quedaron sobreestimadas para un shard que arranca con
una DB limpia. Ejemplos medidos (registrado vs real en `#497`):

| Test | Registrado | Real | Delta |
|---|---:|---:|---:|
| `tests/test_workflow_published_snapshot.py::test_concurrent_patches_are_monotonic` | 15,1 s | 8,5 s | +6,6 s |
| `tests/test_tenant_purge.py::test_tenant_purge_removes_everything_without_collateral_damage` | 18,0 s | 12,5 s | +5,5 s |
| `tests/test_workflow_event_identity.py::test_hundred_concurrent_same_key_one_instance` | 12,2 s | 7,1 s | +5,0 s |
| `tests/test_p18_5_workspace_authorization.py::test_run_detail_is_scoped_to_workspace` | 0,4 s | 4,5 s | −4,1 s |
| `tests/test_p18_3_evidence_api.py::test_evidence_endpoint_walks_all_rows_without_ties_or_nulls_loss` | 0,4 s | 4,4 s | −4,0 s |

La suma registrada (2.569,8 s) es solo 7,5 % mayor que la real (2.389,8 s), pero
el error se concentra en el bloque final: por eso el shard 4 se desvía −27 %.

### 5.2 Comparación de algoritmos y cantidad de shards

Se simuló el reparto con los 6.016 nodeids reales y las duraciones JUnit de
`#497` (datos refresh). `least_duration` es el algoritmo de bin-packing de
`pytest-split`: ordena por duración descendente y asigna al shard con menor
suma.

| Diseño | Shards | Tests por shard | Tiempo estimado por shard | Spread | Runner-min de tests (aprox.) |
|---|---:|---|---:|---:|---:|
| `duration_based_chunks` (actual) | 4 | 2.302 / 973 / 2.016 / 725 | 11,85 / 11,33 / 11,12 / 7,87 min (real) | 3,98 min | 45,9 |
| `least_duration` + duraciones refresh | 4 | 1.510 / 1.502 / 1.502 / 1.502 | 9,96 min cada uno | ~0 s | 44–46 |
| `least_duration` + duraciones refresh | 6 | 1.009 / 1.000 / 1.001 / 1.002 / 1.002 / 1.002 | 6,64 min cada uno | ~0 s | 52–55 |
| `least_duration` + duraciones refresh | 8 | ~750 cada uno | 4,98 min cada uno | ~0 s | 62–66 |

Con el `.test_durations` **sin refresh**, `least_duration` a 6 shards también
mejora el desbalance (predicción 6,41–6,75 min reales por shard, spread 0,34
min) porque mezcla tests de todo el archivo en lugar de cortar bloques
contiguos. El refresh reduce el spread a ~0.

Costo/beneficio: 4→6 shards baja el shard más lento de ~10,0 a ~6,6 min
(−34 %) con un aumento de runner-minutes de tests de ~7 min. 6→8 shards baja
otro ~1,7 min pero agrega ~10–12 runner-minutes. La recomendación inicial es
**6 shards**; 8 queda como modo “latencia primero”.

## 6. Pruebas más costosas

Top 30 por tiempo JUnit real (`#497`). La suma de los 30 es **436,8 s (18,3 %
del total)**; los top 10 son 212,7 s (8,9 %) y los top 50 son 605,8 s (25,4 %).
No hay unas pocas pruebas que expliquen la mayor parte del tiempo: es una cola
larga de tests de integración.

| # | s | Test |
|---:|---:|---|
| 1 | 46,8 | `tests.test_ops_center::test_escalation_policy_fires_once` |
| 2 | 27,0 | `tests.test_production_consistency.TestHundredRunConsistency::test_decision_is_identical_under_perturbation` |
| 3 | 26,4 | `tests.test_fail_closed_authority.TestHundredRunConsistency::test_mixed_perturbation_never_flips_decision` |
| 4 | 21,8 | `tests.test_self_purge::test_self_purge_wipes_org_and_keeps_identity` |
| 5 | 16,6 | `tests.test_tabular_ingestion_engine::test_excel_incremental_resync_skips_and_updates` |
| 6 | 16,4 | `tests.test_knowledge_questions.TestQuestionsApi::test_questions_flow_and_isolation` |
| 7 | 15,0 | `tests.test_knowledge_questions.TestQuestionGenerator::test_generates_enum_variant_and_tax_questions` |
| 8 | 14,3 | `tests.test_knowledge_questions.TestQuestionGenerator::test_field_conflict_generates_ambiguity_question` |
| 9 | 14,3 | `tests.test_knowledge_questions.TestValidationEngine::test_skip_and_defer_do_not_apply_knowledge` |
| 10 | 14,3 | `tests.test_knowledge_questions.TestValidationEngine::test_enum_answer_updates_catalog_and_lexicon` |
| 11 | 14,2 | `tests.test_knowledge_questions.TestValidationEngine::test_tax_answer_creates_approved_business_rule` |
| 12 | 14,1 | `tests.test_knowledge_questions.TestAwaitingValidationLifecycle::test_run_waits_then_completes_after_answers` |
| 13 | 13,1 | `tests.test_relationship_intelligence.TestKnowledgeGraphApi::test_graph_endpoints_and_tenant_isolation` |
| 14 | 12,5 | `tests.test_tenant_purge::test_tenant_purge_removes_everything_without_collateral_damage` |
| 15 | 11,5 | `tests.test_platform_tenant_actions::test_platform_tenant_actions_end_to_end` |
| 16 | 11,5 | `tests.test_knowledge_llm_analysis.TestOrchestratorLLMStage::test_llm_stage_enriches_catalog_and_run` |
| 17 | 11,0 | `tests.test_knowledge_learning.TestLearningRunLifecycle::test_full_run_persists_steps_events_and_score` |
| 18 | 11,0 | `tests.test_tabular_ingestion_engine::test_chunking_policy_change_triggers_full_reindex` |
| 19 | 10,9 | `tests.test_relationship_intelligence.TestKnowledgeGraph::test_graph_nodes_edges_with_evidence_and_filters` |
| 20 | 10,8 | `tests.test_platform_tenant_actions::test_platform_tenant_delete_requires_permission` |
| 21 | 10,7 | `tests.test_knowledge_llm_analysis.TestOrchestratorLLMStage::test_llm_failure_does_not_break_run` |
| 22 | 10,6 | `tests.test_knowledge_learning.TestScoreService::test_score_breakdown_and_gate_without_evaluation` |
| 23 | 10,3 | `tests.test_sources_sql_exposure::test_table_preview_and_sql_endpoints` |
| 24 | 10,3 | `tests.test_knowledge_learning.TestLearningRunLifecycle::test_sse_replay_emits_durable_events` |
| 25 | 10,3 | `tests.test_relationship_intelligence.TestKnowledgeGraph::test_gaps_detect_unmapped_table_and_pending_relationship` |
| 26 | 10,3 | `tests.test_knowledge_evaluation.TestEvaluationStage::test_stage_runs_with_fake_orchestrator` |
| 27 | 10,2 | `tests.test_relationship_intelligence.TestKnowledgeGraph::test_learned_entities_cards` |
| 28 | 10,2 | `tests.test_knowledge_llm_analysis.TestLLMAnalyzer::test_provider_timeout_falls_back_and_persists_failed` |
| 29 | 10,2 | `tests.test_relationship_intelligence.TestRelationshipAnalyzerApply::test_apply_enriches_fk_and_adds_llm_hypothesis` |
| 30 | 10,2 | `tests.test_knowledge_llm_analysis.TestLLMAnalyzer::test_invalid_json_persisted_as_failed` |

Análisis de fixtures/servicios:

- Son tests de integración reales contra PostgreSQL/Qdrant/Redis; el costo está
  en la fase `call` (motores completos, SQL, workflows durables), no en
  `setup`. Medición local representativa de
  `test_knowledge_questions::test_generates_enum_variant_and_tax_questions`:
  `68,54 s call` vs `0,85 s setup`.
- En los 30 archivos más lentos solo hay **un `asyncio.sleep`**: `test_ops_center.py`
  línea 131, `1,1 s`, y existe porque el test exige `mttr_seconds >= 1.0`.
  Se reemplazó por un backdate determinista de `detected_at` (ver Fase 2).
- No hay timeouts artificiales reducidos: el `--timeout=300` es un guard
  anti-cuelgue, no una espera.
- `PostgresCatalogStore.ensure_tables()` se invoca 75 veces (14 CREATE + 22
  ALTER); aun así el `setup` medido es <1 s. Cachearlo a nivel de proceso es
  posible, pero el beneficio es marginal frente al costo real de integración.
- Reutilizar fixtures de sesión para estos tests no es seguro: cada test crea
  organizaciones/entidades y valida aislamiento; compartir estado ocultaría
  contaminación.

## 7. Duplicidades

| Duplicidad | Evidencia | Costo |
|---|---|---|
| Invariantes arquitectónicos ejecutados dos veces en el shard 1 | Los 407 tests de `junit-invariants.xml` también aparecen en `junit-tests-shard-1.xml`; 34 archivos, todos sus tests son invariantes (0 tests fuera de la lista). | Paso de invariantes 0,63 min + 19,3 s de tiempo JUnit re-ejecutado + colección. |
| Tests entre shards | 0 IDs duplicados entre los 4 XML de shard; unión = 6.016 = merged. | Ninguno. |
| Certificación vs suite principal | `pytest tests/` excluye `tests/certification/workflows`; 41 tests de certificación no aparecen en la suite principal. | Ninguno; es intencional. |
| Nightly vs CI | Nightly corre la suite completa y los invariantes otra vez. | Esperado: es otro workflow, no compite con el run de PR. |

La duplicidad de invariantes no solo cuesta tiempo: hace que un mismo test
pueda fallar en dos pasos con distinto contexto, y complica atribuir la
cobertura real.

## 8. Riesgos de cobertura y seguridad detectados

1. **Branch protection no cubre todos los controles.** Los checks obligatorios
   en `master` son: `secrets-scan`, `lint`, `test`, `sdk-python`, `sdk-node`,
   `portal`, `kustomize`, `build`. `pip-audit` y `portal-e2e` **no** son
   required. Además `build` no depende de ellos. Un PR con `pip-audit` o E2E en
   rojo puede mergearse si los 8 checks requeridos pasan. Esto es un hueco de
   release gate, no solo de latencia.
2. **`test` solo validaba tests.** El gate `test` actual verifica shards,
   certificación y evidencia; no verifica lint, pip-audit, secrets, SDKs,
   portal, E2E, kustomize, build ni SBOM. Los required checks individuales
   cubren algunos, pero no todos.
3. **Evidencia JUnit no estricta.** `merge_junit_shards.py` omitía XML inválidos
   con un warning y aceptaba cualquier cantidad de shards; `junit-ci` se subía
   con `if-no-files-found: ignore`. Un run exitoso con evidencia parcial podía
   parecer válido para `fetch_ci_evidence.py`.
4. **E2E con cobertura parcial.** De 36 tests E2E, 25 ejecutan y 11 se omiten
   por flags (`E2E_APPROVAL`, `E2E_DOCK`, `E2E_EFFECTS`, `E2E_MODES`,
   `E2E_VISUAL`, `E2E_WAIT`, `E2E_KNOWLEDGE_BASELINE`). Los flujos durables,
   pagos, idempotencia y tenant isolation sí están cubiertos por los 41 tests
   de certificación Python; no se deben confundir ambas coberturas.
5. **Paralelismo E2E inseguro dentro de un job.** Todos los specs comparten
   `demo@zenttech.com`, la organización demo y entidades con nombre fijo
   (`E2E Smoke Agent`, `e2e-smoke-key`). Subir `workers` a 2 en el mismo job
   genera carreras de datos y rate-limit. La parallelización segura requiere
   DB/servicios por shard (jobs separados), no más workers.
6. **`build` en la ruta crítica sin necesidad.** La imagen se construye después
   del gate aunque no consume ningún artefacto de tests; se pueden solapar sin
   publicar (`push: false`).
7. **Caché ausente en Playwright.** `~/.cache/ms-playwright` se descarga en
   cada job E2E (~0,95 min). La caché npm de `setup-node` y la caché GHA de
   Docker ya existen; la de uv no aporta (instalación de 2–3 s).

## 9. Propuesta priorizada

Impacto = reducción de wall-clock o cierre de un riesgo; complejidad = cambio
necesario; riesgo = probabilidad de romper cobertura/contratos.

| Prioridad | Cambio | Impacto estimado | Complejidad | Riesgo | Estado |
|---|---|---|---:|---|---|
| P0 | `--splitting-algorithm least_duration` + refresh de `.test_durations` desde JUnit de CI | Shard más lento 11,85 → ~6,6 min; spread ~0 | Baja | Bajo | Fase 2 |
| P0 | 6 shards en lugar de 4 | Wall de tests ~−34 %; runner-min +~7 | Baja | Bajo | Fase 2 |
| P0 | Excluir los 34 archivos de invariantes de los shards y fusionar `junit-invariants.xml` una sola vez | −0,6 min y elimina 407 duplicados | Media | Bajo | Fase 2 |
| P0 | `build` sin `needs` (paralelo, `push: false`) | −1,4 min de ruta crítica | Baja | Bajo | Fase 4 |
| P0 | Gate `test` final que exige los 12 controles, incluidos pip-audit y E2E | Cierra hueco de release | Media | Bajo | Fase 4 |
| P0 | Merge JUnit estricto (shards esperados, XML válido, sin duplicados) | Integridad de evidencia | Media | Bajo | Fase 2 |
| P1 | E2E en 2 jobs con DB/servicios propios (`--shard`) | 10,47 → ~6,5 min | Media | Medio | Fase 3 |
| P1 | Caché de browsers Playwright | −0,5 min por shard E2E | Baja | Bajo | Fase 3 |
| P1 | `docker exec psql` en vez de `apt-get install postgresql-client` | −0,15 min por job con DB | Baja | Bajo | Fase 4 |
| P2 | Paralelizar typecheck/lint/test/build del portal | ~−1 min, no crítico | Media | Bajo | No aplicado |
| P2 | 8 shards | −1,7 min vs 6; +10–12 runner-min | Baja | Bajo | No aplicado |
| P2 | 2 shards de certificación | ~−2 min, no crítico con 6 shards | Media | Medio | Descartado |
| — | `workers: 2` en Playwright mismo job | Peligroso: tenant/entidades compartidas | — | Alto | Descartado |
| — | Servidor `preview` en vez de `dev` | Medición local: 2 tests pasaron de 1,4 a 2,8 min + build | — | Medio | Descartado |
| — | Filtros de paths en `on.pull_request` | Deja required checks pendientes | — | Alto | Descartado |
| — | `continue-on-error` / `|| true` / skips | Oculta fallos | — | Alto | Prohibido |

## 10. Criterios cuantitativos de validación

Un cambio solo se acepta si, medido en al menos 3 ejecuciones comparables del
mismo SHA o de SHAs equivalentes:

1. **Wall-clock** del workflow ≤ 10,0 min en push (baseline 15,10 min); objetivo
   de estiramiento ≤ 9,0 min.
2. **Shard más lento** ≤ 7,5 min y `max/min ≤ 1,10` (baseline 11,85 min y 1,52).
3. **Runner-minutes** ≤ 95 (baseline 83; +15 % máximo) para 6 shards + 2 E2E.
4. **Conteo**: tests recolectados = tests en `junit-tests.xml` = suma de shards +
   invariantes; 0 IDs duplicados; 0 IDs perdidos.
5. **Evidencia**: `junit-ci` contiene `junit-tests.xml` y `junit-invariants.xml`
   válidos; la fusión falla si falta un shard, si un XML es inválido o si hay
   duplicados (probado con casos negativos).
6. **Gate**: un fallo en cualquiera de los 12 controles (incluidos pip-audit,
   E2E, certificación y build/SBOM) hace fallar `test`. Un estado `skipped` o
   `cancelled` nunca cuenta como éxito.
7. **Cobertura**: 41 tests de certificación siguen ejecutándose; los flujos de
   durabilidad, idempotencia, pagos, autorización y tenant isolation siguen
   verdes; los 407 invariantes siguen siendo obligatorios.
8. **E2E**: 25 passed / 11 skipped (misma semántica de flags), sin nuevos
   flaky; 0 retries adicionales por configuración.
9. **Variabilidad**: el wall-clock de 3 runs no debe variar más de ±15 %; si
   varía más, identificar el job (runner, DB, caché) antes de aprobar.

## 11. Conclusión de la fase 1

El cuello de botella no es un test individual: es la combinación de (a) un
algoritmo de split secuencial con duraciones sesgadas, (b) 4 shards
desbalanceados, (c) `build` serializado detrás del gate y (d) controles de
seguridad/E2E que no bloquean el merge. La fase 2 ataca (a) y (b); la fase 3,
E2E; la fase 4, (c) y (d). Ninguna mejora se declara lograda hasta medir los
runs del PR de prueba.
