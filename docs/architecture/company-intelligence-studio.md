# Company Intelligence Studio

Tercera capa de **Company Intelligence**. La Fase 5A modeló el *Company Graph*, la
5B lo alimentó y lo compiló en contexto. Esta fase lo **hace navegable**: una
sección del portal donde una persona entiende cómo funciona su empresa, qué
depende de qué, qué fuente manda y qué falta saber.

---

## 1. Qué responde

| Pregunta | Vista |
|---|---|
| ¿Qué sabe Zent de mi empresa? | Overview |
| ¿Cómo se conecta todo? | Company Map |
| ¿Qué procesos existen? | Processes + Process Intelligence |
| ¿Qué sistemas los soportan? | Systems |
| ¿Qué datos utilizan? | Data + tablas y campos |
| ¿Qué reglas los gobiernan? | Rules |
| ¿Qué agentes y workflows participan? | Relaciones entrantes del proceso y del concepto |
| ¿Qué fuente es la verdad? | Source Authority |
| ¿Qué está incompleto? | Knowledge Gaps |
| ¿Qué está contradicho? | Knowledge Gaps + conflictos del Claim Ledger |
| ¿Qué cambiaría si modifico X? | Impact |
| ¿Qué aprendió Zent sobre esto? | Aprendizaje por entidad |

---

## 2. Arquitectura

```
portal /company-intelligence/*          (React + Vite, 14 rutas)
        │  api<T>(...)
        ▼
/api/v1/company-intelligence/*          src/api/routes/company_studio.py
        │
        ▼
CompanyStudioService                    src/company/studio.py     (vistas)
CompanyAskService                       src/company/ask.py        (NL)
        │
        ├── CompanyGraphService      (puerto del grafo: 5A)
        ├── CompanyDiscoveryRepository (candidatos y corridas: 5B)
        ├── MemoryFoundationService  (memoria operativa: Fase 4)
        ├── PostgresLearningCycleStore (findings y experimentos)
        └── CompanyAuthorityService  (source authority: 5A)
```

**Regla dura (§25)**: la Studio consume el **puerto**, nunca SQL propio del grafo.
Un test lo verifica leyendo el código fuente de `studio.py` y comprobando que no
menciona tablas `company_*`. Cuando se agregue el adaptador de Neo4j, nada de
esta capa cambia.

---

## 3. Company Map (§3/§4/§24)

No se renderiza el grafo completo. La vista pide una vecindad acotada:

```
GET /map/{entity_id}?max_nodes=25&max_edges=60&max_depth=1&direction=both
```

- Layout radial determinista en SVG (sin librería de grafos).
- Click en un nodo lo convierte en nueva raíz: la expansión es **lazy**.
- "Expandir más" sube `max_nodes` (tope 200).
- El backend corta con `GraphTraversalLimits`; `truncated: true` avisa que hay más.
- Aristas no confirmadas se dibujan punteadas y con la etiqueta "(no confirmada)".

Filtros (§23): tipo de entidad, tipo de relación, estado, confianza mínima, fecha
(`as_of`), dominio, y búsqueda por texto.

---

## 4. Confianza visible (§10/§22)

Ninguna vista presenta una relación DISCOVERED como si fuera CONFIRMED:

- Cada arista viaja con `status`, `confidence`, `provenance`, `valid_from`,
  `valid_to` y `confirmed`.
- El mismo dato aparece en texto además del color (`Badge` con etiqueta), nunca
  color solo.
- En impacto, el lenguaje cambia según la evidencia (§11):

| Camino | Lenguaje |
|---|---|
| Todos los eslabones confirmados | "Camino confirmado" |
| Algún eslabón no confirmado | "Camino con relaciones no confirmadas: impacto potencial" |

---

## 5. Impacto (§9/§10/§11)

```
GET /entities/{id}/impact?direction=both&max_depth=3
```

Devuelve:

- `direct`: relaciones de primer salto con su certeza (`will` / `may`).
- `indirect`: entidades alcanzadas más allá del primer salto.
- `affected`: agrupado en workflows, agents, processes, systems, data, knowledge, rules.
- `paths`: caminos cortos (máximo 6) con `explanation` paso a paso y `certainty`
  calculada por el eslabón más débil.

