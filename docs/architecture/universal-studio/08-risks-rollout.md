# 08 — Riesgos, rollout y rollback

## 1. Registro de riesgos

| ID | Riesgo | Prob. | Impacto | Mitigación | Propietario | Disparador |
|---|---|---|---|---|---|---|
| R-01 | El planner real sigue devolviendo salida vacía/DSML y no genera Gold | Alta | Alto | Parser robusto, presupuesto, modelo alternativo, eval 100; no publicar con IA | AI/Workflow Lead | `planner.invalid_llm_output` |
| R-02 | El gate de certificación bloquea workflows válidos y frena operación | Media | Alto | Fase `report` → `warn` → `block`; `acknowledge_blockers`; allowlist temporal | Workflow Lead | Aumento de 409/400 en publish |
| R-03 | El arranque durable duplica efectos al reintentar | Media | Crítico | `business_key`, idempotencia, señales, tests de doble webhook, snapshot congelado | Runtime Lead | Doble orden/pago |
| R-04 | La versión de agente fijada no coincide con la versión desplegada | Media | Alto | Resolución determinística, fallback marcado, test de dos versiones | Agent Lead | Run con `legacy_unpinned` |
| R-05 | Un rol de bienestar produce diagnóstico/daño | Media | Crítico | Política determinística, adversariales, handoff, incidentes, no GO sin fase 07 | Safety Lead | `safety_incident` |
| R-06 | Fuga cross-workspace en instancias/agente→workflows | Media | Alto | Filtro workspace, tests, auditoría; no exponer consola sin filtro | Platform Lead | Instancia de otro workspace visible |
| R-07 | PII en trazas de workflow | Alta | Alto | `mask_pii` antes de persistir, tests, retención | Security Lead | PII en DB |
| R-08 | El canvas y el marketplace muestran catálogos distintos | Alta | Medio | `/products` único storefront; migración de canvas; legacy marcado | Product/Portal Lead | Acción no instalable desde canvas |
| R-09 | Presupuesto/concurrencia mal calibrados bloquean workflows legítimos | Media | Medio | Defaults conservadores, telemetría, override por org, flag | SRE Lead | `BUDGET_EXCEEDED` inesperado |
| R-10 | La consulta agente→workflows es O(N) y degrada con muchos workflows | Media | Bajo | Índice GIN, límite, vista materializada si hace falta | Backend Lead | Latencia del detalle de agente |
| R-11 | Migraciones aditivas fallan en bases legacy | Baja | Alto | Idempotencia, `IF NOT EXISTS`, pruebas upgrade/downgrade, backup | DBA/Platform | Error de migración |
| R-12 | Los workflows legacy se rompen por el nuevo gate | Media | Alto | Exención legacy, fase `report`, rollback flag, tests de regresión | Workflow Lead | Aumento de fallos en workflows v1 |
| R-13 | La suite de certificación sigue con timeouts y no da señal | Alta | Medio | Separar suites, presupuesto de tiempo, runners por archivo, JUnit | QA Lead | Timeout |
| R-14 | El marketplace de roles introduce permisos implícitos | Baja | Crítico | Rol = metadata; permisos RBAC; revisión de seguridad | Security Lead | Permiso no declarado |
| R-15 | El alcance universal diluye el caso Gold de ventas | Media | Medio | Gold como caso de aceptación; no bloquear el plan por verticales | Product Lead | Regresión del Gold |
| R-16 | Falta de credenciales sandbox impide certificar pagos | Alta | Alto | Entorno sandbox dedicado; contratos; no declarar GO sin evidencia | QA/Partners | Sin sandbox |
| R-17 | El coste del LLM real se dispara en evaluación | Media | Medio | Presupuesto por job, modelo barato, límite de tokens, cache | FinOps | Coste > umbral |
| R-18 | El audit log crece sin retención | Media | Bajo | Retención por org, particionado, muestreo | SRE | Crecimiento de tabla |

## 2. Riesgos que no se pueden aceptar silenciosamente

Estos requieren decisión explícita y firmada antes de producción:

1. **R-05** bienestar: no se lanza sin política y adversariales.
2. **R-03** duplicación de efectos: no se lanza sin idempotencia probada.
3. **R-07** PII: no se lanza sin máscara en trazas.
4. **R-06** workspace: no se lanza consola sin filtro.
5. **R-16** sandbox: no se declara GO de pagos sin sandbox real.

## 3. Rollout por olas

| Ola | Alcance | Duración | Criterio de avance |
|---|---|---|---|
| 0 | Interno, datos sintéticos, flags off | 1 semana | baseline verde, migraciones OK |
| 1 | Design partners, 1 workspace, roles no sensibles | 2 semanas | sin P0, feedback, métricas |
| 2 | Tenants productivos, workflows existentes | 2 semanas | sin regresión, soporte |
| 3 | Creación IA, tenants seleccionados | 2 semanas | Gold + eval + gate |
| 4 | Universal Studio, roles sensibles | 4 semanas | fase 07/09 |

