# Execution Story human-first

## Estado

Diseño aprobado el 30 de septiembre de 2026.

## Objetivo

Refactorizar por completo la experiencia **Ver flujo / Execution Story** para que una persona que conoce el negocio, pero no la arquitectura interna de Zent, pueda entender cómo se produjo una respuesta.

La vista principal debe explicar, en orden:

1. qué entendió Zent;
2. qué necesitaba comprobar;
3. qué buscó;
4. qué encontró;
5. qué preguntas evaluó JEV;
6. qué decisiones cambiaron la ejecución;
7. por qué se repitió una búsqueda;
8. qué hizo cada llamada al modelo;
9. qué verificó Zent;
10. cómo llegó al resultado final.

La telemetría no se elimina. Se normaliza, se jerarquiza y se separa por audiencia.

## No objetivos

Este trabajo no cambia:

- la lógica de JEV;
- el Evidence Engine;
- Source Routing;
- Document Understanding;
- el RAG;
- el razonamiento o la respuesta del LLM;
- los gates de verificación;
- la autoridad canónica de evidencia;
- la ruta de ejecución;
- ninguna política de decisión.

`ExecutionNarrative` es una proyección presentacional. Puede agrupar, traducir, resumir y formatear estados existentes. No puede decidir si la evidencia alcanza, crear un juicio, alterar grounding, cambiar una ruta ni reinterpretar un resultado.

## Principios

1. **Human story first.** Historia responde “qué hizo Zent”.
2. **Decisions over metrics.** Las decisiones y sus consecuencias preceden scores.
3. **Impact over raw scores.** Una decisión JEV siempre explica si cambió algo.
4. **Evidence over implementation details.** Cobertura y fuentes preceden mecanismos internos.
5. **Progressive disclosure.** Cada etapa ofrece resumen, detalle humano y, finalmente, datos técnicos.
6. **Technical data is never lost.** Toda telemetría permanece accesible en Técnico.
7. **One execution, one coherent story.** Resultado, resumen, timeline y detalle consumen los mismos estados normalizados.
8. **Decision trace, not chain-of-thought.** Solo se muestran hechos estructurados y observables.

## Prohibición de chain-of-thought

La experiencia no almacena, reconstruye ni muestra:

- chain-of-thought;
- scratchpads;
- prompts internos completos;
- razonamiento privado del modelo;
- diálogos simulados entre JEV, el agente y el LLM.

Sí muestra:

- clasificación e interpretación estructurada;
- requisitos;
- preguntas y respuestas JEV registradas;
- probabilidad, certeza y alternativas observadas;
- decisiones aplicadas;
- impacto real;
- búsquedas y retries;
- evidencia y cobertura canónica;
- llamadas al modelo y su propósito observado;
- fallbacks;
- verificaciones;
- correcciones registradas;
- resultado final.

## Arquitectura elegida

### Frontera backend/frontend

El backend construye una proyección semántica `ExecutionNarrative`. El frontend traduce códigos y compone la interfaz.

```text
EvidenceState + GenerationPackage + VerificationState
+ final execution status + canonical events
                         |
                         v
                 flow_story.py
                         |
                         v
               ExecutionNarrative
                         |
                         v
               executionStory.ts
                         |
          +--------------+--------------+
          |              |              |
       Historia      Rendimiento      Técnico
```

No se enviará prosa libre generada para explicar el run. El contrato incluirá códigos semánticos, hechos, referencias y parámetros. El frontend utilizará plantillas de copy profesionales y localizables.

### Compatibilidad

- `flow_version` permanece en `2`.
- `execution_narrative` es aditivo.
- `events`, `steps` y bloques históricos permanecen intactos.
- Un frontend antiguo puede ignorar `execution_narrative`.
- Un frontend nuevo utiliza `execution_narrative` cuando existe.
- Flows históricos sin narrativa pasan por un adapter limitado y honesto.
- El adapter legacy no inventa requisitos, impacto, certeza, propósito ni causa.

### Orden temporal

Los eventos técnicos pueden seguir agrupados por fase. La narrativa causal necesita orden de ejecución.

Cada evento narrativo tendrá:

- `sequence`: ordinal estable;
- `source_event_ids`: eventos técnicos de origen;
- `caused_by_event_id`: causa observable, cuando exista;
- `decision_id`: decisión aplicada relacionada, cuando exista;
- `iteration`: número de búsqueda o llamada, cuando exista.

Sin vínculo causal registrado, la UI puede afirmar que un evento ocurrió, pero no por qué ocurrió.

