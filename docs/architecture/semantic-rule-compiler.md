# Semantic Rule Compiler — Document Rule Understanding

> Responsabilidad diferenciada: **Semantic Reconstruction** resuelve problemas
> estructurales (continuación de fragmentos, tablas, headers). Este compilador
> resuelve **semántica normativa**: convertir reglas expresadas en lenguaje
> natural en conocimiento estructurado, verificable y, cuando la evidencia
> alcanza, ejecutable.

## Principio fundamental

Una palabra relacionada con una propiedad **no** determina su semántica:

| Señal | Interpretación | Error que evita |
|---|---|---|
| "length", "longitud" | `length.policy = UNKNOWN` (mención) | asumir EXACT |
| "may contain more characters than" | `VALUE_MAY_BE_LONGER` (política asimétrica) | igualdad o "distinta longitud" |
| "may" | modalidad MAY | elevar a MUST |
| "unless" | excepción conservada textualmente | perder la excepción |
| "maximum of 5 días" | cantidad, no política de longitud | `length_policy=MAX_LENGTH` |
| "must not change the code" | prohibición (MUST_NOT, polaridad NEGATIVA) | normalizar a positivo |
| dos conceptos juntos | ninguna causalidad | inventar relaciones |
| ejemplo documental | evidencia ilustrativa | convertirlo en regla |

Regla de oro: **nunca convertir una señal lexical en una regla más fuerte que
la evidencia**.

## Flujo

```text
RAW DOCUMENT
  -> Document Understanding (existente)
  -> Canonical Document
  -> Semantic Units / Threads (existente)
  -> Candidate Facts / Definitions / Rules (Knowledge Compiler)
  -> Semantic Rule Compiler            <-- esta capa
       candidates -> verify -> CanonicalRule + RuleConflict
  -> Semantic Fabric / Knowledge OS
  -> Retrieval (canonical rule + supporting evidence + raw source)
  -> Grounded Reasoning
       premisas grounded + datos runtime + operación determinista
  -> Derived Result (DerivedClaim)
  -> Natural-language Answer (el LLM explica; no decide cálculos)
```

Módulos:

| Módulo | Responsabilidad |
|---|---|
| `src/core/domain/rule_semantics.py` | Vocabulario formal + clasificadores deterministas de lenguaje (ES/EN) |
| `src/knowledge/rule_compiler/candidates.py` | CandidateRule con evidencia distribuida (units/windows/threads) |
| `src/knowledge/rule_compiler/language.py` | Enunciado -> propiedades semánticas con evidencia por propiedad |
| `src/knowledge/rule_compiler/verify.py` | Gate por propiedad + conflictos entre reglas |
| `src/knowledge/rule_compiler/merge.py` | Reglas distribuidas: fusión solo compatible |
| `src/knowledge/rule_compiler/compiler.py` | Orquestador + propuestas LLM |
| `src/knowledge/rule_compiler/evaluate.py` | Ejecución determinista de CanonicalRule |
| `src/knowledge/rule_compiler/fabric.py` | Proyección a nodos/aristas del Semantic Fabric |

## Modelo

`CanonicalRule` es la regla verificada. Cada propiedad importante lleva su
propia evidencia (no un blob único):

```json
{
  "operator": "POSITIONAL_MATCH",
  "operator_evidence": ["ev_123"],
  "anchor": "START",
  "anchor_evidence": ["ev_456"],
  "length_policy": "VALUE_MAY_BE_LONGER",
  "length_policy_evidence": ["ev_789"]
}
```

En el modelo real: `properties: {name: RuleProperty(value, state, evidence[],
matched_text, missing_premises)}` más `provenance[]` con locator físico
(documento, página, sección, bloque).

### OBSERVED / INFERRED / DERIVED

- **OBSERVED**: texto explícito de la fuente (`observed.statement`).
- **INFERRED**: interpretación derivada del lenguaje (políticas, operadores).
- **DERIVED**: cómputo runtime. Vive en `DerivedClaim`, nunca en la regla.

### Familias representadas

- Comparaciones: `EQ, NE, GT, GTE, LT, LTE, BETWEEN, OUTSIDE_RANGE` (con
  left/right preservados).
