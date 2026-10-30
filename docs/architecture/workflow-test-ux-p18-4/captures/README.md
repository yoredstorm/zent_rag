# P18.4 — Capturas revisadas

- Fecha: 2026-10-30
- Entorno: build de producción (`vite preview`) contra API local.
- Tenant: demo.
- Workflow: `E2E Studio Flow` (draft), sin agente asignado en el nodo LLM.
- Tema: `zent_theme` light/dark explícito.

| Archivo | Vista | Viewport | Tema |
|---|---|---|---|
| `1440-setup-dark.png` | Probar | 1440x900 | Dark |
| `1440-result-dark.png` | Resultado | 1440x900 | Dark |
| `1440-provider-capped-dark.png` | Resultado provider capeado | 1440x900 | Dark |
| `1440-setup-light.png` | Probar | 1440x900 | Light |
| `1440-result-light.png` | Resultado | 1440x900 | Light |
| `820-setup-dark.png` | Probar en drawer | 820x900 | Dark |
| `390-setup-dark.png` | Probar en drawer | 390x844 | Dark |
| `390-result-dark.png` | Resultado en drawer | 390x844 | Dark |

## Lo que muestran

- Un CTA principal por contexto.
- Modo segmentado en 3 categorías.
- Escenario y JSON cerrados por defecto.
- Footer persistente y visible.
- Resultado con Respuesta, Recorrido y Verificación.
- Provider capeado sin sello y con `UNVERIFIED`.

## Lo que no muestran

- WAIT, aprobación humana, error de nodo, workflow_error, empty result.
- Efectos reales o proveedor real.
- Evaluación con usuarios.

No usar estas imágenes como certificación de proveedor, accesibilidad total ni producción.