## Contrato `ExecutionNarrative`

Forma conceptual:

```text
ExecutionNarrative
  schema_version
  outcome
  summary
  understanding
  requirements[]
  journey[]
  judgments[]
  applied_decisions[]
  evidence
  model_calls[]
  verification
  response_shape
  learning
  diagnostics[]
```

### `outcome`

```text
code:
  ANSWERED
  ANSWERED_WITH_LIMITS
  RETRIED_AND_ANSWERED
  ABSTAINED
  FAILED
  BLOCKED

reason_code
evidence_state
verification_state
final_status
material_fallback
answer_delivered
```

### `understanding`

```text
intent_code
task_code
observed_summary
fields[]
rules[]
references[]
examples[]
entities[]
source_event_ids[]
```

`observed_summary` solo puede proceder de metadata pública ya existente. Si no existe, el frontend compone una frase mediante `task_code` y anchors. No se llama a otro modelo para narrar el run.

### `requirements[]`

```text
id
label
kind: DOCUMENTABLE | USER_INPUT
status: FOUND | MISSING | CONFLICTING | PROVIDED | UNKNOWN
source_required
evidence_refs[]
source_event_ids[]
```

Los anchors técnicos se traducen así:

- `RULE_ANCHOR`: regla;
- `FIELD_ANCHOR`: campo;
- `EXAMPLE_VALUE`: valor del usuario que debe evaluarse;
- otros tipos desconocidos: detalle técnico solamente.

Un `EXAMPLE_VALUE` no se convierte en requisito documental.

### `journey[]`

Tipos narrativos iniciales:

- `QUERY_UNDERSTOOD`;
- `REQUIREMENTS_IDENTIFIED`;
- `KNOWLEDGE_SEARCHED`;
- `EVIDENCE_FOUND`;
- `JEV_CHECKED`;
- `JEV_CHANGED_PATH`;
- `SEARCH_RETRIED`;
- `EVIDENCE_COMPLETE`;
- `LLM_ANALYZED`;
- `ANSWER_DRAFTED`;
- `ANSWER_REVISED`;
- `ANSWER_VERIFIED`;
- `ANSWER_DELIVERED`.

Estos eventos no sustituyen los eventos técnicos. Son una proyección de ellos.

### `judgments[]`

```text
id
pack_id
phase
question_code
type: CHOICE | SCORE | NOUL
answer
probability
certainty
confidence_band
ambiguous
alternatives[]
applied_decision_id
effect_code
source_event_ids[]
```

`confidence_band` debe venir del runtime o usar exactamente la misma función y thresholds que el runtime. La capa narrativa no define thresholds alternativos. Si no existe un band canónico, se omite.

Probabilidad y certeza son conceptos distintos:

- probabilidad: probabilidad de una alternativa o resultado;
- certeza: estabilidad o claridad de la decisión.

Historia muestra el band. El porcentaje exacto y las alternativas viven dentro del detalle. Técnico muestra los valores originales.

### `applied_decisions[]`

```text
id
phase
question_id
action
decider: RULES | JEV | AGENT | LLM | EVIDENCE_ENGINE | GUARDRAIL
reason_codes[]
impact_code
affected_event_ids[]
source_event_ids[]
```

Esta es la única colección que alimenta:

- “decisiones influidas” del hero;
- resumen JEV;
- cards de preguntas;
- timeline;
- vista JEV + LLM.

No habrá contadores paralelos. `decisions_influenced` pasa a derivarse de `applied_decisions.length`.

Si una recomendación no se aplicó, no entra en `applied_decisions`. Puede aparecer como juicio observado con impacto `NO_CHANGE`.

### `evidence`

```text
complete
generation_mode
missing_documentable_evidence[]
conflicts[]
requirements[]
documents[]
document_count
passage_count
searches[]
```

Cada documento:

```text
document_key
document_id
source_id
display_name
title
passage_count
passages[]
```

Cada fragmento:

```text
evidence_id
page
section
excerpt
status
relevance
source_event_ids[]
```

### `model_calls[]`

```text
id
sequence
purpose: ANALYSIS | ANSWER | REVISION | UNKNOWN
model
provider
duration_ms
input_tokens
output_tokens
cost_usd
source_event_ids[]
```

Reglas de presentación:

- `ANALYSIS`: “Analizó la evidencia”.
- `ANSWER`: “Redactó la respuesta”.
- `REVISION`: “Revisó la respuesta”.
- `UNKNOWN`: “Procesó la respuesta”, sin inventar actividad.

