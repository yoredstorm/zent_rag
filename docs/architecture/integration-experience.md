# Zent Integration Experience — Universal API Connector + Living Assistants

> **Status:** Fases F (importer OpenAPI), G (borradores + install), H/I (assistentes,
> actividad e inbox) implementadas. Eventos de connector (§19-20), owner/team (§30)
> y output trust en el nodo `llm` (§40) quedan como siguiente entrega.
> **Fecha:** 2026-09-13
> **Base:** `feat/knowledge-cognitive-os` @ `54f9c5c`
> **Principio:** el discovery nunca ejecuta endpoints; el LLM nunca inventa endpoints;
> las credenciales nunca tocan el grafo.

Este documento audita el estado real del repo contra la misión "Zent Integration
Experience" y describe lo entregado en este commit.

---

## 1. Auditoría (qué existía antes de esta entrega)

| Área | Estado previo (verificado) |
|---|---|
| Manifest v2 (`actions[]` + `events[]`) | ✅ `models.py`, columna `events` (migración 111) |
| PokéAPI / Open-Meteo / JSONPlaceholder | ✅ `demo_integrations.py` con provider `public_rest` |
| Recetas demo (5) | ✅ `DEMO_RECIPES` + `create_from_template` con wire de installs |
| Formularios dinámicos de acciones | ✅ `NodeConfigPanel` + `ports_for_action` + `BusinessParameterForm` |
| Demo Center | ✅ `portal/src/pages/DemoCenter.tsx` |
| Assistants backend | ✅ `agents/{id}/automations` + salud |
| Consola de prueba (backend) | ✅ `POST /installs/{id}/test` y `.../actions/{id}/execute` |
| **Universal API Connector / OpenAPI** | ❌ no existía |
| **Consola de prueba (UI) / import UI** | ❌ no existía |
| **Scoping por tenant de manifests** | ❌ `integration_manifests` era global |
| **Rate limits de integración** | ❌ declarados pero no aplicados |
| **Feed de actividad / inbox de asistente** | ❌ `AgentOverview` huérfano; `/intelligence` sin ruta |
| **UX Asistentes (home + detalle + agregar automatización)** | ❌ no existía |

---

## 2. Entregado en esta entrega

### 2.1 Universal API Connector (fases F–G)

Pipeline determinista **sin ejecutar endpoints de la API externa**:

```
documento OpenAPI (URL o pegado/archivo)
    ↓ parse_openapi_document()      JSON o YAML, OpenAPI 3.x (2.0 rechazado con mensaje)
    ↓ validación de seguridad       https obligatorio, SSRF check, tamaño, sin redirects
    ↓ discover_operations()         operaciones → capabilities/actions de negocio
    ↓ build_draft()                 IntegrationDraft (labels, schemas, output_map, auth)
    ↓ revisión humana               PATCH /drafts/{id} (renombrar, habilitar, mapping, auth)
    ↓ install_draft()               manifest PRIVADO del tenant + installed_integration
```

- `src/platform/marketplace/openapi_import.py` — parser, detección de auth
  (none/api_key/bearer/basic/oauth2), schemas de negocio (`x-business-label`),
  `output_map` identidad editable, reporte de operaciones omitidas (DELETE, etc.).
- `src/platform/marketplace/connector_drafts.py` — persistencia de borradores,
  revisión humana y `install_draft`.
- `src/infrastructure/db_init/versions/113_integration_connector.py` (+ SQL 85) —
  `integration_drafts` y `integration_manifests.organization_id`.
- `src/api/routes/integration_connector.py` —
  `POST /api/v1/integrations/import/openapi`, `GET/PATCH/DELETE /drafts[/{id}]`,
  `POST /drafts/{id}/install`.
- `portal/src/pages/IntegrationsPage.tsx` — import (URL / archivo / pegado),
  revisión con labels editables, instalación, credenciales SecretStore y
  **consola de prueba** con formulario de negocio + salida humana (`DataView`).

### 2.2 Manifests privados por tenant y rate limits

- `catalog.list_catalog/get_manifest/register_manifest` aceptan `organization_id`;
  los manifests importados **no se filtran a otros tenants** (test dedicado).
- `runtime._enforce_rate_limits()` aplica `requests_per_minute` / `requests_per_day`
  con Redis (fail-open) y devuelve `RATE_LIMITED` + `retry_after`.
- `Retry-After` de 429 se propaga (`PROVIDER_RATE_LIMITED`, `retry_after`).
- `_execute_rest` ahora soporta PATCH, Basic Auth, fallback de `base_url` al
  `provider_config` y no envía path params como query.

### 2.3 Living Assistants UX (fases H–I)