Los caminos se calculan sobre la vecindad ya acotada: no hay traversal nuevo ni
sin límite.

---

## 6. Process Intelligence (§7/§8)

```
GET /processes/{id}
```

Separa **diseñado** (config de workflow) de **observado** (`workflow_run_steps`),
con:

- pasos y su frecuencia sobre las corridas reales,
- sistemas, agentes, reglas, eventos y workflows asociados,
- **desviación**: retrabajo detectado en la secuencia observada.

Ejemplo real de la vista:

```
Expected:  A → B → C → D
Observed:  A → B → C → B → C → D
Resultado: "Retrabajo en 50% de 4 corridas observadas."
```

El motor de desviación **no afirma causalidad**: reporta frecuencia y la secuencia
canónica, con la nota explícita `no causation claimed`.

---

## 7. Source of Truth (§13)

```
GET /source-of-truth
```

Por concepto: autoritativa, primaria, secundaria, informativa, con prioridad y
vigencia. Los conceptos sin fuente autoritativa se listan aparte y alimentan los
Knowledge Gaps. Los conflictos salen del **Claim Ledger** (mismo sujeto y
predicado con objetos distintos), no de un sistema paralelo.

---

## 8. Knowledge Gaps (§14)

Dos orígenes, siempre distinguidos en la UI:

| Origen | Cómo se calcula |
|---|---|
| `discovery` | Candidatos de la Fase 5B: paso sin documentar, término sin mapeo, definición contradictoria |
| `graph` | Derivado del grafo: concepto sin autoridad, proceso sin responsable, relación obsoleta |

Tipos soportados: `undocumented_step`, `documented_but_unobserved`,
`no_authoritative_definition`, `missing_technical_mapping`,
`contradictory_definition`, `ambiguous_entity`, `missing_process_owner`,
`stale_relationship`.

---

## 9. Cambios (§15/§16)

- `GET /changes?since=…`: timeline de entidades y candidatos con su marca temporal.
- `GET /entities/{id}/changes?as_of=…`: compara la entidad y sus relaciones contra
  una fecha, y muestra qué se agregó, qué se quitó y el historial.

La vigencia se respeta en todo el recorrido: el compilador de contexto y la
expansión del grafo filtran por `valid_from`/`valid_to`, así que preguntar por el
año pasado no trae versiones actuales.

---

## 10. Institucional y riesgos (§17/§18)

- **Institucional**: personas, roles, equipos y responsables por proceso,
  derivados de relaciones explícitas `OWNS` y `GOVERNED_BY`. Nunca se infiere
  quién es responsable de quién. Los procesos sin dueño se listan como pendiente,
  no como dato.
- **Riesgos**: candidatos detectados por el grafo (dependencia única, dependencia
  compartida, autoridad única). Todos se marcan `level: "potential"`: son
  candidatos a revisar, no riesgos confirmados.

---

## 11. Conocimiento y salud (§19)

`GET /health` combina seis componentes medidos, no decorativos:

| Componente | Qué mide |
|---|---|
| `graph_confirmation` | Entidades confirmadas sobre el total |
| `authority_coverage` | Conceptos con fuente autoritativa |
| `conflict_rate` | Entidades no contradichas |
| `freshness` | Entidades y relaciones no obsoletas |
| `documentation` | Procesos sin huecos de documentación |
| `ownership` | Procesos con responsable declarado |

Cada componente trae su `detail` numérico. No hay métricas sin consulta detrás.

---

## 12. Memoria y conversaciones (§20/§21)

- `GET /entities/{id}/memory`: memoria operativa y findings ligados a la entidad.
- `GET /entities/{id}/conversations`: conversaciones donde la entidad fue relevante.

El store de memoria indexa por **patrón de comportamiento**, no por entidad. La
Studio consulta primero por nombre (camino SQL) y completa con las memorias
recientes cuyo patrón, título o descripción mencionan la entidad o sus aliases.
Todo acotado (tope de lectura y de resultados).

---

## 13. Ask your Company (§12)

