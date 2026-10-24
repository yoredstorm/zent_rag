# 12 — P10: marketplace único y descubrimiento de capacidades

Fecha: `2026-10-23`. Base: `0cbb494ce4` + P00–P09.

## 1. Autoridades auditadas

No se creó una tienda ni un catálogo paralelo:

- catálogo global de productos: `/api/v1/products` y
  `/api/v1/products/installs`;
- integraciones y acciones: `/api/v1/marketplace`;
- contexto del canvas: `/api/v1/workflows/marketplace/context`;
- blueprint portable: `/api/v1/studio/solutions/{id}/export|import` y
  `SolutionV1`;
- instalaciones: `installed_integrations` y `marketplace_product_installs`.

La instalación contextual antigua reutiliza el mismo registro; no copia una
instalación. El canvas ya no instala: muestra disponibles con enlace al
Marketplace y solo inserta acciones de integraciones instaladas.

## 2. Capability Discovery API

`GET /api/v1/workflows/capabilities/discover?q=&limit=` proyecta
`canvas_context` a entradas buscables:

- `capability_ref`, acción, integración y producto;
- `installed`, `install_id`, `status`, `lifecycle`, `legacy`;
- credenciales/purpose, riesgo, coste, input/output schema;
- `marketplace_required=true` para lo no instalado.

No hay tabla ni índice nuevo. Responde con `duplicate_catalog=false` y usa el
mismo catálogo que el canvas y el Marketplace global.

## 3. Retorno seguro y refresco

- `safeReturnTo` solo acepta rutas internas con prefijo permitido; rechaza
  `://`, `//`, backslashes y hosts externos.
- El Marketplace vuelve al diseño solo con `return_to` validado.
- Tras instalar, la página recarga el catálogo/installs y el canvas recarga
  `marketplace/context` al montar; el nodo conserva `workflow_id` y revisión.
- `marketplaceHref` incluye `capability_ref`, `node_id`, `design_session_id` y
  `return_to` saneados.

## 4. Ciclo de vida y blueprint

Los estados de producto (`DRAFT`, `READY`, `PUBLISHED`, `PAUSED`,
`DEPRECATED`, `END_OF_LIFE`) ya existen. La desinstalación calcula impacto y
pide confirmación; no borra un producto del catálogo global.

El blueprint portable usa `zent.solution/v1`: refs lógicas, sin tenant,
secretos ni IDs físicos; export/import ya está en Studio. P10 no añade otra
representación.

## 5. Pruebas

| Comando | Resultado |
|---|---|
| `pytest tests/test_capability_discovery.py tests/test_workflow_marketplace.py tests/test_unified_marketplace.py tests/test_marketplace.py tests/test_catalog_api.py tests/test_migrations.py` | **40 passed** (`junit-p10.xml`) |
| Portal `marketplaceReturn.test.ts` + `NodeLibrary.test.tsx` (existentes) | cubiertos en suite de portal |
| `ruff check` P10 | OK |

Cubre: descubrimiento, instalación única reutilizada, contexto del canvas,
límites de query, catálogo/facetas y contrato de migraciones.

## 6. Límites

- La ruta heredada `/workflows/marketplace/install` sigue existiendo por
  compatibilidad con `Intelligence` y tests existentes; **el canvas no la usa**.
- No se probó compra/pago real ni revocación de producto en una instalación
  viva; el ciclo de vida está auditado por código y tests existentes.
- No se ejecutó un estudio de marketplace ni actualización móvil.
- La instalación de producto desde Marketplace requiere credenciales/purpose
  reales para integraciones que los exijan.

## 7. Rollback

Frontend/backend aditivos: revertir el endpoint de discovery y el helper.
Sin migración nueva en P10.

## 8. Dictamen

**GO P10 staging controlado.** Hay un solo catálogo, descubrimiento explícito,
retorno seguro y sin duplicar la instalación. **NO-GO release:** compra real,
revocación E2E y certificación P12 siguen pendientes.
