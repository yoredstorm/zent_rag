# Knowledge OS — Rediseño de experiencia (UX/UI)

> Estado: arquitectura aprobada para implementación.
> Sustituye la IA de "operador de pipeline" (`Resumen · Fuentes · Modelo · Calidad · Evaluación`)
> por una experiencia de **cerebro empresarial vivo**.
> La tecnología no cambia: el backend ya es el Knowledge OS canónico
> (`docs/architecture/knowledge-os.md`). Cambia lo que el usuario ve y siente.

## 1. Diagnóstico del módulo actual

Lo que existe (verificado en código y datos):

- Backend canónico completo: `knowledge_canonical_objects`, `knowledge_edges`,
  `knowledge_assertions`, `evidence_ledger`, `knowledge_conflicts`,
  `context_gaps`, `knowledge_compilations`, `knowledge_events`.
- API real: `/knowledge/overview`, `/health`, `/domains`, `/objects`,
  `/objects/{id}` (+ edges, assertions, evidence, versions, lineage, impact),
  `/graph`, `/search`, `/gaps`, `/conflicts`, `/quality`, `/activity`,
  `/learning/events`, `/learning/runs`, `/compilations`.
- Portal actual: 5 pilares con estética de panel de control
  (`Overview.tsx`, `Model.tsx`, `Quality.tsx`, `Sources.tsx`, `Activity.tsx`)
  y widgets `ks-*` de sesión de aprendizaje.

Problemas de experiencia:

1. El foco es el pipeline ("runs", "etapas", "indexado"), no el conocimiento.
2. Los números no cuentan una historia: falta delta temporal, pulso y
   interpretación humana de la salud.
3. El explorador es una tabla/drawer; no hay recorrido
   `dominio → objeto → hecho → evidencia → fuente`.
4. No hay vista propia de objeto de conocimiento con historial y conflictos.
5. La actividad se muestra como logs técnicos, no como aprendizaje.
6. Lenguaje mixto: "indexando", "chunks", "embeddings" en el flujo principal.
7. IA de 5 pilares plana: todo pesa igual; el usuario no sabe dónde mirar.

## 2. Principio central

```
INFORMACIÓN → COMPRENSIÓN → CONOCIMIENTO → CONEXIONES → RAZONAMIENTO
```

Nunca:

```
ARCHIVO → INDEXACIÓN → VECTOR DB → COMPLETADO
```

Ley dura: **cada elemento visual representa un dato real**. Sin mocks, sin
números decorativos, sin animación sin evento. Si el backend no lo sabe, la UI
no lo dibuja (estado "no medido", no cero).

## 3. Lenguaje del producto

Dos registros explícitos:

| Registro | Dónde | Ejemplos |
|---|---|---|
| Humano (default) | Toda la experiencia principal | Leyendo · Comprendiendo · Descubriendo · Organizando · Conectando · Verificando · Aprendido · Enriquecido |
| Técnico | Sección "Avanzado", tooltips de detalle, panel de compilaciones | chunks, embeddings, indexación, stages, Qdrant |

Traducción canónica (frontend, `lib/knowledgeLanguage.ts`):

- `stage.chunking` → "Organizando el contenido"
- `stage.embedding` → "Comprendiendo significados"
- `stage.indexing` → "Preparando para responder"
- `learning run` → "ZENT está aprendiendo de {fuente}"
- Evento `discovery` → "Descubrió"
- Evento `ai` → "Comprendió"
- Evento `validation` → "Verificó"
- Evento `indexing` → "Organizó"
- `system` → "Sistema"

Ejemplo de estado:

> **ZENT está comprendiendo este documento**
> 27 conceptos identificados · 8 relaciones encontradas · 3 reglas detectadas

## 4. Information architecture

Pilares (5 + Avanzado), todos con URL estable:

| Pilar | Ruta | Pregunta que responde |
|---|---|---|
| Inicio | `/knowledge` | ¿Qué sabe ZENT y qué cambió? |
| Explorador | `/knowledge/explorer` | ¿Cómo está organizado lo que sabe? |
| Salud | `/knowledge/health` | ¿Qué conocimiento necesita atención? |
| Fuentes | `/knowledge/sources` | ¿De dónde proviene cada conocimiento? |
| Actividad | `/knowledge/activity` | ¿Qué está aprendiendo / qué acaba de descubrir? |
| Avanzado | (disclosure) | Evaluación, Estudio semántico, Playground, Trabajos, Documentos, Colecciones, Workspaces, Glosario, Catálogo, Conectores, Compilaciones |

