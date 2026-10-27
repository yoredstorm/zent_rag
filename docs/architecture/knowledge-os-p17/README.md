# P17 — Knowledge OS UX

Programa de simplificación UX sin cambiar el pipeline canónico.

- [00-audit.md](./00-audit.md): rutas, nav, duplicaciones y deep links.
- [01-feature-matrix.md](./01-feature-matrix.md): función, permiso, endpoint y destino.
- [02-baseline.md](./02-baseline.md): baseline y `NOT_MEASURED`.
- [03-invariants.md](./03-invariants.md): snapshot y no-regresión.
- [04-adr-ux-only.md](./04-adr-ux-only.md): decisión de arquitectura.
- [05-p0-acl-fix.md](./05-p0-acl-fix.md): P0 ACL del chat grounded.
- [06-navigation.md](./06-navigation.md): cuatro experiencias y flag visual.

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
- P17-01: nav de 4 experiencias detrás de `knowledge_simple_ux`, rutas
  `/knowledge/ask` y `/knowledge/improve`, redirects con query conservado.
- No se activó ninguna flag experimental ni `ZENT_GOLD_RELEASE_ENABLED`.
