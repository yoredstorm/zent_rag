# P18-00 — Auditoría y línea base

**HEAD de partida:** `4bfe7d1` (master con PR #10 fusionado).
**Modo:** auditoría de solo lectura antes de los cambios de producto.

## Superficie real

- Rutas canónicas: `/knowledge` (Resumen), `/knowledge/sources` (Fuentes),
  `/knowledge/ask` (Preguntar), `/knowledge/improve` (Mejorar).
- Herramientas avanzadas: explorador, mapa, estudio semántico, evaluación,
  trabajos, documentos, colecciones, workspaces, glosario, catálogo, SQL,
  Database Builder e importación tabular.
- Deep links conservados: `/knowledge/sessions/:id`,
  `/knowledge/sources/:id`, `/knowledge/add`, `/knowledge/add/:sessionId`,
  `/knowledge/objects/:id`, `/chat?target=knowledge`.
- `/knowledge/add/...` sigue siendo la entrada de conectores del
  data-onboarding existente.

## Hallazgos corregidos

1. El menú avanzado era una lista plana de 14 enlaces. Ahora se agrupa por
   Investigar, Administrar, Diagnosticar y Modelar datos, con búsqueda y
   cierre por Escape o clic fuera.
2. Las fuentes subidas no tenían `corpus_id`; Preguntar no podía verlas. La
   carga explícita resuelve o crea el corpus `Principal` del workspace y lo
   devuelve en la respuesta.
3. El resumen sumaba conteos de distinto alcance. `sources_ready` cuenta
   fuentes con documentos activos o indexado; la UI explica el alcance.
4. El banner global usaba porcentajes por etapa (12/32/52/68/84). Se
   reemplazaron por conteos de fuentes listas, en proceso y por revisar.
5. `record_evidence` omitía citas sin excerpt y desalineaba
   `evidence_ids`. Se añadió `record_evidence_aligned` y la UI usa
   `citation_evidence_ids`.
6. La bandeja de Mejorar sumaba categorías solapadas. Ahora normaliza y
   deduplica conflictos, gaps, preguntas, propuestas, mejoras e incidencias de
   ingesta.
7. El wizard existente navegaba fuera de Fuentes y perdía resultados
   parciales. El nuevo wizard conserva el lote, muestra el resultado por
   archivo y permite recuperar la sesión por URL.

## Baseline

El smoke visual `portal/e2e/knowledge-alive.spec.ts` se ejecutó contra el
stack local y dejó capturas en `artifacts/certification/p18/`:

- `knowledge-home-1366.png` · `knowledge-home-390.png`
- `knowledge-import-1366.png` · `knowledge-import-390.png`
- `knowledge-import-files-1366.png` · `knowledge-import-files-390.png`

Cubre navegación, ausencia de overflow horizontal, wizard en desktop/móvil y
axe sin violaciones serious/critical.

## Riesgos abiertos

- La conexión de sistemas mantiene el asistente de data-onboarding como
  subflujo; no se extrajo todavía a un componente embebido.
- El visor de evidencia abre el PDF original con `#page=`, no un canvas con
  bbox.
- Las fuentes históricas sin corpus requieren asignación explícita.
- La prueba con cinco usuarios no se ejecutó; queda como `NOT_MEASURED`.
