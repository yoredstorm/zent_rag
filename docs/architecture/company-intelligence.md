# Company Intelligence — Company Graph

Primera capa de **Company Intelligence** de Zent: pasar de *"conozco documentos"* a
*"comprendo entidades, conceptos, procesos, sistemas, datos, reglas y relaciones dentro de
una organización"*.

**GRAPH-FIRST pero STORAGE-AGNOSTIC.** PostgreSQL es el backend inicial y sigue siendo la
fuente de verdad transaccional. Neo4j no es una dependencia obligatoria: el día que se
justifique, se implementa `Neo4jCompanyGraphRepository` y **ninguna capa superior cambia**.

---

## 1. Principios

| Principio | Consecuencia en el código |
|---|---|
| No reemplazar PostgreSQL | El grafo vive en tablas Postgres (`company_entities`, `company_relationships`, `company_source_authority`) |
| Storage-agnostic | Dominio y servicio dependen solo de `CompanyGraphRepository` (ABC), nunca de SQLAlchemy ni del driver de Neo4j |
| Tipos extensibles | `entity_type` y `relationship_type` son texto normalizado + registry; sin enums rígidos ni proliferación de tablas |
| Nada se auto-confirma | `AUTO_CONFIRMED` solo para relaciones **estructuralmente verificables** |
| Todo tiene provenance | `source`, `source_ref` y `evidence[]` estructurada. Nunca chain-of-thought |
| Tenant isolation | `organization_id` obligatorio en cada operación, incluido el traversal recursivo |

---

## 2. Modelo de entidad — `CompanyEntity`

```python
organization_id      UUID     # tenant, obligatorio
entity_type          str      # normalizado, extensible (registry)
canonical_name       str      # identidad lógica
display_name         str
description          str
domain               str      # 'general' por defecto
aliases              tuple    # "pending", "pendiente", "sin procesar"
status               EntityStatus
confidence           float|None   # [0, 1]
authority_level      SourceAuthorityLevel|None
source               str
source_ref           str
evidence             tuple[ProvenanceRef, ...]
metadata             dict
valid_from / valid_to        # vigencia temporal
first_observed_at / last_observed_at
created_at / updated_at
id                   UUID     # determinista: uuid5(org, entity_type, canonical_name)
```

`id` es **derivado, nunca recibido**: el mismo `(org, tipo, nombre)` produce el mismo UUID en
cualquier proceso → el upsert es idempotente y no hay duplicados por re-ingesta.

**Tipos canónicos iniciales** (`CompanyEntityType`): organization, domain, concept, process,
policy, rule, system, service, database, dataset, table, field, api, knowledge_source,
document, agent, workflow, tool, event, metric, kpi, person, role, team, claim, memory,
decision, finding, experiment, recommendation.

No todos tienen tabla propia: **una sola tabla extensible por tipo de columna** en lugar de
29 tablas. `normalize_entity_type()` acepta tipos nuevos (p. ej. `query_pattern`) sin
migración.

`CompanyRelationship` sigue el mismo patrón: `from_entity_id`, `to_entity_id`,
`relationship_type`, `status`, `confidence`, `source`, `source_ref`, `evidence_refs`,
`valid_from/valid_to`, timestamps.

---

## 3. Tipos de relación

Registry extensible (`RelationshipRegistry`), no enum cerrado. Precargados:

```
BELONGS_TO   CONTAINS    USES        USED_BY     DEPENDS_ON
GOVERNED_BY  AUTOMATES   ASSISTS     CONNECTS_TO READS_FROM
WRITES_TO    DESCRIBES   SUPPORTS    CONTRADICTS MAPS_TO
TRIGGERS     PRODUCES    CONSUMES    OWNS        AFFECTS
RELATED_TO
```

El servicio y otras capas pueden registrar más (`APPLIES_TO`, `CONCERNS`, `IMPROVES`,
`VALIDATES`) en runtime: `RelationshipRegistry.register("concerns")`. Normalización a
`MAYÚSCULAS_CON_GUIONES_BAJOS`; los tipos desconocidos se preservan (no se rechazan).

Relaciones del ecosistema de aprendizaje y memoria se expresan con el mismo registry:

