# JEV Preflight — juicio barato antes de pagar generación cara

Fase 8 — JEV deja de ser una capa que reacciona y pasa a ser **el motor de
juicio previo** del run.

## Principio

```
DETERMINISTIC FACTS
→ COMPANY CONTEXT
→ EVIDENCE
→ JEV JUDGMENT
→ CODE COMPOSES DECISION
→ ONLY IF NECESSARY
→ EXPENSIVE LLM
→ JEV / DETERMINISTIC VERIFICATION
→ ANSWER
```

El objetivo **no** es hacer más llamadas a JEV. Es hacer las preguntas
correctas, en batch, en el momento correcto, antes de pagar razonamiento caro.

### Qué JEV no es

JEV no es fuente de hechos, ni motor de autorización, ni ejecutor, ni generador
de SQL, ni reemplazo de Evidence, ni garantía absoluta de verdad. Los hechos
vienen de Company Intelligence, Knowledge, SQL, tools, schemas, reglas,
evidence y memoria validada. **JEV juzga esas señales. El código decide.**

| Capa | Responsabilidad |
| --- | --- |
| Facts | establecen la realidad |
| Company Intelligence | da contexto |
| Memory | aporta experiencia |
| **JEV** | **juzga** |
| **Código** | **decide** |
| LLM | genera sólo cuando hace falta |
| Verification | comprueba el resultado |

## Las tres primitivas

| Primitiva | Cuándo | Ejemplos |
| --- | --- | --- |
| **Choice** | conjunto cerrado de alternativas | `reasoning_shape`, `preferred_capability`, `next_action`, `generation_tier` |
| **Score** | variables ordinales | `analysis_complexity`, `scenario_completeness`, `evidence_strength`, `answer_readiness`, `risk_of_wrong_answer` |
| **Noul** | afirmaciones binarias | `analysis_complete`, `critical_fact_missing`, `inference_supported`, `expensive_llm_needed`, `timeline_coherent` |

Reglas no negociables:

- **Noul no tiene confidence separado.** `0.0` es un NO fuerte, `1.0` un YES
  fuerte, `0.5` incertidumbre. `noul` **nunca** se convierte en default ni en
  respuesta positiva por fallback (`safe_noul` conserva `0.0` y `False`).
  `certainty = |noul - 0.5| * 2` es una derivada, no una confianza.
- **Choice y Score conservan su distribución.** Se guarda el ganador **y** el
  runner-up, el margen, la entropía normalizada y la vecindad de niveles: la
  alternativa segunda con peso material es información, no ruido.
- **Score no se usa para yes/no** y **Noul no se usa para ordinales**.

## Un pack, una llamada

Una fase no hace 8 requests: registra **un pack** con todas las preguntas
independientes del **mismo estado** y paga una sola llamada.

```
PRE_GENERATION STATE
┌────────────────────────────────────┐
│ JEV QUESTION PACK                  │
│  Choice next_action                │
│  Choice generation_tier            │
│  Score  answer_readiness           │
│  Score  evidence_strength          │
│  Score  risk_of_wrong_answer       │
│  Noul   analysis_complete          │
│  Noul   answerable_from_evidence   │
│  Noul   critical_fact_missing      │
│  Noul   critical_conflict_resolved │
│  Noul   inference_supported        │
│  Noul   expensive_llm_needed       │
│  Noul   needs_complex_model        │
└────────────────────────────────────┘
→ ONE SYSTEM ONE CALL
```

Cada pregunta consume tokens: el límite por pack es `MAX_QUESTIONS_PER_PACK`
(16) y las preguntas condicionales se deciden **antes** de enviar el pack
(`applicable_when`, por ejemplo `needs_structured_data` sólo si `sql_enabled`).

## Fases

Fases de batching existentes (`src/decision/batch.py`): `PRE_RETRIEVAL`,
`POST_RETRIEVAL`, `POST_GENERATION`, `AGENT_STEP`.