```
POST /ask  { "question": "¿qué se ve afectado si PXSAUDIT no está disponible?" }
```

Pipeline:

```
pregunta
   │
   ├── CompanyContextCompiler   → contexto acotado (conceptos, mapeos, procesos, authority)
   │
   ├── Judgment Fabric (JEV)    → clasifica la intención (10 intenciones)
   │     └── si no hay JEV: router léxico determinista (fallback honesto)
   │
   ├── traversal del grafo      → impacto, dependencias, procesos, autoridad, gaps, cambios
   │
   └── conocimiento documental  → solo si la intención lo pide (recuperación, sin LLM)
```

La respuesta siempre trae:

- `intent` y `decision.provider` (`jev` o `lexical`): se ve **con qué** se decidió.
- `certainty`: `confirmed` o `may`, alineado con la evidencia.
- `evidence[]`: entidades, mapeos, caminos, memorias, fragmentos de documento.
- `context_used`: cuántos tokens y cuántas entidades se usaron, y si se recortó.

El JEV **clasifica, no inventa**: si falla, el router léxico decide y la respuesta
lo declara. El router léxico cuenta señales por intención (no se queda con la
primera palabra que reconoce), así que "¿qué aprendió Zent sobre esta tabla?"
gana `learned` sobre `representation`.

### Contexto de página

`POST /ask` acepta `entity_id`. Sirve para preguntas que no nombran nada:
"¿qué aprendió Zent sobre esta tabla?" se resuelve con la entidad de la página
desde la que se pregunta. Si tampoco hay contexto, la respuesta lo dice y pide
nombrar la entidad en lugar de inventar un objetivo.

### Asimetría de los mapeos

Un campo no "se mapea a" conceptos: los conceptos se mapean **hacia** él. Por eso
`entity_detail` expone `mapped_by_concepts` para entidades técnicas, y la
pregunta "¿dónde se representa A1672STO0?" responde con el concepto que lo
representa, no con un vacío.

### Procesos

"¿Qué proceso usa A1672?" no trata la tabla como proceso: busca procesos y
workflows relacionados en ambas direcciones y los enumera con su tipo de
relación y estado.

---

## 14. Demo (§26/§27)

```bash
python -m src.scripts.company_demo_seed --list
python -m src.scripts.company_demo_seed --org <uuid> --with-candidates
```

Siembra el dominio **Fare Audit** (idempotente):

| Entidades | Relaciones |
|---|---|
| ATPCO, Record2, Carrier Code, A1672, A1672STO0, PXSAUDIT | ATPCO `PROVIDES` Record2 |
| Fare Audit, Reconciliation Process, Audit Agent | Record2 `CONTAINS` Carrier Code |
| Reconciliation Workflow, Pending Transaction, Fare Audit Rule, Audit Team | A1672 `BELONGS_TO` PXSAUDIT |
| | Fare Audit `READS_FROM` A1672 |
| | Audit Agent `ASSISTS` Fare Audit |
| | Reconciliation Workflow `AUTOMATES` Reconciliation Process |
| | Pending Transaction `MAPS_TO` A1672STO0 (valores `0`, blank) |

Más: memoria operativa "structured field lookup", Finding "Excel retrieval issue",
Experimento "structured exact" y reglas de authority (PXSAUDIT autoritativa sobre
Pending Transaction).

Preguntas demo que la Studio responde con este escenario:

1. "¿Qué es Record2?"
2. "¿Dónde se representa Carrier Code?"
3. "¿Qué proceso usa A1672?"
4. "¿Qué depende de ATPCO?"
5. "¿Qué se vería afectado si PXSAUDIT no está disponible?"
6. "¿Cuál es la fuente de verdad de ticket status?"
7. "¿Qué aprendió Zent sobre esta tabla?"

---

## 15. API

Prefijo `/api/v1/company-intelligence`, tenant-scoped, permisos `knowledge:read`.

