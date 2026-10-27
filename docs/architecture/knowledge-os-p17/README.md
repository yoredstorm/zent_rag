# P17 — Knowledge OS UX

Programa de simplificación UX sin cambiar el pipeline canónico.

- [00-audit.md](./00-audit.md): rutas, nav, duplicaciones y deep links.
- [01-feature-matrix.md](./01-feature-matrix.md): función, permiso, endpoint y destino.
- [02-baseline.md](./02-baseline.md): baseline y `NOT_MEASURED`.
- [03-invariants.md](./03-invariants.md): snapshot y no-regresión.
- [04-adr-ux-only.md](./04-adr-ux-only.md): decisión de arquitectura.
- [05-p0-acl-fix.md](./05-p0-acl-fix.md): P0 ACL del chat grounded.
- [06-navigation.md](./06-navigation.md): cuatro experiencias y flag visual.
- [07-sources.md](./07-sources.md): entrada única, estados verificables y seguridad.
- [08-summary.md](./08-summary.md): acciones frecuentes y carga parcial.
- [09-ask.md](./09-ask.md): Preguntar, citas y resolución de evidencia.
- [10-improve.md](./10-improve.md): bandeja única y gates de revisión.
- [11-context.md](./11-context.md): vocabulario humano y errores accionables.
- [12-agents-workflows.md](./12-agents-workflows.md): fuente → agente nuevo y scope de workflows.
- [13-validation.md](./13-validation.md): gates reales, límites y decisión de release.

## Baseline reproducible

```bash
uv run --frozen --no-sync python scripts/knowledge_ux_snapshot.py \
  --output artifacts/certification/p17/invariants-before.json

cd portal
E2E_KNOWLEDGE_BASELINE=1 E2E_EXTERNAL=1 E2E_BASE_URL=http://127.0.0.1:8080 \
  npx playwright test e2e/knowledge-baseline.spec.ts --project=chromium
```

El E2E requiere worker de ingesta y Qdrant. En CI se omite por defecto; la
certificación real se ejecuta en el stack local.

## Estado

- P17-00: auditoría, matriz, ADR, snapshot y baseline E2E ejecutados.
- Baseline real: 5 citas API, cross-tenant rechazado; viewer de cita y conflicto
  abierto quedan como gaps documentados para P17-04/P17-05.
- P0 ACL y P17-00 están verdes en CI (`40444744321`).
- P17-01: nav de 4 experiencias detrás de `RAG_KNOWLEDGE_SIMPLE_UX_ENABLED`,
  rutas `/knowledge/ask` y `/knowledge/improve`, redirects con query conservado.
- P17-02: entrada única de Fuentes, estados verificables y confirmación de
  borrado de colección.
- P17-03: tres acciones frecuentes y carga parcial tolerante a fallos.
- P17-04: Preguntar con scope, citas, resolución de evidencia y feedback.
- P17-05: Bandeja de atención en Mejorar, sin tabla nueva ni autoaprendizaje.
- P17-06: vocabulario humano en el flujo principal y errores accionables.
- P17-07: fuente → agente nuevo con `source_ids`, estados de fuente y aviso de
  permisos; workflows conservan su scope existente.
- P17-08: validación técnica y a11y smoke; 5 usuarios, escala 1/100/1000,
  bundle, red y canary quedan pendientes. `GO_STAGING`, no producción.
- No se activó ninguna flag experimental ni `ZENT_GOLD_RELEASE_ENABLED`.
- El canary por tenant queda `NOT_AVAILABLE` por el contrato roto de
  `feature_flags`; el flag de entorno cubre staging y rollback.
