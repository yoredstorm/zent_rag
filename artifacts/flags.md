# Flags de runtime — inventario

Generado por `python -m src.scripts.flags_inventory` (solo lectura).
`default` es el default del código; el `.env` local puede pisarlo.

| Flag | Default | Propósito |
|---|---|---|
| `RAG_ADAPTIVE_RAG_CACHE_TTL_SECONDS` | `600` |  |
| `RAG_ADAPTIVE_RAG_CANARY_PERCENTAGE` | `0` |  |
| `RAG_ADAPTIVE_RAG_EVIDENCE_MIN_COVERAGE` | `0.25` |  |
| `RAG_ADAPTIVE_RAG_EVIDENCE_MIN_SCORE` | `0.25` |  |
| `RAG_ADAPTIVE_RAG_FAST_PATH` | `True` |  |
| `RAG_ADAPTIVE_RAG_JEV_EVIDENCE` | `True` |  |
| `RAG_ADAPTIVE_RAG_MAX_RETRIEVAL_ATTEMPTS` | `3` |  |
| `RAG_ADAPTIVE_RAG_MODE` | `off` | off = pipeline actual. shadow = planifica sin cambiar retrieval. active = aplica estrategia/top_k/retry. canary = porcentaje. |
| `RAG_ADAPTIVE_RAG_REWRITE` | `True` |  |
| `RAG_ADAPTIVE_RAG_TOP_K_COMPARE` | `8` |  |
| `RAG_ADAPTIVE_RAG_TOP_K_LOOKUP` | `3` |  |
| `RAG_ADAPTIVE_RAG_TOP_K_MAX` | `12` |  |
| `RAG_ADAPTIVE_RAG_TOP_K_MIN` | `3` |  |
| `RAG_ADAPTIVE_RAG_TOP_K_MULTI` | `12` |  |
| `RAG_DECISION_BATCH_MODE` | `off` | off = una llamada JEV por modulo (comportamiento previo). shadow = ejecuta legacy + batch y guarda el diff sin cambiar la ejecucion. on = una llamada por fas... |
| `RAG_DECISION_CLAIMS` | `True` | on = verificacion por claim contra evidencia (supported/unsupported/contradicted/not_verifiable) reutilizando el Claim Ledger cuando hay tenant. |
| `RAG_DECISION_CLAIMS_LEDGER` | `True` | on = registra claims verificados en el Claim Ledger (best-effort). |
| `RAG_DECISION_CLAIMS_MAX` | `6` |  |
| `RAG_DECISION_COMPLEX_MODEL` | `-` | Reasoning LLM when JEV confidence is low and the request is complex. |
| `RAG_DECISION_FALLBACK_MODEL` | `-` | Small LLM fallback (Novita/LiteLLM). Vacío = GATEWAY_CHEAP_MODEL. |
| `RAG_DECISION_JUDGMENT_CACHE_TTL_SECONDS` | `120.0` |  |
| `RAG_DECISION_NOUL_NO` | `0.35` |  |
| `RAG_DECISION_NOUL_YES` | `0.65` |  |
| `RAG_DECISION_PASSAGE_JUDGE` | `True` | on = JEV juzga passages individuales solo en la zona incierta, top candidatos, conflictos y casos sensibles (deterministico primero). |
| `RAG_DECISION_PASSAGE_MAX` | `5` |  |
| `RAG_DECISION_RISK_CRITICAL_CHOICE` | `0.9` |  |
| `RAG_DECISION_RISK_CRITICAL_FALLBACK` | `human_review` |  |
| `RAG_DECISION_RISK_CRITICAL_WARRANT` | `0.75` |  |
| `RAG_DECISION_RISK_CRITICAL_WARRANT_REQUIRED` | `True` |  |
| `RAG_DECISION_RISK_HIGH_CHOICE` | `0.8` |  |
| `RAG_DECISION_RISK_HIGH_FALLBACK` | `human_review` |  |
| `RAG_DECISION_RISK_HIGH_WARRANT` | `0.65` |  |
| `RAG_DECISION_RISK_HIGH_WARRANT_REQUIRED` | `True` |  |
| `RAG_DECISION_RISK_LOW_CHOICE` | `0.6` |  |
| `RAG_DECISION_RISK_LOW_FALLBACK` | `respond_directly` |  |
| `RAG_DECISION_RISK_MAX_SELECTABLE` | `high` | Riesgo máximo auto-seleccionable; critical exige habilitación explícita. |
| `RAG_DECISION_RISK_MEDIUM_CHOICE` | `0.7` |  |
| `RAG_DECISION_RISK_MEDIUM_FALLBACK` | `ask_clarification` |  |
| `RAG_DECISION_ROUTING_MODE` | `legacy` | legacy = RAG actual. shadow = compara JEV sin cambiar ejecución. jev = Decision Engine activo. hybrid = canary por porcentaje. |
| `RAG_DECISION_TARGET_SELECTION` | `off` | off = el target de agent/workflow/tool debe venir explícito. shadow = resuelve candidatos y observa la elección JEV sin ejecutar. on = JEV elige dentro del C... |
| `RAG_EMBEDDING_DENSE_REPRESENTATION` | `content` | Fase 10: texto que se embebe (dense) por retrieval unit. content = comportamiento actual; semantic = contextual embedding con el Semantic Fabric; concept/que... |
| `RAG_EMBEDDING_FALLBACK_API_BASE` | `https://api.deepinfra.com/v1/openai` |  |
| `RAG_EMBEDDING_FALLBACK_MODEL` | `openai/BAAI/bge-m3` |  |
| `RAG_EMBEDDING_LATE_CHUNKING` | `auto` | Fase 10: late chunking REAL. auto = se usa solo si el registry declaró la capacidad del modelo y el provider expone embed_late_chunking; si falla, contextual... |
| `RAG_EMBEDDING_LATE_CHUNKING_MODELS` | `-` | Modelos de embedding cuyo API soporta late chunking (coma). Vacío = solo el mapa builtin conservador. Nunca se asume soporte. |
| `RAG_EMBEDDING_MODEL` | `openai/baai/bge-m3` |  |
| `RAG_GATEWAY_CHEAP_MODEL` | `-` |  |
| `RAG_GATEWAY_FALLBACK_API_BASE` | `-` | Base OpenAI-compatible del proveedor del fallback. Vacío = la primaria. |
| `RAG_GATEWAY_FALLBACK_MODEL` | `-` | Modelo real si el primary falla. Vacío = sin fallback. |
| `RAG_GATEWAY_FAST_MODEL` | `-` |  |
| `RAG_GATEWAY_QUALITY_MODEL` | `-` | Primary para alias zent-quality. Vacío = LITELLM_DEFAULT_MODEL. |
| `RAG_JEV_BASE_URL` | `https://api.typesafe.ai` |  |
| `RAG_JEV_CANARY_MODEL` | `-` | Modelo candidato/canary de JEV. Vacío = solo JEV_MODEL. El modelo efectivo queda en traces/usage. |
| `RAG_JEV_CANARY_PERCENTAGE` | `0` | Porcentaje de requests que usa JEV_CANARY_MODEL (0 = off). |
| `RAG_JEV_CIRCUIT_FAILURE_THRESHOLD` | `3` |  |
| `RAG_JEV_CIRCUIT_RECOVERY_SECONDS` | `30.0` |  |
| `RAG_JEV_MODEL` | `jev-latest` |  |
| `RAG_JEV_ROUTING_HIGH_CONFIDENCE` (alias `JEV_ROUTING_HIGH_CONFIDENCE`, `RAG_JEV_ROUTING_HIGH_CONFIDENCE`) | `0.9` |  |
| `RAG_JEV_ROUTING_LOW_CONFIDENCE` (alias `JEV_ROUTING_LOW_CONFIDENCE`, `RAG_JEV_ROUTING_LOW_CONFIDENCE`) | `0.65` |  |
| `RAG_JEV_SHADOW_MODE` (alias `JEV_SHADOW_MODE`, `RAG_JEV_SHADOW_MODE`) | `False` | Si true, JEV observa el tráfico real y no cambia la ejecución. |
| `RAG_JEV_TIMEOUT_SECONDS` | `8.0` |  |
| `RAG_LLM_DISABLE_THINKING` | `False` |  |
| `RAG_NARRATIVE_MAX_COVERAGE_ROUNDS` | `1` | Rondas extra de Narrative Coverage Closure despues del top-k inicial. 1 = como maximo una busqueda dirigida a conceptos faltantes. 0 = no. |
| `RAG_RAG_JEV_PREFLIGHT_MODE` (alias `JEV_PREFLIGHT_MODE`, `RAG_JEV_PREFLIGHT_MODE`, `RAG_RAG_JEV_PREFLIGHT_MODE`) | `off` | off = sin juicio previo (comportamiento previo). shadow = JEV decide que HARIA; la ejecucion legacy manda. on = la decision compuesta controla la generacion.... |
| `RAG_RUNTIME_AGENT_JEV_LOOP` | `on` | off = sin juicio por paso (comportamiento previo). shadow = una llamada JEV por paso, veredicto registrado, sin cambiar el comportamiento. on = el veredicto ... |
| `RAG_RUNTIME_AGENT_JEV_LOOP_CANARY_PERCENTAGE` | `0` |  |
| `RAG_RUNTIME_AGENT_MAX_RETRIEVAL_ROUNDS` | `2` | Rondas de busqueda que el loop JEV puede pedir por run cuando falta evidencia para lo que la pregunta nombra (0 = sin re-consultas). |
| `RAG_RUNTIME_AGENT_MAX_SEARCHES` | `3` | Tope de busquedas a la knowledge base por corrida de agente (modelo + JEV). Evita que el ciclo gaste el presupuesto re-buscando y termine sin responder. 0 = ... |
| `RAG_RUNTIME_ANSWER_FACT_CHECK` | `on` | Verificacion determinista de fechas y anios de la respuesta contra la evidencia consultada: 'on' = corrige una vez y deja registro; 'off' = no verifica. No i... |
| `RAG_RUNTIME_ANSWER_GATE` | `off` | on = JEV verifica el borrador de respuesta del agente antes de finalizar (una revision maximo). shadow = solo observa. |
| `RAG_RUNTIME_ANSWER_MAX_TOKENS` | `4096` | Tope de tokens POR LLAMADA de respuesta del agente (loop y finalize). No es el techo del run (ese es limits.max_tokens del agente): es lo que se le manda al ... |
| `RAG_RUNTIME_BUILD_GIT_SHA` | `-` | SHA del commit desplegado, inyectado en build/deploy. Se publica en la traza del run (build.git_sha) para comprobar el contenedor. |
| `RAG_RUNTIME_BUILD_TIMESTAMP` | `-` | Timestamp ISO del build desplegado; se publica en build.build_timestamp de la traza del run. |
| `RAG_RUNTIME_COMPOSER_MAX_TOKENS` | `400` | Tope de tokens de salida de la llamada de redaccion (presentacion). Target 100-400: no es una respuesta completa de pipeline. |
| `RAG_RUNTIME_COMPOSER_MODEL` | `-` | Modelo barato para la redaccion de presentacion. Vacio = usa GATEWAY_FAST_MODEL / GATEWAY_CHEAP_MODEL; si no hay, el modelo del agente. Nunca se usa un reaso... |
| `RAG_RUNTIME_CONFIG_ACK_DANGEROUS` | `-` | Acknowledgement explícito de combinaciones DANGEROUS (P1-E): códigos de `src/core/config_rules` separados por coma (`dangerous_gate_phase_skipped`, ...). En ... |
| `RAG_RUNTIME_DETERMINISTIC_RENDER_MODE` | `adaptive` | Modo de redaccion de presentacion del fast path determinista: strict=0 llamadas LLM; polish=1 llamada pequena cuando el agente tiene personalidad; adaptive (... |
| `RAG_RUNTIME_EFFICIENCY_COST_WEIGHT` | `0.25` |  |
| `RAG_RUNTIME_EFFICIENCY_FALLBACK_WEIGHT` | `0.15` |  |
| `RAG_RUNTIME_EFFICIENCY_LATENCY_WEIGHT` | `0.2` |  |
| `RAG_RUNTIME_EFFICIENCY_QUALITY_WEIGHT` | `0.4` |  |
| `RAG_RUNTIME_EVIDENCE_BUDGET_CHARS` | `12000` | Presupuesto de contexto de EVIDENCIA (caracteres) del run. El selector reparte ese presupuesto por relevancia (entidad exacta > nombre de fuente > entity pin... |
| `RAG_RUNTIME_FAILED_TOOL_GUARD` | `True` | on = una tool que fallo para la pregunta no se reintenta; la observacion guia al LLM a usar otra herramienta o responder. |
| `RAG_RUNTIME_FAST_PATH` | `on` | Deterministic Fast Path: una consulta ejecutable con autoridad completa (regla SUPPORTED + premisas SATISFIED + envelope) se responde sin LLM. 'off' conserva... |
| `RAG_RUNTIME_FAST_PATH_ESTIMATED_TOKENS` | `0` | Estimacion de tokens evitados por fast path para telemetria de ahorro. 0 = no se declara ahorro de tokens (UNKNOWN != ZERO). |
| `RAG_RUNTIME_FAST_PATH_POLISH` | `False` | Fast path con UNA llamada pequena de estilo opcional. El modelo recibe headline, resultado, checks y citas; no puede cambiar la decision y el texto vuelve a ... |
| `RAG_RUNTIME_FINALIZATION_ENFORCE` | `termination_trigger,draft_gate` | Etapas donde la política de finalización manda sobre la ruta vigente (enforcement del shadow): un trigger que cierra cuando la política resuelve RETRIEVE_MOR... |
| `RAG_RUNTIME_FINALIZATION_ENFORCE_BY_ENV` | `-` | Override del enforcement por environment: 'production=etapas;staging=etapas'. Aplica cuando RAG_ENVIRONMENT coincide. |
| `RAG_RUNTIME_FINALIZATION_ENFORCE_ORGS` | `-` | Override del enforcement por organización: 'org=etapas;org2' (clave sin valor = etapas globales). Prioridad: agente > org > environment > global. |
| `RAG_RUNTIME_FINALIZE_MAX_TOKENS` | `0` | Presupuesto de tokens de la respuesta final del agente (0 = derivado del agente: min(limits.max_tokens, RUNTIME_ANSWER_MAX_TOKENS)). Un presupuesto corto tru... |
| `RAG_RUNTIME_JEV_ANSWER_APPROVE` | `0.66` | Score minimo para aprobar la respuesta sin cambios. |
| `RAG_RUNTIME_JEV_ANSWER_REVISE` | `0.4` | Score minimo para pedir una revision; debajo, abstencion. |
| `RAG_RUNTIME_JEV_MIN_TOOLS` | `3` | Minimo de herramientas disponibles para consultar a JEV en el routing. Con menos, passthrough y decide el LLM. 1 = siempre. |
| `RAG_RUNTIME_JEV_SKIP_PHASES` | `-` | Fases JEV que se saltan por calibracion (redundant_rate): answer_gate,agent_step,termination. Vacio = JEV corre siempre. |
| `RAG_RUNTIME_JEV_SKIP_SHADOW` | `off` | on = no llama al juez en fases shadow (un veredicto shadow no decide): ahorro puro durante el rollout. |
| `RAG_RUNTIME_JEV_STATE_MAX_CHARS` | `30000` | Presupuesto de estado (caracteres) que recibe JEV por juicio. |
| `RAG_RUNTIME_JEV_TOOL_CONFIDENCE` | `0.6` | Score minimo para que JEV imponga su eleccion de herramienta. |
| `RAG_RUNTIME_NARRATIVE_FAST_PATH` | `on` | on = consultas informacionales puras usan una busqueda por codigo y una generacion (sin loop ReAct). off = loop normal con tools. |
| `RAG_RUNTIME_NARRATIVE_GENERATION_TIMEOUT_SECONDS` | `0.0` | Timeout opcional de la generacion narrativa (0 = sin timeout). Si el proveedor primario no entrega a tiempo, se intenta GATEWAY_FALLBACK_MODEL y se registra ... |
| `RAG_RUNTIME_RUN_GUARDS_ENFORCE` | `off` | on = el veredicto de la tabla de run_guards manda en ejecución (una tool que el guard deniega no se ejecuta). off = solo shadow medible (zent_guard_divergenc... |
| `RAG_RUNTIME_RUN_STATE_STRICT` | `off` | on = modo estricto global del estado del run: una violación de invariante crítico (autoridad contradicha/reemplazada, cierre no autorizado por la política) r... |
| `RAG_RUNTIME_RUN_STATE_STRICT_ORGS` | `-` | Canary del modo estricto por organización (ids separados por coma): esas orgs corren fail-closed por invariantes aunque el global esté apagado. La configurac... |
| `RAG_RUNTIME_SHADOW_SAMPLE_RATE` | `0.0` | Optional sample of JEV decisions compared with the previous provider. |
| `RAG_RUNTIME_SOURCE_AWARE_TOOLS` | `True` | on = el runtime quita tools que no aplican a las fuentes del agente (SQL sin fuentes de datos, tabular sin CSV/Excel, call_api sin allowlist). |
| `RAG_RUNTIME_TERMINATION_GATE` | `off` | on = extra Noul gate after tool use; max_steps still hard-stops. |
| `RAG_RUNTIME_TOOL_ROUTING_MODE` | `off` | experimental = JEV Choice selects a subset of agent tools. |
| `RAG_RUNTIME_TURN_FAST_MODEL` | `-` | Modelo barato opcional para turnos conversacionales directos (saludo, agradecimiento, despedida, charla). Vacio = modelo del agente. |
| `RAG_RUNTIME_TURN_INTENT` | `on` | off = sin capa conversacional (comportamiento previo). rules = solo reglas, sin JEV. on = reglas para lo obvio y JEV para la ambiguedad semantica. |
| `RAG_RUNTIME_TURN_INTENT_ACTION_FLOOR` | `0.35` | Probabilidad de action_request a partir de la cual decide el route TOOL. |
| `RAG_RUNTIME_TURN_INTENT_AMBIGUOUS_FLOOR` | `0.45` | Confianza por debajo de la cual una distribucion plana se trata como ambigua (aclaracion o contexto), nunca como fallo. |
| `RAG_RUNTIME_TURN_INTENT_CONVERSATIONAL_FLOOR` | `0.6` | Masa de probabilidad de las familias conversacionales para una respuesta directa. |
| `RAG_RUNTIME_TURN_INTENT_KNOWLEDGE_FLOOR` | `0.3` | Probabilidad de knowledge_question a partir de la cual la intencion material manda sobre una conversacional secundaria. |
| `RAG_RUNTIME_TURN_INTENT_RULES_CONFIDENCE` | `0.8` | Confianza minima de las reglas para no consultar a JEV. |

## Drift con .env.example

- Sin drift: `.env.example` y Settings coinciden.