```
Memory   APPLIES_TO  QueryPattern      Finding  AFFECTS    KnowledgeSource
Memory   CONCERNS    Dataset           Experiment VALIDATES Memory
Memory   IMPROVES   RetrievalStrategy Memory   IMPROVES   Process
```

---

## 4. Estados

```
DISCOVERED       observado, sin sustento todavía
SUPPORTED        con evidencia adjunta
CONFIRMED        validado (humano o verificación fuerte)
AUTO_CONFIRMED   SOLO relaciones estructuralmente verificables
CONTRADICTED     evidencia en contra
STALE            vigente pero posiblemente desactualizado
DEPRECATED       fuera de la vista current
REJECTED         descartado (terminal)
```

**Ley de auto-confirmación.** `AUTO_CONFIRMABLE_PAIRS` es un conjunto cerrado de tripletas
verificables contra estructura física:

```python
("database", "CONTAINS", "table")     ("table", "CONTAINS", "field")
("dataset",  "CONTAINS", "field")     ("system", "CONTAINS", "database")
("api",      "CONTAINS", "field")     ("domain", "CONTAINS", "concept")
("organization", "CONTAINS", "team")  ...
```

`NEVER_AUTO_CONFIRM` bloquea explícitamente `MAPS_TO`, `DESCRIBES`, `SUPPORTS`,
`CONTRADICTS`, `GOVERNED_BY`, `AFFECTS`, `RELATED_TO`.

Ejemplo del spec, hecho código:

* `Table PXSAUDIT.A1672 CONTAINS Field A1672STO0` → **auto-confirmable** (lo dice el schema).
* `Field A1672STO0 MEANS "Pending Transaction"` → **nunca** auto-confirmable por inferencia
  LLM; queda `DISCOVERED` y exige confirmación.

`AUTO_CONFIRMED` tampoco se puede asignar a mano por API: el servicio lo rechaza
(`confirm_relationship` con `status=AUTO_CONFIRMED` → 400).

Las transiciones se validan con `assert_status_transition()`: los estados terminales
(`DEPRECATED`, `REJECTED`) no vuelven a `DISCOVERED`.

---

## 5. Temporal validity

Semántica semiabierta `[valid_from, valid_to)`, con `NULL` = abierto:

* `get relationships valid at date X` → `as_of=X`
* `get current relationships` → `current_only=True` (excluye `deprecated`/`rejected`)
* `get history of entity` → `entity_history()` incluye lo deprecado

Esto permite responder *cómo funciona hoy* vs *cómo funcionaba antes* sin duplicar entidades.
Vigencia vive en cada entidad y en cada arista.

---

## 6. Source Authority

**No existe un ranking global único.** La autoridad depende de dominio y concepto, y es
**configurable por tenant**.

```
policy  → official documentation = AUTHORITATIVE
sales   → production DB          = AUTHORITATIVE
```

Cinco niveles (`SourceAuthorityLevel`): `AUTHORITATIVE`, `PRIMARY`, `SECONDARY`,
`INFORMATIONAL`, `UNTRUSTED`.

`CompanyAuthorityService` resuelve por `(dominio, concepto, fuente)` con filtro de vigencia y
desempate por `priority`, sobre la tabla `company_source_authority` (tenant-scoped). Sin regla
vigente → `INFORMATIONAL` (nunca se asume autoridad).

El mapeo desde el catálogo existente (`catalog_authority`, 4 niveles) preserva compatibilidad:
`authoritative→AUTHORITATIVE`, `approved→PRIMARY`, `informational→SECONDARY`,
`external→INFORMATIONAL`.

---

## 7. Business concepts y mappings técnicos

`Concept` soporta nombre canónico, aliases, descripción, dominio, ejemplos y mappings
técnicos **estructurados** (relación `MAPS_TO`, no texto libre):

```
Concept: Pending Transaction
  aliases: pending, pendiente, sin procesar
  MAPS_TO → Table  PXSAUDIT.A1672
  MAPS_TO → Field  A1672STO0
            metadata: {"values": ["0", ""]}
  MAPS_TO → API    /transactions?status=pending
```

`GET /entities/{id}/mappings` devuelve los `MAPS_TO` vigentes. Un concepto puede mapear a
Database Field, Table, API Field, concepto documental, input de workflow o evento — todos son
entidades del mismo grafo.

---

## 8. Procesos, eventos y aprendizaje