Fases del preflight (mismo motor, mismo cache request-scoped):

| Fase | Cuándo | Qué pregunta |
| --- | --- | --- |
| `PRE_REASONING` | antes de retrieval/LLM caro | forma del análisis, familia de fuente, complejidad, necesidades materiales |
| `POST_RETRIEVAL` | después de recuperar evidencia | evidencia suficiente, faltantes críticos, ronda adicional |
| `POST_RECONSTRUCTION` | después de escenario/timeline/transiciones | completitud, coherencia, hipótesis (por candidato), inferencia |
| `PRE_GENERATION` | **antes del generador** | ¿puedo responder? ¿qué falta? ¿hace falta LLM y de qué nivel? |
| `POST_GENERATION` | después del draft | grounding, claims y verificación de la respuesta |
| `AGENT_STEP` | por paso de agente | tool routing + termination |

Las preguntas que dependen de estado futuro **no** viven en el pack anterior
(§45 del diseño): el motivo de revisión, por ejemplo, se **compone en código** a
partir de los juicios ya emitidos, no se pregunta.

## El código compone la decisión

Ninguna respuesta de JEV se toma como decisión final:

```
Choice reasoning_shape   STATE_TRANSITION 0.92
Noul   needs_timeline    0.96
Noul   needs_state      0.98
Noul   simple_lookup     0.04
↓
CÓDIGO: shape=STATE_TRANSITION, timeline_required=true,
        state_reconstruction=true, fast_path=false
```

Nunca se pide a otro LLM que interprete las respuestas de JEV.

### Política de escalado (`LLMEscalationPolicy`)

El generador caro corre cuando se cumplen las condiciones del gate:

```
answerable_from_current_evidence == YES
analysis_complete                == YES
critical_fact_missing            == NO
critical_conflict_unresolved     == NO
inference_supported              == YES
next_action                      == generate_answer
```

pero con **dos señales, nunca una sola**: si JEV dice "no está listo" y el
código (answerability, evidencia, análisis) ya vio que todo está bien, se
registra el desacuerdo (`conflicts: ["jev_only_signal"]`) y **no** se cambia la
ejecución. Si el código no tiene ninguna señal disponible, bloquear exige un
juicio **concluyente y múltiple** (≥2 condiciones insatisfechas, sin
incertidumbre y con confianza ≥ `no_signal_min_confidence`); un solo cruce de
umbral nunca detiene la generación.

Acciones posibles: `generate_answer`, `retrieve_more`, `reconstruct_more`,
`ask_user`, `abstain`, `deterministic_answer`. Tiers:
`deterministic | small | standard | reasoning`.

Ante `retrieve_more` / `reconstruct_more` con presupuesto disponible se ejecuta
**una** ronda extra de retrieval (respetando `max_retrieval_attempts`) y el
estado se re-juzga: el prompt se arma después, con el contexto ya ampliado.

### Ambigüedad y umbrales

- **Choice ambiguo** (`0.47` vs `0.45`): no se trata como claro. Se marca
  `ambiguous`, se combinan estrategias (por ejemplo `state_transition` +
  `temporal_sequence` ⇒ también hace falta timeline) y se registra la
  incertidumbre.
- **Umbrales centralizados** en `JudgmentConfidencePolicy` (por pregunta, fase
  o riesgo). Nada de números dispersos por módulo.
- **Noul de tres vías** YES / NO / UNCERTAIN con bandas calibrables por
  pregunta y por riesgo.
- La incertidumbre **afecta**: acción, ronda de retrieval, escalado de LLM,
  abstención y la matriz de preparación. No se ignora ni se disfraza.

### Matriz de preparación (`PreLLMReadiness`)

Calculada en código, siempre: `evidence`, `scenario`, `state`, `hypothesis`,
`inference`, `conflicts`, `answerability`, `llm`. Cada fila declara su `source`
(`jev` o `deterministic`) y su estado (`ok | warn | blocked | unknown`). Se habla
de preparación, soporte y confianza — **nunca** de "100% certeza" o "correcto
garantizado": JEV sigue siendo probabilístico.

