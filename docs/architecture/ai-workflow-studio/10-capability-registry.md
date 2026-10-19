# 10 — Prompt 02: Intelligent Capability Registry y Tool Discovery

> Fecha: 2026-10-19. Base: `master` + Prompt 01 (`d2fb77a`).
> Objetivo: que el Architect encuentre, inspeccione y seleccione capacidades
> **reales, tipadas y gobernadas**, sin volcar el catálogo en el prompt ni
> duplicar el Marketplace ni los registros internos.

## 1. Inventario de fuentes reales (Fase A)

| Fuente | Módulo / tabla | Qué aporta | Uso |
|---|---|---|---|
| Registry de nodos | `nodes.registry` | 29 tipos ejecutables, riesgo, capabilities, puertos | Descriptor `node.*` |
| Catálogo semántico | `node_catalog.py` | negocio, `when_to_use`, `requires`, ejemplo | Texto y dependencias |
| Schemas de negocio | `parameters.py` / `business_schema.py` | parámetros y outputs por nodo | `input_schema` / `output_schema` de `node.*` |
| Contratos commerce/pagos | `commerce/contracts.py` | 14 + 5 capacidades con JSON Schema, `financial`, idempotencia, eventos | Descriptor `catalog.*`, `inventory.*`, `sales.*`, `payments.*` |
| Bindings | `workflow_capability_bindings` + `bindings.py` | provider real por tenant/workspace | `availability`, `resolve_binding` |
| Marketplace | `integration_manifests`, `integration_capabilities`, `integration_actions` | acciones, versiones, schemas, auth, propósito, riesgo, aprobación, eventos | Descriptor de acciones |
| Instalaciones | `installed_integrations`, `integration_credentials` | estado, acciones habilitadas, credenciales, purpose | Disponibilidad real |
| Agentes | tabla `agents` + `config_json` | propósito, tools, KBs, output schema | Descriptor `agent.<id>` |
| Tools de agentes | `src.agents.tools.registry` | nombre, descripción, input schema, permiso, timeout | Descriptor `tool.<name>` |
| Knowledge / datos / conectores | `knowledge_bases`, `managed_databases`, `connectors` | recursos del tenant | `resource.*` |
| Eventos | `event_registry.py` | 37 eventos con campos | `event.*` |
| Plantillas | `workflow_templates` | recetas y dependencias | `workflow.template.*` |

Todo se limita por `organization_id`, `workspace_id` y `permissions`. Las
instalaciones org-level (`workspace_id NULL`) se consideran visibles para el
workspace, igual que `list_installs`; nunca se mezclan organizaciones.

## 2. Contrato canónico (Fase B)

`CapabilityDescriptor` (`zent.capability/v1`) se construye **componiendo** las
fuentes anteriores. Campos y origen:

| Campo | Origen |
|---|---|
| `capability_ref` | `action_id` (marketplace), ref de contrato (commerce), `agent.<id>`, `tool.<name>`, `node.<type>` |
| `version` | `integration_actions.version`, `integration_manifests.version`, `NodeTypeDef.version`, `1` para contratos base |
| `display_name` / `description` | DB / catálogo; humanizado solo si la fuente no trae texto |
| `owner_module` | módulo dueño real (`marketplace`, `commerce`, `nodes`, `agents`, `tools`) |
| `category` / `tags` / `aliases` | categoría de la fuente + tokens funcionales |
| `use_cases` / `when_to_use` / `when_not_to_use` | catálogo de nodos o descripción del proveedor |
| `input_schema` / `output_schema` | JSON Schema de `integration_actions` o `commerce/contracts.py`; nodos desde `business_schema` |
| `required_inputs` | `required` del JSON Schema / parámetros required |
| `errors` | códigos reales del runtime (`ACTION_NOT_ENABLED`, `CREDENTIALS_MISSING`, `PURPOSE_REQUIRED`, `CONTRACT_INVALID`, …) |
| `side_effects` | `read_only`, `writes_db`, `calls_external`, `financial`, `contains_personal_data` |
| `risk_level` | acción / nodo / contrato financiero |
| `required_permissions` | mapa de capabilities del runtime (`external_actions:execute`, `agents:execute`, …) |
| `idempotency_policy` | `idempotency_support` de la acción o `idempotency: required` del contrato |
| `timeout_policy` | `timeout_ms` de la acción / tool / default del runtime |
| `available_events` | eventos del manifest o del contrato de pagos |
| `dependency_refs` | install, capability slug, binding, provider, approval, purpose, tools, KBs |
| `provider_kind` | binding o `marketplace_action`/`internal`/`agent_runtime`/`agent_tool` |
| `availability` | ver §5 |
| `health_status` | `unknown` salvo que exista health check (no se inventa) |
| `supports_simulation` | registry / executor |
| `example_inputs` / `example_outputs` | `example(s)` del schema; nunca secretos |
| `contract_hash` | SHA-256 del descriptor sin disponibilidad/health/alias |
| `contract_gaps` | campos críticos ausentes (se reportan, no se rellenan) |

