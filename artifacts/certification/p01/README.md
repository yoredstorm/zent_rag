# Evidencia P01

Base: `0cbb494ce4264077a1e6d4823f4520fbc32928b9` + WIP declarado.

| Archivo | Resultado |
|---|---|
| `junit-publication-gate.xml` | 10 passed — gate publish/activate, certificados, stale, workspace, legacy, approval, race |
| `junit-gate-studio.xml` | 22 passed — gate + Workflow Studio |
| `junit-workflows.xml` | 67 passed — durable, architect, workflows, graph |
| `junit-invariants.xml` | 24 passed — architecture, authority, migrations |
| `junit-red-proof.xml` | 6 failed — rojos P00 que siguen abiertos (P02/P05) |

## No verificado

- Suite Vitest completa: excedió 600 s. La suite dirigida de workflow/studio
  pasó 25/25 y `npm run typecheck`, `lint` y `build` pasaron.
- `alembic downgrade 163` no se ejecutó para no borrar certificados de la
  corrida; el upgrade 163→164 sí se aplicó.
- Playwright y proveedores reales no se ejecutaron en P01.