- Longitud: `EXACT, VALUE_MAY_BE_LONGER, VALUE_MAY_BE_SHORTER,
  PATTERN_MAY_BE_LONGER, PATTERN_MAY_BE_SHORTER, MIN_LENGTH, MAX_LENGTH,
  RANGE, UNCONSTRAINED, UNKNOWN`.
- Matching: literal, wildcard, positional, prefix, suffix, contains,
  starts_with, ends_with, fixed_position, case sensitivity, alfabeto
  permitido/prohibido, posiciones opcionales/repetidas, separador,
  normalización.
- Lógica: `AND, OR, NOT, IMPLIES, ONLY_IF, IF_AND_ONLY_IF, UNLESS, EXCEPTION,
  DEFAULT, OVERRIDE, PRECEDENCE, FALLBACK`.
- Cantidades: mínimo, máximo, inclusivo/exclusivo, unidad, tolerancia.
- Tiempo: before, after, from/to, vigencia, expiración, duración,
  simultaneidad.
- Enumeraciones: permitidos, prohibidos, mapping code→meaning, alias.
- Fórmulas: target, expresión, operandos, unidad, redondeo, precisión.

La lista es **extensible**: `properties` es un diccionario abierto; agregar una
política nueva no exige cambiar el esquema.

## Verificación

Una regla propuesta no se vuelve canónica por existir. Cada propiedad pasa por:

1. evidencias presentes y localizables;
2. el marcador textual existe en la evidencia;
3. sin contradicción de negación en la cláusula;
4. excepciones conservadas;
5. alcance/sección;
6. unidad declarada cuando la cantidad la exige;
7. dirección preservada (asimetría);
8. inclusividad declarada (jamás asumida);
9. negación conservada en modalidad/polaridad;
10. referencias cruzadas resueltas o declaradas.

Estados: `PROPOSED | SUPPORTED | PARTIALLY_SUPPORTED | CONFLICTING |
UNSUPPORTED | UNKNOWN`.

Solo `SUPPORTED` con premisas cerradas puede ejecutarse. Una propiedad
`UNKNOWN` bloquea la ejecución y queda nombrada en `missing_premises`; el
evaluador devuelve `UNDETERMINED`, nunca un default silencioso.

## Reglas distribuidas

`build_candidates` reúne evidencia de:

- distintas líneas/párrafos/páginas/secciones (`RuleEvidence.locator`);
- definiciones y símbolos definidos antes o en otra sección
  (`matching.symbol.*`, relaciones `USES_SYMBOL`, `DEPENDS_ON`);
- excepciones alejadas por solapamiento de términos (`HAS_EXCEPTION`);
- referencias cruzadas resueltas (`REFERENCES`);
- ejemplos: evidencia ilustrativa (`corroborating`), nunca reglas.

`merge_distributed_rules` fusiona fragmentos **solo si son compatibles**
(misma dimensión con distinto valor = no se fusiona; queda para el detector de
conflictos). La fusión conserva provenance de todas las piezas y elige el tipo
dominante (una definición no vuelve no ejecutable a la regla de matching).

## Conflictos

`RuleConflict` compara por **dimensión** (mismo nombre base), no por familia
amplia: `matching.alphabet` vs `matching.operator` no es conflicto. Resolución
solo con base declarada:

1. vigencia (`effective_from`) posterior;
2. `version_label`;
3. override/precedence explícito en el enunciado;
4. prioridad numérica;
5. especificidad de alcance.

Sin base de resolución: `CONFLICTING` y **no se ejecuta ninguna alternativa**.

## Semantic Fabric

`project_rules_to_fabric` conecta `Rule` con
`DEFINES / APPLIES_TO / CONSTRAINS / DEPENDS_ON / HAS_CONDITION /
HAS_EXCEPTION / HAS_CONSEQUENCE / USES_SYMBOL / USES_UNIT / SUPPORTED_BY /
CONFLICTS_WITH / SUPERSEDES`. Nada se crea sin evidencia.

## Retrieval y ejecución

- La regla canónica se persiste en `knowledge_canonical_objects` (kind
  BUSINESS_RULE) con `semantics`, `verification_state` y `provenance` en
  `metadata` (sin migración de base).
- El retrieval puede adjuntar el payload en
  `evidence.metadata["canonical_rules"]`.