Rutas nuevas:

- `/knowledge/objects/:objectId` — vista de objeto de conocimiento.
- `/knowledge/search?q=` — búsqueda universal.

Redirects legados (no romper bookmarks):

- `/knowledge/model` → `/knowledge/explorer`
- `/knowledge/map` → `/knowledge/explorer?view=graph`
- `/knowledge/quality` → `/knowledge/health`
- `/knowledge/review` → `/knowledge/health?tab=conflicts`
- `/knowledge/improvements` → `/knowledge/health?tab=gaps`
- `/knowledge/learning` → `/knowledge/activity`

## 5. Pantallas

### 5.1 Knowledge Home (`/knowledge`)

Orden de lectura (overview → drill-down):

1. **Hero vivo**: "ZENT KNOWLEDGE / Tu conocimiento empresarial está creciendo"
   + contadores reales (entidades, relaciones, hechos, reglas, fuentes)
   + delta 24 h + Knowledge Health con interpretación en una frase.
2. **Knowledge Pulse**: visualización de actividad cognitiva real.
   Nodos = dominios/tipos con volumen real; pulsos = eventos reales de
   `knowledge_events` / `knowledge/activity`; tooltip por nodo con la historia
   ("Record 4 fue enriquecido por una nueva fuente").
3. **Knowledge Delta**: ventana `24 h · 7 d · 30 d · personalizado`,
   altas por tipo, conceptos enriquecidos, reglas actualizadas, conflictos
   resueltos + timeline de barras real.
4. **Knowledge Domains**: áreas descubiertas con cobertura, objetos,
   relaciones, fuentes, última actualización, conflictos y actividad.
5. **Necesita atención**: conflictos, gaps, fuentes degradadas, sin evidencia.
6. **Aprendizaje reciente**: últimos eventos humanos + compilaciones.
7. Búsqueda universal (omnibox) siempre visible en el hero.

### 5.2 Explorador (`/knowledge/explorer`)

Recorrido `Dominio → Tema → Concepto/Entidad → Hecho → Evidencia → Fuente`.

- Columna izquierda: dominios reales (de `/domains`) con conteos.
- Al elegir un dominio, el centro muestra sus **temas** (tipos de conocimiento
  con conteo y cobertura reales, `domains[].by_type`).
- Al elegir un tema, la lista se filtra por ese tipo; la ruta de exploración
  queda visible (`Dominio / Tema`) y se puede volver atrás.
- Grafo como vista alternativa (`?view=graph`) con foco y expansión,
  limitado a vecindario (nunca miles de nodos).
- Cada objeto abre `/knowledge/objects/:id`.

### 5.3 Objeto de conocimiento (`/knowledge/objects/:id`)

Panel/página propia con:

- **Resumen**: qué es, qué entiende ZENT, tipo, estado, confianza explicable.
- **Relaciones**: edges entrantes/salientes con predicado humano.
- **Hechos**: assertions con confianza, método y estado.
- **Reglas / Métricas / Ejemplos**: según tipo.
- **Evidencia**: `evidence_ledger` con excerpt, página/sección, fuente.
- **Historial**: versiones reales (`knowledge_object_versions`).
- **Conflictos**: conflictos abiertos del objeto.
- **Impacto**: qué depende de este objeto (`/impact`).

### 5.4 Salud (`/knowledge/health`)

- Overall + interpretación humana ("Tu Knowledge OS está saludable…").
- Dimensiones con score, razón, fórmula, issues (ya vienen explicables).
- Tabs: Conflictos · Gaps · Cobertura · Evidencia · Duplicados.
- Cada métrica enlaza a la acción (resolver, ver fuente, ver objeto).

### 5.5 Fuentes (`/knowledge/sources`)

Biblioteca existente, demotada a origen:

- Al abrir una fuente: qué aportó (entidades/hechos/relaciones/reglas/evidencias),
  qué enriqueció, qué actualizaciones detectó.
- Los datos de aporte salen de `knowledge_compilations` + evidencia.

