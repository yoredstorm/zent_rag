# P17 — Knowledge OS UX

Programa de simplificación UX sin cambiar el pipeline canónico.

- [00-audit.md](./00-audit.md): rutas, nav, duplicaciones y deep links.
- [01-feature-matrix.md](./01-feature-matrix.md): función, permiso, endpoint y destino.
- [02-baseline.md](./02-baseline.md): baseline y `NOT_MEASURED`.
- [03-invariants.md](./03-invariants.md): snapshot y no-regresión.
- [04-adr-ux-only.md](./04-adr-ux-only.md): decisión de arquitectura.
- [05-p0-acl-fix.md](./05-p0-acl-fix.md): P0 ACL del chat grounded.

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
- P0 ACL: corregido en PR separado; pendiente de CI.
- Baseline real: 5 citas API, cross-tenant rechazado; viewer de cita y conflicto
  abierto quedan como gaps documentados para P17-04/P17-05.
- P17-01 no empieza hasta que P0 ACL esté verde.
- No se activó ninguna flag experimental ni `ZENT_GOLD_RELEASE_ENABLED`.
