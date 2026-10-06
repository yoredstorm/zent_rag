# Premise Closure — retrieval dirigido por premisas faltantes

Estado: activo (runtime determinista). Versión del motor: `premise-closure-1`.

## Problema

Cuando el Requirement Graph sabe exactamente qué premisas faltan
(`definition:symbol:X`, `matching:positional`, `matching:literal`,
`length_policy`), una segunda búsqueda semántica de la pregunta original
repite la misma distribución y no cierra nada. El caso observado:

- pregunta ejecutable (`&&&F` / `ABCFGEGE`) terminaba en abstención;
- la fuente SÍ contenía las reglas;
- JEV pedía `retrieve_more`, pero la ronda repetía la búsqueda genérica.

## Diagnóstico sobre el documento real (auditoría)

Script: `python -m src.scripts.premise_closure_audit --org <uuid> --document <uuid>`.

Hallazgos sobre `Data Application For Record 2 – Category Control`
(documento `e57bab1f-…`, 46 objetos `business_rule`):

| Pregunta de auditoría | Resultado |
| --- | --- |
| ¿Se crearon CanonicalRules? | Sí, pero la definición de `&` y el matching general no quedaron ejecutables |
| ¿Persistidas? | Sí (`knowledge_canonical_objects`, `kind='business_rule'`) |
| ¿SUPPORTED? | 12 de 30 con semántica; la mayoría son ejemplos |
| ¿executable? | 1 sola (un ejemplo mal clasificado como CONSTRAINT) |
| ¿provenance? | Sí (`metadata.rule_provenance`) |
| ¿Rule Lane las encuentra? | **No** al inicio: consultaba `kind='BUSINESS_RULE'` contra datos `business_rule` → 0 candidatas SIEMPRE |
| ¿Compilación o retrieval? | Ambos: retrieval roto + gap de compilación en símbolo/matching/length general |

Clasificación explícita que emite la auditoría:

- `COMPILATION_MISSING` — la evidencia existe, ninguna regla representa la premisa.
- `RULE_INDEX_MISSING` — filas de regla sin representación recuperable.
- `RULE_RETRIEVAL_MISS` — hay reglas persistidas, el Rule Lane devuelve 0.
- `PREMISE_LINK_MISSING` — la regla existe pero no declara la dimensión.
- `EVIDENCE_RETRIEVAL_MISS` — la evidencia necesaria no aparece en chunks.
- `PREMISE_UNSUPPORTED` — la regla existe y se encuentra, pero no es ejecutable.

## Mecanismo

```
RequirementGraph (missing_premises)
  → PremiseQueryPlanner (ontología lingüística, domain-agnostic)
  → multi-query dirigida (exacto/símbolo ANTES de dense)
  → merge sin duplicados + graph expansion + source-local
  → compilación provisional QUERY_LOCAL (mismo compilador y gates)
  → reevaluación
  → information_gain por ronda
```

Terminaciones explícitas: `SATISFIED`, `CONFLICTING`,
`NO_INFORMATION_GAIN`, `BUDGET_EXHAUSTED`, `NO_SEARCH`.

Reglas del contrato:

1. El contenido de la siguiente búsqueda sale del Requirement Graph, no de la
   pregunta original (JEV decide “necesitamos más”; Premise Closure decide
   “qué exactamente”).
2. Una ronda sin reducción medible de premisas buscables termina el loop.
3. Una premisa se cierra cuando una regla la representa (dimensión declarada),
   no cuando la evaluación deja de pedirla por silencio.
4. Si la evidencia cubre la premisa y el compilador no la representó:
   `COMPILATION_GAP` + `RULE_COMPILER_MISSED_EVIDENCE` (señal de calidad para
   backfill), nunca una respuesta inventada.
5. La compilación query-local es `PROPOSED → VERIFY contra evidencia`; se marca
   `relations["QUERY_LOCAL"]` y **nunca se persiste** como verdad global.

## Componentes

- `src/runtime/premise_closure.py` — planner, loop, gain, gaps, feedback.
- `src/runtime/premise_search.py` — Rule Index dirigido, source-local, fabric.
- `src/runtime/query_local_rules.py` — compilación provisional verificada.
- `src/runtime/deterministic_authority.py` — fase `premise_closure` entre
  grounding y decision envelope (fail-closed intacto).
- `src/runtime/rule_retrieval.py` — `RULE_OBJECT_KIND` y consulta
  case-insensitive del kind persistido.

## Observabilidad (“Ver flujo”)

Steps mapeados: `build`, `query_semantics`, `rule_retrieval`,
`rule_evaluation`, `requirement_graph`, `premise_closure`, `grounding`,
`deterministic_operation`, `derived_claim`, `answer_state`,
`decision_envelope`, `derived_guard`, `finalization`.

El step `premise_closure` publica: `termination`, `rounds`,
`information_gain`, `missing_before`, `missing_after`, `compilation_gaps`,
`rules_added`, `evidence_added` y `detail` con las consultas por ronda.
Los tipos sin mapping se preservan con `unmapped=true` (sección técnica).

Contadores de evidencia en `DerivedPreparationResult.evidence_counters`:
`retrieved`, `unique`, `used_for_reasoning`, `used_for_decision`. Una
evidencia que cierra una premisa cuenta como `used_for_reasoning` aunque la
respuesta final no la cite.

## Build info

`src/runtime/build_info.py` expone `git_sha_display`
(`BUILD_SHA_UNAVAILABLE` cuando no hay SHA) y las versiones de cada motor:
rule retrieval, rule compiler, rule evaluation, grounding, decision envelope,
derived guard, deterministic authority, query semantics, premise closure y
query-local rules.

## Tests

- `tests/test_premise_closure.py` — planner, loop, gain, gaps, expansión.
- `tests/test_premise_closure_real_fixture.py` — fixture RAW del manual,
  pipeline real, 50 paráfrasis, fuente distribuida, 100 páginas de ruido y
  cross-domain.
- `tests/test_premise_closure_authority.py` — cableado en
  `prepare_derived_authority` y fail-closed.
- `tests/test_rule_retrieval_kind.py` — regresión del kind del Rule Lane.
- `tests/test_deterministic_observability.py` — build info y mapping.
- `portal/src/pages/chat/executionStory.premiseClosure.test.ts` — historia UI.

Fixture: `tests/fixtures/documents/record2_fare_class_ampersand.txt`.