### Costo

Integrado con wallet/budget sin degradar seguridad: el presupuesto sólo baja el
tier cuando el juicio ya lo permitía (`needs_complex_reasoning_model == NO`) y
nunca cuando el riesgo de responder mal es material. Sin baseline real **no se
calcula costo evitado**.

## Registro y versionado de preguntas

`src/decision/registry.py` es el catálogo central: `id`, fase, tipo,
instrucciones, criterios, `ui_label`, riesgo, `threshold_key`, `applicable_when`
y **versión**. Cada juicio registra `question_version`, así una pregunta
reformulada no se mezcla con su historia.

El Learning Engine puede señalar que una pregunta está mal calibrada y proponer
una versión candidata; la promoción es explícita (shadow, golden set,
comparación, aprobación humana). **Nunca mutación automática.**

## Rollout

`RAG_JEV_PREFLIGHT_MODE` ∈ `off | shadow | on | canary` (default `off`).

| Modo | Qué hace |
| --- | --- |
| `off` | sin juicio previo: comportamiento anterior |
| `shadow` | JEV decide qué **haría**; la ejecución legacy manda; se registra el diff |
| `on` | la decisión compuesta controla la generación |
| `canary` | `on` para `RAG_JEV_PREFLIGHT_CANARY_PERCENTAGE` de requests |

En `canary`, los requests fuera del porcentaje **no** cambian su ejecución pero
sí se observan (quedan como `shadow` en la historia y en el reporte): el canary
no degrada ni el juicio ni la comparación.

Flags relacionados: `RAG_JEV_PREFLIGHT_ENFORCE` (observar sin aplicar en modo
`on`), `_STRICT_THRESHOLDS`, `_NEXT_ACTION_CHOICE`,
`_ALLOW_DETERMINISTIC_ANSWER`, `_ALLOW_SMALL_TIER`, `_EXTRA_RETRIEVAL`,
`_REASONING_FIRST`.

En `on`/`canary` con `_REASONING_FIRST=true` el razonamiento (Evidence
Reasoning) corre **antes** de generar: el juicio ve el escenario reconstruido y
la historia lo muestra como control real de la respuesta, no como análisis
observado.

## Qué se registra

Eventos canónicos (`jev_batch_completed` conceptual): fase, modelo, preguntas
con su decisión y efecto, latencia, tokens y costo.

```json
{
  "phase": "pre_generation",
  "model": "jev-latest",
  "questions": [
    {"id": "analysis_complete", "type": "noul", "noul": 0.97, "decision": "yes",
     "effect": "generation_allowed"},
    {"id": "next_action", "type": "choice", "choice": "generate_answer",
     "confidence": 0.95, "probabilities": {"generate_answer": 0.95}}
  ],
  "latency_ms": 41.2,
  "cost_usd": 0.0004
}
```

Nunca se registra razonamiento privado: sólo id, versión, decisiones, números y
efectos. Los eventos `jev_batch_started` / `jev_question_answered` no se
persisten por request (volumen); el batch completado lleva las respuestas.

## Ver flujo

La historia muestra el juicio previo como **juicios previos**, no como "JEV
intervino":

```
JEV · Antes de generar
14 preguntas · 1 llamada · 36 ms

¿El análisis está completo?           Sí/No    Sí      97%
¿Falta información crítica?           Sí/No    No      96%
¿Hace falta razonamiento avanzado?    Sí/No    No      92%
Efecto: evitó el modelo caro

Preparación antes de generar
Evidencia Listo 94% · Escenario Listo 91% · Conflictos Bloqueado
```

Y la tarjeta superior resume el impacto:

```
Juicio previo (JEV)
4 llamadas agrupadas · 26 juicios · 3 decisiones influidas
0 juicios críticos inciertos · Generación cara evitada: 1
```

