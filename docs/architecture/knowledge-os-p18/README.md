# P18 — Knowledge Alive

Programa de experiencia para que una persona no técnica pueda incorporar
información, ver el progreso real y preguntar con evidencia, sin exponer el
pipeline.

## Alcance implementado en esta rama

- Navegación principal de cuatro experiencias: Resumen, Fuentes, Preguntar,
  Mejorar. Herramientas avanzadas en un diálogo agrupado por intención.
- Resumen factual con una acción primaria, tres señales de alcance explícito y
  una bandeja compacta de atención.
- Asistente de incorporación de archivos en tres pasos, con recuperación por
  `session_id`, resultados por archivo y primera pregunta.
- Destino consultable por defecto: corpus `Principal` enlazado a la fuente.
- Progreso sin porcentajes inventados: estados por archivo y etapas con
  etiquetas humanas.
- Preguntar con scope de corpus y `source_ids`, evidencia alineada por cita,
  apertura de página original y enlace explícito a agente.
- Mejorar como una sola bandeja deduplicada con problema, motivo, evidencia y
  acción.
- Fuente con panel «Esto encontró ZENT» y resumen del parser.
- Flag `RAG_KNOWLEDGE_SIMPLE_UX_ENABLED` con default `true`; `false` conserva
  la navegación anterior como rollback.

## Límites conocidos

- La pantalla de elección duplicada se eliminó: `/knowledge/add` sin `kind`
  redirige al wizard de Fuentes. Las conexiones con `?kind=` siguen usando el
  asistente de data-onboarding, ahora con macro-pasos Elegir, Incorporar y
  Comprobar. La extracción de un `ConnectorJourney` completamente embebido y
  el retiro del upload legacy de data-onboarding quedan pendientes.
- El visor de evidencia abre el PDF original en la página indicada mediante el
  endpoint existente, no un visor embebido con bbox.
- El baseline visual está en `artifacts/certification/p18/`; las pruebas con
  cinco usuarios no se ejecutaron en esta sesión.
- Las fuentes históricas sin `corpus_id` no se backfillean en silencio.

## Evidencia

- `portal/e2e/knowledge-alive.spec.ts`: cuatro pestañas, sin overflow, wizard y
  axe en 1366×768 y 390×844.
- `portal/src/pages/knowledge/Sources.test.tsx`: wizard, parcial, duplicado,
  una sesión por lote.
- `tests/test_sources_upload_dedupe.py`: corpus por defecto en la carga.
- `tests/test_grounding_ledger.py`: IDs de evidencia alineados con citas.
- `artifacts/certification/p18/*.png`.
