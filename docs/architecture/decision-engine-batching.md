# ADR: batcheo de preguntas System One

Estado: **propuesto** (no implementado). Depende de
[decision-engine.md](decision-engine.md).

## Contexto

Hoy cada etapa pide su propio `POST /v1/systemone`:

| Etapa | Preguntas | Momento | Código |
|---|---|---|---|
| Routing | capability, domain, complexity, 3 noul | Antes de retrieval | `src/decision/questions.py` |
| Plan adaptativo | modality, retrieval_strategy, needs_rewrite, needs_reasoning | Antes de retrieval | `src/rag/adaptive/questions.py` |
| Evidence gate | evidence_sufficient, on_topic, direct, quality | Post-retrieval | `src/rag/adaptive/questions.py` |
| Grounding | answer_grounded | Post-LLM | `src/rag/adaptive/questions.py` |
| Tool routing / termination | needs_tool, tool / satisfied | Por paso de agente | `src/runtime/questions.py` |

Con JEV configurado y `ADAPTIVE_RAG_MODE=active` una query puede hacer 2
llamadas pre-LLM (routing + plan) más evidence y grounding. Cada una suma
hasta `RAG_JEV_TIMEOUT_SECONDS` (8s default) de latencia y costo.

TypeSafe acepta varias preguntas en un mismo `state`; el diseño ya declara
"same state, many independent questions". El límite es nuestro: cada módulo
construye su payload por separado.

## Decisión propuesta

**Un solo `system_one` por fase de estado**, no por módulo.

1. **Fase pre-retrieval (obligatoria).** Fusionar las preguntas de routing y
   de plan adaptativo en una llamada cuando compartan estado. El estado
   fusionado ya existe: `user_request`, `classification_kind`,
   `lexical_ratio`, `sql_heuristic`, `available_capabilities`,
   `tenant_policy`, `budget`.
   - Las preguntas `needs_complex_reasoning` (routing) y `needs_reasoning`
     (plan) son la misma señal: se responde una vez.
   - El planner lee `capability`, `complexity` y nouls del payload de routing
     en vez de repetir la llamada; mantiene su fallback determinístico si el
     payload no trae la respuesta.
2. **Fase post-retrieval (evidence).** Se mantiene separada: depende de
   `evidence_preview` y no comparte estado con la fase 1.
3. **Fase post-respuesta (grounding).** Opcional y apagable por flag
   (`ADAPTIVE_RAG_GROUNDING_JEV=false`) cuando el grounding determinístico
   alcanza; no se fusiona con evidence porque el estado cambia dos veces.
4. **Agentes.** Tool routing y termination gate comparten el mismo estado
   incremental (`user_request`, `tool_results`, `available_tools`). Se baten
   en una llamada por paso solo si `RUNTIME_TOOL_ROUTING_MODE=experimental`
   y `RUNTIME_TERMINATION_GATE=on` a la vez; si no, cada flag mantiene su
   llamada aislada.

## Contrato

- Nuevo módulo `src/decision/batch.py`:
  - `build_phase_questions(phase: str, context) -> dict[str, QuestionSpec]`
    compone preguntas de los módulos existentes sin duplicar ids.
  - `DecisionEngine.judge_batch(phase, state, questions)` con presupuesto
    único de timeout: la llamada completa usa `RAG_JEV_TIMEOUT_SECONDS`, no
    uno por pregunta.
  - Resultado cacheado por `request_id` durante la request para que routing y
    planner lean el mismo payload sin segunda llamada.
- Métricas: `zent_decision_judge_total{outcome, phase}` (ya implementado en
  P0; ver [decision-engine.md](decision-engine.md)) y
  `zent_decision_judge_dedup_total` (llamadas evitadas) para medir el ahorro.
- Rollout: `RAG_DECISION_BATCH_MODE=off|shadow|on` (default `off`).
  En `shadow` se arma el payload batcheado y se compara contra la secuencia
  actual sin cambiar la ejecución; `decision_traces.payload.batch` guarda el
  diff (preguntas equivalentes, confianza y elección por pregunta).

## Consecuencias

- Menos latencia y costo por request; menos superficie de fallback parcial
  (una sola llamada puede fallar y caer al composite una vez).
- Riesgo: una pregunta mal formada en el batch degrada todas. Mitigación:
  ids estables + validación por pregunta en `_from_answers`, y sombra previa
  con diff por campo.
- El circuit breaker de `jev.system_one` pasa a contar fases, no módulos;
  revisar `JEV_CIRCUIT_FAILURE_THRESHOLD` al activar.

## No objetivos

- No batchear evidence con pre-retrieval (estados incompatibles).
- No batchear entre requests distintos.
- No eliminar los fallbacks determinísticos: rules/planner siguen resolviendo
  si el payload batcheado no trae una respuesta.