Cuando la metadata histórica permite distinguir razonamiento y respuesta, el adapter puede usar los fallbacks aprobados “Analizó la evidencia” y “Redactó la respuesta”. Si ni siquiera existe orden o acción suficiente, usa `UNKNOWN`.

### `verification`

```text
overall
checks[]
primary_available
fallback_used
fallback_code
affected_outcome
corrections[]
source_event_ids[]
```

Una corrección solo aparece cuando existe un evento real de revisión, retry o cambio de respuesta.

### `diagnostics[]`

Diagnósticos presentacionales, no decisiones:

```text
code
field
raw_value
source_event_id
```

Ejemplos:

- probabilidad fuera de `0..1`;
- fuente sin display name;
- referencia a decisión inexistente;
- propósito de llamada desconocido;
- conteo histórico inconsistente.

Los diagnósticos se muestran exclusivamente en Técnico.

## `StoryOutcome`

### Precedencia

La proyección usa esta precedencia y solamente estados canónicos:

1. `ABSTAINED`: abstención explícita registrada.
2. `FAILED`: estado final de error o fallo sin respuesta entregada.
3. `BLOCKED`: guardrail, análisis incompleto o bloqueo canónico sin respuesta entregada.
4. `ANSWERED_WITH_LIMITS`: respuesta entregada con evidencia canónicamente incompleta, verificación materialmente parcial o fallback material.
5. `RETRIED_AND_ANSWERED`: retry aplicado, respuesta entregada y sin límites finales.
6. `ANSWERED`: respuesta entregada sin las condiciones anteriores.

Si falta suficiente información para clasificar, el resultado usa el estado final observable y añade diagnóstico. No inventa una causa.

### Separación entre evidencia y verificación

Evidencia y verificación son ejes distintos.

Caso obligatorio:

```text
EvidenceState.complete = true
missing_documentable_evidence = []
VerificationState = partial/warn
```

Presentación:

- evidencia: “Evidencia documental completa”;
- verificación: “Verificación parcial” o causa canónica equivalente;
- nunca: “Evidencia insuficiente”.

Un warning, fallback o estado `blocked` genérico no basta para declarar insuficiencia documental.

## Agrupación de fuentes

### Identidad documental

Clave primaria:

1. `document_id`;
2. fallback: `source_id + normalized_filename`;
3. fallback final: identificador técnico, solo en Técnico.

Nombre visible:

1. `display_name`;
2. `source_title`;
3. `document_title`;
4. `title`;
5. filename normalizado;
6. “Documento sin título”.

Un UUID nunca se usa como título en Historia.

### Identidad de fragmento

Clave primaria:

1. `evidence_id`;
2. fallback: `page + section + normalized_excerpt_hash`.

No se deduplican fragmentos diferentes solamente porque comparten filename.

Historia distingue:

- documentos;
- fragmentos.

Ejemplo: “2 documentos · 5 fragmentos”, no “5 fuentes”.

## Probabilidades y porcentajes

Habrá un único `ProbabilityDisplay` con contrato estricto:

```text
input: number en rango 0..1
output: porcentaje 0..100%
```

Ejemplo obligatorio:

```text
0.7091 = 70.9%
```

Si el valor no es finito o está fuera de rango:

- no se muestra porcentaje;
- no se clampa;
- se registra `INVALID_PROBABILITY` en diagnósticos técnicos.

Ningún componente concatena confidence, score o rerank score.

## Reflexiones observables

La experiencia toma como referencia el patrón de “reflexiones” de NotebookLM, pero solo con señales públicas reales.

La sección se llama **Cómo Zent comprobó su camino** y puede mostrar:

1. pregunta estructurada;
2. sistema que la evaluó;
3. respuesta;
4. probabilidad o certeza cuando corresponda;
5. impacto;
6. corrección aplicada;
7. nueva comprobación.

Ejemplo válido:

```text
JEV
¿Conviene buscar más evidencia?
Sí · Certeza media

Qué cambió
Zent realizó una segunda búsqueda.
```

Ejemplo inválido:

```text
JEV: Creo que tal vez deberíamos buscar más.
LLM: Estoy de acuerdo.
```

Cuando una verificación detecta un problema, la historia muestra el ciclo solamente si existen eventos que lo acreditan:

```text
Verificación detectó una afirmación sin respaldo
Zent revisó la respuesta
Verificación comprobó la versión corregida
```

## Tres niveles de profundidad

