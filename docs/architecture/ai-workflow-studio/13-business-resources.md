# Prompt 05 — Business Resource Resolution y Capability Binding

> **Fase:** resolución de recursos reales del tenant. **Fecha:** 2026-10-19.
> **Base:** `7af5020` (Semantic Compiler v2).
> **Alcance:** descubrimiento read-only, autoridad, campos, bindings,
> disponibilidad, agentes, configuración guiada y contratos entre sistemas.
> **No** se crea un catálogo ficticio ni se reemplaza la fuente de verdad.

## 1. Fuentes reutilizadas

`BusinessResourceResolver` (`src/platform/workflows/business_resources.py`)
proyecta, sin duplicar registros:

| Fuente | Uso |
|---|---|
| `catalog_sources` / `catalog_tables` / `catalog_columns` | conexiones, tablas, tipos, nulabilidad, PK y sensibilidad |
| `catalog_entities` / `catalog_fields` | Semantic Catalog y Mapping Studio |
| `catalog_authority` | fuente autoritativa por dominio/concepto |
| `knowledge_bases` | conocimiento documental vía snapshot |
| `connectors` / `managed_databases` | proveedores y bases del tenant |
| Capability Registry / Marketplace | capacidades, acciones, instalación, salud |
| `workflow_capability_bindings` | proveedor real por capacidad lógica |
| `agents` | agentes desplegados, herramientas y knowledge scope |

El resolver es read-only. No ejecuta SQL generado por el LLM, no lee filas y no
devuelve credenciales ni configuración de binding.

## 2. Descubrimiento autorizado

La API nueva:

```http
POST /api/v1/workflows/architect/resources/resolve
{
  "need": "catálogo real de productos con precio y moneda",
  "required_fields": [
    {"name": "price", "type": "number", "currency": "PEN"},
    {"name": "stock", "type": "integer"}
  ],
  "concepts": ["stock"],
  "domain": "commerce",
  "kinds": ["catalog_table", "catalog_entity"],
  "capability_refs": ["catalog.products.search", "payments.qr.create"],
  "limit": 10
}
```

El Planner también recibe la herramienta `resource.resolve` con el mismo
contrato. `resource.inspect_schema` sigue inspeccionando un recurso concreto y
`agent.search` descubre agentes por propósito, herramientas y conocimiento.

El reporte `zent.resource.resolution/v1` devuelve:

- recurso seleccionado o `null`;
- candidatos con schema, campos, tipos, unidad y moneda;
- autoridad por concepto;
- ambigüedades;
- requisitos no resueltos;
- bindings por capacidad;
- candidatos de capacidades y agentes;
- configuración guiada;
- traza con snapshot hash y conteos, sin secretos.

## 3. Identificación de autoridad

`catalog_authority` se evalúa con vigencia (`effective_from/effective_to`).

Reglas:

- una sola fuente con la prioridad máxima: se selecciona;
- varias fuentes con la misma prioridad: `RESOURCE_AUTHORITY_AMBIGUOUS`;
- sin autoridad y varias fuentes compatibles: `RESOURCE_AMBIGUOUS`;
- datos de conocimiento y datos transaccionales en la misma necesidad:
  `RESOURCE_CLASS_AMBIGUOUS`; nunca se sustituye stock por RAG;
- con `required_fields` y autoridad faltante: requisito explícito.

La autoridad no se inventa: si el tenant no la registró, el resultado pide
configurarla en Mapping Studio / Semantic Catalog.

## 4. Bindings

Cada necesidad de capacidad se resuelve primero a la capacidad lógica:

`payments.checkout.create` → binding del tenant → Stripe/IZIPAY/rest_api.

`BindingReport` incluye:

- versión y hash de contrato;
- disponibilidad lógica;
- binding encontrado, id lógico, provider kind y estado;
- presencia de credential ref (nunca el secreto);
- permiso, aprobación, degradación e instalación;
- razones.

El plan conserva `capability_ref`; el binding físico se resuelve en ejecución.
El reporte de resolución es evidencia de configuración, no una referencia
física dentro del plan.

## 5. Disponibilidad y configuración guiada

Se distinguen:

`AVAILABLE`, `NEEDS_INSTALLATION`, `NEEDS_CREDENTIALS`,
`NEEDS_CONFIGURATION`, `PERMISSION_DENIED`, `PENDING_APPROVAL`,
`DEGRADED`, `INCOMPATIBLE`, `DEPRECATED`, `UNAVAILABLE`, `UNKNOWN`.

Una integración instalada no se considera saludable por sí sola: se revisan
credenciales, binding, estado del provider y `health_status`.

Cada faltante produce `GuidedConfiguration`:

- qué necesita;
- para qué sirve;
- módulo responsable (`catalog`, `integrations`, `marketplace`, `rbac`);
- disponibilidad en Marketplace;
- pasos concretos;
- permisos;
- pruebas que deben superarse.

No se instala, conecta ni modifica nada automáticamente. Esas acciones requieren
una operación explícita y autorizada del usuario.

## 6. Agentes como capacidades

`agent.search` y `agent_candidates` usan:

- propósito/descripción;
- herramientas;
- knowledge base scope;
- schema de entrada/salida;
- estado de despliegue;
- permisos;
- presupuesto;
- versión.

El ranking combina esos campos, no solo el nombre. Un agente no ejecutable se
reporta con su estado; no se ofrece como disponible.

## 7. Contratos entre sistemas

La resolución evalúa:

- campos requeridos presentes;
- tipos JSON (`string`, `number`, `integer`, `array`, `object`, `boolean`);
- unidad y moneda de campos de Mapping Studio;
- nulabilidad;
- identificadores y taxonomía de `mapping_type`;
- cardinalidad de arrays;
- campos sensibles/PII para advertencia;
- contrato de entrada de la capacidad y salida esperada.

Una transformación no se inventa. Si el campo no existe o el tipo no es
compatible, el resolver devuelve `RESOURCE_FIELD_MISSING`,
`type_mismatches`, `unit_mismatches` o `currency_mismatches`, y el Planner debe
corregir o pedir confirmación.

## 8. Seguridad

- consultas SQL fijas y parametrizadas; ninguna consulta arbitraria del LLM;
- `organization_id` y `workspace_id` en cada consulta de catálogo;
- fuentes de otro workspace no aparecen;
- bindings redactados;
- sin filas de negocio, secretos ni credenciales;
- descubrimiento read-only; simulación sin escrituras;
- ejecución real revalida permisos y binding en runtime;
- publicación revalida contrato/version/permisos (Prompt 04).

## 9. Prueba principal: tenant real

`tests/test_business_resource_resolution.py` siembra, con SQL real en la base de
pruebas:

- conector y tablas PostgreSQL de catálogo;
- tabla de inventario;
- entidad `Product` y campos de Mapping Studio;
- autoridad de stock;
- Knowledge Base;
- agente con herramientas y presupuesto;
- binding de catálogo;
- binding de pago de pruebas;
- una capacidad de pago sin binding.

Escenarios cubiertos:

| Requisito | Prueba |
|---|---|
| Descubre el catálogo correcto | `test_discovers_catalog_entity...` |
| Inspecciona campos y moneda | misma prueba |
| Distingue conocimiento de datos | `test_knowledge_is_distinguished...` |
| Resuelve autoridad de stock | `test_authority_selects_inventory...` |
| No elige arbitrariamente | `test_ambiguous_stock...` |
| Campo requerido ausente | `test_missing_required_field...` |
| Binding lógico y payment provider | `test_binding_is_resolved...` |
| Agente por propósito/herramientas | `test_agents_are_ranked...` |
| Aislamiento workspace | `test_workspace_isolation...` |
| API read-only y trazable | `test_resource_api...` |
| Tool del Planner | `test_planner_resource_tool...` |

Resultado local: **10 passed**.

## 10. Límites declarados

- El resolver no ejecuta consultas de negocio ni valida filas; valida metadatos,
  contratos y configuración.
- La autoridad se aplica a los conceptos declarados por el Planner; no adivina
  conceptos a partir de todo el prompt.
- El validador de payload y compatibilidad es determinista y acotado; no sustituye
  una prueba real contra el proveedor.
- Marketplace no se instala desde el resolver.
- Los agentes requieren `agents:execute`; los bindings requieren autorización de
  workflow.
- No se declara Zent listo para producción: falta ejecución contra todos los
  conectores/proveedores reales y carga empresarial completa.
