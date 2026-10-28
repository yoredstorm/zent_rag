# P18-00 — Baseline visual y de comportamiento

## Comando

```bash
cd portal
E2E_EXTERNAL=1 E2E_BASE_URL=http://127.0.0.1:8090 \
  npx playwright test e2e/knowledge-alive.spec.ts --project=chromium
```

Resultado local: `1 passed (45.6s)`.

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

## Qué no verifica todavía

- Ingesta real con worker/Qdrant y cita abierta en PDF.
- Cinco usuarios no técnicos.
- Canary por tenant.
- Rollback del flag en un entorno desplegado.

Estos puntos quedan como gates de P18-08, no como resultados inventados.