### Historia

Objetivo: explicar la ejecución en 5–6 pasos y aproximadamente 1–1.5 pantallas para una consulta normal.

Contenido:

- hero de resultado;
- interpretación;
- requisitos;
- evidencia;
- preguntas e impacto JEV;
- retries;
- llamadas al modelo por propósito;
- verificación;
- memoria/aprendizaje compacto;
- mapa opcional JEV + LLM.

No contiene:

- tokens;
- modelos o providers;
- canonical version;
- `V2_PROMOTED`;
- semantic units;
- legacy chunks;
- nombres de campos crudos;
- UUIDs;
- scores internos;
- JSON;
- telemetry matrix.

### Rendimiento

Contenido:

- tiempo wall-clock total;
- búsqueda/retrieval;
- JEV;
- análisis del modelo;
- redacción del modelo;
- verificación;
- overhead/coordinación;
- número de llamadas;
- tokens de entrada y salida;
- costo;
- solapes entre spans.

La suma de spans nunca sustituye wall-clock.

### Técnico

Contenido:

- telemetría completa;
- tipos de evento;
- IDs;
- provider y modelo;
- JEV raw values;
- probabilidades y certeza;
- scores;
- `Knowledge Representation`;
- versiones canónicas;
- requisitos internos;
- exact hits, reranker, pass A/pass B;
- payloads;
- diagnósticos.

Técnico no usa un bloque de JSON serializado como interfaz principal. Utiliza grupos, pares clave/valor y un explorador jerárquico recursivo. Los valores originales se preservan sin reinterpretación.

## Diseño de Historia

### `StoryHero`

Responde en cinco segundos:

- resultado;
- qué hizo Zent;
- fuentes;
- intervención JEV;
- tiempo;
- costo.

Ejemplo:

```text
Respuesta completada

Zent encontró la regla solicitada y respondió usando
documentación de Record 2.

Fuentes             2 documentos · 5 fragmentos
Intervención JEV    Pidió ampliar la búsqueda
Tiempo              27.5 segundos
Costo               $0.00176
```

Telemetría parcial no produce “Revisar” por sí sola.

### `UnderstandingStory`

Explica interpretación y anchors:

```text
Comprobar cómo funciona una regla de FCLAS y aplicar
&&&F al valor QNNF0SME.

Regla                 &&&F
Campo                 FCLAS
Valor que evaluaremos QNNF0SME
```

No muestra `RULE_ANCHOR`, `FIELD_ANCHOR` ni `EXAMPLE_VALUE`.

### `EvidenceJourney`

Muestra:

- requisitos documentales;
- valores aportados por el usuario;
- búsquedas en orden;
- requisitos encontrados;
- estado canónico final;
- documentos y fragmentos agrupados.

Cada búsqueda adicional explica su causa observable. Una búsqueda normal no se marca como “Requiere atención”.

### `JudgmentJourney`

Resumen:

```text
JEV hizo 4 comprobaciones.
1 influyó en la ejecución.
```

Detalle por pregunta:

- pregunta;
- respuesta;
- probabilidad, si aplica;
- certeza;
- alternativas útiles;
- impacto;
- decider, solo en detalle.

Sin decisiones aplicadas:

```text
JEV revisó el camino, pero no necesitó cambiarlo.
```

Tool choice ambiguo:

```text
JEV no vio una opción claramente superior y dejó la
decisión al agente.
```

Si el agente decidió después:

```text
El agente decidió consultar el conocimiento.
```

### JEV frente al Evidence Engine

JEV es asesor. Evidence Engine es autoridad canónica de cobertura.

Si JEV recomienda ampliar y no se ejecuta la búsqueda:

```text
JEV sugirió ampliar la búsqueda, pero el motor de evidencia
ya había encontrado todos los requisitos documentales.
```

Si se ejecuta:

```text
Zent realizó una búsqueda adicional por precaución.
Después de ella no quedaron requisitos pendientes.
```

### `ModelJourney`

Una tarjeta por propósito, no una tarjeta genérica por `llm`.

Dos llamadas:

```text
1. Analizó la evidencia
2. Redactó la respuesta
```

Tokens, modelo y costo quedan en Rendimiento/Técnico.

### `VerificationStory`

Explica:

- qué comprobaciones corrieron;
- cuáles no corrieron;
- si hubo fallback;
- si el fallback afectó el resultado;
- qué corrección ocurrió;
- estado final.

Ejemplo:

