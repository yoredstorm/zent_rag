# Evidencia P10

Base: `0cbb494ce4264077a1e6d4823f4520fbc32928b9` + P00–P09.

| Archivo | Resultado |
|---|---|
| `junit-p10.xml` | 40 passed — discovery, marketplace, catálogo y migraciones |

## Estado

- `GET /workflows/capabilities/discover` sobre `canvas_context`; sin catálogo nuevo.
- Canvas muestra disponibles con enlace al Marketplace y solo inserta acciones instaladas.
- `return_to` saneado y reutilizado en el Marketplace.
- Instalación contextual heredada comparte el mismo registro; no duplica.
- Blueprint portable existente (`zent.solution/v1`).
- Sin migración P10.

## No verificado

- Compra/pago real.
- Revocación de producto sobre una instalación viva.
- Estudio de marketplace/móvil.
- La ruta heredada de install sigue disponible para compatibilidad, no para canvas.
