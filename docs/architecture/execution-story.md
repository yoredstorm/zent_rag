# Execution Story — "Ver flujo" como historia auditable

Fase 7 — la traza deja de ser un visor de logs y pasa a ser la historia de cómo
Zent llegó a la respuesta.

## Principio

Dos niveles, un mismo dato:

| Nivel | Para quién | Qué muestra |
| --- | --- | --- |
| **Historia** (default) | todos, incluido admin | fases, decisiones, evidencia, hipótesis, veredictos, límites |
| **Técnico** | admin | proveedor, JEV, scores, tokens, costos, ids y traza cruda |

La telemetría no se elimina: se separa. El administrador no es excusa para
mostrar telemetría incomprensible por defecto.

## Qué nunca se muestra

Cadena de pensamiento, scratchpad, razonamiento libre del modelo. La interfaz
explica **qué pasó**, no **qué pensó el modelo**. Lo que sí se muestra:
decisiones, señales, evidencia, rutas, alternativas consideradas, veredictos,
confidence, políticas, referencias de memoria y pasos de razonamiento.

## Fases canónicas

`understanding`, `context`, `planning`, `evidence`, `reasoning`, `decision`,
`generation`, `verification`, `learning` (orden canónico en
`src/rag/flow_story.py` y `portal/src/pages/chat/executionStory.ts`).

No todas aparecen siempre: una consulta directa muestra entender, evidencia,
generación y verificación; una pregunta compleja suma contexto, plan,
razonamiento y aprendizaje.

## Contrato: FlowEvent canónico

`rag_flows.flow` sigue siendo la fuente (JSONB). `with_story()` agrega, de forma
aditiva y fail-soft:

```json
{
  "flow_version": 2,
  "events": [
    {
      "id": "step-3",
      "phase": "reasoning",
      "kind": "scenario_parse",
      "status": "ok | warn | error | skipped | pending",
      "duration_ms": 12.5,
      "summary": "clave semántica (sólo incidentes)",
      "metrics": { "scenario": { "events": 17, "unparsed": 3 } },
      "decision": { "reason_codes": [] },
      "evidence_refs": [], "memory_refs": [], "entity_refs": [],
      "technical": { "items": [] }
    }
  ]
}
```

Reglas del contrato:

- El backend entrega **semántica** (fases, tipos, estados, números, referencias).
  Nunca strings de UI: la traducción vive en el frontend.
- Un dato que no existe se omite; no se inventa un cero.
- Los campos históricos (`steps`, `sources`, `decision`, `retrieval`, …) se
  mantienen intactos para que un portal viejo siga renderizando.

## Builder y componentes

`portal/src/pages/chat/executionStory.ts` — función pura `buildExecutionStory(flow)`:

eventos crudos → eventos canónicos → agrupación por fase → resumen, narrativa,
incidentes, breakdown y bloque técnico. Acá vive toda la traducción; los
componentes sólo componen:

- `story/StorySummary.tsx` — tarjeta superior + distribución del tiempo.
- `story/ExecutionTimeline.tsx` — timeline vertical con divulgación progresiva.
- `story/StoryCards.tsx` — decisiones, evidencia, fuentes, SQL, generación,
  juicio previo (`jev_pack`).
- `story/ReasoningStory.tsx` — plan, escenario, cadena de estados, hipótesis,
  inferencia y completitud del análisis.
- `story/JudgmentStory.tsx` — packs JEV (agrupados), matriz de preparación,
  impacto agregado e incertidumbre.
- `story/LearningSummary.tsx` — memoria usada / creada / reforzada / contradicha.
- `story/TechnicalTrace.tsx` — modo técnico + juicios JEV (id, versión,
  primitiva, distribución) + traza cruda.
- `pages/chat/FlowDrawer.tsx` — composición, carga de datos, memoria y replay.

## Juicio previo (JEV) en la historia

Los juicios previos al generador se publican como **packs** (`kind: jev_pack`),
uno por fase, con las preguntas, su decisión y su **efecto**:

```
JEV · Antes de generar
14 preguntas · 1 llamada · 36 ms
¿El análisis está completo?         Sí/No   Sí   97%
¿Falta información crítica?         Sí/No   No   96%
Efecto: evitó el modelo caro
```