```text
La comprobación principal no estuvo disponible.
Zent utilizó una validación alternativa.

Resultado
Respuesta parcialmente verificada.
```

### `ResponseShapeCard`

Se mueve a “Cómo decidió explicarlo”, cerrado por defecto:

```text
Zent eligió una respuesta técnica, con ejemplo y citas.
```

### Memoria y aprendizaje

Con cero actividad:

```text
Memoria
No fue necesaria en esta respuesta.

Aprendizaje
Esta respuesta no generó observaciones nuevas.
```

No se muestran tarjetas grandes para ceros.

### Vista JEV + LLM

Sección opcional compacta:

```text
Pregunta
  |
Planner
  |
JEV check
  |
Knowledge search
  |
Evidence Engine
  |
JEV pidió ampliar
  |
Knowledge search #2
  |
Evidence complete
  |
LLM análisis
  |
LLM respuesta
  |
Verificación
```

Solo contiene nodos observados.

## Estados y color

Lenguaje humano:

- Completado;
- Buscó nuevamente;
- Respondió con límites;
- No pudo comprobarlo;
- Verificación parcial;
- Omitido porque no era necesario.

`WARN`, `BLOCKED` y `SKIPPED` quedan en Técnico.

Color:

- gris: información;
- accent/azul-teal: decisión o actividad;
- verde: comprobado;
- ámbar: limitación real;
- rojo: fallo o bloqueo real.

Certeza baja sin impacto no usa color de alarma.

## Componentes y reutilización

### Componentes principales

- `StoryHero`;
- `UnderstandingStory`;
- `EvidenceJourney`;
- `JudgmentJourney`;
- `ObservableReflection`;
- `ModelJourney`;
- `VerificationStory`;
- `CompactLearningStory`;
- `JevLlmJourney`;
- `PerformanceStory`;
- `TechnicalTrace`;
- `ProbabilityDisplay`.

### Evolución de componentes existentes

- `ExecutionStoryView`: conserva tabs y separación de modos.
- `ExecutionTimeline`: evoluciona a timeline causal de 5–6 pasos.
- `JudgmentStory`: alimenta preguntas JEV, reflexión e impacto.
- `ReasoningStory`: queda reservado a hechos estructurados relevantes.
- `StorySummary`: evoluciona a `StoryHero`.
- `PerformanceStory`: permanece aislado de Historia.
- `TechnicalTrace`: organiza toda la telemetría por grupos.
- `ResponseShapeCard`: expander cerrado por defecto.
- `LearningSummary`: se compacta cuando los contadores son cero.

No se crean componentes nuevos cuando uno actual puede asumir la responsabilidad sin mezclar niveles.

## Responsive y accesibilidad

El drawer actual tiene 440 px de ancho máximo. Historia se diseña primero para esa restricción.

Reglas:

- una columna;
- hero con facts en dos columnas y una columna en pantallas muy estrechas;
- labels y valores apilables;
- sin tablas anchas;
- sin JSON;
- sin scroll horizontal en Historia;
- timeline vertical;
- expansores accesibles;
- tabs existentes o primitiva accesible del design system;
- focus visible;
- áreas interactivas de al menos 40 px, idealmente 44 px;
- color nunca es la única señal;
- `aria-expanded` en divulgación progresiva;
- números dinámicos con `tabular-nums`.

Técnico puede ser más denso, pero sus filas deben hacer wrap y el explorador debe permitir colapsar ramas.

## Manejo de errores y degradación

### Narrativa ausente

El frontend usa el adapter legacy. Solo presenta hechos que pueda vincular a campos existentes.

### Builder narrativo falla

`with_story()` sigue siendo fail-soft:

- la respuesta no falla;
- eventos técnicos permanecen;
- Técnico informa `NARRATIVE_BUILD_FAILED`;
- Historia usa el adapter legacy.

### Metadata incompleta

- dato desconocido: se omite o se marca “No disponible”;
- cero real: se muestra como cero;
- no aplica: “No fue necesario”;
- telemetry missing: explicación neutral;
- verification affected: limitación real.

### Fuente sin nombre

Historia usa “Documento sin título”. Técnico conserva IDs.

### Causa desconocida

Se muestra el evento sin atribuir una causa.

## Plan de pruebas

### Backend

Agregar pruebas en `tests/test_flow_story.py` y, cuando corresponda, `tests/test_agent_flow_v2.py`.

Casos:

