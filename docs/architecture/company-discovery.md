# Company Discovery Engine

Segunda capa de **Company Intelligence**. La Fase 5A construyó el *Company Graph*
(el modelo: entidades, relaciones, autoridad, vigencia). Esta fase construye el
**motor que lo alimenta** y el **compilador que lo consume**: Zent empieza a
descubrir automáticamente cómo habla y cómo funciona una organización.

---

## 1. La regla que gobierna todo

```
DISCOVER  →  SUPPORT  →  SUGGEST  →  VALIDATE  →  CONFIRM
```

Nunca:

```
LLM dice X  →  X es verdad de la compañía
```

Consecuencias en el código:

| Regla | Implementación |
|---|---|
| Un candidato no es una entidad | `DiscoveryCandidate` vive en su propia tabla (`company_discovery_candidates`), separada del grafo |
| Nada se confirma solo | `promote()` exige actor humano salvo verificación estructural (`requires_human_confirmation`) |
| No se saltan etapas | `assert_stage_transition` + `_advance()` recorre la cadena legal |
| Sin evidencia no hay confianza | `score_candidate` mide corroboración en dimensiones independientes, no repeticiones |
| Nada se fusiona por parecido | el resolver marca `ambiguous` y **no** une entidades |
| El LLM solo desambigua | `adjudicate()` y el resultado sigue siendo sugerencia |

---

## 2. Fuentes de descubrimiento

`DiscoverySource` es un ABC con loaders **inyectados**: el extractor es puro y
testeable sin base de datos, y una fuente nueva se agrega registrándose
(`DiscoverySourceRegistry.register`) sin tocar el motor.

| Fuente | Señal que consume | Produce |
|---|---|---|
| `DatabaseSchemaSource` | `catalog_tables`, `catalog_columns` | Database `CONTAINS` Table, Table `CONTAINS` Field |
| `CatalogSemanticSource` | `catalog_entities/fields/enum_values` | conceptos + `MAPS_TO` técnicos |
| `TabularStructureSource` | `tabular_tables/columns` | Dataset `CONTAINS` Table `CONTAINS` Field |
| `WorkflowConfigSource` | `workflows.graph/steps` | proceso **DESIGNED**, Workflow `USES` Tool/Agent, Event `TRIGGERS` Workflow |
| `AgentConfigSource` | `agents.tools`, `config_json` | Agent `USES` Tool / KnowledgeSource |
| `SqlUsageSource` | `sql_audit_logs` exitosos, `verified_queries` | términos de negocio + mappings técnicos + gaps |
| `ObservedProcessSource` | `workflow_run_steps` | proceso **OBSERVED** con frecuencia por paso |
| `AuthorityCandidateSource` | `verified_queries` con dependencias | candidato a fuente de verdad |
| `DocumentConceptSource` | `structured_documents/blocks` | conceptos, identificadores técnicos, vigencias, contradicciones |
| `TemporalVersionSource` | `structured_document_versions` | Policy v1 `SUPERSEDED_BY` v2 |
| `KnowledgeGapSource` | `claim_ledger` (conflictos) + divergencias | huecos de conocimiento |

Prioridad del spec §2 (estructurado antes que interpretativo): las fuentes
deterministas están en `STRUCTURAL_SOURCES` y pueden elevar confianza sin
interpretación; las interpretativas acumulan soporte y esperan validación.

### Ejemplo real: "pending"

```
Usuario dice:      "¿cuántas transacciones pending hay?"
SQL exitoso usa:   A1672STO0 IN ('0','')
```

Con `min_runs=3`, actores distintos y sin contradicciones, el motor propone:

```
Concept:  pending
MAPS_TO:  A1672STO0
values:   0, (blank)
```

Una sola ocurrencia no alcanza: `SqlUsageSource` no emite mapping bajo el umbral
y `mapping_confident()` exige runs + corroboración + ausencia de contradicciones.

---

## 3. Resolución de entidades