- El evento vive en la fase donde ocurrió (preparación → `planning`, evidencia →
  `evidence`, reconstrucción → `reasoning`, antes de generar → `decision`,
  verificación → `verification`), así que la timeline sigue siendo "qué pasó,
  dónde pasó".
- La matriz de preparación (`metrics.readiness`) y los efectos agregados viajan
  en el mismo evento; los componentes sólo traducen.
- La tarjeta superior resume el impacto desde `flow.jev_preflight.summary`
  (`calls`, `judgments`, `decisions_influenced`, `uncertain_critical_judgments`,
  `llm_escalations_avoided`).
- Un juicio incierto se muestra como incierto y explica por qué el run fue más
  largo; nunca se convierte en veredicto.
- Nada de CoT: sólo ids, versiones, decisiones, números y efectos.
  Las distribuciones completas viven en el modo Técnico.

El contrato del bloque: `docs/architecture/jev-preflight.md`.

## El backend es la única fuente de verdad

El portal **renderiza**; no reconstruye el run. Antes, el Agent Playground
rearmaba el flow en el navegador (`flowFromAgentSteps`) y perdía tipos,
payloads de razonamiento, señales de JEV, tokens y verificación: la historia
mostraba "Decidió el camino → Redactó la respuesta" para un run con tools,
reasoning y gates.

Flujo único:

```
AgentRuntime → AgentRunResult → build_agent_flow() (server-side)
→ Canonical Flow v2 → with_story() → SSE done.flow → portal
→ buildExecutionStory() → render
```

- `src/runtime/agent_flow.py` es el builder canónico de agentes (steps,
  generación, verificación, tiempos, telemetría, fuentes).
- `src/rag/flow_story.py` convierte cualquier flow en eventos canónicos v2.
- `GET /api/v1/executions/{kind}/{id}/flow` normaliza `query`, `agent` y
  `workflow` bajo el mismo contrato.
- El flow se persiste con el run (`agent_runs.flow`) y viaja en el `done`.

El portal sólo cae a un builder local si el servidor **no** envió `flow`
(servidor viejo): `flowFromAgentStepsLegacy`, marcado `legacy` y sin inventar
nada.

## Unknown is not zero

| Caso | Se muestra |
| --- | --- |
| Valor no medido | se omite (no hay fila ni `0`) |
| Cero real | se muestra como 0 |
| No aplica | "No aplica" |
| No observado | "No observado" / "No disponible" |

Nunca `confidence: 0`, `score: 0` ni `tokens: 0/0` para decir "no sé". El
endpoint de dispatch ya no fabrica `confidence: 0`: la procedencia
(`explicit_target`, `agent_runtime`, `routing_decision`) viaja en
`decision.provider` y la confianza sólo aparece si existe.

## Verificación y resultado

`verification` es un conjunto de comprobaciones, no un booleano:

```
analysis_complete  ✓
inference_supported ✓
answer_gate        ✓ (approve)
grounding          ✓
overall            verified
```

- `verified` exige respaldo declarado; sin él, `partial` →
  "Verificada parcialmente" (no "Respaldada" si sólo corrió el gate).
- `blocked` con abstención → "Retenida por seguridad"; con análisis incompleto
  → "Análisis incompleto"; el resto → "Evidencia insuficiente".
- La telemetría faltante **no** marca el run como "Revisar": sólo lo hacen un
  error real, una verificación bloqueada, un fallback material, un guardrail o
  una retención.

## Telemetría (completeness, no confidence)

`flow.telemetry` declara, por dimensión (`routing`, `reasoning`,
`company_context`, `jev`, `tools`, `evidence`, `generation`, `verification`,
`memory`, `cost`, `timings`), si la señal se **observó**, **no aplica** o **no
está disponible**. No se agrega a un porcentaje: se lista.

El badge superior resume la calidad del dato: **Telemetría completa**,
**Telemetría parcial** o **Flujo histórico** (`flow_version < 2`).

## ExecutionRef

La historia y la memoria no dependen de `query_id`:

```ts
type ExecutionRef = { kind: "query" | "agent" | "workflow"; id: string };
```

- `query/{query_id}` → `rag_flows`.
- `agent/{run_id}` → `agent_runs.flow` (memoria: `/memory/runs/{run_id}/impact`).
- `workflow/{run_id}` → detalle del run (v1 honesto; memoria "no disponible").

