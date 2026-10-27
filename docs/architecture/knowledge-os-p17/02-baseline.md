# P17-00 — Baseline UX, red y rendimiento

## 1. Método

Se medirá antes y después con el mismo entorno. No se comparan cifras de
distintos flags, tenants o proveedores.

- Flujo A–G: elegir base, subir PDF, observar ingesta, preguntar, abrir cita,
  localizar conflicto, intentar resolver con reader/admin.
- Clicks: interacciones de puntero/teclado hasta completar la tarea.
- Tiempo: desde la primera acción hasta el estado final verificable.
- Red: requests, bytes, errores y writes disparados por navegación/render.
- Bundle: tamaños de `portal/dist` y chunks; sin budget actual.
- Latencia: endpoints `/knowledge/*` medidos por request, p50/p95.
- Accesibilidad: axe, teclado, foco y zoom 200%.

## 2. Medido en HEAD

- HEAD: `11aeec7d1a8145f388ef952d7b08608a5df59b43`.
- Suite completa histórica: 5476 tests, 0 fallos, 4 skipped (`8ee8200`).
- Invariantes históricos: 406 tests, 0 fallos.
- Rollback de release ensayado: 16.9 s (`edeeb61`).
- PDF benchmark: KCS 0.7346/0.7743; recall@K 0.3889/0.4722; veredicto
  `D_NEED_MORE_DATA`.
- Estas cifras son anteriores a HEAD y no son baseline de Knowledge UX.

## 2.1 Baseline E2E ejecutado

`E2E_KNOWLEDGE_BASELINE=1` contra Docker local:

- workspace creado por API;
- PDF `atpco.pdf` subido y fuente creada;
- la sesión quedó `available` mientras la fuente aún estaba `ingesting`;
- `POST /knowledge/workspaces/{id}/chat` devolvió **5 citas reales** con
  página/locator;
- la página del workspace cargó;
- la cita **no** abre un viewer porque la fuente no está asociada al corpus:
  `citation_ui=NOT_VERIFIED` (gap de P17-04);
- conflicto abierto: `NOT_AVAILABLE` en el entorno de baseline;
- cross-tenant: rechazado.
- Duración del recorrido: 57.2 s, incluida ingesta real y una llamada LLM.
- El segundo chat de UI no se repite para no duplicar LLM; el gap de viewer se
  registra como hallazgo, no como PASS.

## 3. NOT_MEASURED

| Medición | Estado |
|---|---|
| Bundle inicial y por chunk | NOT_MEASURED; no hay budget ni reporte versionado |
| Cobertura backend/portal | NOT_MEASURED; no hay provider instalado en CI |
| Latencias `/knowledge/overview|health|delta|objects` | NOT_MEASURED |
| Tiempo de ingesta PDF de punta a punta | NOT_MEASURED |
| Requests y writes durante navegación | NOT_MEASURED |
| a11y de las páginas Knowledge | NOT_MEASURED; axe solo cubre dashboard/tour |
| Tiempo de la suite E2E | NOT_MEASURED |
| Usabilidad con 5 personas | NOT_STARTED |

## 4. Criterio de mejora

Una mejora solo se declara si:

1. La tarea se completa con menos decisiones de navegación y sin ayuda.
2. No aumenta el número de writes accidentales.
3. No se degrada la exactitud de citas ni el aislamiento.
4. El bundle no crece sin justificación medida.
5. Las diferencias se miden en el mismo entorno y flags.

## 5. Instrumentación

- `scripts/knowledge_ux_snapshot.py`: snapshot de invariantes y conteos.
- `portal/e2e/knowledge-baseline.spec.ts`: recorrido reproducible.
- Reporte de red del navegador en el E2E.
- `portal/dist` sizes y chunk names para el baseline de bundle.
- Cualquier widget caído debe degradar solo su bloque, no la portada.
