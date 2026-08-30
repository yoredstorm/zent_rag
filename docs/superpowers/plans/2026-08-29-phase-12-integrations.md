# Fase 12 — Integrations (Connectors) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Índice: [`docs/platform/ZENT_PLATFORM_ROADMAP.md`](../../platform/ZENT_PLATFORM_ROADMAP.md)

**Goal:** Ampliar fuentes empresariales **como plugins**, sin fork del ingestion engine. Prioridad: Google Drive, luego SharePoint; el resto (Notion, Snowflake, BigQuery, Kafka) queda listado como follow-up en el mismo plan solo si el primero está verde.

**Architecture:** Registry [`src/knowledge/connectors/registry.py`](../../../src/knowledge/connectors/registry.py) + plugin platform [`src/connectors/plugin/`](../../../src/connectors/plugin/). Secrets en Vault/encrypted store, **nunca** `config_json`. Knowledge Center (Fase 01) debe listar el nuevo `type`.

**Tech Stack:** Connector base class, OAuth (Drive) con tokens en secret store, pytest con HTTP mock. No credenciales reales en CI.

## Global Constraints

- No reescribir SQL/CSV/PDF connectors.
- Identidad de tenant solo del Bearer; OAuth callback debe atar `organization_id` del state firmado.
- API `1.0.0` additive (`type` enum crece).
- Copy portal en español.
- Tests + ruff.
- No K8s. Un solo conector **completo** (Drive) es éxito; SharePoint es segundo milestone en el mismo plan solo si el tiempo lo permite — si no, Drive + stub de registro SharePoint **prohibido** (no stubs). Mejor un conector sólido.

## Protocolo del agente (obligatorio)

1. Inspect existing architecture
2. Do not rewrite working functionality
3. Identify existing components
4. Design changes
5. Implement
6. Add migrations (`kb_sources.type` check constraint / `008_connector_types` pattern)
7. Add tests
8. Update API (`CreateSourceRequest` pattern)
9. Update frontend (Knowledge sources type picker)
10. Update documentation
11. Run tests
12. Run lint
13. Check backwards compatibility
14. Report files changed
15. Report remaining risks

---

## Exists / Reuse

- Types actuales: `sql|file|csv|excel|web|s3|api`.
- [`docs/developers/connectors.md`](../../developers/connectors.md).
- Secret store: [`src/infrastructure/secrets/`](../../../src/infrastructure/secrets/).
- Guards SSRF en API connectors.

## Diseño Drive (v1)

- OAuth app; `POST /api/v1/connectors/oauth/drive/start` → URL; callback guarda refresh token en secret store keyed by `connector_id`.
- Sync: listar archivos de una folder ID en config; normalizar a markdown/pdf pipeline existente (`file` normalizers).
- Incremental: `source_sync_state` (ya existe).

---

### Task 1: Plugin + tests

- [ ] **Step 1: Tests** de connector con fixtures (lista de files, download mock). Isolation: org A token no sync org B.
- [ ] **Step 2: Registrar** type `gdrive` (nombre estable).
- [ ] **Step 3: Constraint SQL** de types actualizado (ver `008_connector_types.py`).

---

### Task 2: UI Knowledge

- [ ] Type en el alta de source; flujo OAuth popup o redirect.
- [ ] Status / last sync / errors igual que otras sources.

---

### Task 3: Docs

- connectors.md: scopes OAuth, límites, que no hay Notion aún.

```bash
ruff check src/ tests/ sdk/python
pytest tests/test_plugins.py tests/test_connector_*.py tests/test_knowledge_queue.py tests/test_tenant_isolation.py -q
```

Expected: PASS

## Criterios de aceptación

- Un tenant conecta Drive (en mock/CI) e indexa al menos un PDF/Doc al KB.
- Secrets no salen en GET source.
- Tipos viejos no se rompen.

## Fuera de alcance (salvo segundo PR explícito)

SharePoint, Notion, Snowflake, BigQuery, Kafka, ERP/CRM genérico.

## Riesgos residuales

- Google API quotas; backoff.
- Shared drives vs My Drive permissions.
- OAuth redirect URLs por ambiente (prod Fase 11).
