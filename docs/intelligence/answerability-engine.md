# Zent Answerability Engine — Intelligence Layer (FASE 23)

> Zent nunca se siente obligado a generar una respuesta.
> La ausencia de evidencia suficiente produce una **abstención estructurada**,
> no una respuesta especulativa.

## 1. Arquitectura

```
Pregunta
  → Query Understanding (intención, entidades, conceptos, ambigüedad)
  → Query Planner (SQL | RAG | SQL+RAG | API/TOOL | CLARIFICATION | ABSTAIN)
  → Resolución de contexto (definiciones aprobadas + fuentes)
  → Retrieval / SQL (pipeline existente, guiado por el plan)
  → Evidence Collection (toda fuente → EvidenceObject)
  → Answerability Gate (señales deterministas; LLM solo como crítico opcional)
  → ANSWERABLE            → prompt + generación + trace
  → CLARIFICATION/ABSTAIN → respuesta estructurada de abstención + trace
```

Nuevo paquete `src/intelligence/` (capa de servicios, depende solo de puertos de
`core/` + factories de sesión, igual que `rag/` y `agents/`). Entidades puras en
`src/core/domain/intelligence.py`.

| Módulo | Responsabilidad |
|---|---|
| `understanding.py` | Intención/entidades/conceptos/período/ambigüedad (determinista + LLM opcional) |
| `planner.py` | Estrategia antes de ejecutar herramientas (nunca SQL-first ciego) |
| `evidence.py` | `EvidenceObject` desde SQL, chunks, definiciones, tools |
| `signals.py` | 16 señales deterministas + score compuesto plan-aware |
| `answerability.py` | `AnswerabilityGate` con orden de prioridad fijo |
| `abstention.py` | Abstención estructurada (qué falta, por qué, siguiente paso) |
| `fsm.py` | Máquina de estados finita + presupuesto duro (`Budget`) |
| `loop_guard.py` | Fingerprints deterministas; retry solo con nueva información |
| `store.py` | Persistencia `business_definitions`, `intelligence_traces`, `context_gaps` |
| `engine.py` | Fachada que compone el pipeline dentro del orchestrator |

## 2. Estados formales

| Estado | Cuándo |
|---|---|
| `ANSWERABLE` | Evidencia suficiente y validada; confianza HIGH/MEDIUM |
| `CLARIFICATION_REQUIRED` | Una única pregunta resuelve la ambigüedad |
| `CONTEXT_MISSING` | La data existe pero falta su definición/regla empresarial |
| `DATA_MISSING` | La información física no existe o no está conectada |
| `DATA_QUALITY_LOW` | Data presente pero frescura/autoridad/cobertura débiles |
| `AMBIGUOUS` | Ambigüedad sin pregunta única que la resuelva |
| `ACCESS_BLOCKED` | Permisos/blocklists denegaron el acceso |
| `SOURCE_CONFLICT` | Fuentes se contradicen sin fuente autoritativa |
| `EXECUTION_FAILED` | La ejecución falló sin evidencia alternativa |
| `HUMAN_REVIEW_REQUIRED` | Score < umbral o crítico LLM no soporta la respuesta |

### Orden de prioridad (determinista)

```
ACCESS_BLOCKED > EXECUTION_FAILED > SOURCE_CONFLICT > CLARIFICATION_REQUIRED
> AMBIGUOUS > CONTEXT_MISSING > DATA_MISSING > DATA_QUALITY_LOW
> HUMAN_REVIEW_REQUIRED > ANSWERABLE
```

El LLM puede actuar como crítico post-generación (`RAG_ANSWERABILITY_LLM_CRITIC_ENABLED`),
pero **nunca es la única señal**: el estado lo deciden reglas sobre señales
objetivas del sistema.

## 3. DATA_MISSING vs CONTEXT_MISSING

- **`DATA_MISSING`**: la data física necesaria no existe o no está conectada.
  Ej.: *"No puedo calcular margen porque no tengo costo de producto / COGS."*
- **`CONTEXT_MISSING`**: la data existe pero Zent no conoce su significado.
  Ej.: *"Existen `STATUS_CD = A,B,C,I` pero no hay definición aprobada de qué
  significa cada valor."*

