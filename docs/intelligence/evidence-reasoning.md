# Evidence Reasoning

Fase 6 — razonamiento sobre hechos: qué permiten concluir los hechos.

Antes, Zent hacía `retrieve → generate → verify` y podía encontrar la
documentación correcta y aun así concluir mal, porque empezaba a redactar antes
de reconstruir el escenario. Ahora, para preguntas complejas:

```
UNDERSTAND → COMPILE COMPANY CONTEXT → DETERMINE REQUIRED REASONING
→ PLAN WHAT MUST BE PROVEN → STRUCTURE THE SCENARIO → COLLECT MISSING EVIDENCE
→ RECONSTRUCT STATE → TEST ALTERNATIVE EXPLANATIONS → VERIFY INFERENCES
→ ANSWERABILITY → GENERATE → CLAIM VERIFY
```

## Responsabilidades (no mezclar)

| Capa | Responde |
| --- | --- |
| Company Intelligence | qué es la empresa (entidades, procesos, mappings, autoridad) |
| Memory | qué aprendió Zent operando |
| Judgment Fabric (JEV) | qué conviene hacer ahora |
| **Evidence Reasoning** | **qué permiten concluir los hechos** |

Company Intelligence **no se redescubre**: el contexto se compila y se consume.
Memory es señal de estrategia, nunca prueba de un hecho actual.

## Piezas

`src/core/domain/reasoning.py` — tipos puros.

- `ReasoningShape` (eje ortogonal al intent): `SIMPLE_LOOKUP`, `MULTI_EVIDENCE`,
  `STATE_TRANSITION`, `TEMPORAL_SEQUENCE`, `CONSISTENCY_CHECK`, `CAUSAL_ANALYSIS`,
  `DIAGNOSTIC`, `HYPOTHESIS_TEST`, `COMPARATIVE_REASONING`, `GRAPH_REASONING`.
- `ReasoningPlan` con `question_to_prove` operacional (no una conclusión),
  operaciones por forma, condiciones de completitud y `ResearchBudgets`.
- `StructuredScenario` / `ScenarioEvent` / `MissingRequirement`.
- `Fact` (`SUPPORTED|CONFIRMED|CONTRADICTED|UNRESOLVED`), `Timeline`,
  `StateTransitionSet` + `TransitionLink`, `HypothesisSet`, `InferenceRecord`,
  `AnalysisCompletion`, `AnswerBlueprint`, `ReasoningWorkspace`.

`src/intelligence/reasoning/` — el motor.

| Módulo | Rol |
| --- | --- |
| `classifier.py` | forma de razonamiento determinista; JEV sólo en banda incierta con preguntas atómicas |
| `scenario.py` | parser + resolución de schemas (§17); **nunca inventa layouts** |
| `sequence.py` | timeline con tres órdenes + transiciones con regla por eslabón |
| `assessment.py` | hipótesis (incluida la del usuario), autoridad de fuente, verificación de inferencias, gate de completitud |
| `coordinator.py` | `EvidenceReasoningEngine`, operaciones por forma, adquisición por requisito, blueprint, traza pública |
| `metrics.py` | métricas `zent_reasoning_*` (fail-soft) |
| `wiring.py` | composition root: Company Context, retrieval, autoridad, memoria, discovery |

## Reglas que el motor garantiza

- **Nothing invented**: registros de ancho fijo sin layout conocido producen
  `RECORD_LAYOUT_REQUIRED` / `SEQUENCE_FIELD_POSITION_REQUIRED`; el ítem queda
  en `unparsed_items` y el análisis no concluye.
- **DISCOVERED ≠ CONFIRMED**: una relación `DISCOVERED` informa hipótesis; sólo
  `CONFIRMED`/`AUTO_CONFIRMED` funciona como premisa firme.
- **La autoridad del tenant desempata**: con evidencia en conflicto gana el
  nivel configurado (`AUTHORITATIVE > PRIMARY > SECONDARY > INFORMATIONAL >
  UNTRUSTED`). Sin autoridad configurada el conflicto se declara, no se resuelve
  por score vectorial ni por "lo que dijo el LLM".
- **Tres órdenes**: `original`, `effective`, `logical`; el criterio usado se
  registra y la cronología no probada por fechas se declara como limitación.
- **UNKNOWN se queda UNKNOWN**: no se rellena un estado con inferencia libre.
- **La hipótesis del usuario no se asume cierta**: se representa, se prueba
  (support / reject / unresolved) y puede quedar sin resolver.
- **Verificación de inferencias**: premisas correctas con conclusión que no se
  sigue de ninguna regla da `UNSUPPORTED` — el caso que la verificación de
  claims no detecta.
- **El runtime no escribe el grafo**: emite candidatos con provenance y Company
  Discovery decide el ciclo `DISCOVER → SUPPORT → SUGGEST → VALIDATE → CONFIRM`.
- **Sin chain-of-thought**: workspace, trazas y memoria guardan referencias,
  veredictos y límites.