No se construye BPMN: el modelo es **suficiente para navegar**. `Process` se relaciona con
steps, systems, rules, owners, workflows, agents, events, inputs y outputs vía `CONTAINS`,
`USES`, `GOVERNED_BY`, `OWNS`, `TRIGGERS`, `PRODUCES`, `CONSUMES`.

Eventos organizacionales (`sale.created`, `inventory.low`, `ticket.exchanged`, `rule.changed`,
`workflow.failed`) son entidades tipo `event` y participan con `TRIGGERS` (→ workflow),
`AFFECTS` (→ process), `PRODUCES`/`CONSUMES` por system, `ASSISTS` por agent.

**No se duplican** Claim, Memory, Finding, Experiment, Recommendation: existen ya en sus
módulos (`src/core/domain/evidence.py`, `memory.py`, `learning_cycle.py`). El grafo los
referencia como entidades (`entity_type` = `claim`/`memory`/`finding`/...) y su provenance
apunta al objeto real vía `ProvenanceRef(kind=CLAIM|MEMORY|EXPERIMENT|..., ref=<id>)`.

---

## 9. Provenance — ¿por qué Zent cree esto?

`ProvenanceRef(kind, ref)` con kinds trazables: `source`, `claim`, `memory`, `conversation`,
`run`, `experiment`, `finding`, `recommendation`, `schema`, `catalog`, `database`, `document`,
`manual`, `evidence`.

`GET /entities/{id}/explain` responde exactamente esa pregunta:

```json
{
  "id": "...", "status": "supported", "confidence": 0.7,
  "source": "schema", "source_ref": "catalog_scan:42",
  "evidence": [{"kind": "document", "ref": "doc-123#p4"}],
  "authority_level": "authoritative"
}
```

Nunca se persiste chain-of-thought: solo referencias localizables.

---

## 10. Puerto — `CompanyGraphRepository`

Contrato de dominio, sin dependencia de almacenamiento:

```python
get_entity()            find_entities()        find_relationships()
neighbors()             traverse()             find_path()
impact_analysis()       entity_history()
upsert_entity()         propose_relationship() confirm_relationship()
deprecate_relationship()
```

Guardarraíles en `GraphTraversalLimits`: `max_depth` (1–10), `max_nodes` (1–5000),
`max_edges` (1–10000). Los límites tienen defaults conservadores y validación en el
constructor: **no hay traversal sin cota**.

`RelationshipFilter` filtra por tipos, estados, vigencia (`as_of`), `current_only` y
`min_confidence`.

`CompanyGraphService` es la capa de negocio: valida extremos en el mismo tenant, decide la
auto-confirmación estructural, expone `explain()`, `concept_mappings()` y las transiciones. La
lógica no vive en el repositorio.

---

## 11. Adapter Postgres

`PostgresCompanyGraphRepository` (migración `129_company_graph.py`):

* **One-hop**: `neighbors()` con filtros y tope de aristas.
* **Multi-hop limitado**: `traverse()` con `WITH RECURSIVE` que filtra por `organization_id`
  en cada salto, corta por `max_depth`, deduplica con `UNION` y evita ciclos con
  `path` (array de UUID) — un ciclo se detecta y se poda, no cuelga la query.
* **Path search**: BFS en memoria sobre el subgrafo ya recolectado y tenant-scoped.
* **Impact analysis**: recorrido agrupado por `entity_type` (`by_type`), devolviendo el grafo
  verificable; **sin conclusiones LLM**.
* **Temporal / status / confidence**: filtros SQL en cada consulta.
* **Paginación** con `limit`/`offset` acotados (máx. 200).

Índices dedicados por `(org, from)`, `(org, to)`, `(org, type)` y parcial por estado current.
Sin extensiones nuevas: solo `uuid-ossp`/`pgcrypto` ya presentes.

---

## 12. Future Neo4j adapter

`Neo4jCompanyGraphRepository` existe en `src/core/ports/company_graph.py` como **stub explícito**
(su constructor levanta `NotImplementedError` con el mensaje de migración). Migrar es:

1. Implementar la clase contra el driver de Neo4j.
2. Cambiar `company_graph_service()` en `src/company/wiring.py`.

Nada más: dominio, servicio, API y tests no saben qué backend está detrás.

