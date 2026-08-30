# Fase 07 — Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Índice: [`docs/platform/ZENT_PLATFORM_ROADMAP.md`](../../platform/ZENT_PLATFORM_ROADMAP.md)

**Goal:** Cerrar huecos de seguridad pre-venta enterprise **sin** rehacer RBAC/audit/tenant isolation que ya existen. Platform admin + impersonate ya son Fase 02; esta fase es hardening perimetral, lifecycle de usuarios, scanning y tests extra.

**Architecture:** Extender middleware, CI, y auth flows. No introducir un segundo modelo de identidad. SSO/OIDC queda **fuera** salvo que el PR documente un IdP mínimo; el default de este plan es **no SSO**.

**Tech Stack:** FastAPI, headers, gitleaks (ya en CI), ruff, pytest, opcional Trivy en CI.

## Global Constraints

- No debilitar `is_platform_admin` ni isolation tests.
- Identidad de tenant solo del Bearer.
- API `1.0.0` additive only.
- `core/` no importa `infrastructure` ni FastAPI.
- Copy del portal en español.
- Tests: `pytest`. Lint: `ruff check src/ tests/ sdk/python`.
- No Stripe nuevo, no K8s, no widget nuevo.

## Protocolo del agente (obligatorio)

1. Inspect existing architecture
2. Do not rewrite working functionality
3. Identify existing components
4. Design changes
5. Implement
6. Add migrations (password reset tokens si aplica)
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

- Tenant isolation tests, API key hashing, bcrypt, login rate limit, idempotency, body size limit, SQL Expert AST, prompt injection defenses (verificar en `src/agents` / query), gitleaks workflow.
- Audit org: `GET /api/v1/audit-logs`.
- Security tests: `tests/test_security_hardening.py`, `tests/test_sql_security.py`.
- Headers: revisar `src/api/main.py` (security headers existentes).
- Invites: Fase 01.

## Gaps (hacer)

- Password reset / forgot password (no hay mailer: token de un solo uso en 201 o log seguro de dev; en prod documentar SMTP futuro).
- CORS whitelist **por organización** (README corto plazo) — `organizations.config_json.cors_origins` aplicado a portal y embed.
- CSRF en mutaciones cookie-less: las sesiones son Bearer; documentar por qué CSRF es N/A **o** añadir header custom `X-Zent-CSRF` si se introduce cookie. No añadir cookies de sesión sin diseño.
- Secret rotation runbook (`PORTAL_SESSION_KEY`, API keys rotate ya existe).
- Container scanning en CI (Trivy) + dependency audit (`pip-audit` o similar) sin romper CI en vulns de transitives de baja: start `continue-on-error` o severity HIGH+.
- Más casos en `test_tenant_isolation.py` para recursos de Fases 01–06 (invites, embed, platform impersonate).

## Gaps (no hacer aquí)

- SSO/SAML/OIDC.
- Encryption at rest de PG (managed en Fase 11).
- MFA.

---

### Task 1: Auth lifecycle

- [ ] **Step 1: Tests** forgot-password: token un uso, expirado 400, no revela si el email existe (mismo 200).
- [ ] **Step 2: Implementar** `POST /api/v1/auth/forgot-password`, `POST /api/v1/auth/reset-password`.
- [ ] **Step 3: UI** Settings / login link “Olvidé mi contraseña”.

---

### Task 2: CORS por org + headers

- [ ] **Step 1: Inspeccionar** CORS actual en `main.py`.
- [ ] **Step 2: Tests** origin no listado en org config → fail en rutas portal; no relajar `*` en `ENVIRONMENT=production` (ya hay check).
- [ ] **Step 3: Security headers** (CSP portal nginx, `X-Content-Type-Options`, `Referrer-Policy`) — no romper `/docs` OpenAPI.

---

### Task 3: CI scanning + isolation tests extra

- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_tenant_isolation.py` (casos nuevos)
- Create: `docs/platform/SECURITY_RUNBOOK.md` — rotación de `PORTAL_SESSION_KEY`, `admin:*` keys, Stripe secrets (si 04).

```bash
ruff check src/ tests/ sdk/python
pytest tests/test_security_hardening.py tests/test_tenant_isolation.py tests/test_identity_hardening.py tests/test_sql_security.py tests/test_auth.py -q
```

Expected: PASS

## Criterios de aceptación

- Isolation tests cubren invites/embed/platform si esas fases ya están mergeadas (skip condicional **prohibido**; si la fase no está, el test no se escribe — el agente añade solo lo que existe en el tree).
- Forgot-password no enumera usuarios.
- CI tiene scan de secretos (ya) + un scan de deps o imágenes.
- Runbook de rotación existe.

## Riesgos residuales

- Sin SMTP, reset es “copiar token” — no es enterprise-ready; documentarlo.
- Trivy puede ser ruidoso: fijar baseline.
- Prompt injection: no hay garantía 100%; eval (Fase 09) mide, no reemplaza guards.
