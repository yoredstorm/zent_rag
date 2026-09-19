# Decision Engine (JEV) y Adaptive RAG

Estado: implementado, default off. Última revisión: 2026-09.

## Contexto

El chat RAG decidía SQL-first vs RAG con heurísticas locales
(`SqlIntentRouter`) y no existía una capa única que registrara *por qué* se
eligió un camino. Se incorporó TypeSafe/JEV System One como fuente de juicio
(Choice / Score / Noul) y un pipeline adaptativo de retrieval.

## Decisión

JEV **decide**; el orquestador **ejecuta**. La frontera es explícita:

- `src/core/domain/decision.py` — `RoutingDecision`, `DecisionContext`,
  `CapabilitySpec`. Sin frameworks.
- `src/core/ports/decision.py` — puerto `DecisionProvider` y
  `CapabilityRegistry`.
- `src/decision/` — proveedores (`rules`, `jev`, `llm`), composite, policy de
  autorización, trazas, métricas, settings y el hook que consume el
  orquestador.
- `src/runtime/` — capa experimental (`ZentRuntime`, executor, wallet,
  tool routing, termination gate, efficiency score, experiment lab).
- `src/rag/adaptive/` — planner de retrieval, evidence gate, fast path,
  rewrite, grounding, retry.

Reglas no negociables:

1. **JEV nunca ejecuta ni autoriza.** `authorize_decision()` recorta cualquier
   capability fuera de `available_capabilities`, de la allowlist del tenant o
   sin permiso declarado. El fallback seguro es `knowledge.answer`
   (o `respond_directly`).
2. **Shadow y muestreo son observacionales.** `composite` devuelve
   `resolved=False` con candidatos en metadata; `retrieval_hint()` no emite
   señales cuando `metadata["acting"]` es `False`.
3. **Sin JEV configurado** la cadena es rules → LLM pequeño → LLM de
   razonamiento, y con `DECISION_ROUTING_MODE=legacy` nada cambia.
4. **La autorización es por capa:** la capa de decisión valida
   disponibilidad; el rol `customer`, las blocklists SQL y el RBAC de tools
   siguen en los handlers.

## Modos

| Flag | Valores | Efecto |
|---|---|---|
| `RAG_DECISION_ROUTING_MODE` | `legacy` (default) · `shadow` · `jev` · `hybrid` | `hybrid` actúa solo en el canary |
| `RAG_JEV_SHADOW_MODE` | bool | Fuerza observación en cualquier modo |
| `RAG_RUNTIME_SHADOW_SAMPLE_RATE` | 0-1 | Muestreo de observación sobre tráfico legacy |
| `RAG_ADAPTIVE_RAG_MODE` | `off` · `shadow` · `active` · `canary` | Aplica plan de retrieval |
| `RAG_RUNTIME_TOOL_ROUTING_MODE` | `off` · `experimental` | Subconjunto de tools por JEV en agentes |
| `RAG_RUNTIME_TERMINATION_GATE` | `off` · `on` | Gate Noul tras uso de tools |

Rollout recomendado: `legacy` + `RAG_JEV_SHADOW_MODE=true` → comparar
`decision_traces` (agreement) → `hybrid` con canary 5-10 → `jev`.
Adaptive RAG se calibra aparte con `compare_legacy_vs_adaptive` sobre golden
set antes de `active`.

## Capacidades

`BUILTIN_CAPABILITIES` incluye familias que el chat no enruta por heurística
(`agent.*`, `workflow.*`, `tool.*`). Están marcadas `availability="advisory"`
en el registry y `default_capability_ids()` no las ofrece a JEV.

Se ejecutan de dos formas:

1. **Dispatcher con target explícito** (implementado): el request de
   `POST /api/v1/rag/query` puede incluir `agent_id`, `workflow_id`, `run_id`,
   `tool` y `tool_arguments`. Rules las resuelve como intención explícita
   (`metadata.explicit`, actúa en todos los modos), `authorize_decision()`
   valida y `CapabilityDispatcher` ejecuta el handler registrado por el
   composition root (`agent_runtime`, `workflow_engine`, `tool_registry`).
   Permisos por handler: `agents:execute`, `workflows:run` y el permiso de la
   tool si declara uno (`tool:query_database` y `tool:call_api` están
   sembrados para owner/admin; migraciones 119 y 122).
2. **Endpoints propios**: `POST /agents/{id}/run`, `POST /workflows/{id}/run`,
   tool registry vía agentes/MCP.

El chat sin target sigue ejecutando: `knowledge.*`, `database.*`, `llm.*`,
`respond_directly`, `document.read`.

Allowlist por tenant: `organizations.config_json["decision"]` acepta
`{"capability_allowlist": ["knowledge.answer", ...]}`; el hook lo pasa como
`tenant_policy` y `authorize_decision()` lo aplica antes de emitir señales de
routing.

## Trazas y costo

- `decision_traces` (migración 120) guarda cada decisión; `update_actual()`
  completa `actual_capability` y `agreement` después de ejecutar, en todos los
  modos, no solo shadow.
- `engine.judge()` (preguntas atómicas de adaptive/agent/workflow) no emite
  usage events por no tener contexto de tenant; se mide con
  `zent_decision_judge_total` y `zent_decision_judge_tokens_total`.
- `tenant_wallets` y `efficiency_score_weights` (migración 121) alimentan el
  Control Center; los pesos por env son solo default inicial.

## Límites conocidos

- Cada etapa (routing, plan, evidencia, grounding) usa su propia llamada
  System One. No se baten en una sola; el planner omite JEV cuando la señal
  determinística es fuerte (saludo, lexical, SQL ≥ 0.8). Plan de batcheo:
  [decision-engine-batching.md](decision-engine-batching.md).
- El dispatcher cubre `agent.*`, `workflow.*`, `tool.*` con target explícito.
  JEV no elige *cuál* agente/workflow/tool: sin target no hay ejecución.
- El rewrite de query re-embebe solo en el camino adaptativo; el rerank usa
  el texto reescrito.
- Aún no hay Alertmanager ni dashboards Grafana dedicados a estos flags.