Cada ola:

- activa flags por org/workspace, no global;
- compara métricas de runs, errores, latencia y costo;
- tiene criterio de abortar y rollback;
- no cambia workflows publicados ni instancias vivas.

## 4. Rollback por fase

| Fase | Flag | Rollback de código | Rollback de datos |
|---|---|---|---|
| 01 | todos off | deploy anterior | columnas nullable se conservan |
| 02 | `AGENT_ROLE_POLICIES_ENABLED=false` | agentes vuelven a modo legado | `role_*` se conserva |
| 02 | `AGENT_VERSION_PINNING_ENABLED=false` | runtime usa agente vivo | `agent_versions` se conserva |
| 03 | `STUDIO_SOLUTIONS_ENABLED=false` | oculta intake | `studio_solutions` se conserva |
| 04 | `MARKETPLACE_UNIFIED_CANVAS=false` | canvas vuelve a `/integrations` | sin cambios |
| 05 | `WORKFLOW_DURABLE_TRIGGERS_ENABLED=false` | vuelve a `run_workflow` | instancias existentes se conservan |
| 05 | `WORKFLOW_RUN_BUDGETS_ENABLED=false` | no aplica límites | usage se conserva |
| 06 | `WORKFLOW_CERTIFICATION_GATE=report` | no bloquea | certificaciones se conservan |
| 07 | `AGENT_ROLE_POLICIES_ENABLED=false` | desactiva guardrails | incidentes se conservan |
| 08 | `UNIVERSAL_STUDIO_ENABLED=false` | portal anterior | sin cambios |
| 09 | flags por ola | deploy anterior | artefactos/evidencia se conservan |

**Regla:** nunca se borra una versión publicada, una instancia o una
certificación para “rollback”. Se desactiva el camino nuevo y se conserva la
evidencia.

## 5. Runbook mínimo

### 5.1 El gate bloquea un workflow que antes funcionaba

1. Confirmar flag `WORKFLOW_CERTIFICATION_GATE`.
2. Bajar a `warn` o `report` por org.
3. Revisar `PublicationEvidence.reasons`.
4. Corregir configuración o certificar.
5. Reintentar publish.
6. No borrar la versión anterior.

### 5.2 Un workflow durable falla en schedule

1. Confirmar `graph_requires_instance`.
2. Revisar `trigger_mode` del run.
3. Si no creó instancia, activar flag o revisar despliegue.
4. Si creó instancia y falló, revisar `instance_timeline`.
5. Reanudar por señal o cancelar; no reejecutar a ciegas.

### 5.3 El planner real falla

1. Revisar `artifacts/certification/ai/gold-real-llm.c65dbdf.json`.
2. Confirmar modelo/proveedor y presupuesto.
3. No publicar el borrador.
4. Activar fallback heurístico solo con confirmación humana.
5. Registrar incidente de calidad.

### 5.4 Incidente de bienestar

1. Detener el agente/rol (`AGENT_ROLE_POLICIES_ENABLED=false` o pausar).
2. Preservar `safety_incidents` y trazas.
3. Notificar a Safety Lead.
4. Revisar política y adversariales.
5. No reactivar sin aprobación.

## 6. Métricas de adopción y salud

| Métrica | Uso |
|---|---|
| `studio_solutions_created` | adopción del intake |
| `studio_solutions_published` | conversión a producción |
| `workflow_publish_denied_total{reason}` | fricción del gate |
| `workflow_certification_state{state}` | calidad de simulación |
| `workflow_durable_trigger_total` | cobertura durable |
| `workflow_run_budget_exceeded_total` | calibración |
| `agent_version_pinned_total` | reproducibilidad |
| `safety_incident_total{role}` | bienestar |
| `workflow_trace_pii_masked_total` | privacidad |
| `workflow_run_cost_usd{workflow}` | FinOps |

## 7. Riesgos abiertos con propietario

| Riesgo | Propietario | Fecha objetivo | Estado |
|---|---|---|---|
| Gold real | AI/Workflow Lead | Fase 09 | Abierto |
| Sandbox pagos | QA/Partners | Fase 09 | Abierto |
| Carga/chaos | SRE Lead | Fase 09 | Abierto |
| Worker restart | SRE Lead | Fase 09 | Abierto |
| Bienestar | Safety Lead | Fase 07 | Abierto |
| PII trazas | Security Lead | Fase 07 | Abierto |
| Workspace isolation | Platform Lead | Fase 05 | Abierto |
| Marketplace canvas | Product/Portal Lead | Fase 04 | Abierto |
| Timeout certificación | QA Lead | Fase 01/09 | Abierto |

Estos riesgos se revisan en el gate de cada fase. Ninguno se cierra por “existe
una clase” o “existe un test simulado”.
