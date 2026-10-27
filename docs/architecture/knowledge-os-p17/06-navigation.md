# P17-01 — Navegación de cuatro experiencias

## Contrato

Con `knowledge_simple_ux=true`:

- `/knowledge` → Resumen
- `/knowledge/sources` → Fuentes
- `/knowledge/ask` → Preguntar
- `/knowledge/improve` → Mejorar
- `Avanzado` → disclosure con Explorador, Mapa, Estudio semántico,
  Evaluación, Trabajos, Documentos, Colecciones, Workspaces, Glosario,
  Catálogo, Fuentes SQL, Database Builder, Importar CSV/Excel y Conectores.

Con el flag apagado la nav de cinco pilares no cambia. Es un rollback visual.

## Flag

`RAG_KNOWLEDGE_SIMPLE_UX_ENABLED`, default `false`. `GET /api/v1/auth/me` lo
expone en `feature_flags.knowledge_simple_ux` (aditivo, sin endpoint nuevo). El
portal lo persiste como booleano visual, nunca como secreto, y lo limpia en
logout.

La tabla `feature_flags` existente **no** permite scopes organization/workspace:
sus columnas de scope forman la PK y son NOT NULL, así que el servicio
`set_flag` no puede insertar una fila con `NULL` en plan/org/workspace. No se
inventa una migración destructiva; el flag de entorno cubre staging y rollback.
El canary por tenant queda `NOT_AVAILABLE` hasta que el owner de plataforma
corrija ese contrato.

## Rutas y compatibilidad

- `/knowledge/ask` reutiliza `Playground`; `/knowledge/improve` reutiliza
  `Quality`.
- `/knowledge/health`, `/knowledge/playground`, `/knowledge/search` siguen
  existiendo.
- Redirects legacy conservan query:
  `/knowledge/quality?tab=conflicts` → `/knowledge/health?tab=conflicts`;
  `/knowledge/model?focus=...` → `/knowledge/explorer?focus=...`;
  `/knowledge/review` → `/knowledge/health?tab=reviews`;
  `/knowledge/improvements` → `/knowledge/health?tab=improvements`.
- Aliases `/ingestion`, `/knowledge-bases`, `/data-sources` y `/knowledge-hub`
  conservan query.

## Pruebas

- `knowledgeNav.test.ts`: 4 secciones, sección activa, avanzado real, redirects
  con query.
- `KnowledgeLayout.test.tsx`: 4 links + Avanzado, `aria-current`, disclosure
  con Mapa y Fuentes SQL; la nav legacy sigue en 5.
- `api.test.ts`: el flag visual se persiste sin token.
- `KnowledgePillarLinks.test.tsx`: Dashboard/Chat siguen mostrando la nav
  legacy cuando no hay flag.
- `test_auth.py`/`test_trial_start_mode.py`/`test_workspace_isolation.py`:
  `/me` aditivo sin regresión.

## Riesgos

- La flag se lee de `localStorage` para evitar acoplar el layout al contexto de
  auth; un cambio de flag requiere recarga de sesión.
- `/knowledge/health` sigue mostrando el heading legacy "Salud"; la ruta
  canónica nueva es `/knowledge/improve`.
- No se movieron datos ni se creó un segundo registro de fuentes.
- P17-02/P17-04 reemplazarán los contenidos de Fuentes/Preguntar; esta fase solo
  fija la arquitectura de navegación.

## Rollback

Apagar `knowledge_simple_ux`. Sin migración ni borrado. Las rutas legacy
quedan disponibles.
