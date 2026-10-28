# P18-01 — Contratos de estado y alcance

## Fuente

`kb_sources.status` conserva el ciclo de vida existente. La UI solo declara
`Listo para consultar` con `indexed`. `ready` de una fuente SQL significa
estructura lista, no disponibilidad de recuperación; se muestra como
procesamiento.

## Job

`ingestion_jobs.progress` puede valer 50 mientras el worker procesa un lote
largo; es un marcador indeterminado, no un porcentaje de tiempo. La UI no lo
presenta como porcentaje.

## Sesión de aprendizaje

- `preparing`, `learning`: trabajo en curso.
- `available`: hay fuentes consultables, el cliente aún puede adjuntar más.
- `optimizing`: todas terminaron; corre el enriquecimiento derivado.
- `completed`: sesión sellada, sin fallos.
- `partial`: sesión sellada con fuentes fallidas.
- `failed`/`canceled`: no hay promesa de disponibilidad.
- `ready_sources = min(source_count, available_sources + completed_sources)`.
- `is_available` no es verdadero para una sesión parcial sin ninguna fuente
  consultable.

## Corpus y scope

- La carga explícita resuelve `corpus_id` desde la colección o crea/reutiliza
  el corpus `Principal` del workspace.
- `Preguntar` envía `corpus` y, si corresponde, `source_ids`.
- El backend valida que cada `source_id` pertenezca a la organización y al
  workspace; el retriever recibe la lista completa, no solo el primero.
- Una fuente histórica sin corpus no se presenta como consultable.

## Wizard

- El estado del wizard es una representación; la verdad durable es la fuente,
  el job y la sesión.
- `session_id` en la URL permite reabrir el paso Comprobar.
- Minimizar conserva la sesión mediante el banner global; no promete cancelar
  trabajo del backend.
- Un fallo por archivo no convierte el lote en éxito total.

## Permisos

- Leer conocimiento: `knowledge:read`.
- Subir o sellar: `sources:write`.
- Crear/editar fuentes: `sources:write`.
- Vincular a agentes: `agents:write`; la navegación no crea ni publica nada.
- El scope de tenant/workspace se aplica en cada endpoint; la UI no sustituye
  ACL.