Solo los conceptos que **requieren definición** (derivados/estados de negocio
como `activo`, `rentable`, `margen`) disparan `CONTEXT_MISSING`; sustantivos
genéricos (`cliente`, `producto`, `devoluciones`) no bloquean la respuesta.

## 4. Señales del Gate (16)

`intent_resolution`, `concept_resolution`, `schema_link_quality`,
`retrieval_relevance`, `retrieval_coverage`, `sql_validation`,
`sql_execution_success`, `result_presence`, `result_relevance`,
`source_freshness`, `source_authority`, `source_agreement`,
`business_definition_status`, `permission_check`, `data_quality`, `ambiguity`.

El score compuesto es **plan-aware**: las señales que no aplican a la ruta
ejecutada (p. ej. schema en una ruta solo-RAG) no inflan el score.

### Sin falsa precisión

Confianza discreta: `HIGH` (≥0.8) · `MEDIUM` (≥0.6) · `LOW` (≥0.4) ·
`INSUFFICIENT` (<0.4), acompañada de la explicación (definición aprobada,
fuente autoritativa, consulta ejecutada, datos actualizados, fuentes
consistentes).

## 5. SQL Evidence Pipeline

Se conservan todas las protecciones del SQL Expert existente y se refuerza:

1. SELECT-only + una sola sentencia (sqlglot AST)
2. `RAG_SQL_MAX_REPAIR_ATTEMPTS` (default 3 = 1 validación + 2 ejecución,
   comportamiento histórico) — ahora configurable
3. **Loop prevention**: `(sql, error)` idéntico repetido corta el repair
   (`SQLRepairGuard`); un retry exige nueva información (schema discovery,
   error distinto)
4. EXPLAIN cost gate, tenant filter injection, blocklists, rol read-only,
   límites de filas/timeout, auditoría `sql_audit_logs`
5. Resultado → `EvidenceObject` (`type=sql_result`, `authority=authoritative`,
   `freshness=live`) con métricas `rag_sql_repair_attempts_total`

## 6. Loop prevention (agentes y SQL)

Fingerprint determinista: `sha256(tool|source|args_normalizados|query|agent_id|org)`.

- **Agent Runtime**: una llamada de tool con el mismo fingerprint y sin
  cambio en la observación se bloquea (`rag_agent_loop_preventions_total{scope=agent_runtime}`).
- **SQL repair**: `(sql, error)` idéntico se detiene (registra
  `retry_reason / previous_attempt / new_information / modified_plan`).

Ejemplo válido de retry:

```text
SQL #1 → Unknown column TOTAL
Schema inspection → TOTAL_AMT discovered (new_information)
SQL #2 → corregido
```

## 7. Límites duros por ejecución

| Setting | Default |
|---|---|
| `RAG_ANSWERABILITY_MAX_PLAN_ATTEMPTS` | 2 |
| `RAG_ANSWERABILITY_MAX_RETRIEVAL_ROUNDS` | 2 |
| `RAG_ANSWERABILITY_MAX_LLM_CALLS` | 10 |
| `RAG_ANSWERABILITY_MAX_EXECUTION_SECONDS` | 45 |
| `RAG_ANSWERABILITY_MAX_TOTAL_TOKENS` | 6000 |
| `RAG_ANSWERABILITY_MAX_COST_USD` | 0.10 |
| `RAG_SQL_MAX_REPAIR_ATTEMPTS` | 3 |

Se integran con la infraestructura existente: quota preflight de billing,
rate limits, guardrails del Agent Runtime (`RAG_AGENT_*`).

## 8. Evidencia y trazabilidad

- `intelligence_traces`: understanding, plan, evidencia, decisión, presupuesto,
  respuesta, latencia — org-scoped, enlazado con `query_id`.
- `business_definitions`: conceptos/metrícas aprobadas por organización
  (única fuente de verdad; Zent no inventa definiciones).
- `context_gaps`: agregación de gaps de contexto/datos para hacerlos accionables.
- Cada respuesta expone `trace_id` y el bloque `answerability` con
  `evidence` (resúmenes: id, tipo, fuente, autoridad, frescura — nunca filas).
- Nunca se persisten secretos ni contenido de filas de negocio.

## 9. API

### POST /api/v1/rag/query (extendido, backward compatible)

