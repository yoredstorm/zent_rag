# Turn intent — la capa conversacional del turno

Documento de la corrección de la regresión «hola como estas»: con un agente que
tiene `search_knowledge`, un saludo terminaba en `INSUFFICIENT_ANSWER`.

## 1. Causa raíz

El sistema confundía dos preguntas distintas:

```
«¿necesito conocimiento para responder?»   -> necesidad de evidencia
«¿puedo responder?»                        -> permiso de responder
```

El turno se enrutaba al pipeline documental por defecto y el **Answer Gate**
juzgaba el borrador contra evidencia inexistente. El detector determinista
(`_GREETING_RE`) sólo reconocía saludos anclados («hola», «gracias»); en cuanto
el mensaje tenía algo más («hola como estas») dejaba de ser conversacional y el
gate documental lo anulaba.

## 2. Qué es (y qué no es)

Es una **señal**, no un route: qué está haciendo el usuario en este turno, con
qué confianza y si el turno necesita evidencia externa. La política compone el
route en código; JEV no ejecuta nada. El generador sigue redactando.

No es un motor de sentimiento ni un segundo sistema de routing: reutiliza el
Decision Engine, la fase `PRE_RETRIEVAL` y el batching existente.

Intenciones (vocabulario funcional):

```
knowledge_question · social_conversation · greeting · gratitude · farewell
complaint · capability_question · action_request · contextual_followup
clarification · ambiguous
```

## 3. Reglas primero, JEV para la ambigüedad

| Caso | Quién decide | Ejemplo |
|---|---|---|
| El mensaje ES el acto | regla (confianza alta) | `hola`, `gracias`, `chau` |
| Entidad/verbo de conocimiento | regla | `buenas, qué significa byte 105?` |
| Acción explícita | regla | `ejecuta el proceso X` |
| Queja sin pregunta factual | regla | `esto no sirve` |
| Capacidad del agente | regla | `qué puedes hacer?` |
| Referencia sin contexto | regla | `eso?` (→ `clarification`) |
| Mixto/ambiguo | **JEV** | `hola como estas`, `gracias, pero no entendí` |

De la respuesta Choice de JEV se conserva **la distribución completa**
(`choice`, `confidence`, `probabilities`). Las reglas publican confianza, no una
distribución inventada.

## 4. Una señal, no un route

La política mira la distribución, no sólo el `choice`:

```
knowledge_prob = P(knowledge_question)
action_prob    = P(action_request)
conv_mass      = P(greeting) + P(gratitude) + P(farewell) + P(social)
```

- `action_prob >= RUNTIME_TURN_INTENT_ACTION_FLOOR` → `tool`.
- `needs_external_evidence` (JEV) o `knowledge_prob >= KNOWLEDGE_FLOOR` → `knowledge`.
- `capability_question` → `direct` (configuración del agente, no documentos).
- `conv_mass >= CONVERSATIONAL_FLOOR` o `direct` con confianza suficiente → `direct`.
- `contextual_followup` → `context` (social) o `knowledge` (factual).
- distribución plana (`confidence < AMBIGUOUS_FLOOR`) → `clarify` (o `context` si hay turno previo); **nunca** un fallo.

Así, `{"greeting": 0.18, "knowledge_question": 0.78}` termina en `knowledge`:
la intención secundaria material no se borra.

## 5. `needs_external_evidence`

Decisión explícita y auditable:

| Turno | needs_external_evidence | Fuente |
|---|---|---|
| greeting / gratitude / farewell / social | no | regla |
| complaint | no, salvo que la queja contenga una pregunta factual | regla + JEV |
| capability_question / clarification | no (lee configuración) | regla |
| contextual_followup | sí si pide un dato; no si es social | regla/JEV |
| knowledge_question / action_request | sí | regla/JEV |

El Noul de JEV puede subirlo a sí (conservador) pero no puede apagar una señal
material de conocimiento.

## 6. Qué cambia en ejecución

Con `direct` + `needs_external_evidence = false`:

- no hay retrieval (ni embedding, ni Qdrant, ni reranker, ni selector);
- no se emite `evidence_sufficiency` en fallo: la fase **no aplica**;
- el Answer Gate documental se registra como `verdict: not_applicable`;
- el agente no ve herramientas en el prompt (no las necesita) y se responde con
  el mismo generador (tier `fast` si hay `RUNTIME_TURN_FAST_MODEL`);
- `action_request` y `knowledge_question` siguen el camino normal.

Capacidad: la respuesta usa la **configuración real** del agente (nombre,
propósito, herramientas, fuentes). No es conocimiento de negocio y no se busca
en documentos.

UNKNOWN != FAILURE: lo que no se ejecutó se publica como `not_applicable`, no
como `0`/`false`/`failed`.

## 7. Dónde vive

| Pieza | Archivo |
|---|---|
| Vocabulario, reglas, política, JEV | `src/runtime/turn_intent.py` |
| Preguntas JEV de la fase | `build_turn_intent_questions()` + `src/decision/batch.py` (`PRE_RETRIEVAL`) |
| Plan (RAG) | `src/rag/adaptive/planner.py` + campos del `AdaptivePlan` |
| Runtime de agentes | `src/agents/runtime/agent_runtime.py` (`conversation_intent`, `turn_route`) |
| Orquestador RAG | `src/agents/runtime/orchestrator.py` (salta inteligencia/preflight/gate documental) |
| Métricas | `zent_turn_intent_total`, `zent_turn_retrieval_skipped_total`, `zent_turn_intent_latency_seconds` |

## 8. Configuración

Ver `.env.example`:

| Variable | Default | Qué hace |
|---|---|---|
| `RAG_RUNTIME_TURN_INTENT` | `on` | `off` comportamiento previo · `rules` sin JEV · `on` reglas + JEV |
| `RAG_RUNTIME_TURN_INTENT_RULES_CONFIDENCE` | `0.80` | Reglas ciertas no pagan JEV |
| `RAG_RUNTIME_TURN_INTENT_KNOWLEDGE_FLOOR` | `0.30` | Intención material secundaria |
| `RAG_RUNTIME_TURN_INTENT_ACTION_FLOOR` | `0.35` | Route TOOL |
| `RAG_RUNTIME_TURN_INTENT_CONVERSATIONAL_FLOOR` | `0.60` | Respuesta directa |
| `RAG_RUNTIME_TURN_INTENT_AMBIGUOUS_FLOOR` | `0.45` | Distribución plana |
| `RAG_RUNTIME_TURN_FAST_MODEL` | vacío | Modelo barato para turnos conversacionales |

## 9. Tests

`tests/test_turn_intent.py` (reglas, JEV, política, planner, cache) y
`tests/test_conversational_turn.py` (runtime: saludo sin retrieval ni gate,
queja directa, capacidad desde configuración, mixto con conocimiento que sí
busca fuentes, y conocimiento sin evidencia que sigue siendo documental).