## Integración

- **Answerability** (`src/intelligence/answerability.py`): `evaluate(..., reasoning=...)`
  aplica `apply_reasoning_signals`, que degrada a `CONTEXT_MISSING` con los
  reason codes `ANALYSIS_INCOMPLETE`, `SCHEMA_REQUIRED`, `STATE_UNRESOLVED`,
  `HYPOTHESIS_UNRESOLVED`, `INFERENCE_UNSUPPORTED`, `TIMELINE_INCOMPLETE`,
  `GRAPH_RELATION_UNCONFIRMED`. No se agregaron estados nuevos.
- **AgentRuntime** (`src/agents/runtime/reasoning_step.py`): regla 8 del prompt
  consciente de la forma (simple conserva la regla actual; complejo exige
  análisis completo o abstención explícita), Company Context compilado
  automáticamente si el caller no lo pasa (lo explícito manda y no se recompila),
  workspace acotado en `_FINALIZE`, y el termination gate queda retenido
  mientras el análisis esté incompleto.
- **Company** (`CompanyContextCompiler` / `CompanyAskService`): el contexto
  entra compilado; las formas de grafo delegan en Company Ask.
- **Analytical** (`AnalyticalReasoningEngine`): se reutiliza como
  `AnalyticalStrategy` para `CAUSAL_ANALYSIS` y `DIAGNOSTIC`; no hay un segundo
  motor que duplique su trabajo.
- **Memoria**: al cerrar un razonamiento complejo se registra un evento
  operativo (forma, completitud, rondas, hipótesis, contexto usado, costo,
  latencia).

## Fast path

`SIMPLE_LOOKUP` no entra al motor: no hay plan, workspace, hipótesis ni
retrieval extra. La métrica `zent_reasoning_activation_total` frente a
`zent_reasoning_requests_total` da la tasa de activación, es decir, qué
porcentaje de preguntas necesitó razonamiento de verdad.

## Rollout

`RAG_EVIDENCE_REASONING_MODE` ∈ `off | shadow | on | canary`.

- `off`: comportamiento legacy.
- `shadow`: ejecuta y mide (comparación de answerability, forma, completitud,
  latencia) pero la respuesta la produce el camino legacy.
- `on`: el razonamiento controla los requests complejos.
- `canary`: porcentaje configurable (`RAG_EVIDENCE_REASONING_CANARY_PERCENT`).

Presupuestos: `RAG_EVIDENCE_REASONING_MAX_EVENTS`, `_MAX_HYPOTHESES`,
`_MAX_REQUIREMENTS`, `_MAX_RETRIEVAL_ROUNDS`, `_MAX_ANALYSIS_STEPS`, más
`ResearchBudgets` y `LoopGuard`.

## Ver flujo

Pasos observables (sin razonamiento privado): `reasoning_classification`,
`company_context`, `reasoning_plan`, `scenario_parse`, `state_reconstruction`,
`hypothesis_test`, `analysis_completion`.

## Golden scenarios (tests)

`tests/test_evidence_reasoning.py` (fixtures sintéticos, sin datos privados ni
hardcodeo de dominio):

1. `STATE_TRANSITION` con renumeración → hipótesis "falta un registro"
   **REJECTED**, alternativa de renumeración **SUPPORTED**.
2. Golden negativo con regla de cierre obligatorio → **SUPPORTED** (evita
   "renumerar siempre significa que no falta cierre").
3. Registros de ancho fijo sin schema → parse parcial y `CONTEXT_MISSING` con
   `SCHEMA_REQUIRED`; no se inventan posiciones.
4. Grafo `CONFIRMED` como evidencia fuerte; `DISCOVERED` no prueba solo.
5. Documento interno contra especificación autoritativa → gana la autoritativa.
6. Regla vigente hasta 2025 vs regla 2026 con escenario 2025 → usa la histórica.
7. Genéricos: `OPEN/UPDATE/CLOSE`, ticket `REOPENED`, finanzas
   `TRANSACTION/REVERSAL/REPLACEMENT`, workflow con `RETRY` (retry ≠ hueco).
8. Inferencias: premisas respaldadas sin regla que las conecte →
   `INFERENCE_UNSUPPORTED`.

`tests/test_agent_reasoning_integration.py`: early answer retenido, respuesta
permitida con análisis completo y con presupuesto agotado, termination retenido,
workspace en `_FINALIZE`, Company Context automático vs explícito y fast path de
preguntas simples.

## Límites conocidos

- El parser reconoce registros delimitados y bloques de secuencia; los formatos
  de ancho fijo requieren schema declarado (por diseño).
- La resolución de acciones/reglas depende del léxico bilingüe declarado en
  `assessment.rule_signals`; un dominio nuevo puede necesitar sus marcadores.
- La síntesis en prosa de la respuesta final sigue siendo del generador; el
  motor aporta hechos, veredictos, límites y blueprint.