Los secretos nunca se incluyen: los parámetros marcados `secret` van como
`writeOnly` + `x-secret`, y el binding se devuelve con config redactada.

## 3. Búsqueda semántica (Fase C)

`search_capabilities()` / `search_descriptors()`:

1. match exacto por `capability_ref` (peso máximo);
2. alias funcionales (tokens + sinónimos de negocio: producto↔product, stock↔inventory, RUC↔taxpayer, pago↔payment/checkout…);
3. coincidencia textual ponderada por campo (ref > display > alias > descripción/tags);
4. rerank semántico **opcional** con embeddings de Zent (`semantic=true`), acotado al top léxico y cacheado por `contract_hash`; si falla, vuelve a léxico sin error;
5. filtros deterministas: `category`, `source`, `status`, `executable`, `risk_level`, `side_effect`, `provider_kind`;
6. `limit` 1–50, `offset`, `total_matches`; nunca se trunca el catálogo en silencio.

Ejemplos reales (snapshot dev, permisos de owner):

| Consulta | Top resultados |
|---|---|
| `buscar productos en el catálogo del negocio` | `catalog.products.search` (37), `catalog.product.get` (24), `catalog.product.price` (22) |
| `consultar stock disponible` | `inventory.stock.get` (40), `catalog.product.price`, `payments.status.get` |
| `verificar RUC del contribuyente` | `peru.taxpayer.lookup` (16; NEEDS_INSTALLATION) |
| `crear checkout de pago` | `payments.checkout.create` (306), `payments.qr.create`, `payments.cancel` |
| `enviar mensaje al cliente` | `conversation.send` (297), `sales.order.create` |

## 4. Herramientas de inspección (Fase D)

API read-only (`workflows:read`), con logging de procedencia y sin secretos:

| Operación | Endpoint |
|---|---|
| `capability.search` | `GET /api/v1/capabilities?q=…&limit=…&semantic=false` |
| `capability.inspect` | `GET /api/v1/capabilities/{ref}` |
| `capability.list_dependencies` | `GET /api/v1/capabilities/{ref}/dependencies` |
| `capability.check_availability` | `GET /api/v1/capabilities/{ref}/availability` |
| `capability.resolve_binding` | `GET /api/v1/capabilities/{ref}/binding` |
| `capability.compose` | `GET /api/v1/capabilities/{ref}/compose?to=…` |
| `resource.discover` / `resource.inspect_schema` | `GET /api/v1/capabilities/resources[/{ref}]` |
| `event.inspect` | `GET /api/v1/capabilities/events/{event_type}` |
| `workflow.template.search/inspect` | `GET /api/v1/capabilities/templates[/{slug}]` |
| Cobertura | `GET /api/v1/capabilities/metrics` |

Cada respuesta incluye `snapshot_hash`, `generated_at` y, en búsqueda,
`coverage`, `total_matches`, `returned`, `semantic_used`.

## 5. Disponibilidad real (Fase E)

`CapabilityAvailability` separa:

`exists`, `published`, `installed`, `enabled`, `configured`, `permitted`,
`provider_healthy`, `executable` + `status` + `reasons`.

Precedencia de estado para una acción de Marketplace:

1. no existe / no publicada → `UNAVAILABLE`
2. no instalada → `NEEDS_INSTALLATION`
3. instalación pausada o acción no habilitada → `DISABLED`
4. faltan credenciales → `NEEDS_CREDENTIALS`
5. falta purpose/base legal → `NEEDS_CONFIGURATION`
6. sin permiso → `PERMISSION_DENIED`
7. proveedor deprecado → `DEPRECATED` (con `executable` según el resto)
8. resto → `AVAILABLE`