- `src/platform/workflows/assistant_activity.py` — feed business-friendly derivado
  de `workflow_runs` + `workflow_run_steps` ("El agente analizó…", "Envió una
  notificación…", "La condición se cumplió…"); los ids/latencia/correlación van
  en `tech` y se muestran sólo en "Ver detalles técnicos".
- `GET /api/v1/agents/assistants` — home de asistentes (salud, qué vigila,
  automatizaciones, actividad de hoy, owner).
- `GET /api/v1/agents/{id}/activity` — feed legible + detalles técnicos.
- `portal/src/pages/AssistantsPage.tsx` — cards de asistente (§22).
- `portal/src/pages/AssistantDetailPage.tsx` — tabs Resumen / Automatizaciones /
  Actividad / Conocimiento / Permisos / Ajustes, botón "Agregar automatización"
  con textarea → copiloto (`/workflows/new/ask?agent=…&q=…`) y nota de costo
  ("puede funcionar sin IA").
- Inbox (§29): `business_results.acknowledged_at/by` (migración 114 + SQL 86),
  `POST /api/v1/intelligence/results/{id}/acknowledge`; la página Intelligence
  vuelve a tener ruta (`/intelligence`) y ofrece "Marcar resuelto" + "Abrir workflow".
- `AskZent` acepta `initialPrompt/agentId/agentName` y **preselecciona el agente**
  del asistente en los nodos `llm` del plan compilado (no lo obliga: si no hay
  nodo llm, el flujo es determinista).

---

## 3. Seguridad (misión §38-§41)

| Riesgo | Mitigación implementada |
|---|---|
| SSRF en import | https obligatorio + `CallApiTool._ssrf_check` (bloquea localhost/metadata/privadas), sin redirects |
| Documento malicioso | tamaño máximo 2 MB, JSON/YAML parseado sin ejecución, máximo 50 operaciones |
| Métodos peligrosos | allowlist GET/POST/PUT/PATCH; DELETE se omite y se reporta |
| Credenciales | sólo `POST /installs/{id}/credentials` → SecretStore; nunca en graph ni en respuestas |
| Cross-tenant | manifests con `organization_id`; drafts y ejecución tenant-scoped (tests) |
| Abuso de API externa | rate limits por integración, circuit breaker existente, timeout y límite de respuesta |
| Datos externos | la ejecución se registra como `external_evidence` (UNTRUSTED) |

**Pendiente §40:** el nodo `llm` interpola outputs de `marketplace_action`/`api_call`
como texto; falta envolverlos explícitamente como `UNTRUSTED DATA` a nivel de nodo
(hoy la defensa vive en el system prompt del AgentRuntime).

---

## 4. Pendientes explícitos

| Tema | Estado |
|---|---|
| Connector events (manifest `events[]` visible en catálogo de eventos y trigger UI) | Pendiente: `register_manifest` ya persiste `events`, falta surfacing en `event-catalog` |
| Polling event adapter (HTTP cursor/watermark → BusinessEvent) | Pendiente: contrato en `living-workflows.md` (fase F/G) |
| Owner/team en workflows y su uso en errores/aprobaciones | Pendiente: `workflows.created_by` existe pero no se expone ni usa |
| Output trust en nodo `llm` | Pendiente |
| OAuth2 completo en connector | Pendiente: hoy se acepta token temporal; UX de proveedor OAuth queda para la fase de infraestructura compartida |
| Mapping editor avanzado (paths anidados) | Parcial: `output_map` editable vía API; UI edita labels y el mapping generado |

---

## 5. Verificación

- `tests/test_openapi_connector.py` — parser JSON/YAML, seguridad SSRF/límites,
  auth, revisión humana, install, ejecución mockeada, aislamiento cross-tenant,
  rate limit y Retry-After.
- `tests/test_assistants.py` — home, feed de actividad (runs/steps sembrados),
  inbox acknowledge.
- `tests/test_integration_experience.py` — sin regresiones (PokéAPI/Open-Meteo/
  JSONPlaceholder + recetas demo).
- `tests/test_workflow_marketplace.py`, `test_workflow_graph.py`,
  `test_workflow_studio.py`, `test_workflows.py`, `test_living_workflows.py`,
  `test_workflow_business_schema.py`, `test_workflow_partial_runs.py` — 100 passed.
- `portal/src/pages/IntegrationsPage.test.tsx`, `typecheck` y suites existentes.
- Docker: `pyyaml` declarado explícitamente en `Dockerfile.api` y `pyproject.toml`
  (litellm solo lo trae en extras proxy/cli); import YAML perezoso para que los
  documentos JSON sigan funcionando sin esa dependencia. `docker compose config`
  validado en dev y prod; `npm run build` del portal verificado.