- `reason_over_evidence(..., canonical_rules=...)` prioriza la regla compilada:
  `evaluate_rule` decide con `OperationRegistry` (comparaciones, rangos, enum,
  fechas, longitudes, fórmulas) y produce `DerivedClaim` con premisas y
  evidencia. Si no hay reglas compiladas se conserva el camino histórico.

## Fallo de retrieval

`RETRIEVAL_UNAVAILABLE` es un estado operativo diferenciado: la búsqueda no
llegó a ejecutarse. No es `INSUFFICIENT_EVIDENCE` y no es `NO_MATCH`/FALSE. El
generador no responde de memoria del modelo cuando falta conocimiento del
tenant.

## Migración de `PatternSemantics.length_sensitive`

`length_sensitive: bool` mezclaba políticas. Se reemplazó por
`length_policy: LengthPolicy` (+ `length_value`, `length_upper`,
`length_boundary`). `length_sensitive` queda deprecado como propiedad y es
`True` **solo** con evidencia explícita de igualdad/fixed/exact length. Una
mención de longitud produce `UNKNOWN`, nunca `EXACT`.

## Observabilidad «Ver flujo»

`GroundedReasoningResult.to_public_dict()` expone:

- `canonical_rules_used[]`: rule_id, kind, modality, operator,
  verification_state, executable, properties con evidencia, excepciones,
  missing_premises, conflicts_with;
- `canonical_rule_flow[]`: rule_id, status, operación, resultado, checks con
  operandos, premisas usadas, evidence_refs, missing_premises.

En ingesta, el observer recibe `CANONICAL_RULE_COMPILED` por regla persistida.
Sin cadena de pensamiento: solo regla, evidencia, operación y resultado.

## Propuestas LLM

`SemanticRuleCompiler.propose_candidate` acepta structured output
(`candidate_rules`, `semantics`, `source_evidence`, `confidence`,
`ambiguities`, `missing_premises`, `reason` corto). La propuesta entra como
`extraction_method=llm_proposed`, estado `PROPOSED` y
`verification_required`; `verify_candidate` la degrada a
`UNSUPPORTED/PARTIALLY_SUPPORTED/UNKNOWN` si la evidencia no la sostiene. Nunca
se convierte en canónica en silencio.

## Pruebas

- `tests/test_rule_semantics.py`: mención vs política, asimetría, modalidad,
  negación, límites.
- `tests/test_rule_compiler.py`: 20 casos cross-domain (wildcard, longitudes,
  rangos inclusivos/exclusivos, mínimos, fechas, unless, only if, enums,
  fórmula, regla entre páginas, definición y condición separadas, excepción
  alejada, contradicciones, ejemplo que no es regla, mención sin política,
  respuesta UNDETERMINED) + proyección Fabric + propuesta LLM.
- `tests/test_rule_evaluation.py`: ejecución determinista, merge de fragmentos,
  integración con el grounded engine, `RETRIEVAL_UNAVAILABLE`.
- `tests/test_pattern_grammar.py`: migración de `length_policy`.
- `tests/test_derived_guard.py`: el LLM no invierte MATCH/NO_MATCH; estados de
  respuesta; operaciones extendidas.
- `tests/test_runtime_rule_integration.py`: retrieval de reglas por id, claim
  determinista end-to-end, guard sobre FakeLLM, requirements, reglas OR /
  only_if / unless, conflicto → CONFLICTING_EVIDENCE, fallo → RETRIEVAL_UNAVAILABLE.
- Regresión ATPCO en `tests/test_rule_compiler.py::TestAtpcoRegression` con la
  redacción real disponible en las fuentes del repo. La lógica de producción
  **no contiene condiciones de dominio ATPCO**: el motor deriva la semántica
  del lenguaje.

# Query-time (runtime completo)

## Flujo

```text
user question
  -> query semantics (DOMAIN_CONCEPT | DOCUMENTABLE_RULE | RUNTIME_INPUT |
                      RUNTIME_PATTERN | OPERATION_REQUEST | CONSTRAINT |
                      OUTPUT_REQUEST)
  -> runtime values (nunca exigidos como ocurrencia en fuentes)
  -> rule retrieval  (CanonicalRule por canonical_rule_ids del chunk)
  -> requirement coverage (SATISFIED | MISSING | CONFLICTING | NOT_APPLICABLE)
  -> rule applicability (superseded/only_if/unless)
  -> deterministic execution (registry existente + operaciones extendidas)
  -> DerivedClaim (deterministic=True)
  -> derived guard (el generador no invierte el resultado)
  -> grounded answer (explica, cita, no reinterpreta)
```

