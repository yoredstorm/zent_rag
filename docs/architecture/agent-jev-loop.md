# Agent JEV Loop — el LLM y JEV se consultan en cada paso

> Evidence/Knowledge dan los hechos. El LLM redacta. **JEV decide el camino**,
> paso a paso, en una sola llamada por paso, y todo queda en "Ver flujo".

Antes de esto, un run de agente podía terminar con `jev: {used: false, calls: 0}`:
los ganchos existían pero venían apagados, no había re-consultas (el loop guard
bloqueaba el reintento) y el juicio no se publicaba completo en la traza.

## El ciclo

```
LLM propone (tool o respuesta)
   ↓
tool ejecuta → observación (+ cobertura: lo que la pregunta nombra y falta)
   ↓
UNA llamada JEV por paso (fase agent_step):
   needs_tool · tool · needs_more_evidence · satisfied
   ↓
el CÓDIGO compone el veredicto (next_action):
   generate_answer | retrieve_more | abstain
   ↓
retrieve_more → el runtime ejecuta la búsqueda con consulta refinada (bounded)
generate_answer → termina (con gate de respuesta si el agente usa conocimiento)
abstain → declara que no hay evidencia suficiente (no inventa)
```

El veredicto vuelve al modelo como **observación** (dato, no razonamiento
privado): qué falta, con qué consulta se volvió a buscar y qué puede afirmar.

## Rollout

| Flag | Default | Qué hace |
|---|---|---|
| `RUNTIME_AGENT_JEV_LOOP` | `on` | `off` sin juicio por paso · `shadow` juzga y registra sin actuar · `on` el veredicto manda · `canary` por porcentaje de runs |
| `RUNTIME_AGENT_JEV_LOOP_CANARY_PERCENTAGE` | `0` | porcentaje para `canary` |
| `RUNTIME_AGENT_MAX_RETRIEVAL_ROUNDS` | `2` | búsquedas extra que JEV puede pedir por run |

Override por agente: `agents.config_json.runtime.jev_loop`
(`off|shadow|on|canary`) y `runtime.answer_gate` (`on|shadow|off`).
Los flags legacy (`RUNTIME_TOOL_ROUTING_MODE`, `RUNTIME_TERMINATION_GATE`,
`DECISION_BATCH_MODE`) siguen funcionando para esa parte, pero el loop ya no
depende de ellos.

## Veredicto compuesto en código (`src/runtime/agent_step.py`)

| Situación | `next_action` | Motivo |
|---|---|---|
| JEV dice que la evidencia alcanza | `generate_answer` | `termination_satisfied` |
| Falta evidencia (o la pregunta nombra algo que la evidencia no trae) y hay presupuesto | `retrieve_more` | `evidence_gap` |
| No hay evidencia usable y no hay presupuesto | `abstain` | `no_usable_evidence` |
| Sólo falta elegir herramienta | `generate_answer` | `tool_choice_pending` |

`needs_more_evidence` viaja **siempre** con el loop, incluso en agentes de una
sola herramienta (donde el routing no aplica): sin esa pregunta no habría forma
de pedir otra ronda.

## Re-consulta dirigida

- La consulta refinada es **determinista**: entidades sin cubrir
  (`src/intelligence/response/entities.py`, ya usado por la cobertura de la
  respuesta) escritas también en su forma compacta (`cat31`, como los nombres de
  fuente del dominio) + las palabras significativas de la pregunta. Nada inventado.
- Pasa por los mismos guards que una tool del LLM (allowlist del agente, RBAC,
  rate limit, timeout, loop guard). El loop guard recibe `new_information`,
  `retry_reason` y `modified_plan`, así que una re-consulta **dirigida** se
  permite y un duplicado idéntico no dirigido se sigue bloqueando.
- Tope duro: `RUNTIME_AGENT_MAX_RETRIEVAL_ROUNDS`. Al agotarse, el veredicto es
  `abstain` (se declara la falta de evidencia en vez de responder de memoria).

## Gate de respuesta

Con el loop `on`, un agente que responde con conocimiento corre el gate de
respuesta en modo `on` (salvo override del agente): JEV puntúa respaldo,
completitud, calidad y presentación; permite **una** revisión y puede abstenerse.
En agentes puramente de tools no se activa solo (ahí la evidencia no es
documental y la config del agente manda).

El gate juzga **la misma evidencia** que vio el generador (`evidence_id`
estables, ver [evidence-first-gate.md](evidence-first-gate.md)) y compone la
acción en código:

| Situación | Acción |
|---|---|
| Sin evidencia usable | `retrieve_more` (con presupuesto) → `abstain` |
| Evidencia irrelevante a lo pedido | `retrieve_more` → `abstain` |
| Evidencia relevante y borrador sin respaldo | `retrieve_more` → `revise` |
| Respaldo ok, falta completitud o forma | `revise` (nunca abstención) |
| Claims sin respaldo | `revise` (se corrigen; no se anula la respuesta) |
| Respaldo parcial (falta una entidad) | `answer_with_limits` |
| Todo ok | `approve` |

El cierre por termination/guardrail **también** verifica (con evidencia
registrada): una respuesta sin respaldo no se entrega porque el run terminó
antes; se abstiene o se entrega con los límites declarados.

## Evidencia en "Ver flujo"

- Step `agent_step` con `questions`, `routing`, `termination`, `next_action`,
  `action_reason` y `uncovered_entities` → fase **Decisión**, con el veredicto
  rotulado ("JEV decidió: …").
- Step `jev_retrieval` con `query`, `round`, `reason` y `entities` → fase
  **Evidencia** ("Volvió a buscar: faltaba evidencia").
- Step `evidence_sufficiency` con la cobertura de entidades, `exact_entity_match`
  y la acción recomendada → fase **Evidencia**.
- `flow["evidence"]` con los fragmentos recuperados (`evidence_id`, título,
  sección, página, score, método de recuperación, `doc_index` del prompt,
  `status` USED/RETRIEVED y `cited`) y `flow["citations"]` ancladas a esos ids.
- `flow["jev_preflight"]` con los **packs** del run (mismo contrato que el RAG):
  tarjeta "Paso del agente · N preguntas · 1 llamada · Xms", con cada juicio y su
  distribución, más los veredictos aplicados.
- `coverage_gap` en el step de la tool: qué pidió la pregunta y la evidencia no
  trae (se muestra como dato en la historia).
- Métricas: `zent_agent_jev_action_total{mode,action,reason}`,
  `zent_agent_jev_retrieval_total{round,outcome}`,
  `zent_evidence_sufficiency_total{action,reason}`,
  `zent_evidence_selected_chars` y `zent_decision_judge_*` con
  `phase=agent_step` (ya no aliasado a `tool_routing`).

## Nunca

- JEV no autoriza ni ejecuta: el subconjunto de tools que propone se re-valida
  contra RBAC y grants del agente en el momento de ejecutar.
- JEV no redacta: sólo juzga; el código compone y el LLM escribe.
- Sin evidencia y sin presupuesto no se responde de memoria: se abstiene.
