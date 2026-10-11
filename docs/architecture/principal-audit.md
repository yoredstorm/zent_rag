# Principal Audit — TOP 10 sistémico (post programa P2–P10)

Solo hallazgos con evidencia en el repo. Ordenados por
`impacto × probabilidad × riesgo de implementación`.

## TOP 10

### 1. Contabilidad partida (P1)
- **Evidence**: `agent_runtime._record_usage_event` (result fields) vs
  `orchestrator._record_usage_event` (recálculo con embeddings +
  `cognitive_cost_usd`); JEV/embeddings/rerank no entran al `RunBudgetLedger`;
  el orquestador no tiene ledger. `log_inference` fabricaba
  `prompt=total, completion=total//2` (corregido en P5).
- **Failure mode**: sub/sobre-facturación y cortes de budget que no ven el
  gasto real (JEV caro no cuenta para `max_cost`).
- **Root cause**: dos caminos de accounting sin ledger compartido.
- **Fix**: un solo `record_llm_call`/ledger por run en ambos caminos; JEV y
  embeddings como líneas del ledger.
- **DO NOT**: sumar ambos usage events (doble conteo) ni tocar precios.
- **Test**: `ledger.total_tokens == usage_event.total_tokens` para agente y RAG.

### 2. Adopción incompleta del resolver de autoridad (P1)
- **Evidence**: `finalization_policy` corre en observabilidad + strict; los
  gates siguen decidiendo (answer_gate, termination, `_gate_draft`).
- **Failure mode**: contradicciones de cierre silenciosas hasta que alguien
  prende `RUNTIME_RUN_STATE_STRICT`.
- **Root cause**: el plan pedía centralizar la resolución, no la lógica; la
  migración quedó explícitamente incremental.
- **Fix**: adoptar por etapas (tool guard → finalize guard → gate), canary por
  organización, con `decision_matches_terminal` como aserción.
- **DO NOT**: convertir el resolver en mega-función ni duplicar gates.
- **Test**: por cada etapa, un caso que antes divergía y ahora coincide.

### 3. Resiliencia de providers acoplada al modelo (P1)
- **Evidence**: `_circuit_check` marca `_circuit_open` global por modelo;
  fallback de candidatos solo en el loop de tools.
- **Failure mode**: un provider degradado abre circuito para todas las orgs;
  runs sin fallback caen a `PROVIDER_FAILURE` directo.
- **Root cause**: estado de salud global sin scope de tenant/camino.
- **Fix**: circuit breaker por (modelo, tenant opcional) + fallback en ambos
  caminos + métrica de aperturas.
- **DO NOT**: desactivar el breaker.
- **Test**: fallas de una org no afectan runs de otra (fake provider).

### 4. `adaptive` sigue siendo storage en el orquestador (P2)
- **Evidence**: `plan`, `quality`, `evidence`, `attempts` se escriben y leen del
  dict; el estado canónico es espejo parcial.
- **Failure mode**: deriva entre espejo y storage (el riesgo que el programa
  buscaba eliminar).
- **Root cause**: migración de writers por claves, no por camino.
- **Fix**: regenerar `adaptive` desde el estado al final de cada fase (como ya
  se hace con las claves modeladas).
- **DO NOT**: borrar claves antes de migrar readers del flow.
- **Test**: flow byte-idéntico con estado como fuente.

### 5. JEV sin criterio de skip por datos (P2)
- **Evidence**: `jev_value` ahora mide `redundant_rate` en el flow; turn intent
  ya es rules-first, el batch por paso existe, ejecutables hacen bypass.
- **Failure mode**: JEV redundante encarece runs informacionales.
- **Root cause**: faltaba medición; los skips previos eran estructurales.
- **Fix**: umbral de `redundant_rate` por fase → flags de skip conservadores
  (`RUNTIME_JEV_SKIP_<PHASE>`), apagados por defecto.
- **DO NOT**: dejar que JEV autorice ni que un skip aplique a incertidumbre real.
- **Test**: golden set con calidad igual y tokens JEV medidos antes/después.