1. `EvidenceState.complete = true`, `missing_documentable_evidence = []`, verification warning: resultado no es evidencia insuficiente.
2. Cuatro passages de dos documentos: `document_count = 2`, `passage_count = 4`.
3. Dedupe por `evidence_id`.
4. Fallback de dedupe por página, sección y excerpt hash.
5. Mismo filename con fragmentos distintos no colapsa evidencia.
6. Cuatro preguntas JEV y una decisión aplicada.
7. Cuatro preguntas JEV y cero decisiones aplicadas.
8. Resumen y timeline consumen `applied_decisions.length`.
9. Retry vinculado a decisión JEV.
10. Retry sin vínculo no inventa causa.
11. Llamadas `reasoning` y `answer` producen propósitos diferentes.
12. Corrección solo con evento real de revisión.
13. Source title resuelto antes que UUID.
14. Flow legacy sin narrativa permanece válido.
15. Fallo del builder no rompe `with_story()`.

### Frontend: modelo

Agregar pruebas en `executionStory.test.ts`, `executionStory.agent.test.ts` y `executionStory.jev.test.ts`.

Casos:

1. outcome canónico y precedencia completa;
2. evidencia completa con verificación parcial;
3. documentos frente a fragmentos;
4. requirements documentables frente a input del usuario;
5. JEV probability frente a certainty;
6. tool choice 55/45 con certeza baja;
7. 0 decisiones aplicadas;
8. 1 decisión aplicada compartida por todos los resúmenes;
9. dos model calls con purpose;
10. `0.7091` produce `70.9%`;
11. valor fuera de rango produce diagnóstico, no porcentaje;
12. telemetry partial sin impacto no cambia headline;
13. legacy flow no inventa datos.

### Frontend: render

Agregar o actualizar pruebas en `ExecutionStoryView.test.tsx` y `JudgmentStory.test.tsx`.

Casos:

1. Historia no contiene `V2_PROMOTED`, `canonical_version`, `semantic units` ni `legacy chunks`;
2. Técnico sí contiene esos valores;
3. Historia muestra solo dos source cards para cuatro passages de dos documentos;
4. “JEV hizo 4 comprobaciones”;
5. “1 influyó en la ejecución”;
6. cero impacto muestra “no necesitó cambiarlo”;
7. retry explica el impacto;
8. dos llamadas no aparecen como dos tarjetas “LLM”;
9. memoria y aprendizaje cero ocupan una línea cada uno;
10. Response Shape está cerrado por defecto;
11. no aparece JSON serializado en Historia;
12. reflection no simula diálogo;
13. estado incierto sin impacto no aparece como warning.

### Responsive y visual

Playwright verificará:

- drawer a 440 px;
- viewport móvil de 390 px;
- ausencia de overflow horizontal en Historia;
- hero legible;
- expanders utilizables por teclado;
- estados dark y light;
- console y page errors en cero.

### Verificación general

- `pytest` de suites backend afectadas;
- `npm run typecheck`;
- `npm run lint`;
- `npm run test`;
- `npm run build`;
- Playwright focalizado.

## Criterios de aceptación

Una persona de negocio puede responder rápidamente:

- qué entendió Zent;
- qué necesitaba demostrar;
- qué encontró;
- qué preguntó JEV;
- qué decidió JEV;
- si cambió algo;
- por qué buscó nuevamente;
- qué hizo el LLM;
- si la evidencia quedó completa;
- si la respuesta se verificó;
- cuánto tardó.

Una persona desarrolladora puede abrir Técnico y ver toda la telemetría original, organizada sin perder campos.

La misma ejecución nunca presenta resultados contradictorios entre hero, timeline, JEV, evidencia y verificación.

## Alcance de implementación

Archivos principales que deben auditarse y refactorizarse:

- `src/rag/flow_story.py`;
- `src/runtime/agent_flow.py`;
- `portal/src/pages/chat/executionStory.ts`;
- `portal/src/pages/chat/story/ExecutionStoryView.tsx`;
- `portal/src/pages/chat/story/ExecutionTimeline.tsx`;
- `portal/src/pages/chat/story/JudgmentStory.tsx`;
- `portal/src/pages/chat/story/ReasoningStory.tsx`;
- `portal/src/pages/chat/story/StorySummary.tsx`;
- `portal/src/pages/chat/story/PerformanceStory.tsx`;
- `portal/src/pages/chat/story/TechnicalTrace.tsx`;
- tests correspondientes.

Cambios en `agent_flow.py` solo pueden enriquecer metadata presentacional existente. No pueden modificar decisiones, routes, prompts, grounding ni ejecución.