```python
def company_graph_service() -> CompanyGraphService:
    return CompanyGraphService(
        Neo4jCompanyGraphRepository(...),   # único cambio
        company_authority_service(),
    )
```

---

## 13. Tenant isolation

`organization_id` en cada método del puerto y en cada `WHERE`, incluido el término recursivo
del CTE (la semilla y **todos** los saltos filtran por tenant). Sin RLS: aislamiento a nivel de
aplicación, igual que el resto de Zent.

Tests dedicados:

* acceso directo cross-tenant (`get_entity`, `neighbors`, `traverse`, `impact`)
* **leakage multi-hop**: un tenant no alcanza nodos ajenos ni en profundidad
* endpoints inexistentes para el otro tenant → `404`, no `403` con datos
* authority por tenant: reglas y resolución aisladas
* extremos de relación cross-tenant → `ValueError`

---

## 14. API

Prefijo `/api/v1/company-graph`, tenant-scoped, paginada.

| Método | Ruta | Permiso |
|---|---|---|
| GET | `/entities` | `knowledge:read` |
| POST | `/entities` | `knowledge:write` |
| GET | `/entities/{id}` | `knowledge:read` |
| GET | `/entities/{id}/explain` | `knowledge:read` |
| GET | `/entities/{id}/history` | `knowledge:read` |
| GET | `/entities/{id}/mappings` | `knowledge:read` |
| GET | `/entities/{id}/neighbors` | `knowledge:read` |
| GET | `/entities/{id}/impact` | `knowledge:read` |
| GET | `/relationships` | `knowledge:read` |
| POST | `/relationships` | `knowledge:write` |
| POST | `/relationships/{id}/confirm` | `knowledge:write` |
| POST | `/relationships/{id}/deprecate` | `knowledge:write` |
| GET | `/paths` | `knowledge:read` |
| GET | `/authority` | `knowledge:read` |
| POST | `/authority` | admin de organización |

Paginación: `limit` (1–200) + `offset`, devueltos en la respuesta.

---

## 15. Diagrama

```
        PostgreSQL                    Qdrant
   transactional truth          semantic retrieval
   (tenants, ledgers,           (embeddings, chunks,
    grafos, claims)              búsqueda vectorial)
            │                            │
            └────────────┬───────────────┘
                         ▼
                   Company Graph                 ← primera capa de
        entidades + relaciones + provenance        Company Intelligence
        status + confidence + authority
        vigencia temporal (valid_from/to)
                         │
                         ▼
                        JEV                    ← Judgment Fabric:
                juicio, routing, gate            decide qué hacer
                         │
                         ▼
                        LLM                    ← reasoning / generation
              (razona sobre el grafo,            (nunca fuente de verdad)
               nunca lo define)
```

Cada capa tiene un rol único: Postgres guarda la verdad transaccional, Qdrant recupera
semánticamente, el Company Graph **relaciona**, el JEV **juzga**, el LLM **razona y genera**.
Ninguna capa reemplaza a otra y el grafo no es un almacén de vectores ni un motor de decisión.

---

## 16. Criterio de éxito

Zent puede representar una empresa como un conjunto navegable de concepts, processes, systems,
data, rules, agents, workflows, knowledge y memories — con relaciones, evidencia, confianza,
autoridad y vigencia temporal — **sin quedar acoplado a Neo4j**: PostgreSQL es el backend
inicial y el puerto de dominio permite cambiar de motor sin tocar las capas superiores.

---

## 17. Estado de implementación

| Fase | Artefacto |
|---|---|
| Dominio | `src/core/domain/company_graph.py` |
| Puerto | `src/core/ports/company_graph.py` |
| Adapter Postgres | `src/infrastructure/postgres/company_graph.py` |
| Servicio + Authority | `src/company/service.py` |
| Wiring (composition root) | `src/company/wiring.py` |
| Migración | `src/infrastructure/db_init/versions/129_company_graph.py` |
| API | `src/api/routes/company_graph.py` |
| Tests | `tests/test_company_graph.py` (22) |

### Impact query foundation

`impact_analysis(entity_id)` descubre dependencias directas e indirectas y las agrupa por tipo
(affected processes, agents, workflows, systems, data, knowledge). Devuelve **solo grafo
verificable**: la interpretación LLM es una fase posterior y consumirá esta salida como
evidencia, no como prompt libre.