### 6. AgentRuntime todavía concentra demasiado (P2)
- **Evidence**: `agent_runtime.py` ~5.8k líneas; narrative fast path ~800
  líneas dentro de `_run_loop`; finalización en closures.
- **Failure mode**: cambios locales con efectos globales; tests frágiles.
- **Root cause**: el loop creció por features sin frontera.
- **Fix (P9)**: extraer `narrative_fast_path` y el finalizador con parámetros
  explícitos; criterio: el método principal se lee en <10 min.
- **DO NOT**: reescribir el ReAct ni crear microarchivos.
- **Test**: mismos 1000+ tests verdes tras cada extracción; sin cambios de flow.

### 7. Mezcla de contextos en prompt sin sobre (P2)
- **Evidence**: `context_block`, company context, memory hits y evidencia
  entran al prompt por caminos separados; `ContextEnvelope` ya existe con
  trust/scope (contrato testeado) pero no se inyecta.
- **Failure mode**: memoria o escenario tratados como evidencia documental.
- **Root cause**: no había contrato de procedencia en el prompt assembly.
- **Fix**: construir los bloques del prompt desde el sobre; herramientas
  (untrusted) nunca en bloque de evidencia.
- **DO NOT**: crear un sistema de memoria nuevo.
- **Test**: ningún item `MEMORY`/`USER_TURN` aparece en el bloque de evidencia.

### 8. Story para humanos sin congelar (P3)
- **Evidence**: `story_view.business_steps/technical_steps` implementados con
  `reason_code`; el portal todavía traduce steps crudos.
- **Failure mode**: dump interno en UI, textos divergentes por backend.
- **Root cause**: no había contrato semántico.
- **Fix**: congelar el diccionario de `reason_code` y migrar el portal a
  `build_story(steps, view)`; jamás CoT.
- **DO NOT**: hardcodear frases por step en distintos backends.
- **Test**: contrato de reason codes versionado + snapshot de traducción.

### 9. Aislamiento por conversación no auditado end-to-end (P3)
- **Evidence**: `ContextEnvelope.isolation_key = tenant:conversation`; caches
  de conversación/response usan claves propias; no hay test único de fuga.
- **Failure mode**: respuesta cacheada de otra conversación del mismo tenant.
- **Root cause**: claves de cache dispersas sin contrato de aislamiento.
- **Fix**: helper único de key de cache + test de fuga cruzada (conversación A/B).
- **DO NOT**: confiar en TTLs cortos como aislamiento.
- **Test**: mismo tenant, dos conversaciones, cache hit nunca cruzado.

### 10. Matriz adversarial sin fallos de provider/budget (P3)
- **Evidence**: `test_adversarial_matrix` cubre autoridad/evidencia/budget/
  razonamiento/tools; provider 429/timeout/fallback y continuaciones no entran
  en la matriz.
- **Failure mode**: regresiones de resiliencia no detectadas.
- **Root cause**: fakes de provider simplificados.
- **Fix**: extender fakes (429, timeout, stream cortado, fallback) y correr la
  matriz con `same input × 100` en ambos caminos.
- **DO NOT**: tests que dependan de red real.
- **Test**: matriz extendida verde en CI.

## Roadmap

**NOW** (1–2 sesiones)
1. Contabilidad única (hallazgo 1) + test de igualdad ledger/usage.
2. Adopción etapa 1 del resolver: tool guard (hallazgo 2).

**NEXT**
3. Circuit breaker por tenant (3).
4. `adaptive` regenerado (4).
5. Skips JEV por `redundant_rate` (5) con golden set.
6. Extracción narrative fast path (6).

**LATER**
7. Prompt desde ContextEnvelope (7).
8. Portal a `build_story` + congelar reason codes (8).
9. Aislamiento de conversación end-to-end (9).
10. Matriz adversarial extendida (10).

## Regla

Simplification, consolidation, correctness, reliability, observability, cost —
antes que nuevas features, agentes, modelos o abstracciones.