| Método | Ruta |
|---|---|
| GET | `/overview` |
| GET | `/map/{entity_id}` |
| GET | `/entities` |
| GET | `/entities/{entity_id}` |
| GET | `/entities/{entity_id}/impact` |
| GET | `/entities/{entity_id}/changes` |
| GET | `/entities/{entity_id}/memory` |
| GET | `/entities/{entity_id}/conversations` |
| GET | `/concepts/{entity_id}` |
| GET | `/processes/{entity_id}` |
| GET | `/relationships` (vía Company Graph) |
| GET | `/domains` |
| GET | `/source-of-truth` |
| GET | `/knowledge-gaps` |
| GET | `/changes` |
| GET | `/institutional` |
| GET | `/risks` |
| GET | `/health` |
| POST | `/ask` |

---

## 16. Frontend

`portal/src/pages/companyIntelligence/` (14 rutas, sección "Company Intelligence"
en el grupo Conocimiento del sidebar):

```
/company-intelligence              Overview
/company-intelligence/map          Company Map
/company-intelligence/concepts     Conceptos        ┐
/company-intelligence/processes    Procesos         │
/company-intelligence/systems      Sistemas         ├ listado por tipo
/company-intelligence/data         Datos            │
/company-intelligence/rules        Reglas           │
/company-intelligence/events       Eventos          ┘
/company-intelligence/relationships
/company-intelligence/authority
/company-intelligence/gaps
/company-intelligence/changes
/company-intelligence/people
/company-intelligence/ask
/company-intelligence/entity/:id   Detalle con pestañas (resumen, relaciones, impacto, proceso, aprendizaje, cambios)
```

Pestañas del detalle: **Resumen** (descripción, aliases, mapeos técnicos, fuentes,
gaps), **Relaciones** (entrantes, salientes y vecindad agrupada), **Impacto**,
**Proceso**, **Aprendizaje**, **Cambios**.

---

## 17. Tests

| Suite | Qué cubre |
|---|---|
| `tests/test_company_studio.py` (40) | overview, map acotado y filtrado, detalle, concepto, proceso y desviación, impacto con certeza, autoridad, gaps (discovery + graph), cambios y comparación temporal, institucional, riesgos potenciales, salud, memoria y conversaciones, Ask (intención léxica, juez, juez roto, procesos relacionados, mapeos inversos, contexto de página, tenant), contrato del puerto |
| `tests/test_company_studio_api.py` (11) | seed idempotente, endpoints, preguntas demo §27, aislamiento por tenant, auth |
| `portal/.../companyIntelligence.test.tsx` (8) | overview, gaps, autoridad, ask con evidencia, mapa con aristas no confirmadas, detalle, institucional |
| `tests/test_company_graph.py`, `test_company_discovery*.py` | capas 5A y 5B (sin regresiones) |

### Entorno de test del portal

`vite.config.ts` fija `test.env.NODE_ENV=development`: con el build de producción
de React, `react.act` no existe y @testing-library/react no puede renderizar (la
suite entera fallaba antes de esta fase).

---

## 18. Configuración

Las vistas funcionan sin flags. Solo el descubrimiento (que alimenta candidatos,
gaps y procesos observados) se activa aparte:

| Variable | Default | Efecto |
|---|---|---|
| `RAG_COMPANY_DISCOVERY_ENABLED` | `false` | worker de descubrimiento y hook de ingesta |

---

## 19. Artefactos

| Capa | Archivo |
|---|---|
| Vistas compuestas | `src/company/studio.py` |
| Exploración NL | `src/company/ask.py` |
| Demo seed | `src/company/demo_seed.py` + `src/scripts/company_demo_seed.py` |
| API | `src/api/routes/company_studio.py` |
| Wiring | `src/company/wiring.py` |
| Frontend | `portal/src/pages/companyIntelligence/*`, `portal/src/components/CompanyIntelligenceLayout.tsx`, `portal/src/lib/companyNav.ts` |

---

## 20. Criterio final

Un usuario puede abrir Zent y responder, con evidencia y sin ambigüedad sobre la
confianza: qué sabe Zent de su empresa, cómo se conecta todo, qué procesos
existen, qué sistemas los soportan, qué datos usan, qué reglas los gobiernan, qué
agentes y workflows participan, qué fuente es la verdad, qué está incompleto, qué
está contradicho, qué cambiaría si modifica algo y qué aprendió Zent al respecto.