Capas, de determinista a interpretativa (`EntityResolutionEngine`):

1. **exact canonical match**
2. **alias match**
3. **technical identifier match** (identificadores declarados o el propio nombre técnico)
4. **deterministic normalization** (acentos, separadores, artículos, sufijos legales)
5. **abbreviation / acronym** en ambas direcciones (ADM ↔ Agency Debit Memo)
6. **semantic similarity** (opcional: se inyectan similitudes ya calculadas)
7. **JEV/LLM solo si la ambigüedad persiste** (`adjudicate`) — y su salida sigue
   siendo una sugerencia que requiere validación

Todas las capas se evalúan y luego se decide: si dos entidades empatan, el
resultado es `ambiguous=True`, `matched_id=None`, y se emite una señal para
revisión humana. **Nunca** se fusionan entidades ambiguas.

Cada resultado registra `strategy` y `reason`: se puede auditar por qué se
resolvió (o no) un candidato. El ejemplo del spec (ADM / Agency Debit Memo /
agency debit memo) resuelve al mismo Concept sin LLM.

---

## 4. Confianza

`score_candidate` combina factores explícitos y trazables:

| Factor | Peso | Por qué |
|---|---|---|
| estructural (schema/config) | base 0.9 | verificación determinista |
| base interpretativa | 0.25 | documento/conversación no es verdad |
| fuentes distintas | 0.08 c/u (máx 3) | corroboración cruzada |
| actores distintos | 0.10 c/u (máx 2) | independencia humana |
| ejecuciones exitosas | 0.03 c/u (máx 6) | señal de uso real |
| repetición de observaciones | 0.002 c/u (máx 10) | **casi nulo a propósito** |
| autoridad de la fuente | ×0.4–1.15 | configurable por tenant |
| contradicciones | −0.15 c/u | penalización explícita |
| puerta de independencia | ×0.6 | sin corroboración no se sugiere |

Repetir 50 veces una observación de una sola fuente da ~0.17; cuatro
observaciones corroboradas por tres fuentes y dos actores dan ~0.63.

Umbrales: `SUPPORT_CONFIDENCE` (sugerir) 0.55, `VALIDATE_CONFIDENCE` 0.75.

---

## 5. Procesos: DESIGNED vs OBSERVED

```
DESIGNED  lo que la organización dice que hace   (workflow config)
OBSERVED  lo que realmente corre                 (workflow_run_steps)
```

`compare_processes()` produce la divergencia, base de Process Intelligence:

```
Step C occurs in 82% of observed runs but is absent from process documentation
```

De ahí nacen los **Knowledge Gaps** (`UNDOCUMENTED_STEP`,
`DOCUMENTED_BUT_UNOBSERVED`), que al promoverse se registran como `Finding` del
Learning Engine (`category="KNOWLEDGE_GAP"`) — no se inventa un store paralelo.

---

## 6. Conflictos de compañía

Se **reutiliza el Claim Ledger**: `KnowledgeGapSource` lee `claim_ledger`
buscando mismo sujeto+predicado con objetos distintos. No hay sistema paralelo
de contradicciones. Los documentos también producen `CONTRADICTORY_DEFINITION`
cuando definen el mismo término de dos formas distintas.

---

## 7. Company Context Compiler

El objetivo es explícito: **no enviar el grafo completo al runtime**.

```python
compiled = await CompanyContextCompiler(graph).compile(
    organization_id, "¿dónde se representa pending?", budget=ContextBudget(max_concepts=8)
)
```

Pipeline determinista (sin LLM):

1. **tokens de la petición** — normalizados, sin stopwords
2. **ranking de semillas** — solapamiento léxico × autoridad × confianza × recencia
3. **expansión por grafo** — 2 saltos desde las 3 mejores semillas, acotado
   (`max_depth=2, max_nodes=30, max_edges=80`), respetando vigencia y estados
   terminales: preguntar por "el año pasado" no trae versiones actuales
