# P17-00 — Matriz función, necesidad y destino

| Función actual | Necesidad humana | Ruta / API | Permiso | Efecto | Destino P17 | Test de protección |
|---|---|---|---|---|---|---|
| Ver qué sabe ZENT | Orientarse | `GET /knowledge/overview`, `/health`, `/delta` | `knowledge:read` | Lectura | Resumen | `Home.test.tsx`, `test_knowledge_model.py` |
| Añadir archivo | Cargar información | `POST /sources/files/upload-batch` + `POST /knowledge/sessions` | `sources:write` | Escritura | Fuentes | `Sources.test.tsx`, upload dedupe |
| Conectar sistema | Traer datos | `/connectors`, `/knowledge/add?kind=` | `connectors:read/write` | Escritura | Fuentes (simple) / Avanzado | onboarding specs |
| Ver ingesta | Saber si está listo | `/jobs`, `/knowledge/sessions/:id` | `sources:read` | Lectura | Fuentes | jobs/sessions tests |
| Ver fuentes | Inventario | `GET /sources` | `sources:read` | Lectura | Fuentes | `test_knowledge_api.py` |
| Detalle de fuente | Diagnosticar | `/sources/:id` | `sources:read` | Lectura | Fuentes | `SourceDetail.test.tsx` |
| SQL de fuente | Consulta exacta | `POST /sources/:id/sql` | `sources:sql` | Lectura | Avanzado | backend SQL tests |
| Preguntar | Verificar conocimiento | `POST /rag/query` o `/knowledge/workspaces/:id/chat` | `knowledge:read` | Lectura + ledger | Preguntar | `KnowledgeWorkspace` / RAG tests |
| Abrir cita | Comprobar evidencia | `evidence_ids` + `GET /knowledge/evidence/:id` (P17-04) | `knowledge:read` | Lectura | Preguntar | nuevo test de cita |
| Explorar objetos | Entender relaciones | `/knowledge/objects`, `/objects/:id`, `/graph` | `knowledge:read` | Lectura | Avanzado | Explorer/Map/ObjectView |
| Ver conflictos | Decidir corrección | `GET /knowledge/conflicts` | `knowledge:read` | Lectura | Mejorar | `test_knowledge_model.py` |
| Resolver conflicto | Corregir con criterio | `POST /knowledge/conflicts/:id/resolve` | `knowledge:admin` | Escritura | Mejorar (gate) | backend test |
| Ver gaps | Detectar faltantes | `GET /knowledge/gaps` | `knowledge:read` | Lectura | Mejorar | backend test |
| Resolver gap | Cerrar faltante | `POST /knowledge/gaps/:id/resolve` | `knowledge:write` | Escritura | Mejorar (gate) | backend test |
| Revisar preguntas | Aportar conocimiento | `POST /learning/questions/:id/answer` | `knowledge:write` | Escritura | Mejorar | learning tests |
| Aprobar mapeos | Curar semántica | `/catalog/studio/*` | `catalog:write` | Escritura | Avanzado | catalog tests |
| Verificar objeto | Validar hecho | `POST /objects/:id/verify` | `knowledge:validate` | Escritura | Mejorar (gate) | `test_knowledge_model.py` |
| Evaluación | Medir calidad | `/knowledge/learning/evaluation` | `knowledge:read/write` | Lectura/escritura | Mejorar / Avanzado | learning tests |
| Glosario | Lenguaje de negocio | `/catalog/glossary` | `catalog:read/write` | Lectura/escritura | Avanzado | catalog tests |
| Actividad | Auditar cambios | `/knowledge/activity`, `/runs` | `knowledge:read` | Lectura | Resumen / Avanzado | activity tests |
| Workspace/corpus | Scope de consulta | `/knowledge/workspaces` | `knowledge:read` | Lectura/escritura | Preguntar / Avanzado | workspaces API test |
| Agente usa fuentes | Poner conocimiento en uso | `source_ids` / `knowledge_scope` | `agents:write` | Configuración | P17-07 | agent tests |
| Workflow publicado | No romper producción | versión publicada | workflow permissions | Lectura | P17-07 | workflow tests |

## Reglas de destino

- Toda función conserva una ruta accesible. Las que salen de la nav principal
  quedan en `Avanzado` o como detalle contextual.
- Detectar no es resolver. Las acciones de escritura se muestran solo con
  permiso y siempre pasan por el endpoint autorizado.
- Los agregados de atención se componen en UI; no se crea una tabla `reviews`
  ni se mueven ledgers.
- El scope de agente/workflow no se amplía al mostrar una fuente o un grafo.