Commerce/bindings: sin binding → `NEEDS_CONFIGURATION`; provider `managed_db`
sin DB → `NEEDS_CONFIGURATION`; `rest_api` sin URL → `NEEDS_CONFIGURATION`;
binding `marketplace_action` sin instalación → `NEEDS_CONFIGURATION`.

Nodos: `catalog_availability` + permisos. Agentes/tools: activo/registrado +
permiso. Una capacidad no instalada **se descubre** como opción, pero el
validator del Architect la bloquea con `requirement` y el runtime nunca la
ejecuta como si estuviera activa.

## 6. Dependencias y composición (Fase F)

`dependency_refs` conecta cada descriptor con install, capability slug,
binding, provider, approval, purpose, tools y KBs. `list_dependencies` resuelve
cada ref y devuelve su estado real.

La composición se deduce de contratos, no de un flujo hardcodeado:

- `schema_links(output_schema, input_schema)` une por **mismo nombre** o por
  **contenedores genéricos tipados** (`products`→`items`, `rows`→`data`, …).
- No une dos strings arbitrarios (`checkout_id`→`currency`) solo por tipo.
- Devuelve `confidence` (`high`/`medium`/`low`), `unmatched_required` y `notes`.
- `compose_capabilities` marca `compatible` solo si hay vínculo y no quedan
  inputs requeridos sin resolver.
- `suggest_next` ordena candidatos por vínculos y tokens; nunca afirma que un
  flujo sea válido sin contrato.

Ejemplo verificado: `catalog.products.search` (products: array) puede alimentar
`sales.order.create` (items: array) con confidence media; `payments.checkout.create`
no aporta `items` y el gap queda visible (`unmatched_required`/`notes`).

## 7. Versionado y cache (Fase G)

- `contract_hash` por descriptor; `snapshot_hash` sobre ref+version+contrato+
  estado+recursos+eventos+revisión.
- Cache in-process TTL 30s, clave `org:workspace:permissions:revision`; la
  revisión se calcula con counts/max(updated_at) de installs, bindings,
  manifests, actions, agents, KBs, conectores y capabilities.
- `force_refresh=True` para guardar/publicar.
- Historial de snapshots (15 min, 64 entradas) para verificar el snapshot que
  usó el plan: si cambió un ref usado → `409 CAPABILITY_SNAPSHOT_STALE`; si el
  cambio fue de otra capacidad → se permite.
- Un snapshot desconocido (reinicio) exige re-interpretar antes de guardar:
  nunca se publica a ciegas.

## 8. Métricas de cobertura (snapshot dev)

Valores reales del entorno local, sin agentes/KBs adicionales:

```
total_capabilities        63
business_capabilities     34   (19 commerce + 1 conversation + 14 marketplace)
business_complete         25
business_completeness     73.53%
by_source                 commerce 19, marketplace 14, node 29, binding 1
by_status                 AVAILABLE 24, NEEDS_CONFIGURATION 25, NEEDS_INSTALLATION 14
events                    37
```

Brechas honestas: `inventory.reserve/release/commit`, `sales.order.create/
confirm/mark_paid/fulfill/cancel` y otras capacidades tienen output schema
`object` sin propiedades; 9 nodos no tienen `business_schema`. Se reportan en
`coverage.contract_gaps` y en el digest, no se rellenan con suposiciones.

## 9. Evidencia de aislamiento multi-tenant

Test `test_tenant_isolation_does_not_leak_installs_or_agents`:

- Org A instala `demo-echo`; Org B no.
- Snapshot A: `demo.echo.availability.installed = true`; snapshot B:
  `NEEDS_INSTALLATION`.
- Agente privado de A no aparece en B; `GET /capabilities/agent.<id>` con la
  sesión de B devuelve `404`.
- El descriptor del agente no contiene `system_prompt` ni secretos.

## 10. Integración con el planner

- `discover_capabilities()` construye el snapshot y proyecta el shape existente
  (`agents`, `knowledge_bases`, `actions`, `managed_db`) + `capabilities`,
  `resources`, `tools`, `capability_index`, `capability_snapshot`.
- `capability_digest(caps, query=…)` busca por el pedido y renderiza **solo los
  contratos relevantes** (ref, estado, ejecutable, inputs/outputs, permisos,
  bloqueos). No vuelca las 63 capacidades.
- Nuevo paso semántico `capability_call` (`params.capability`, `params.inputs`,
  `inputs[{step, field, to}]`) compila al nodo `capability_call` existente. El
  validator exige ref conocida, disponibilidad ejecutable e inputs requeridos.