4. **buckets** — concepts, processes (process+workflow), systems
   (system/service/database/api/tool/agent), rules (rule/policy/kpi/metric)
5. **mappings y dependencias** — `MAPS_TO` del concepto y vecindad verificable
6. **authority** — reglas vigentes por dominio/concepto
7. **memoria** — `MemoryRecallService` (opcional): la memoria dice qué aprendió
   Zent operando; el grafo dice qué es la compañía
8. **presupuesto de tokens** — recorte por sección hasta entrar en el límite

### Presupuesto

```python
ContextBudget(max_concepts=8, max_mappings=8, max_processes=4, max_systems=4,
              max_rules=4, max_authority=4, max_memories=4,
              max_relationships=20, max_tokens_estimate=1500)
```

Validado en el constructor: **nunca sin tope**. Los tests golden fallan si algo
desborda el presupuesto por defecto.

---

## 8. Consumidores

El compilador no está acoplado a ningún consumidor: expone adaptadores.

| Consumidor | Adaptador | Punto de inyección real |
|---|---|---|
| JEV / Judgment Fabric | `to_jev_state()` | `DecisionContext.company_context` → `sanitized_state()` |
| Agent Runtime | `to_agent_context()` | `AgentRunRequest.context` (ya etiquetado y truncado a 6000 chars) |
| Workflows | `to_workflow_section()` | sección de contexto del workflow |
| SQL agent | `to_sql_hints()` | hints de datos; **nunca** SQL generado |

`DecisionContext.company_context` es aditivo: si está vacío, el state —y su
fingerprint de cache— quedan idénticos a antes de esta fase.

`to_sql_hints()` entrega solo datos (`concepto: columna (values: ...)`). No
contiene sentencias SQL y el SQL expert conserva todas sus validaciones.

---

## 9. Jobs

```
event-driven   la ingesta encola (on_document_ingested)
background     worker drena pendientes (FOR UPDATE SKIP LOCKED)
scheduled      el loop encola para organizaciones con actividad
```

- `company_discovery_runs` es el job durable (estado, métricas, error).
- Redis sólo despierta al worker (`rag:company:discovery:queue`).
- La ingesta **nunca** se bloquea: el hook está envuelto en try/except y
  apagado por defecto (`RAG_COMPANY_DISCOVERY_ENABLED=false`).
- El discovery pesado jamás corre dentro de un request (salvo `run_now=true`
  explícito en la API).

---

## 10. Observabilidad

Métricas Prometheus (`company_discovery/metrics.py`, fail-soft):

`company_entities_discovered_total`, `company_entities_confirmed_total`,
`company_relationships_discovered_total`,
`company_relationships_confirmed_total`, `company_discovery_candidates_total`,
`company_entity_resolution_conflicts_total`, `company_knowledge_gaps_total`,
`company_discovery_run_duration_seconds`, `company_context_compile_latency_seconds`,
`company_context_entities_used`, `company_context_relationships_used`,
`company_context_tokens_estimate`.

---

## 11. API

Prefijo `/api/v1/company-discovery`, tenant-scoped, paginada.

| Método | Ruta | Permiso |
|---|---|---|
| GET | `/candidates` | `knowledge:read` |
| GET | `/candidates/{id}` | `knowledge:read` |
| GET | `/candidates/{id}/explain` | `knowledge:read` |
| POST | `/candidates/{id}/validate` | `knowledge:write` |
| POST | `/candidates/{id}/confirm` | `knowledge:write` (+ admin para authority) |
| POST | `/candidates/{id}/reject` | `knowledge:write` |
| GET | `/gaps` | `knowledge:read` |
| GET | `/conflicts` | `knowledge:read` |
| GET | `/stats` | `knowledge:read` |
| POST | `/runs` | `knowledge:write` |
| GET | `/runs` | `knowledge:read` |
| POST | `/context/compile` | `knowledge:read` |
| POST | `/context/preview` | `knowledge:read` |