```json
{
  "query_id": "...",
  "status": "completed",
  "answer": "No tengo suficiente información para responder esta pregunta. Datos faltantes: costo de producto / COGS. Siguiente paso sugerido: Connect the required data source...",
  "answerability": {
    "status": "DATA_MISSING",
    "answerable": false,
    "confidence": "insufficient",
    "reason_codes": ["NO_SQL_RESULT", "NO_RETRIEVAL"],
    "missing_context": [],
    "missing_data": ["costo de producto / COGS"],
    "conflicting_sources": [],
    "clarifying_question": null,
    "recommended_actions": ["Conectar la fuente de datos requerida o reindexar la knowledge base"],
    "evidence": [
      {"evidence_id": "...", "type": "sql_result", "source_name": "ERP",
       "authority_level": "authoritative", "freshness": "live"}
    ]
  },
  "trace_id": "..."
}
```

Todos los campos nuevos son opcionales: sin el engine activo la respuesta es
idéntica a la anterior. Streaming: el evento `done` incluye `answerability` y
`trace_id`.

### Nuevos endpoints

| Método | Path | Permiso |
|---|---|---|
| GET | `/api/v1/intelligence/traces/{trace_id}` | `rag:read` |
| GET | `/api/v1/intelligence/definitions` | `org:read` |
| POST | `/api/v1/intelligence/definitions` (upsert) | `org:write` |
| DELETE | `/api/v1/intelligence/definitions/{concept}` | `org:write` |

Todos org-scoped (404 cross-tenant, sin revelar existencia).

## 10. Observabilidad

| Métrica | Semántica |
|---|---|
| `rag_answerable_queries_total` | Consultas contestables |
| `rag_abstained_queries_total{reason}` | Abstención estructurada (10 estados) |
| `rag_context_missing_total` | CONTEXT_MISSING |
| `rag_data_missing_total` | DATA_MISSING |
| `rag_ambiguous_queries_total` | AMBIGUOUS + CLARIFICATION_REQUIRED |
| `rag_source_conflicts_total` | SOURCE_CONFLICT |
| `rag_execution_failures_total` | EXECUTION_FAILED |
| `rag_sql_repair_attempts_total` | Intentos de repair SQL |
| `rag_agent_loop_preventions_total{scope}` | Operaciones idénticas bloqueadas |

Etiquetas de baja cardinalidad (`organization_id`, `reason`). Ratios derivados:
`answerability_rate`, `abstention_rate`, `sql_success_rate`, etc. pueden
computarse en Grafana a partir de los contadores.

## 11. Evaluación

`EvalCase` gana `expected_answerability` (estado formal esperado) y la métrica
`answerability_accuracy` (1.0 si coincide, None si no aplica). Golden set de
referencia: `tests/golden/answerability_cases.json` (8 casos):

1. Definición aprobada → `ANSWERABLE`
2. Concepto sin definición → `CONTEXT_MISSING`
3. Data de costo ausente → `DATA_MISSING`
4. Fuentes contradictorias → `SOURCE_CONFLICT`
5. Métrica ambigua → `CLARIFICATION_REQUIRED`
6. Tabla sin permiso → `ACCESS_BLOCKED`
7. SQL que falla repetido → `EXECUTION_FAILED` (loop cortado)
8. Resultado vacío válido → `ANSWERABLE` (0 ≠ sin data)

## 12. Seguridad

- Identidad solo del Bearer; todas las tablas org-scoped (`organization_id`).
- Evidencia expuesta sin filas de datos de negocio (resúmenes).
- `ACCESS_BLOCKED` se detecta de forma determinista (permission_check +
  errores `blocked for role` del SQL Expert), no por el LLM.
- Trazas sin secretos ni datos sensibles; SQL auditado como siempre.

## 13. Extensibilidad futura

- **Definiciones**: CRUD listo para el portal (aprobación de métricas).
- **Fuente autoritativa**: `business_definitions.authoritative_source_id`
  resuelve `SOURCE_CONFLICT` automáticamente.
- **Critic LLM**: activable por org/settings (`RAG_ANSWERABILITY_LLM_CRITIC_ENABLED`).
- **Freshness por fuente**: resolver inyectable (`freshness_resolver`) basado en
  `source_sync_state.last_success_at`.
- **Multi-turn**: `context_gaps` alimenta recomendaciones proactivas.