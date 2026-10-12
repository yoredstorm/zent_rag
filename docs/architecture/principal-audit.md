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
- **Estado (este pase)**: JEV suma sus tokens al run vía `record_judge_call`
  (answer_gate, agent_step, termination, turn intent) y el ledger lo ve en la
  próxima construcción; falta el camino RAG, embeddings/rerank y la tarifa del
  juez (no se inventa costo si el precio es desconocido).
- **Estado (contabilidad RAG)**: el evento de uso del pipeline etiqueta
  `jev_tokens`/`jev_cost_usd` desde `flow.jev_preflight` (no se suman a `cost`:
  el juez factura por su propio usage event). Embeddings y reranking ya viajan
  en el evento; falta la tarifa del juez para costearlo ahí.
- **Estado (contabilidad unificada)**: el camino RAG cuenta sobre
  `RunBudgetLedger` con `run_accounting` como único writer
  (`account_rag_result`: LLM + embedding + rerank + charge + JEV, idempotente).
  El evento de uso LEE los totales del ledger (`_build_usage_event`) y no los
  recalcula. Líneas explícitas: `embedding`, `rerank`, `charge`, `jev_usage`
  (`billed_separately`). Sin tarifa el costo es `unknown`, nunca 0. Test:
  `tests/test_run_accounting_rag.py` (ledger == usage event). Doc:
  `docs/architecture/run-accounting.md`.

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
- **Estado (este pase)**: etapa 1 hecha — `run_guards` es la tabla explícita y
  el loop ya no ejecuta tools con budget agotado; las denegaciones registran
  `guard_reason` (`BUDGET_EXHAUSTED`, `DUPLICATE_TOOL_CALL`,
  `TOOL_NOT_AUTHORIZED`).
- **Estado (etapa 2)**: el gate de respuesta adopta la política —
  `gate_abstention_action` convierte una abstención JEV en `answer_with_limits`
  cuando la evidencia canónica alcanza (completa o `can_answer`), y mantiene la
  abstención si la evidencia es insuficiente o el retrieval falló (caso D de
  evidence-first preservado).
- **Estado (shadow medible)**: `observe_shadow_divergence` emite
  `zent_finalization_shadow_divergence_total{stage, action, reason_code}` cuando
  la ruta vigente no coincide con la resolución (`closure`,
  `termination_trigger`, `draft_gate`). Gate de adopción por etapas: cero
  divergencias sobre el corpus antes de convertir una señal en autoridad.
- **Estado (allowlist de transiciones)**: `tests/test_terminal_transitions_allowlist.py`
  fija la lista CERRADA de transiciones terminales fuera de la política (15
  ocurrencias en 4 archivos, cada una con justificación). Cualquier transición
  nueva rompe el test hasta rutearse por la política o documentarse.

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
- **Estado (este pase)**: implementado — circuit scoped por tenant
  (`organization_id` en `model_circuit_breakers`, migración **151**, unique por
  `(model_name, COALESCE(organization_id))`). El runtime pasa la org:
  fallos del tenant abren solo su scope; `check_circuit` combina con el global
  (el peor estado manda) para que un provider caído siga protegiendo a todos.
  Métricas `zent_model_circuit_failures_total`/`_openings_total{model,scope}` y
  alerta `ModelCircuitMultiTenantOpen` (varios tenants abriendo el mismo modelo
  = problema de provider, no de una org). `reset_circuit(model)` sin scope
  resetea todos los circuitos del modelo (admin); con scope, solo el tenant.

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
- **Estado (este pase)**: parcial — `_adaptive_publish` regenera al cierre las
  claves modeladas (registry/selection/sufficiency/evidence_state/grounded/
  envelope/package/query_executable/response_plan/long_context). `plan`,
  `quality`, `evidence`, `attempts` son engine-native del hook y quedan en
  `adaptive`; moverlas requiere modelarlas en el estado primero.
- **Estado (engine-native modeladas)**: hecho — las cuatro claves viven en el
  estado (`plan.adaptive_plan`, `evidence.engine_evidence/engine_quality/
  retrieval_attempts`, mismas referencias) y `adaptive` pasó a proyección: el
  writer único es `_adaptive_write` (estado + proyección) y
  `_adaptive_publish` regenera las cuatro claves. Test de writers = 1:
  `tests/test_adaptive_projection.py` (escaneo del repo; solo la proyección
  escribe directo).

### 5. JEV sin criterio de skip por datos (P2)
- **Evidence**: `jev_value` ahora mide `redundant_rate` en el flow; turn intent
  ya es rules-first, el batch por paso existe, ejecutables hacen bypass.
- **Failure mode**: JEV redundante encarece runs informacionales.
- **Root cause**: faltaba medición; los skips previos eran estructurales.
- **Fix**: umbral de `redundant_rate` por fase → flags de skip conservadores
  (`RUNTIME_JEV_SKIP_<PHASE>`), apagados por defecto.
