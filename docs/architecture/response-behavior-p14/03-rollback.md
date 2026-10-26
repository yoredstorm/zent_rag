# P14 — Rollback

## Código

P14 no agrega migraciones ni tablas. El rollback es de aplicación:

1. Revertir al SHA anterior de P13 (`f6b4f4a` o el vigente antes de P14).
2. Rebuild/redeploy de `api` + `ingestion-worker` + `portal`.
3. Las configuraciones guardadas con campos V2 (`profile_id`, estrategias,
   `audience_assumptions`) son aditivas y se ignoran en el código anterior; no
   hay pérdida de los campos legacy (`tone`, `default_detail`, etc.).

## Comportamiento

- `RAG_RESPONSE_INTELLIGENCE_MODE=off` sigue siendo el interruptor de
  emergencia: el contrato desaparece y la traza lo declara
  (`style_degraded=true`, `response_intelligence_off`). No se finge que el
  estilo se aplicó.
- `ZENT_GOLD_RELEASE_ENABLED` no se toca en P14 y permanece `false`.
- Si el portal nuevo habla con un backend anterior, el catálogo no existe y la
  UI no inventa presets: muestra el perfil guardado y no permite comparar.

## Datos

No hay migración que revertir. Si se desea limpiar los campos V2 de un agente,
basta con guardar de nuevo su `response_profile` desde el catálogo anterior; no
se borran fuentes, agentes, versiones ni historial.
