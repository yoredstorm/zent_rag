# Fase 06 — Embedded Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Índice: [`docs/platform/ZENT_PLATFORM_ROADMAP.md`](../../platform/ZENT_PLATFORM_ROADMAP.md)

**Goal:** El cliente publica un agente en su web (script o iframe) sin construir frontend. Feature comercial encima del Agent Builder (Fase 05).

**Architecture:** Endpoint público acotado (token de embed, no la API key `zent_sk_live` de producción con write). CORS por orígenes en `agents.config_json.embed.allowed_origins`. El widget llama `POST /api/v1/agents/{id}/run/stream` o un alias `/api/v1/embed/{token}/chat`. Entitlement `embed_widget` (Fase 03) debe ser true.

**Tech Stack:** JS snippet estático servido por `portal` nginx o `api` (`/embed.js`), iframe en `portal/embed.html`, FastAPI, pytest.

## Global Constraints

- No reescribir agent runtime.
- Identidad: el embed token se resuelve a org+agent en servidor; **nunca** aceptar `organization_id` del query string como autoridad.
- API `1.0.0` additive only.
- `core/` no importa `infrastructure` ni FastAPI.
- Copy del widget: configurable; default español.
- Tests: `pytest` + test de CORS. Lint: `ruff check src/ tests/ sdk/python`.
- No Stripe nuevo, no K8s, no Drive.

## Protocolo del agente (obligatorio)

1. Inspect existing architecture
2. Do not rewrite working functionality
3. Identify existing components
4. Design changes
5. Implement
6. Add migrations (si `embed_tokens` tabla)
7. Add tests
8. Update API
9. Update frontend (snippet UI en Agent Builder)
10. Update documentation
11. Run tests
12. Run lint
13. Check backwards compatibility
14. Report files changed
15. Report remaining risks

---

## Exists / Reuse

- `POST /api/v1/agents/{id}/run/stream`, scopes `agents:execute`.
- CORS global `CORS_ALLOWED_ORIGINS` ([`config.py`](../../../src/core/config.py)) — hoy puede ser `*` en dev y prohibido en prod.
- Entitlement key `embed_widget` (Fase 03).
- Rate limit middleware existente.

## Gaps

- No hay widget, iframe, ni public token.
- CORS no es por organización.

## Diseño

Tabla `agent_embed_tokens` (preferible a meter el secreto en `config_json`):

- `id`, `agent_id`, `organization_id`, `token_hash`, `token_prefix`, `allowed_origins TEXT[]`, `revoked_at`.

Prefix visible `zent_emb_`. Hash SHA-256 como API keys.

Rutas:

```
POST /api/v1/agents/{id}/embed/token     # org admin; 201 muestra token una vez
GET  /api/v1/agents/{id}/embed            # { script, iframe_src, allowed_origins }
POST /api/v1/embed/{public_id}/chat      # público; Origin allowlist; body { messages }
```

El `public_id` no es el UUID del agente (enumeración). Usar id opaco.

Snippet:

```html
<script src="https://{host}/embed.js" data-embed="{public_id}"></script>
```

Iframe: `https://{host}/embed/{public_id}` — UI similar al mock FarmaAI (título, input, mensajes). Branding desde `config_json.embed.title`.

---

### Task 1: Tokens + CORS por origin

- [ ] **Step 1: Tests** — origin no allowlisted → 403; token revoked → 401; token de org A no corre agente de org B; sin entitlement `embed_widget` → 403 al crear token.

- [ ] **Step 2: Implementar** verificación Origin/Referer. Rate limit más estricto en `/embed/`.

- [ ] **Step 3: No** loguear el token en claro.

---

### Task 2: Widget + Builder UI

- [ ] **Step 1:** `embed.js` + página iframe. XSS: no `innerHTML` de respuestas sin sanitizar (markdown del chat portal ya tiene helper — reusar patrón).

- [ ] **Step 2:** Tab “Embed” en Agent Builder: orígenes, copiar script, revocar token.

- [ ] **Step 3:** Documentar CSP: el cliente debe permitir frame/script de Zent.

---

### Task 3: Quality

```bash
ruff check src/ tests/ sdk/python
pytest tests/test_embed.py tests/test_agent_api.py tests/test_tenant_isolation.py tests/test_entitlements.py -q
```

Expected: PASS

## Criterios de aceptación

- Una farmacia pega el script y el widget responde con el agente correcto.
- Un origin atacante no usa el embed.
- Revocar token corta el widget.
- Customer Portal y API keys normales no se ven afectados.

## Riesgos residuales

- `CORS_ALLOWED_ORIGINS=*` vs CORS por embed: el embed debe usar middleware **específico**, no relajar el CORS global.
- Prompt injection desde la web pública: reusar defenses existentes; no es un bypass de tenant isolation.
- GDPR/cookies del widget: documentar “no cookie de tracking en v1” (solo session de conversación en memory/local del iframe).
