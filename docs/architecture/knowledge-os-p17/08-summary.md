# P17-03 — Resumen

## Decisiones

- Resumen reutiliza `KnowledgeHero`, `KnowledgePulse`, `KnowledgeDelta`,
  `KnowledgeDomains`, `AttentionPanel` y `ActivityFeed`.
- Se agregaron tres acciones frecuentes, visibles cuando el usuario tiene el
  permiso correspondiente:
  - Añadir información → `/knowledge/sources?new=1`
  - Hacer una pregunta → `/knowledge/ask`
  - Revisar problemas → `/knowledge/improve?tab=conflicts`
- Si la sesión no trae permisos, se conserva el comportamiento legacy y el
  backend sigue siendo la autoridad final.
- La carga de overview/delta/grafo usa `Promise.allSettled`: el fallo de un
  widget no borra los demás. Solo se muestra el error de portada si fallan los
  tres.
- El feed ya era independiente y sigue siéndolo.

## Evidencia y límites

- No se agregaron KPIs calculados en frontend.
- No se inventaron porcentajes, nodos ni actividad.
- El estado vacío sigue explicando los primeros pasos.
- `KnowledgeHero` conserva sus cifras del backend; si no hay datos, muestra
  `No medido`/vacío según su contrato existente.
- La portada no demuestra por sí sola que cada widget tenga datos; las pruebas
  cubren éxito, error total y fallo parcial.

## Pruebas

- `Home.test.tsx`: hero, acciones frecuentes, error total y fallo parcial de
  delta sin ocultar pulse/acciones.
- `KnowledgeHero`/`AttentionPanel` tests existentes.
- No se cambió el contrato de `/knowledge/overview`, `/health`, `/delta` ni
  `/activity`.

## Rollback

Revertir Home y sus pruebas. Sin migración ni datos nuevos.