- **DO NOT**: dejar que JEV autorice ni que un skip aplique a incertidumbre real.
- **Test**: golden set con calidad igual y tokens JEV medidos antes/después.
- **Estado (este pase)**: medición lista (`flow["jev_value"]` + tokens JEV en el
  run). Los skips quedan a la espera de `redundant_rate` real de producción;
  los estructurales ya existen (rules-first, batching, bypass fail-closed).
- **Estado (skip por calibración)**: mecanismo implementado —
  `RUNTIME_JEV_SKIP_PHASES=answer_gate,agent_step,termination` (default vacío:
  JEV corre igual). Con el flag, la fase devuelve `provider="skip_config"` sin
  llamar al juez. Se activa solo con datos que muestren redundancia alta.
- **Estado (activación)**: `RUNTIME_JEV_SKIP_SHADOW=on` (settings + compose)
  evita pagar la llamada del juez cuando el veredicto es shadow — no decide,
  así que es ahorro puro; implementado en el gate de respuesta. El `.env` local
  queda con `answer_gate` en skip phases y shadow-skip on para probarlo; la
  suite es hermética (conftest neutraliza ambos). El skip duro de fases en
  producción sigue pendiente de `redundant_rate`.

### 6. AgentRuntime todavía concentra demasiado (P2)
- **Evidence**: `agent_runtime.py` ~5.8k líneas; narrative fast path ~800
  líneas dentro de `_run_loop`; finalización en closures.
- **Failure mode**: cambios locales con efectos globales; tests frágiles.
- **Root cause**: el loop creció por features sin frontera.
- **Fix (P9)**: extraer `narrative_fast_path` y el finalizador con parámetros
  explícitos; criterio: el método principal se lee en <10 min.
- **DO NOT**: reescribir el ReAct ni crear microarchivos.
- **Test**: mismos 1000+ tests verdes tras cada extracción; sin cambios de flow.
- **Estado (este pase)**: pendiente por diseño (P9); prerrequisito antes de
  extraer: preservar la suite verde del programa y no tocar el contrato del flow.
- **Estado (legibilidad)**: lifecycle documentado en el loop (8 fases con sus
  estados) y transiciones en `run_guards`.
- **Estado (extracción acotada)**: `_resolve_narrative_search_plan` (semántica +
  packs + top_k de la ruta narrativa) extraído del closure a función de módulo
  con parámetros explícitos y tests propios; verificado con la ruta narrativa
  ACTIVA (`test_narrative_runtime_regression`, top_k del agente incluido).
  La extracción completa del narrative fast path sigue con criterio explícito
  (módulo con parámetros, sin rewrite del ReAct).
- **Estado (extracción por pasos, 2026-10-11)**: 9 pasos commiteados al módulo
  `src/runtime/narrative_fast_path.py`, comportamiento idéntico y tests propios:
  1) bloques puros (frames, context blocks, nota de gaps);
  2) cierre (`fast_path_overrun`, `patch_narrative_verification`,
  `mark_partial_grounded`); 3) proyecciones de traza (coverage/frames);
  4) generación (`generate_narrative_answer`: timeout, fallback, continuación);
  5) prompt + plan de presupuesto (`build_narrative_prompt_plan`);
  6) payload del step (`FastPathStep.to_step`);
  7) search inicial (`run_initial_narrative_search`);
  8) preparación de cobertura (`prepare_narrative_coverage` +
  `language_bridge_step`); 9) ronda de cobertura y paquete final
  (`run_coverage_round`, `finalize_narrative_coverage`).
  El closure bajó de ~780 a ~359 líneas y ahora se lee por etapas nombradas
  (cada paso es una llamada). `agent_runtime.py`: 5854 a 5482 líneas.
  Resta el finalizador (`_try_finalize_answer` y cierres asociados) para una
  próxima sesión; es la otra mitad del P9.

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
- **Estado (este pase)**: parcial — el `ContextEnvelope` se publica al cierre y
  el prompt ya etiqueta el trust por canal (workflow «datos no confiables»,
  observaciones de tools «untrusted data», hechos del workspace con
  `[authority]`, evidencia desde el registry). Falta construir los bloques
  desde el sobre y migrar el portal a `story_view` (frontend, fuera del backend).
- **Estado (encabezados desde el sobre)**: hecho — `PROMPT_BLOCK_HEADERS` +
  `prompt_block_header(origin)` (`context_envelope`) son la fuente ÚNICA de las
  etiquetas de procedencia del prompt (origen → trust); `agent_runtime` las usa
  para el contexto de workflow y las observaciones de tools (strings idénticos:
  cero cambio de comportamiento). Tests: `tests/test_prompt_block_headers.py`
  (origen→trust, inyección en contexto de workflow queda como DATA, wiring).
  Falta: construir memory/company blocks desde el sobre (mismo mecanismo) y la
  extracción del narrative fast path (~780 líneas, sesión propia).