### 5.6 Actividad (`/knowledge/activity`)

Feed de aprendizaje en lenguaje humano:

- Agrupación de eventos repetitivos ("ZENT aprendió 27 Carrier Codes").
- Filtros: ventana temporal, fuente, categoría.
- Delta del período arriba.
- Los runs técnicos quedan en Avanzado → Trabajos.

### 5.7 Búsqueda universal (`/knowledge/search?q=`)

Busca objetos canónicos (conceptos, entidades, reglas, métricas, términos,
tablas, fuentes, documentos) y agrupa por tipo; al abrir un resultado cae en la
vista de objeto con sus relaciones y evidencia. Reutiliza `/knowledge/search`.

### 5.8 Empty state

"ZENT todavía no conoce tu negocio." + "Agrega tus primeras fuentes y observa
cómo empieza a construir conocimiento." + Knowledge Pulse inicial (sin
partículas falsas: solo el contorno del sistema).

### 5.9 Live Learning (ingesta)

La carga de fuentes es una sesión observable (`/knowledge/sessions/:id`), no un
uploader. Todo viene de eventos semánticos reales del Knowledge Compiler y del
detalle durable de la sesión:

- **Hero**: "ZENT está aprendiendo", fuentes comprendidas (19/25), contadores
  reales (conceptos, hechos, relaciones, reglas, evidencias) y clasificación
  viva Nuevo · Reforzado · Actualizado · Conectado · Conflicto · Ignorado.
- **Etapas cognitivas** expandibles: Leyendo (parser), Comprendiendo
  (Semantic Reconstruction: estructura, continuidad y significado),
  Organizando (entity resolution), Conectando (knowledge graph),
  Verificando (evidence linking), Aprendido (indexes), con contadores reales.
- **Semantic Reconstruction visible**: "ZENT reconstruyó 18 bloques que estaban
  divididos por el formato original", "Detectó 12 tablas", "Reconoció la
  estructura de 3 hojas de cálculo", "Descartó 7 fragmentos incompletos"
  (eventos `SEMANTIC_RECONSTRUCTED`, `CONTINUATIONS_MERGED`,
  `FRAGMENTS_REJECTED`, `SCHEMAS_INFERRED`).
- **Knowledge Pulse central**: núcleo ZENT, nodos de la sesión (nuevos vs ya
  conocidos), relaciones reales y pulsos por evento (ENTITY_DISCOVERED,
  RELATIONSHIP_DISCOVERED, ENTITY_MERGED, FACT_REINFORCED, CONFLICT_DETECTED).
  Pantalla completa disponible; sin actividad no hay animación.
- **Momentos importantes**: solo hitos (conexiones entre áreas conocidas,
  versiones nuevas, conflictos, consolidaciones, descubrimientos grandes).
- **Conocimiento existente**: reencuentros reales (ENTITY_MATCHED / MERGED) con
  contadores de refuerzo y enriquecimiento.
- **Descubrimientos**: feed agrupado en lenguaje humano (los eventos de alta
  frecuencia llegan con `payload.count` + muestras).
- **Fichas por archivo**: checklist de etapas con conteos por fuente; Excel/CSV
  con su estructura (hojas, tablas, columnas, filas, claves, relaciones) y las
  tablas reconocidas, sin animar filas.
- **Resumen final**: "ZENT aprendió esta información", delta, antes/ahora,
  qué cambió y CTAs (explorar, preguntar, mapa, conflictos, fuentes).
- **Modo técnico**: drawer con eventos crudos, contadores, jobs y
  compilaciones. Disponibilidad parcial y errores por fuente sin detener la
  sesión.
- **Replay**: la sesión se reabre con su historial durable; el resumen y los
  hitos se reconstruyen de los mismos eventos.

### 5.10 Knowledge Map (`/knowledge/map`)

Representación navegable del conocimiento con **zoom semántico** y LOD real:

- Nivel 1 Dominios (clusters con tamaño por objetos y pulse si hay actividad).
- Nivel 2 Temas (tipos de conocimiento del dominio, `domains[].by_type`).
- Nivel 3 Objetos (grafo del tema con relaciones reales del backend).
- Nivel 4 Entidad (vecindario enfocado, `focus_id` + depth).
- Nunca se renderiza el grafo completo: cada nivel pide solo lo que se ve.
- Click inspecciona, doble click profundiza, breadcrumb y URL compartible.
- Inspector: entity card, Knowledge strength explicable (componentes reales de
  `confidence_detail` + fuentes independientes + consistencia), relaciones,
  evidence path ("¿cómo sabe ZENT esto?"), timeline de versiones y vigencias,
  conflictos y preguntas abiertas.