Reglas de la UI: cada juicio declara su **efecto** cuando cambió algo
(`→ se detuvo retrieval`, `→ se usó el modelo pequeño`); un juicio incierto se
muestra como incierto (⚠) y explica por qué el run fue más largo; los ids,
versiones y distribuciones completas viven en el modo Técnico.

## Control Center

`GET /api/v1/platform/decision/preflight` devuelve KPIs del juicio previo:
juicios, llamadas agrupadas, preguntas por llamada, latencia media, costo,
escalados evitados, juicios inciertos, decisiones influidas, embudo de escalado
y utilidad por pregunta (preguntada / incierta / con efecto). La sección
**JEV Effectiveness** del Decision Engine los muestra.

El embudo de escalado sólo cuenta requests que llegaron al gate: sin baseline no
se publica "costo evitado".

## Métricas

`zent_decision_preflight_total{mode,phase,outcome}`,
`zent_decision_preflight_questions_total{phase,type}`,
`zent_decision_preflight_escalation_total{mode,action,tier}`,
`zent_decision_preflight_avoided_total{reason}`,
`zent_decision_preflight_uncertain_total{phase}`.

## Código

| Módulo | Rol |
| --- | --- |
| `src/decision/distributions.py` | lectura de Choice/Score/Noul con distribución y ambigüedad |
| `src/decision/registry.py` | catálogo versionado de preguntas |
| `src/decision/confidence.py` | `JudgmentConfidencePolicy` (umbrales por pregunta/fase/riesgo) |
| `src/decision/preflight.py` | packs, composición en código, `LLMEscalationPolicy`, `PreLLMReadiness`, traza |
| `src/decision/preflight_report.py` | observaciones y reporte de efectividad |
| `src/rag/preflight_hook.py` | frontera fina con el RAG path (estado acotado + decisión) |
| `src/rag/flow_story.py` | eventos canónicos del juicio para "Ver flujo" |

## Golden tests

`tests/test_jev_preflight.py`:

1. **Simple** (`§57`): una consulta directa no paga packs complejos.
2. **State transition** (`§58`): el gate habilita generar con `next_action ==
   generate_answer`.
3. **Sin schema** (`§59`): análisis incompleto + faltante crítica ⇒ no se invoca
   el modelo caro para adivinar.
4. **Choice de baja confianza** (`§60`): no se elige a ciegas.
5. **Noul 0.0** (`§61`): se mantiene como NO fuerte.
6. **Modelo caro evitado** (`§62`): tier barato.
7. **Modelo caro requerido** (`§63`): se aprueba el tier de razonamiento.

Portal: `portal/src/pages/chat/executionStory.jev.test.ts` (builder) y
`portal/src/pages/chat/story/JudgmentStory.test.tsx` (render).

## Límites conocidos

- El embudo de escalado cuenta los requests que llegaron al gate (no todos los
  requests del tenant): no se extrapola a "costo evitado" sin baseline.
- El gate vive en el camino RAG. El AgentRuntime conserva sus fases propias
  (`AGENT_STEP`, `ANSWER_GATE`) y todavía no evalúa el pack
  `PRE_GENERATION` por paso.
- `POST_RETRIEVAL` y `POST_GENERATION` siguen viajando en los packs del motor
  adaptativo (evidence gate, passage judge, grounding y claims) y se muestran en
  la historia a partir de las respuestas públicas que ya persistían.
- El tier sólo cambia de modelo si hay candidato configurado
  (`DECISION_FALLBACK_MODEL` / `GATEWAY_CHEAP_MODEL` /
  `DECISION_COMPLEX_MODEL` / `GATEWAY_QUALITY_MODEL`) y el tenant no fijó
  `llm_model_override`: JEV no inventa ids ni pisa una decisión explícita.
- La calibración de umbrales por pregunta necesita datos: el reporte de utilidad
  por pregunta es el insumo, la promoción de versiones es humana.
