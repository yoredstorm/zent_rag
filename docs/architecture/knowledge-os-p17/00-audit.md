# P17-00 — Auditoría funcional y línea base

**HEAD auditado:** `11aeec7d1a8145f388ef952d7b08608a5df59b43`
**Alcance:** Knowledge OS del portal y contratos que lo alimentan.
**Modo:** auditoría de solo lectura; P17 no cambia el pipeline.

## 1. Superficie real

- 25 rutas de conocimiento, 5 redirects internos y 4 aliases externos.
- Navegación normal: 5 pilares (`Inicio`, `Explorador`, `Salud`, `Fuentes`,
  `Actividad`) + 10 pestañas en `Avanzado`.
- 12 páginas usan `KnowledgeLayout`; `KnowledgeWorkspaces` y
  `KnowledgeWorkspace` no lo usan.
- Solo `ObjectView` y `SourceDetail` tienen gates de permiso explícitos en la
  UI. El backend sí aplica permisos; ocultar una acción no sustituye ese gate.

## 2. Árbol de rutas

| Ruta | Componente | Destino P17 |
|---|---|---|
| `/knowledge` | `Home` | Resumen |
| `/knowledge/sources` | `Sources` | Fuentes |
| `/knowledge/sources/:sourceId` | `SourceDetail` | Fuentes (detalle) |
| `/knowledge/add/:sessionId?` | `OnboardingWizard` | Fuentes (alta) |
| `/knowledge/sessions/:sessionId` | `LearningSession` | Fuentes (ingesta) |
| `/knowledge/search` | `Search` | Preguntar (alias) |
| `/knowledge/playground` | `Playground` | Preguntar (alias) |
| `/knowledge/workspaces` | `KnowledgeWorkspaces` | Preguntar / Avanzado |
| `/knowledge/workspaces/:corpusId` | `KnowledgeWorkspace` | Preguntar |
| `/knowledge/health` | `Quality` | Mejorar |
| `/knowledge/evaluation` | `Evaluation` | Mejorar / Avanzado |
| `/knowledge/activity` | `Activity` | Resumen / Avanzado |
| `/knowledge/objects/:objectId` | `ObjectView` | Evidencia / Avanzado |
| `/knowledge/explorer` | `Explorer` | Avanzado |
| `/knowledge/map` | `Map` | Avanzado |
| `/knowledge/understanding` | `Understanding` | Avanzado |
| `/knowledge/jobs` | `Jobs` | Avanzado |
| `/knowledge/collections` | `Collections` | Avanzado |
| `/knowledge/documents` | `Documents` | Avanzado |
| `/knowledge/sql` | `SqlSources` | Avanzado |
| `/knowledge/database` | `DatabaseBuilder` | Avanzado |
| `/knowledge/database/import` | `ManagedImport` | Avanzado |
| `/knowledge/glossary` | `Glossary` | Avanzado |
| `/knowledge/catalog` | `Catalog` | Avanzado |
| `/connectors` | `Connectors` | Avanzado |
| `/chat?target=knowledge` | `Chat` | Preguntar (deep link) |

Redirects/aliases que deben conservarse: `/ingestion`, `/knowledge-bases`,
`/data-sources`, `/knowledge-hub`, `/knowledge/learning`, `/knowledge/model`,
`/knowledge/quality`, `/knowledge/review`, `/knowledge/improvements`.

## 3. Duplicaciones UX

| Necesidad | Implementaciones actuales | Consolidación |
|---|---|---|
| Preguntar | `Search`, `Playground`, `KnowledgeWorkspace`, `Chat` | Una autoridad `Preguntar`; el resto queda como alias o modo |
| Fuentes | `Sources`, `SourceDetail`, `Collections`, `Documents`, `SqlSources`, `Jobs`, `Catalog`, `Connectors`, `DatabaseBuilder`, `ManagedImport` | Una entrada y una lista; operación técnica en Avanzado |
| Resumen/Salud/Actividad | `Home`, `Quality`, `Activity`, `KnowledgeHero`, `HealthSummary`, `AttentionPanel` | Resumen + Mejorar, reutilizando componentes |
| Explorar | `Explorer` (lista/grafo), `Map`, `ObjectView`, `Understanding` | Un Explorador; `ObjectView` como ficha; Understanding en Avanzado |

## 4. Deep links críticos

No se pueden perder:

- `?new=1` en Fuentes.
- `?kind=database|documents|spreadsheets|drive|website|api` en alta.
- `?tab=resumen|documentos|sincronizar` y aliases legacy en SourceDetail.
- `?tab=issues|conflicts|ingestion|gaps|questions|reviews|improvements` en
  Salud/Mejorar.
- `?view=runs&run=<id>` en Actividad.
- `?source_id`, `?q`, `?domain`, `?type`, `?status`, `?order`, `?view=graph`,
  `?level`, `?topic`, `?focus`.
- `/knowledge/sessions/:id`, `/knowledge/sources/:id`,
  `/knowledge/objects/:id`, `/chat?target=knowledge`.

## 5. Deep links ya roos en HEAD

1. `/knowledge/quality?tab=...` redirige a `/knowledge/health` sin query.
2. `/knowledge/model?focus=...` redirige a `/knowledge/explorer` sin query.
3. `/knowledge/documents?document=...` no se consume.
4. `?tab=confidence|evidence|descriptions` no existe en `Quality`.
5. `/knowledge/sql`, `/knowledge/database`, `/knowledge/database/import`,
   `/knowledge/map` y `/knowledge/search` no tienen entrada de navegación.

P17-01 corrige los redirects con query y conserva los aliases; no se borran
páginas.

## 6. Terminología a unificar

- Inicio/Conocimiento/Resumen.
- Salud/Calidad/Mejorar.
- Playground/Búsqueda/Preguntar.
- Fuente/Documento/Colección/Conector/Base.
- Workspace de organización vs corpus de conocimiento.

La copy de P17 usa `Base de conocimiento` para el contenedor visible y deja los
términos técnicos en el drawer avanzado.

## 7. Evidencia y estados

No presentar como listo/aprendido/verificado lo que solo está subido, en
proceso, inferido o no medido. La disponibilidad real se deriva de
`kb_sources.status`, `ingestion_jobs`, `knowledge_learning_sessions` y
`knowledge_scores`; no hay un gate único de retrieval hoy. La UI debe mostrar
la señal disponible y `No medido` cuando falte, nunca un porcentaje inventado.

## 7.1 Hallazgo de flags

`feature_flags` usa `(key, scope, plan_name, organization_id, workspace_id)`
como PK y las tres dimensiones son NOT NULL. `set_flag` inserta `NULL` para las
dimensiones no aplicables, por lo que los scopes organization/workspace/platform
no se pueden escribir. P17 usa `RAG_KNOWLEDGE_SIMPLE_UX_ENABLED` para el flag
visual y reporta el canary por tenant como `NOT_AVAILABLE`.

## 8. Conclusión

La simplificación es viable sin tocar el pipeline. El riesgo principal no es
visual: es la consistencia de ACL, scopes y deep links. P17-00 deja el P0 ACL
documentado y bloquea P17-01 hasta que esté corregido y verde.