- Acciones desde el nodo: explorar, preguntar a ZENT (prefill de `/chat?q=`),
  ver fuentes, compartir vista.
- Rail de inteligencia: Knowledge Health, cobertura real por dominio, evolución
  7 días, aprendido recientemente y vacíos.
- Filtros básicos (tema, confianza) y avanzados (estado, solo conflictos,
  cambios recientes) sin saturar la vista inicial.

## 6. Design system de conocimiento

Componentes nuevos (`portal/src/components/knowledge/`), construidos sobre
las primitivas `ui/` y los tokens de `index.css`:

| Componente | Dato real |
|---|---|
| `KnowledgeMetric` | counts del overview |
| `KnowledgePulse` | events + activity + domains |
| `KnowledgeNode` / `KnowledgeConnection` | graph / domains |
| `KnowledgeCard` | contenedor base |
| `EvidenceBadge` | evidence_ledger |
| `SourceBadge` | catalog_sources / kb_sources |
| `ConfidenceBadge` | confidence + confidence_detail (ya existe en `knowledgeLearning/`) |
| `HealthIndicator` | knowledge_health |
| `LearningEvent` | knowledge_events |
| `KnowledgeDelta` | endpoint nuevo `/knowledge/delta` |
| `ConflictCard` | knowledge_conflicts |

Reglas: sin gradientes decorativos, un accent (teal), bordes hairline,
tipografía Geist/Geist Mono, `tabular-nums` en todo dato numérico.

## 7. Data mapping (live, sin mocks)

| UI | Endpoint |
|---|---|
| Hero counts + health | `GET /api/v1/knowledge/overview` |
| Delta 24 h / 7 d / 30 d | `GET /api/v1/knowledge/delta?window=` (nuevo) |
| Pulse | `GET /api/v1/knowledge/activity` + `GET /api/v1/knowledge/learning/events` + `GET /api/v1/knowledge/domains` + `GET /api/v1/knowledge/stream` (SSE) |
| Domains | `GET /api/v1/knowledge/domains` |
| Explorer | `GET /api/v1/knowledge/objects` + `/domains` |
| Graph | `GET /api/v1/knowledge/graph` |
| Object view | `GET /api/v1/knowledge/objects/{id}` (+ `/edges`, `/evidence`, `/history`, `/impact`) |
| Health | `GET /api/v1/knowledge/health` + `/quality` + `/conflicts` + `/gaps` |
| Activity | `GET /api/v1/knowledge/activity` + `/learning/events` + `/compilations` |
| Search | `GET /api/v1/knowledge/search` |
| Fuentes | endpoints existentes de sources/documents/compilations |
| Live Learning (sesión) | `GET/POST /api/v1/knowledge/sessions` + `/{id}` + `/{id}/events` + `/{id}/feed` + `/{id}/graph` + `/{id}/stream` (SSE) |
| Modo técnico de sesión | eventos crudos + `GET /api/v1/knowledge/compilations` (filtrado por fuente) |
| Knowledge Map | `GET /knowledge/domains` + `/graph` (focus/depth/limits) + `/objects/{id}` (+ evidencia, versiones) + `/conflicts` + `/health` + `/quality` + `/gaps` + `/delta` |

Reglas de error: 503 tipado = estado de error con reintento; nunca ceros.

## 8. Motion

- Solo `transform`/`opacity`; duraciones 120–420 ms (`--dur-*`).
- Entrada de tarjeta: `opacity 0 + translateY(6px)`.
- Nodo nuevo en Pulse: `scale .6 → 1` con spring moderado, una vez.
- Relación nueva: trazo de línea con `stroke-dashoffset` (≤ 500 ms).
- Conocimiento reforzado: pulse de opacidad sobre nodo existente.
- Conflicto: transición a tono `warn`, sin parpadeo.
- `prefers-reduced-motion`: se eliminan trazos, springs y pulsos; queda el
  cambio de opacidad/color.

