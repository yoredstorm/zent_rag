# 07 — GO / NO-GO

> **Actualización 2026-10-22:** el corte Gold horizontal no publica a producción.
> `ZENT_GOLD_RELEASE_ENABLED` queda en `false`. Evidencia y matriz en
> [`12-release-gold.md`](12-release-gold.md). La decisión de abajo sigue siendo
> el baseline de la auditoría; no se reescribió con números nuevos.

> **Decisión de esta fase: NO-GO para producción general.**
>
> No se declara GO del Universal Agent & Workflow Studio porque **no está
> implementado**. Lo que sí se certifica es el estado del runtime existente y la
> calidad de sus pruebas mockeadas/integración local.

## 1. Decisión global

| Dimensión | Decisión | Base |
|---|---|---|
| Runtime de workflows existente | **GO condicionado a staging controlado** | 81 + 44 tests verdes; WAIT/RESUME/instancias ya certificados en el SHA anterior; no se revalidó reinicio real en este HEAD |
| Creación de workflows con IA | **NO-GO** | Gold real `FAILED` con `planner.invalid_llm_output`; 0 pasos, 0 grafo |
| Universal Studio (rol → agente → workflow) | **NO-GO** | No implementado; plan 01–09 |
| Publicación con certificación | **NO-GO** | El gate no consume la certificación; `READY_TO_PUBLISH` acepta pins declarados |
| Workflows durables desde schedule/webhook | **NO-GO** | No crean instancia; fallan en el primer disparo |
| Marketplace global | **GO condicionado** | `/products` es canónico; canvas sigue usando `/integrations`; falta unificación |
| Bienestar / roles sensibles | **NO-GO** | No hay política de rol ni guardrails determinísticos |
| Operación empresarial | **NO-GO** | Sin consola de instancias/aprobaciones, sin budgets por workflow, sin PII masking en trazas |
| Proveedores reales (pagos) | **NO-GO** | Sin sandbox real en este HEAD |

## 2. Criterios GO por fase

### Fase 01 — Fundaciones

**GO si:**

- migraciones aditivas aplican y revierten;
- flags default off/report;
- contratos versionados;
- baseline verde;
- no hay cambio de comportamiento sin flag.

**NO-GO si:** migración destructiva, flag default on, baseline rojo.

### Fase 02 — Agente universal y roles

**GO si:**

- `role_key`, `role_profile`, `safety_policy` persisten;
- versión de agente gobierna runtime;
- agente en 2 workflows/2 workspaces sin fuga;
- tests de versión y rol verdes;
- agentes existentes siguen funcionando.

**NO-GO si:** rol concede permisos, versión no se usa, fuga workspace.

### Fase 03 — Compositor

**GO si:**

- blueprint con agentes + workflows;
- materialización solo con confirmación;
- no auto-publicación;
- no secretos/permisos en blueprint;
- e2e de rol a draft.

**NO-GO si:** auto-publicación, blueprint con bindings físicos, duplicación de
canvas/marketplace.

### Fase 04 — Capacidades y marketplace

**GO si:**

- readiness/publish usan `capability_registry`;
- canvas usa `/products`;
- legacy marcado y funcional;
- no hay catálogo nuevo.

**NO-GO si:** dos autoridades, canvas con catálogo distinto, retiro de legacy
sin ventana.

### Fase 05 — Ejecución

**GO si:**

- durable triggers crean instancia;
- no durable sigue igual;
- budgets/rate limit funcionan;
- service identity no amplía permisos;
- workspace isolation;
- `llm` v2 sin agente falla.

**NO-GO si:** doble efecto, instancia para todos, regresión legacy, fuga.

### Fase 06 — Simulación y gate

**GO si:**

- `UNVERIFIED`/stale no publican;
- `DECLARED` con efectos externos no es `READY`;
- sandbox/provider sí;
- cobertura crítica;
- gate manual;
- UI muestra evidencia.

**NO-GO si:** publicar stale, `READY` con pins, LLM real en simulación, gate
solo Architect.

### Fase 07 — Seguridad y bienestar

**GO si:**

- wellness no diagnostica/receta; deriva;
- publicar sin política se bloquea;
- PII fuera de trazas;
- audit log;
- RBAC probado o riesgo aceptado.

**NO-GO si:** respuesta clínica, PII en DB, publicación sin auditoría.

### Fase 08 — UX y operación

**GO si:**

- un solo flujo;
- consola read-only;
- aprobaciones/señales;
- sin duplicar superficies;
- accesibilidad.

**NO-GO si:** duplicación, operación sin workspace, acciones destructivas sin
confirmación.

### Fase 09 — Certificación y GA

**GO si:**

1. suite completa verde;
2. Gold real + dataset 100;
3. sandbox real;
4. load/backpressure;
5. sin P0;
6. wellness adversarial;
7. rollback ensayado;
8. evidencia por SHA/modelo.

**NO-GO si:** cualquiera de los anteriores falta.

## 3. Lo que cambiaría la decisión

Para pasar de NO-GO a GO en creación IA:

1. corregir el planner real (salida vacía/DSML/JSON) y ejecutar el Gold;
2. ejecutar 100 requerimientos con métricas por modelo/versión;
3. repetir reinicio real incluyendo worker;
4. sandbox real Stripe/IZIPAY con estados asíncronos y cross-tenant;
5. load/concurrencia con dos clientes por el último producto;
6. certificación persistida en el gate de publicación.

Para pasar de NO-GO a GO en Universal Studio:

1. completar fases 01–08;
2. certificar roles, multi-agente, versiones y workspace;
3. certificar bienestar con adversariales;
4. operar en staging con design partners;
5. ensayar rollback por flag.

## 4. Decisión recomendada

- **Mantener** workflows existentes y ejecución durable en staging controlado.
- **Bloquear** creación/publicación con IA para tenants productivos.
- **No exponer** roles de bienestar hasta fase 07.
- **No declarar** `READY_TO_PUBLISH` con pins declarados.
- **Iniciar** fase 01 (fundaciones) con flags off y migraciones aditivas.
- **Reevaluar** al cerrar fase 06 y fase 09 con la evidencia de
  [`06-test-evidence.md`](06-test-evidence.md).

## 5. Firma de responsabilidad

| Rol | Responsable | Decisión |
|---|---|---|
| Arquitectura | Principal Engineer / Architect | NO-GO global; plan 01–09 aprobado para ejecución por fases |
| Calidad | QA Lead | Baseline mockeado verde; real/sandbox/carga pendientes |
| Seguridad | Security Lead | NO-GO bienestar; PII y RBAC pendientes |
| Producto | Product Lead | Ventas Gold no certificado; universal studio no implementado |
| Operación | SRE Lead | Sin load/chaos/worker restart en este HEAD |