## Rule retrieval

`src/runtime/rule_retrieval.py` carga las reglas canónicas ANTES de la
evidencia de soporte, desde `knowledge_canonical_objects.metadata.semantics` +
`rule_provenance`. `load_rules_for_evidence` es fail-soft: sin ids o sin DB
devuelve `[]` y el camino histórico queda intacto. La evidencia cruda sigue
disponible para citas, verificación y auditoría.

## Requisitos y reglas compuestas

`RuleEvaluation.requirements[]` expone el estado por premisa y
`condition_results[]` la traza estructurada (sin chain-of-thought):

```json
{
  "rule_id": "...",
  "conditions": [
    {"condition_id": "check:comparison", "result": "MATCH"},
    {"condition_id": "exception:0", "result": "NO_MATCH"}
  ],
  "operation": "COMPARISON",
  "result": "MATCH"
}
```

- `AND` (default) / `OR` (conector explícito) con ramas evaluadas.
- `unless` / `except`: condición compilada si es estructurable; si aplica →
  `NOT_APPLICABLE` (`exception_applied`); si no es evaluable → `UNDETERMINED`
  con `exception_condition` (jamás se asume que la excepción no aplica).
- `only_if`: condición falsa → `NOT_APPLICABLE`; no evaluable → `UNDETERMINED`.
- `override`/`supersede`: el perdedor queda `NOT_APPLICABLE` (`superseded_by`),
  nunca ejecuta.

## Operaciones deterministas

Registry seguro (sin `eval`) con: `ARITHMETIC`, `COMPARISON`, `BOOLEAN`,
`SET_MEMBERSHIP`, `STRING_EQUALITY`, `STRING_COMPARE`, `NUMERIC_COMPARE`,
`POSITIONAL_MATCH`, `RANGE_CHECK`, `ENUM_CHECK`, `DATE_COMPARISON`,
`DATE_RANGE`, `DATE_ARITHMETIC`, `UNIT_CONVERSION`, `FORMULA_EVALUATION`,
`BOOLEAN_RULE`, `SET_RELATION`.

## DerivedClaim y contrato de generación

`DerivedClaim` incluye `canonical_rule_ids`, `deterministic`,
`unresolved_requirements` y `conflicts`. El prompt recibe el bloque
`AUTHORITATIVE DERIVED RESULTS` con resultado, operación, inputs, reglas y
evidencia, más las instrucciones de no reinterpretar/invertir.

`src/runtime/derived_guard.py` verifica el texto final: si el borrador
contradice un claim determinista, se reemplaza por el resultado canónico
(`override`); si el claim además tiene conflictos, se marca
`INTERNAL_GROUNDING_CONFLICT` y no se elige una versión.

## Estados de respuesta (código decide)

`resolve_answer_state()` en `src/runtime/answer_gate.py`:

| Estado | Cuándo |
|---|---|
| `DERIVED_RESULT` | existe claim determinista |
| `RETRIEVAL_UNAVAILABLE` | búsqueda falló operativamente y 0 evidencia |
| `CONFLICTING_EVIDENCE` | reglas/fuentes contradictorias |
| `UNDETERMINED_RULE` | evidencia presente, premisa faltante |
| `INSUFFICIENT_EVIDENCE` | búsqueda exitosa, 0 evidencia |

El orquestador captura el fallo de retrieval (`adaptive.retrieval_failure`) y
usa este helper en el gate de no-info: no llama al generador para una respuesta
factual de dominio cuando la búsqueda no llegó a ejecutarse.

## Instrumentación de timeout

`RetrievalContext.stage_ms` transporta: `query_embedding_ms`, `vector_ms`,
`lexical_ms`, `hybrid_fusion_ms`, `exact_ms`, `entity_pin_ms`,
`parent_expansion_ms`, `rerank_ms`, `context_build_ms`, `total_ms`. El guard
de tools (`agents/tools/guards.py`) reporta la **etapa dominante** en el error
de timeout y en `meta`, en vez de solo subir el timeout. `search_knowledge`
mantiene `last_stage_ms` con el avance parcial para que un cuelgue a mitad de
camino diga dónde ocurrió.
