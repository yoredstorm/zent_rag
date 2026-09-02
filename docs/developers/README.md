# Developer docs

- [Quickstart](quickstart.md) — `client.chat()` en < 5 minutos
- [Authentication](authentication.md)
- [Chat](chat.md)
- [RAG](rag.md)
- [Agents](agents.md)
- [Embedded chat](embed.md)
- [Tools](tools.md)
- [Connectors](connectors.md)
- [Webhooks](webhooks.md)
- [Usage](usage.md)
- [MCP Server](mcp.md) — Model Context Protocol (`/mcp`)

## Producto SaaS (roadmap)

Índice canónico: [Zent Platform Roadmap](../platform/ZENT_PLATFORM_ROADMAP.md). Freeze de producto: [PRODUCT.md](../platform/PRODUCT.md) · [IA](../platform/INFORMATION_ARCHITECTURE.md) · [Presentación](../platform/PRESENTATION.md).

Ejecutar **una fase por PR/chat**, en este orden. Cada archivo es el prompt de implementación (inspect → no rewrite → tests → lint).

| Fase | Plan |
|---|---|
| 00 Producto | [2026-08-29-phase-00-product.md](../superpowers/plans/2026-08-29-phase-00-product.md) |
| 01 Customer Portal 2.0 | [2026-08-29-phase-01-customer-portal.md](../superpowers/plans/2026-08-29-phase-01-customer-portal.md) |
| 02 Super Admin | [2026-08-29-phase-02-super-admin.md](../superpowers/plans/2026-08-29-phase-02-super-admin.md) |
| 03 Entitlements | [2026-08-29-phase-03-entitlements.md](../superpowers/plans/2026-08-29-phase-03-entitlements.md) |
| 04 Billing (Stripe) | [2026-08-29-phase-04-billing.md](../superpowers/plans/2026-08-29-phase-04-billing.md) |
| 05 Agent Builder | [2026-08-29-phase-05-agent-builder.md](../superpowers/plans/2026-08-29-phase-05-agent-builder.md) |
| 06 Embedded Chat | [2026-08-29-phase-06-embedded-chat.md](../superpowers/plans/2026-08-29-phase-06-embedded-chat.md) |
| 07 Security | [2026-08-29-phase-07-security.md](../superpowers/plans/2026-08-29-phase-07-security.md) |
| 08 FinOps | [2026-08-29-phase-08-finops.md](../superpowers/plans/2026-08-29-phase-08-finops.md) |
| 09 RAG Evaluation UI | [2026-08-29-phase-09-rag-evaluation.md](../superpowers/plans/2026-08-29-phase-09-rag-evaluation.md) |
| 10 AI Gateway | [2026-08-29-phase-10-ai-gateway.md](../superpowers/plans/2026-08-29-phase-10-ai-gateway.md) |
| 11 Production infra | [2026-08-29-phase-11-production-infra.md](../superpowers/plans/2026-08-29-phase-11-production-infra.md) |
| 12 Integrations | [2026-08-29-phase-12-integrations.md](../superpowers/plans/2026-08-29-phase-12-integrations.md) |
| 13 API Marketplace | [2026-08-29-phase-13-marketplace.md](../superpowers/plans/2026-08-29-phase-13-marketplace.md) |
| 14 Kubernetes (opcional) | [2026-08-29-phase-14-kubernetes.md](../superpowers/plans/2026-08-29-phase-14-kubernetes.md) |

FinOps: [FINOPS.md](../platform/FINOPS.md) · Eval: [EVALUATION.md](../platform/EVALUATION.md) · Gateway: [GATEWAY.md](../platform/GATEWAY.md) · Prod: [PRODUCTION.md](../platform/PRODUCTION.md) · [BACKUPS.md](../platform/BACKUPS.md) · [DR](../platform/DISASTER_RECOVERY.md) · K8s (opcional, **no es requisito de venta**): [KUBERNETES.md](../platform/KUBERNETES.md).

Roadmap de implementación: fases 00–14. Kubernetes no es requisito de venta.

Rutas del Customer Portal (Fase 01): `/`, `/chat`, `/knowledge/*` (sources, collections, documents, sql, jobs, playground), `/projects`, `/agents`, `/connectors`, `/prompts`, `/users`, `/keys`, `/usage`, `/billing`, `/audit`, `/settings`. Redirects: `/ingestion` → `/knowledge/sql`, `/knowledge-bases` → `/knowledge/collections`.

Control Center (Fase 02–03): `/admin/login`, `/admin`, `/admin/customers`, `/admin/customers/:orgId`, `/admin/plans`.

OpenAPI: `/docs`, `/redoc`, `/openapi.json` y `/api/v1/openapi.json`. Contrato: `GET /api/v1` → `{ "version": "1.0.0" }`.

## Evaluation Engine (PROMPT 04)

- **eval_examples first-class**: `POST/GET/DELETE /api/v1/eval/datasets/{id}/examples`
  (manual o bulk). `materialize_cases()` regenera `eval_datasets.cases` (JSONB v2)
  para que el runner existente no cambie; self-healing migra cases legacy.
- **CSV import**: `POST /eval/datasets/{id}/import-csv` (columnas question,
  expected_answer, expected_behavior, expected_sources separadas por `|`/`;`, must_cite).
- **Synthetic**: `POST /eval/datasets/{id}/synthetic` genera ejemplos con LLM
  (topics + grounding opcional por KB).
- **Failures**: `GET /eval/runs/{id}/failures?min_score=&max_hallucination=` lista
  casos bajo thresholds.
- **Clasificación de compare**: `compare_runs` devuelve
  `classification: regression | improvement | no_material_change` junto a overall.
- **Promotion gate** (opcional): `EVAL_PROMOTION_MIN_SCORE` (0=off) y
  `EVAL_PROMOTION_MAX_HALLUCINATION` (1.0=off). Promover a production sin run
  evaluado (o bajo umbral) → 409.
