# P18-00 — Baseline visual y de comportamiento

## Comando

```bash
cd portal
E2E_EXTERNAL=1 E2E_BASE_URL=http://127.0.0.1:8090 \
  npx playwright test e2e/knowledge-alive.spec.ts --project=chromium
```

Resultado local (Vite sobre API local): `1 passed (45.6s)`.
Resultado sobre Docker local reconstruido (`8080`): `1 passed (34.8s)`.

## Evidencia

- `artifacts/certification/p18/knowledge-home-1366.png`
- `artifacts/certification/p18/knowledge-home-390.png`
- `artifacts/certification/p18/knowledge-import-1366.png`
- `artifacts/certification/p18/knowledge-import-390.png`
- `artifacts/certification/p18/knowledge-import-files-1366.png`
- `artifacts/certification/p18/knowledge-import-files-390.png`

## Qué verifica

- Cuatro pestañas primarias y `Herramientas avanzadas` visible.
- Sin overflow horizontal de página en 1366×768 y 390×844.
- Wizard en paso Elegir y paso documental en ambos viewports.
- axe sin violaciones serious/critical en Inicio y Fuentes.

## Ingesta real en Docker local

```bash
cd portal
E2E_EXTERNAL=1 E2E_BASE_URL=http://127.0.0.1:8080 \
  E2E_KNOWLEDGE_BASELINE=1 \
  npx playwright test e2e/knowledge-baseline.spec.ts --project=chromium
```

Resultado: `1 passed (1.1m)`. Verificó PDF recibido, sesión disponible,
5 citas reales por API, fuente enlazada al corpus y aislamiento cross-tenant.

## Qué no verifica todavía

- Cinco usuarios no técnicos.
- Canary por tenant.
- Rollback del flag en un entorno desplegado.

Estos puntos quedan como gates de P18-08, no como resultados inventados.
