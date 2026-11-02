# P19.1-05 — UX de datos: publicar, consultar, entender

- **Estado:** PARTIAL. Núcleo implementado; faltan wizard de 3 etapas, panel de
  políticas y pruebas de usabilidad humana.

## Hallazgo AS-IS

- `DataQueryForm` refrescaba toda la página con `window.location.reload()` tras
  publicar; se perdía canvas, zoom y borradores.
- `PublishQueryModal` marcaba todas las columnas y elegía la PK como parámetro.
- El tipo de parámetro se fijaba en `string`; no había decimal, UUID, fecha,
  datetime, booleano o enum.
- El preview renderizaba JSON crudo, sin tabla ni mensaje humano.
- No había estado vacío para “sin política”, “sin permiso” o “plan stale”.

## Implementado

- Publicar actualiza el catálogo vía `loadPlans()` y selecciona el plan nuevo sin
  recargar la página ni tocar el canvas.
- Cero columnas por defecto; sin auto-PK; el usuario elige tabla, operación,
  columna de búsqueda y salida.
- Tipos de entrada:
  - `integer`/`number` con `inputMode`;
  - `decimal` se envía como string y el backend usa `Decimal` (sin float JS);
  - `date`/`datetime-local`;
  - `boolean` con select Sí/No;
  - `uuid`/`enum`/texto.
- Preview:
  - mensaje humano (`Encontré...`, `No hay coincidencias...`, `Hay varias...`,
    `La conexión no respondió...`);
  - tabla de máximo 5 filas;
  - PII redactada;
  - aviso de plan legacy;
  - código técnico solo en avanzado.
- `PublishQueryModal` refresca y devuelve el plan publicado.
- `PublishQueryModal` carga la política del conector, oculta tablas/columnas no
  autorizadas, marca columnas sensibles y exige propósito para publicarlas.
- `aria-live` en el resultado; estados vacíos conservan el botón de publicar.

## Rutas/archivos

- `portal/src/components/workflowStudio/DataQueryForm.tsx`
- `portal/src/components/workflowStudio/PublishQueryModal.tsx`
- `portal/src/components/workflowStudio/PublishQueryModal.test.tsx`
- `src/platform/workflows/bindings.py` (`decimal`, `uuid`, `enum`)
- `src/platform/workflows/data_sources.py` (preview con `safe_message`)

## Pruebas

| Caso | Resultado | Evidencia |
|---|---|---|
| Sin planes, estado accionable | PASS | `DataQueryForm.test.tsx` |
| Seleccionar plan, llenar SKU, probar | PASS | idem |
| Data Picker inserta referencia | PASS | idem |
| Cero columnas al elegir tabla | PASS | `PublishQueryModal.test.tsx` |
| Filtro por política y propósito sensible | PASS unitario (mock) | idem |
| Typecheck | PASS | `npm run typecheck` |
| Publicar sin reload / canvas intacto | NOT_RUN | requiere Playwright con canvas real |
| axe/teclado/390-768-1440 | PARTIAL | axe no ejecutado en este cambio |
| 5 usuarios no técnicos | NOT_RUN | no hay sesión de usabilidad |

## Compatibilidad y rollback

- Sin migración.
- Los planes existentes siguen funcionando; el frontend tolera `legacy_plan`.
- Rollback restaura reload y preselección (no recomendado).

## Riesgos residuales

- Falta el wizard visual de 3 etapas y un panel de administración de allowlists.
- Falta mostrar “Titular verificado requerido” con estado real del principal y
  políticas por columna en la UI.
- No se implementó la sugerencia automática de rama de recuperación con diff de
  grafo.
- Faltan capturas responsive y pruebas de usabilidad reales.
- El modal aún lista tablas físicas del conector; el backend las rechaza si no
  están en la política, pero la UI no las oculta.
