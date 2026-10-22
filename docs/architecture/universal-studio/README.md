# ZENT — Universal Agent & Workflow Studio (Prompt 00)

> **Fase:** auditoría verificada + contrato de arquitectura + plan 01–09.
> **No se implementaron funcionalidades en esta fase.**
>
> **Fecha:** 2026-10-21.
> **HEAD auditado:** `c65dbdf729327eaf54fd74a9326cf5ae328dc0be`
> (`feat(workflows): add durable conversation guard and explicit AI fallback`).
> **Árbol de trabajo al iniciar:** limpio (`git status --porcelain` sin entradas).
> **Migración más reciente:** `162_conversation_guard.py`.
>
> **Implementación posterior:** la slice de RoleProfile/Solution está en
> [`../universal-roles/README.md`](../universal-roles/README.md) (migración 163).
>
> Regla de lectura: **donde este documento y el código discrepen, manda el código**.
> Cada hallazgo cita archivo y línea. Las afirmaciones de pruebas se separan en
> mocks, sandbox y proveedor real.

## 1. Propósito

Convertir ZENT de una plataforma con piezas técnicas potentes pero separadas
(agentes, workflows, marketplace, conocimiento, operaciones) en un
**Universal Agent & Workflow Studio**:

1. describir cualquier rol o proceso en lenguaje natural;
2. conectarlo con capacidades reales del tenant;
3. componer uno o varios agentes y uno o varios workflows;
4. simular, certificar y publicar con evidencia;
5. operar de forma segura, auditable y reversible.

Ventas es el caso Gold de referencia, **no** el modelo de dominio central.
El dominio universal es: **rol → agente(s) → workflow(s) → capacidades**.

## 2. Documentos

| # | Documento | Contenido |
|---|---|---|
| 00 | [`00-executive-summary.md`](00-executive-summary.md) | Resultado, cambios desde el último informe, bloqueos y decisión |
| 01 | [`01-as-is-audit.md`](01-as-is-audit.md) | Inventario verificado de superficies, flags, migraciones y recorridos |
| 02 | [`02-target-architecture.md`](02-target-architecture.md) | Modelo universal, límites, reutilización y contratos |
| 03 | [`03-gap-matrix.md`](03-gap-matrix.md) | AS-IS → TARGET → GAP → archivo → severidad → prueba |
| 04 | [`04-adr-universal.md`](04-adr-universal.md) | ADR específicos de la universalización |
| 05 | [`05-plan-01-09.md`](05-plan-01-09.md) | Fases, dependencias, archivos candidatos, integración, GO/NO-GO |
| 06 | [`06-test-evidence.md`](06-test-evidence.md) | Comandos, resultados y separación mock/sandbox/proveedor real |
| 07 | [`07-go-no-go.md`](07-go-no-go.md) | Criterios de certificación y decisión por dominio |
| 08 | [`08-risks-rollout.md`](08-risks-rollout.md) | Riesgos abiertos, propietarios, rollout y rollback |

## 3. Relación con el contrato anterior

Este trabajo **no reemplaza** `docs/architecture/ai-workflow-studio/`.
Lo extiende:

- `ai-workflow-studio/` resolvió el planner, el compilador semántico, la
  simulación ejecutable y las sesiones de diseño;
- `universal-studio/` resuelve el **dominio universal** (roles, composición
  agente↔workflow, operación, políticas de rol, marketplace único y gate de
  publicación end-to-end).

El informe de certificación
[`../certification/workflow-ai-go-no-go.md`](../certification/workflow-ai-go-no-go.md)
auditó `a826d8c`. El HEAD actual tiene **5 commits posteriores** y varios
bloqueos cambiaron de estado. La comparación está en
[`00-executive-summary.md`](00-executive-summary.md) §2.

La remediación del planner real, el dataset de 100 casos y la evidencia de
proveedor están en
[`../certification/universal-studio-remediation.md`](../certification/universal-studio-remediation.md).

## 4. No-objetivos (leyes respetadas)

- **Un solo engine:** `execute_graph()` / `run_workflow()`.
- **Un solo IR canónico:** `WorkflowGraph` v2.
- **Un solo scheduler de workflows:** `workflow_v2_scheduler_loop()`.
- **Un solo bus de eventos:** `events.py` + dispatcher existente.
- **Un solo marketplace global:** `/api/v1/products` como storefront canónico.
- **Una sola autoridad de capacidades para el planner:**
  `capability_registry.build_capability_snapshot()`.
- **Sin motor alterno, sin catálogo duplicado, sin tienda por módulo.**
- **LLM propone; backend descubre, valida, autoriza, compila, simula y ejecuta.**
- **Secretos solo en SecretStore.**
- **Aislamiento por organización/workspace y permisos efectivos del actor.**
- **Los flujos de bienestar no son psicoterapia ni diagnóstico automático.**

## 5. Estado de esta entrega

Esta fase entrega:

- auditoría con evidencia de código y de ejecución;
- matriz de brechas con estado explícito;
- arquitectura TARGET y ADR;
- plan 01–09 con dependencias y criterios GO/NO-GO;
- riesgos, rollout y rollback;
- evidencia de baseline separada por tipo de prueba.

**No entrega** código de producto, migraciones nuevas ni cambios de
comportamiento. Cualquier fase 01+ requiere su propio PR pequeño, flag y red de
pruebas.