- El guardado (`/architect/draft`) re-descubre con snapshot fresco y verifica
  el `capability_snapshot_hash` del plan.

## 11. Pruebas

| Caso obligatorio | Test | Resultado |
|---|---|---|
| Instalada y habilitada | `test_installed_and_enabled_capability_is_available` | ✅ |
| Existe, no instalada | `test_existing_but_not_installed_is_an_option` | ✅ |
| Instalada sin credenciales | `test_installed_without_credentials_needs_credentials` | ✅ |
| Sin permiso | `test_user_without_permission_cannot_execute` | ✅ |
| Dos proveedores | `test_two_providers_expose_alternatives` | ✅ |
| Cambio de versión | `test_contract_version_change_changes_hashes` | ✅ |
| Output no satisface input | `test_composition_is_derived_from_schemas` | ✅ |
| Aislamiento de tenant | `test_tenant_isolation_does_not_leak_installs_or_agents` | ✅ |
| Capacidad nueva sin tocar prompt | `test_new_capability_is_discovered_without_code_changes` | ✅ |
| Catálogo grande con top-k | `test_large_catalog_returns_top_k_and_total` | ✅ |
| Digest con contratos y KB | `test_capability_digest_includes_contracts_and_kb_names` | ✅ |
| API search/inspect/metrics | `test_capability_api_search_inspect_and_metrics` | ✅ |
| `capability_call` compila | `test_capability_call_compiles_with_contract_inputs` | ✅ |
| Sin binding bloquea | `test_capability_call_missing_binding_blocks_and_reports_requirement` | ✅ |
| Snapshot obsoleto → 409 | `test_draft_rejects_stale_capability_snapshot` | ✅ |
| Cambio no relacionado → 200 | `test_draft_allows_unrelated_catalog_changes` | ✅ |

Resultados: `tests/test_capability_registry.py` + `test_workflow_architect_capability_call.py` → **18 passed**. Suite de regresión del Architect + registry + studio/readiness → **48 passed**. Architect+patch+eval+canonical → **36 passed**. Workflows legacy + marketplace + catálogo → **34 passed**. Durabilidad → **27 passed**. Certificación (gold + portabilidad + dependencias de Marketplace) → **11 passed**. Frontend dirigido → **11 passed**; `tsc --noEmit` sin errores; `vite build` OK; `ruff`/`eslint` limpios.

## 12. Limitaciones declaradas

1. La búsqueda semántica con embeddings es opcional y acotada al top léxico; no
   se ejecuta por defecto (costo/latencia) y su cache es in-process.
2. El historial de snapshots vive en el proceso: en multi-worker, un draft que
   cae en otro worker puede recibir `409` y exigir re-interpretar (seguro, no
   silencioso).
3. Los recursos `managed_db`/conectores no exponen schema de tablas; se marcan
   `schema_source="unknown"` y `contract_gaps` en lugar de inventarlo.
4. Las descripciones de las capacidades commerce se derivan de un mapa de
   negocio; los contratos (schemas, permisos, riesgo, efectos) salen de
   `commerce/contracts.py`.
5. `for_each` sigue fuera del vocabulario semántico (bloqueado por el validator).
6. La tool de agentes sólo aparece si el Agent Runtime registró sus tools en el
   proceso; no se instancian tools con dependencias desde el registry.

## 13. Archivos

**Nuevos**
- `src/platform/workflows/capability_registry.py`
- `src/platform/workflows/capability_services.py`
- `src/api/routes/capabilities.py`
- `tests/test_capability_registry.py`
- `tests/test_workflow_architect_capability_call.py`

**Modificados**
- `src/platform/workflows/architect_discovery.py` (snapshot + digest por query)
- `src/platform/workflows/architect_models.py` (`capability_call`, `PlanInputRef.to`)
- `src/platform/workflows/architect_compiler.py` (nodo `capability_call`, actions dict)
- `src/platform/workflows/architect_validator.py` (contrato/disponibilidad/inputs)
- `src/platform/workflows/architect.py` (digest query, snapshot hash, draft stale)
- `src/platform/workflows/versions.py` (gate de capacidades al publicar)
- `src/api/routes/workflows.py` (`capability_snapshot_hash` y 409)
- `src/api/main.py` (router)
- `portal/src/components/workflowStudio/workflowArchitect.ts` y `ArchitectAskZent.tsx`
  (hash de snapshot + cobertura visible)