## 9. Densidad y progressive disclosure

- Nivel 1: qué ocurre (hero, pulse, delta).
- Nivel 2: por qué (dominios, salud, atención).
- Nivel 3: detalle (vista de objeto, evidencia, fórmulas).
- Nivel 4: técnico (compilaciones, stages, raw payloads en Avanzado).

Máximo un foco por pantalla. Paneles densos, no sábanas de tarjetas.

## 10. Mobile

Prioridad móvil: Salud · Pulse · Aprendizaje reciente · Dominios · Alertas.
El grafo completo se abre aparte (`/knowledge/explorer?view=graph`).
Nada de tablas horizontales infinitas: listas con drill-down.

## 11. Performance

- Pulse: ≤ 60 nodos visibles, agregación por dominio, SVG con keys estables.
- Listas: paginación/`limit` real, sin renderizar miles de filas.
- Eventos: polling batcheado (15–30 s) + `since_seq` cuando exista stream.
- Grafo: `limit_nodes`/`limit_edges` del backend; expansión on-demand.
- Delta: una sola query agregada por ventana (no N+1).

## 12. Accesibilidad

- Navegación por teclado en nodos del pulse (Enter/Espacio abre detalle).
- `aria-label` en cada visualización con su resumen numérico real.
- Contraste AA con tokens existentes; estado nunca solo por color.
- `prefers-reduced-motion` respetado.
- Focus visible en todos los interactivos.

## 13. Backend a añadir

Solo una pieza falta para el brief: **Knowledge Delta**.

`GET /api/v1/knowledge/delta?window=24h|7d|30d|custom&since=&until=`

Respuesta (agregada, org-scoped, ERROR ≠ ZERO):

```json
{
  "window": "24h",
  "since": "...", "until": "...",
  "totals": {
    "objects": 0, "entities": 0, "relationships": 0, "facts": 0,
    "rules": 0, "metrics": 0, "evidence": 0, "sources": 0,
    "conflicts_resolved": 0, "conflicts_open": 0
  },
  "enriched": [{"id": "...", "name": "...", "type": "entity", "updated_at": "..."}],
  "by_domain": [{"domain": "...", "objects": 0, "relationships": 0, "facts": 0}],
  "timeline": [{"bucket": "...", "objects": 0, "facts": 0, "relationships": 0, "evidence": 0}]
}
```

Fuente: `knowledge_canonical_objects` (created/updated), `knowledge_assertions`,
`knowledge_edges`, `evidence_ledger`, `knowledge_conflicts`, `catalog_sources`.
El resto se compone de endpoints existentes.

Además:

- `GET /api/v1/knowledge/stream` (SSE, permiso `knowledge:read`): replay durable
  de `knowledge_events` + eventos live del bus. Knowledge Pulse y el feed se
  refrescan batcheados al recibir eventos; si el stream cae, queda el polling
  de respaldo.
- `GET /api/v1/knowledge/domains` incluye `by_type` (temas por dominio) para el
  drill-down del Explorador.
- `GET /api/v1/knowledge/compilations` acepta `source_id` para la vista de
  fuente ("qué aportó").

## 14. Plan de implementación

1. **Backend delta** (repo + service + ruta + tests).
2. **Fundaciones frontend**: `knowledgeNav` nuevo, rutas, `knowledgeLanguage`,
   tipos y fetchers (`lib/knowledgeDelta.ts`, `lib/knowledgeActivity.ts`).
3. **Home**: hero, delta, salud resumida, dominios, atención, feed.
4. **Pulse**: SVG real-event-driven con reduced motion.
5. **Explorador + vista de objeto**.
6. **Salud** (reutiliza Quality con nueva jerarquía e interpretación).
7. **Actividad** (feed humano + delta).
8. **Búsqueda universal**.
9. **Empty states y mobile**.
10. **Motion/performance/a11y pass**.
11. **Verificación**: `typecheck`, `lint`, `test`, `build`, backend pytest,
    QA visual (dark/light, 1440/820/390) y revisión de experiencia.

## 15. Fuera de alcance (explícito)

- No se crea otro motor de conocimiento ni otra base de datos.
- No se tocan retrieval, agentes ni JEV.
- No se eliminan rutas: se redirigen.
- No se usan mocks permanentes ni números de ejemplo en producción.
