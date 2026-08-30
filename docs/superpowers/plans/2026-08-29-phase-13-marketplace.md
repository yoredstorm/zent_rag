# Fase 13 — API Marketplace / Developer Keys Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Índice: [`docs/platform/ZENT_PLATFORM_ROADMAP.md`](../../platform/ZENT_PLATFORM_ROADMAP.md)

**Goal:** Experiencia de developer portal: keys `live` vs `test`, scopes claros, límites por key. Encima de API keys y scopes que **ya existen**.

**Architecture:** Distinguir entorno por prefijo (`zent_sk_live` vs `zent_sk_test`) ya parcialmente en entidades (`API_TOKEN_PREFIXES`). Enforcement: keys `test` no leen Qdrant de prod **o** apuntan a la misma org con rate más bajo — **elegir**: v1 = misma data, cuota y watermark `test` en respuestas, más rate limit estricto. No segundo cluster.

**Tech Stack:** `src/platform/auth/scopes.py`, `organizations` API keys UI [`portal/src/pages/Keys.tsx`](../../../portal/src/pages/Keys.tsx), pytest.

## Global Constraints

- No rehacer hashing ni el modelo `api_keys`.
- Identidad solo del Bearer.
- API `1.0.0` additive (campos `environment`, más scopes si hacen falta).
- Scopes nuevos deben mapear a permisos RBAC existentes o añadirse al catálogo SQL.
- Tests + ruff.
- No K8s, no Stripe.

## Protocolo del agente (obligatorio)

1. Inspect existing architecture
2. Do not rewrite working functionality
3. Identify existing components
4. Design changes
5. Implement
6. Add migrations (si `environment` column)
7. Add tests
8. Update API
9. Update frontend
10. Update documentation
11. Run tests
12. Run lint
13. Check backwards compatibility
14. Report files changed
15. Report remaining risks

---

## Exists / Reuse

- Prefijos `zent_sk_live`, legacy `rag_live_` / `rag_test_`.
- Scopes: `rag:read|write`, `agents:execute`, `connectors:read|write`, `usage:read`. Alias `rag:query`.
- UI keys con checkboxes de scopes.
- Rate limit middleware.
- SDKs Python/Node.

## Gaps

- No hay creación explícita test vs live en UI.
- No hay scopes `knowledge:read` (alias de rag/sources) ni `analytics:read` (alias usage) como en la visión — añadir **aliases** en `LEGACY_SCOPE_ALIASES` / `PUBLIC_API_KEY_SCOPES` sin romper clientes.
- Límites 100 req/min y 10k/day por key: hoy rate limit es más global; añadir counters Redis `rag:rl:key:{id}`.

---

### Task 1: Environment + limits por key

- [ ] **Step 1: Tests** crear key `test`; prefijo `zent_sk_test`; live sigue `zent_sk_live`.
- [ ] **Step 2: Tests** de rate limit por `token_id`.
- [ ] **Step 3: Aliases** `knowledge:read` → permisos sources/kbs read; `agents:read`; `analytics:read` → usage. Documentar en authentication.md.

---

### Task 2: Developer UI

- [ ] Keys page: secciones Production / Development.
- [ ] Mostrar scopes y límites. Rotación ya existe en billing token rotate — no duplicar si es el mismo recurso; unificar copy.

---

### Task 3: Docs + SDKs

- [`docs/developers/authentication.md`](../../developers/authentication.md), [`docs/developers/quickstart.md`](../../developers/quickstart.md).
- SDKs: ejemplo `zent_sk_test_` en README de sdk **sin** keys reales.

```bash
ruff check src/ tests/ sdk/python
pytest tests/test_api_key_scopes.py tests/test_scopes.py tests/test_auth.py tests/test_identity_hardening.py -q
```

Expected: PASS

## Criterios de aceptación

- Un tenant crea `sk_test` y `sk_live` (nombres de producto; prefijos Zent).
- Scope inválido sigue 400.
- Keys viejas `zent_sk_live` siguen funcionando.

## Riesgos residuales

- Test keys sobre datos reales: watermark y cuota, no isolation física.
- `rag:query` alias vs `rag:read` — no romper Bruno collections.