Sin integración disponible la memoria dice "no disponible", nunca 0. Con la
consulta respondida y buckets vacíos muestra los ceros reales.

## Paridad de agentes

El AgentRuntime emite hoy: `llm`, `tool_routing`, `tool_call`, `tool_filter`,
`termination_gate`, `answer_gate`, `answer_revision`, `router_fallback`,
`reasoning_incomplete`, `guardrail`, `error`, `final`, `context`, `memory` y los
steps de razonamiento (`reasoning_classification`, `company_context`,
`reasoning_plan`, `scenario_parse`, `state_reconstruction`, `timeline`,
`hypothesis_test`, `inference_verification`, `analysis_completion`).

Reglas:

- Los payloads estructurados viajan tal cual (`plan`, `scenario`,
  `transitions`, `hypotheses`, `inference`, `completion`, `meta`, `action`, …).
- Un step **sin** mapping canónico no se descarta: se emite con su `kind`
  original, fase segura (`decision`) y `technical.unmapped = true`.
- El invariante está fijado por test: todo tipo que el runtime puede emitir
  está mapeado o declarado como oculto a propósito.

Varias llamadas al modelo no se atribuyen a "redactar": la fase muestra
`N llamadas al modelo (x de razonamiento · y de respuesta)`.

## Compatibilidad histórica

Los flows sin `flow_version` se normalizan con `normalizeLegacyFlow()` a los
mismos eventos canónicos, así que las conversaciones viejas siguen mostrando su
historia (marcadas como "Flujo histórico"). Un run nuevo **nunca** lleva ese
badge: el backend siempre emite `flow_version: 2` con `events[]`.

## Traducciones (backend → humano)

- `reasoning_classification` → "Entendió qué tipo de análisis necesitaba"
- `company_context` → "Recuperó contexto empresarial"
- `reasoning_plan` → "Preparó el análisis" (con la pregunta a demostrar)
- `scenario_parse` → "Interpretó el escenario"
- `state_reconstruction` → "Reconstruyó los cambios"
- `hypothesis_test` → "Contrastó explicaciones"
- `analysis_completion` → "Verificó que el análisis estuviera completo"
- `tool_routing` → "Eligió qué herramienta usar"
- `answer_gate` → "Verificó la respuesta"

Estados: `SUPPORTED → Respaldada`, `REJECTED → Descartada` (no es un error: se
muestra en tono neutro con ✕), `UNRESOLVED → Sin resolver`.
Autoridad: `AUTHORITATIVE → Autoritativa`, `PRIMARY → Principal`,
`SECONDARY → Secundaria`, `INFORMATIONAL → Informativa`,
`UNTRUSTED → No confiable`.
Passage judge: `KEEP → Utilizada`, `DROP_IRRELEVANT → No relevante`,
`DROP_WEAK → Evidencia débil`, `FLAG_CONTRADICTION → En conflicto`,
`DROP_INJECTION → Contenido inseguro bloqueado`.

Los motivos ("Porque…", "Falta…") se traducen desde `reason_codes` del backend.
El frontend nunca fabrica una razón: si no hay señal, no se muestra.

## Accesibilidad y rendimiento

- Nunca sólo color: cada estado lleva icono, etiqueta y texto (§53).
- Divulgación progresiva: la timeline renderiza rápido; el detalle de claims,
  cuerpos de evidencia y la traza cruda se cargan al expandir.
- Drawer sin canvas de grafo; timeline vertical también en mobile.

## Backend

`src/runtime/agent_flow.py` (builder canónico de agentes),
`src/rag/flow_story.py` (eventos canónicos + steps sin mapping),
`src/agents/runtime/reasoning_step.py` (semántica del razonamiento) y
`src/api/routes/executions.py` (contrato único por tipo de ejecución).

En el camino RAG el razonamiento corre después de generar cuando
`RAG_EVIDENCE_REASONING_MODE` no está en `off`: la historia lo muestra como
análisis observado salvo que el JEV Preflight lo mueva antes del generador.

Tests: `tests/test_flow_story.py` y `tests/test_agent_flow_v2.py` fijan el
contrato del backend; `executionStory.test.ts`, `executionStory.agent.test.ts`,
`executionRef.test.ts` y `ExecutionStoryView.test.tsx` fijan la traducción y el
render.
