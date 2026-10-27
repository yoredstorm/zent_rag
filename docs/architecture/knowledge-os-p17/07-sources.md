# P17-02 — Fuentes: alta, estado y diagnóstico

## Entrada única

La acción principal de Fuentes ahora se llama `Añadir información` y abre tres
caminos visibles:

- **Subir archivos**: dispara el selector existente y el mismo
  `upload-batch`.
- **Conectar un sistema**: abre `/knowledge/add` con el asistente existente.
- **Usar una fuente existente**: cierra el alta y lleva a la lista canónica.

No se creó un registro nuevo. La lista sigue leyendo `GET /api/v1/sources`;
SQL, managed DB, Drive y APIs siguen siendo fuentes con su tipo y su ficha.
Las tablas SQL y los conectores se operan en Avanzado.

## Estados verificables

`portal/src/pages/knowledge/sourceState.ts` traduce el estado real:

| Estado de fuente | Etiqueta de usuario |
|---|---|
| `created`, `connected` | Recibido |
| `discovering`, `profiled`, `ready`, `ingesting` | Procesando |
| `indexed` | Listo para consultar |
| `error` | Necesita atención |
| desconocido | No medido |

`ready` **no** se presenta como listo para consultar: hasta que el indexado
termina no se promete recuperación. El progreso sigue viniendo de la sesión y
los jobs reales; no se agregó una barra ficticia.

## Seguridad y escritura

- Se eliminó el header cliente `X-User-Role: admin` del sync de tablas SQL.
  El permiso se decide en backend.
- Fuente: confirmación existente con impacto en agentes.
- Colección: se agregó `ConfirmDialog`; antes el borrado era inmediato.
- No se ampliaron ACL, workspace ni scopes.
- El alta conserva la idempotencia de la UI y la sesión única.

## Pruebas

- `sourceState.test.ts`: solo `indexed` es listo; `error` es atención; estados
  desconocidos son `No medido`.
- `Sources.test.tsx`: entrada con 3 opciones, `?new=1`, uploads por archivo,
  413, duplicado, sesión única, borrado y paginación.
- `SourceDetail.test.tsx`: nuevo label de fuente indexada, tabs y acciones.

## Límites de esta fase

- La lista visual de fuentes es la canónica; las operaciones de tablas SQL y
  credenciales de conectores siguen en sus pantallas técnicas. No se creó un
  segundo inventario de fuentes.
- El estado "listo" se deriva de `kb_sources.status`; la sesión puede estar
  `available` mientras el status todavía dice `ingesting`. La UI muestra
  `Procesando` hasta que el status sea `indexed`, que es la señal conservadora.
- La verificación de disponibilidad con jobs/eventos en una sola llamada queda
  como deuda de backend, no se simula.

## Rollback

Revertir el adaptador y las etiquetas; no hay migración ni pérdida de datos.