### 8. Story para humanos sin congelar (P3)
- **Evidence**: `story_view.business_steps/technical_steps` implementados con
  `reason_code`; el portal todavía traduce steps crudos.
- **Failure mode**: dump interno en UI, textos divergentes por backend.
- **Root cause**: no había contrato semántico.
- **Fix**: congelar el diccionario de `reason_code` y migrar el portal a
  `build_story(steps, view)`; jamás CoT.
- **DO NOT**: hardcodear frases por step en distintos backends.
- **Test**: contrato de reason codes versionado + snapshot de traducción.
- **Estado (backend)**: `GET /agents/runs/{run_id}/story?view=business|technical`
  y alias unificado `GET /executions/agent/{run_id}/story` devuelven
  `build_story(...)` desde los steps persistidos (business sin campos técnicos
  ni CoT; technical con contenido truncado).
- **Estado (portal)**: `portal/src/pages/chat/story/businessStory.ts` traduce
  `reason_code`+`facts` a copy humano con tonos (`translateReasonCode` /
  `translateBusinessSteps`, 5 tests vitest) y el `FlowDrawer` muestra la sección
  «Pasos del run» para runs de agente (fetch fail-soft al endpoint, 1 test de
  integración vitest).

### 9. Aislamiento por conversación no auditado end-to-end (P3)
- **Evidence**: `ContextEnvelope.isolation_key = tenant:conversation`; caches
  de conversación/response usan claves propias; no hay test único de fuga.
- **Failure mode**: respuesta cacheada de otra conversación del mismo tenant.
- **Root cause**: claves de cache dispersas sin contrato de aislamiento.
- **Fix**: helper único de key de cache + test de fuga cruzada (conversación A/B).
- **DO NOT**: confiar en TTLs cortos como aislamiento.
- **Test**: mismo tenant, dos conversaciones, cache hit nunca cruzado.
- **Estado (aislamiento)**: implementado — `_hash_query` incluye
  `conversation_id` en la clave de respuesta; `conversation_cache_key`
  (`src/runtime/cache_fingerprint.py`) es el helper único del historial
  (tenant + conversación, usado por el pipeline y la abstención temprana);
  `_response_cache_key` centraliza la clave con degradación compatible para
  proveedores viejos (tests/embebidos). Tests:
  `tests/test_conversation_isolation.py` (dos conversaciones no comparten
  clave; la firma legacy no se rompe).

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
- **Estado (streaming)**: implementado — `tests/test_llm_stream_fallback.py`
  cubre 429/timeout/circuit open antes del primer token (va al fallback),
  stream cortado tras emitir (error, sin cambiar de modelo), todos los
  candidatos fallan (propaga) y estabilidad ×100. El camino no-streaming ya
  estaba cubierto por `tests/test_llm_router.py` y los retries de embeddings
  por `tests/test_llm_embed_retry.py`.

## Roadmap

**HECHO (2026-10-11)**
1. Contabilidad unificada del camino RAG sobre `RunBudgetLedger` + test
   ledger/usage (`run-accounting.md`, hallazgo 1).
2. Adopción etapa 1 (tool guard) y etapa 2 (answer gate) del resolver;
   shadow medible con `zent_finalization_shadow_divergence_total` (hallazgo 2).
3. Circuit breaker por tenant (3).
4. Skips JEV por calibración con shadow-skip (5).
8. Story views + portal a `build_story` (8); catálogo único de reason codes
   (`src/runtime/reason_codes.py`, versionado).
9. Aislamiento por conversación en caches (tenant + conversación) con tests
   de fuga (hallazgo 9).
10. Matriz adversarial de streaming por provider (429/timeout/circuit/fallback
    + estabilidad ×100) (hallazgo 10).

**HECHO (segunda pasada 2026-10-11)**
5. `adaptive` regenerado: `plan`, `quality`, `evidence`, `attempts` modeladas
   en el estado; writer único `_adaptive_write`; writers=1 verificado (4).
7. Encabezados de bloque del prompt desde `ContextEnvelope` (fuente única
   origen → trust) (7).

**NEXT**
6. Extracción del finalizador (`_try_finalize_answer` + cierres, ~200 líneas)
   con parámetros explícitos; el narrative fast path ya quedó extraído en 9
   pasos (ver estado). Sesión propia con la suite verde como red (6).
11. Invariantes de texto para el resto de los estados de respuesta (ya
    cubiertos RETRIEVAL_UNAVAILABLE y UNDETERMINED).
12. Bloques memory/company del prompt desde el sobre (mismo mecanismo que los
    encabezados ya migrados).

## Regla

Simplification, consolidation, correctness, reliability, observability, cost —
antes que nuevas features, agentes, modelos o abstracciones.
