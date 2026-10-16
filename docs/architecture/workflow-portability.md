# Portabilidad de workflows (zent.workflow.package/v1)

Estado: implementado (migración 156)
Fecha: 2026-10-16

## Objetivo

Un workflow portable depende de **capacidades lógicas**, no de tablas, acciones
concretas ni credenciales. Tenant A exporta; Tenant B importa, resuelve sus
bindings y ejecuta el mismo proceso.

```
catalog.products.search
      ↓ (binding del tenant)
managed db | connected db | marketplace action | semantic query | REST | ERP
```

## Formato `zent.workflow.package/v1`

```json
{
  "schema": "zent.workflow.package/v1",
  "schema_version": 1,
  "package_version": "1.0.0",
  "generated_at": "...",
  "checksum": "sha256 de (package sin checksum)",
  "metadata": {"name": "...", "description": "...", "min_zent_version": null},
  "workflow": {"graph": {...}, "trigger_type": "...", "trigger_config": {...}},
  "dependencies": [{"kind": "capability|action", "ref": "...", "requirement": "required|optional"}],
  "capabilities": [{"ref": "catalog.products.search", "requirement": "required"}],
  "events": [{"ref": "payment.succeeded", "requirement": "required"}],
  "parameters": {...},
  "permissions": ["external_actions:execute"],
  "tests": [],
  "security": {"contains_secrets": false, "tenant_scoped": false}
}
```

Nunca viaja: API keys, passwords, connection strings, secrets, `hook_secret_hash`,
`organization_id`/`workspace_id`/`tenant_id`, `install_id`, `credential_ref`.
La denylist es dura (`packages.scan_security`) y bloquea el import (`UNSAFE`).

Los contratos de cada capacidad (`contract_input_schema` /
`contract_output_schema`) viven en el **binding del tenant**, no en el paquete:
el mismo workflow exige la misma forma de datos, cada tenant la implementa con
su proveedor.

## Import en dos fases

```
POST /workflows/import/inspect   → readiness report, NO persiste
POST /workflows/import           → re-valida y crea SOLO draft
POST /workflows/{id}/publish     → bloqueado si hay requisitos críticos
```

Estados del report: `RESOLVED`, `OPTIONAL_MISSING`, `NEEDS_CONFIGURATION`,
`NEEDS_CREDENTIALS`, `DISABLED`, `MISSING`, `VERSION_MISMATCH`,
`PERMISSION_DENIED`, `AMBIGUOUS`, `UNSAFE`.

Cada item incluye `kind`, `requirement`, `message`, `hint` y `resolution`
(p. ej. `marketplace`) para el CTA "Resolver" del Studio, que apunta al
Marketplace global (no se embebe marketplace dentro del workflow).

## CapabilityBinding

`workflow_capability_bindings` (155): `capability_ref` → `provider_kind` +
`config` + contratos. Unique por `(org, workspace, capability_ref)` con
variante org-level (`workspace_id NULL`).

Providers con executor v1:

| provider | ejecución |
| --- | --- |
| `marketplace_action` | `execute_action` (marketplace runtime) — resolver capability→install reutilizado |
| `semantic_query` | RAG orchestrator (semantic compiler + text-to-SQL) |
| `managed_db` / `connected_db` | SELECT declarativo validado (tabla/columnas/filtros/orden/límite ≤ 500), sin SQL en plantillas |
| `rest_api` | httpx con SSRF check + credenciales del SecretStore |

`erp` y `custom` están registrados como kinds sin executor: un workflow que los
requiera devuelve `NEEDS_CONFIGURATION` explícito (nunca falla en silencio).

El nodo `capability_call` ejecuta `capability_ref + inputs`; errores accionables
como `NEEDS_CONFIGURATION`, `NEEDS_CREDENTIALS`, `CONTRACT_INVALID`.

## Export

`GET /workflows/{id}/export` produce el paquete con `checksum` sha256 del
contenido canónico (sin el propio checksum), `schema_version`, `package_version`
y `generated_at`. Firmas de publisher quedan como evolución futura.

## Templates

Un solo sistema: `workflow_templates` gana `package JSONB` y `graph JSONB`;
`steps` legacy se conserva para compatibilidad. `create_from_template` usa
`graph` cuando existe (paquete) y cae al wiring legacy de instalaciones cuando
no.

## Test portable

`tests/test_workflow_durable_instances.py::test_portable_package_export_inspect_import`:
Tenant A exporta un workflow con `capability_call` → Tenant B inspecciona
(detecta la capacidad sin resolver), import bloqueado con 409, B configura el
binding, import crea draft, publicar activa, y el paquete pasa el scan de
seguridad. `test_import_rejects_package_with_secrets` prueba el rechazo UNSAFE.
