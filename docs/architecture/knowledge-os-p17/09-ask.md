# P17-04 — Preguntar

## Autoridad

`/knowledge/ask` es la experiencia canónica. Usa el chat grounded existente de
`POST /api/v1/knowledge/workspaces/{corpus_id}/chat`; no crea un motor de
consulta ni un segundo retrieval.

- Selector de base (corpus) visible.
- Una pregunta por vez; la respuesta muestra citas reales.
- Cada cita puede resolver su `evidence_id` y abrir la fuente.
- Si no hay citas, la UI dice `Sin evidencia suficiente`; no inventa una
  referencia.
- El scope se mantiene en la URL (`?corpus=`) y en la autorización del backend.

## Backend mínimo

`GET /api/v1/knowledge/evidence/{evidence_id}`:

- permiso `knowledge:read`;
- organización y workspace del contexto;
- 404 si la evidencia no existe o es de otro tenant/workspace;
- devuelve `source_id`, `document_id`, `page`, `section_path`,
  `table_reference`, `row_reference`, `excerpt`, `authority` y `version`.

No se creó tabla ni se almacenaron respuestas.

## Feedback

Los botones `Sí`, `La fuente no coincide` y `Falta información` usan el
mecanismo existente `POST /api/v1/knowledge/nutrition/feedback` y solo aparecen
con `knowledge:write`. No convierten una respuesta en verdad ni promueven
conocimiento.

## Pruebas

- Backend `test_knowledge_evidence_api.py`: evidencia propia, 404 cross-org,
  404 cross-workspace y evidencia org-level.
- Portal `Ask.test.tsx`: selector de base, respuesta, cita con página,
  resolución de evidencia, enlace a fuente y feedback.
- El baseline P17-00 ya obtuvo 5 citas reales por API; la UI de Ask es la
  autoridad nueva para mostrarlas.

## Límites

- La conversación es de una pregunta; no hay hilo persistente en esta fase.
- El chat grounded puede seguir mostrando `available` en la sesión mientras la
  fuente está `ingesting`; la resolución de evidencia no depende de ese estado.
- El visor PDF/bbox completo sigue en el workspace existente; esta página
  enlaza a la fuente y muestra el excerpt. No se declara paridad de visor.
- No se agregó reranking, plan de retrieval ni top_k a la UI.