`POST /candidates/{id}/confirm` es la única puerta al grafo. Sin actor humano,
un candidato interpretativo devuelve `400 cannot_promote`.

---

## 12. Promoción al grafo

| Candidato | Materialización |
|---|---|
| ENTITY | `CompanyEntity` (`AUTO_CONFIRMED` solo si estructura + tipo verificable) |
| RELATIONSHIP | extremos + `propose_relationship` (auto-confirm gate del servicio 5A) |
| MAPPING | concept + field + `MAPS_TO` con `values` y `predicate` en metadata |
| PROCESS | entidad `process` con `mode` y steps en metadata |
| SOURCE_AUTHORITY | regla de authority (requiere admin) |
| KNOWLEDGE_GAP | `Finding` del Learning Engine |
| TERM | entidad `concept` con aliases observados |
| TEMPORAL | entidad con `valid_from/valid_to` + relación `SUPERSEDED_BY` |

Los ids son deterministas (`company_entity_uuid`), así que promover dos veces el
mismo candidato no duplica nodos.

---

## 13. Tests

`tests/test_company_discovery.py` (40), `tests/test_company_discovery_api.py` (3)
y `tests/test_company_discovery_golden.py` (9):

descubrimiento estructurado, conceptos documentales, dedupe, alias,
ambigüedad que no se fusiona, mapping técnico con evidencia acumulada,
proceso observado, designed vs observed, knowledge gap (divergencia y claim),
authority candidate, versión temporal, relevancia del compilador, presupuesto,
aislamiento por tenant (lectura, escritura y promoción), JEV/agent/SQL/workflow
consumen el contexto, y un **end-to-end** descubrir → promover → compilar.

### Golden set

`tests/golden/company_discovery.json` — preguntas empresariales del spec:

| Pregunta | Verifica |
|---|---|
| ¿qué significa pending? | concepto Pending Transaction |
| ¿dónde se representa pending? | mapping a `A1672STO0` con valor `0` |
| ¿qué sistema almacena ticket status? | sistema PXSAUDIT (vía expansión de grafo) |
| ¿qué proceso usa esta tabla? | proceso Reconciliation |
| ¿qué workflow depende de esta API? | workflow invoice-wf |
| ¿qué fuente manda sobre ticket? | authority PXSAUDIT = authoritative |
| ¿cómo funcionaba esta política el año pasado? | Refund Policy v1, sin v2 (temporal) |

---

## 14. Configuración

| Variable | Default | Efecto |
|---|---|---|
| `RAG_COMPANY_DISCOVERY_ENABLED` | `false` | activa worker + hook de ingesta |
| `RAG_COMPANY_DISCOVERY_INTERVAL_SECONDS` | `900` | intervalo del loop |

---

## 15. Artefactos

| Capa | Archivo |
|---|---|
| Dominio | `src/core/domain/company_discovery.py` |
| Puerto | `src/core/ports/company_discovery.py` |
| Adapter Postgres | `src/infrastructure/postgres/company_discovery.py` |
| Migración | `src/infrastructure/db_init/versions/130_company_discovery.py` |
| Motor | `src/company/discovery/engine.py` |
| Fuentes | `src/company/discovery/sources_{structured,config,usage,documents}.py` |
| Resolución | `src/company/discovery/resolution.py` |
| Confianza | `src/company/discovery/confidence.py` |
| Gaps y conflictos | `src/company/discovery/gaps.py` |
| Jobs | `src/company/discovery/jobs.py` |
| Métricas | `src/company/discovery/metrics.py` |
| Context Compiler | `src/company/context.py` |
| API | `src/api/routes/company_discovery.py` |
| Wiring | `src/company/wiring.py` |

---

## 16. Criterio final de la fase

Zent puede convertir documents, schemas, queries, runs, workflows, agents y
memoria en **propuestas estructuradas** de entidades, relaciones, conceptos,
mappings y procesos — y compilar **solo el contexto empresarial relevante** para
cada request, sin que nada inferido se convierta en verdad sin validación.
