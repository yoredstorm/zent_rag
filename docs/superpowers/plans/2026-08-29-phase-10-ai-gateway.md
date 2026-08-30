# Fase 10 — Zent AI Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Índice: [`docs/platform/ZENT_PLATFORM_ROADMAP.md`](../../platform/ZENT_PLATFORM_ROADMAP.md)

**Goal:** Encima de LiteLLM in-process, un router de plataforma: el cliente llama un modelo virtual; Zent elige cheap / complex / failover / enterprise. Sin desplegar un contenedor LiteLLM proxy “para verse enterprise”.

**Architecture:** Nueva unidad `src/infrastructure/llm/router.py` (o `src/platform/gateway/`) que implementa política y llama al `LiteLLMProvider` existente ([`provider.py`](../../../src/infrastructure/llm/provider.py)). Circuit breaker ya existe. Overrides por org `llm_model_override` ya mencionados en auditoría — reutilizar.

**Tech Stack:** LiteLLM SDK actual, settings, pytest con provider fake.

## Global Constraints

- No añadir servicio Compose LiteLLM en esta fase.
- Identidad de tenant solo del Bearer.
- API `1.0.0`: opcional `POST /v1/chat/completions` **compatible** (additive) que autentica igual que `/rag/query` — si se hace, debe pasar por tenant middleware y usage. Si es demasiado, documentar que el gateway es interno al orchestrator y no OpenAI-surface aún (Marketplace Fase 13 puede ser el surface).
- **Recomendación:** router interno primero; OpenAI-compatible solo si cabe en el mismo PR sin romper quotas.
- Copy español en UI de “modelo” del Agent Builder (selector de rutas).
- Tests + ruff.
- No K8s.

## Protocolo del agente (obligatorio)

1. Inspect existing architecture
2. Do not rewrite working functionality
3. Identify existing components
4. Design changes
5. Implement
6. Add migrations (tabla `model_routes` opcional; settings YAML también válido)
7. Add tests
8. Update API
9. Update frontend (Agent Builder model dropdown = rutas)
10. Update documentation
11. Run tests
12. Run lint
13. Check backwards compatibility
14. Report files changed
15. Report remaining risks

---

## Exists / Reuse

- `LiteLLMProvider` `acompletion` / `aembedding`.
- Circuit breaker [`src/infrastructure/resilience/circuit_breaker.py`](../../../src/infrastructure/resilience/circuit_breaker.py).
- Usage events con `model`, `provider`, `estimated_cost`.
- Agent `model` string.

## Diseño de rutas

```python
# settings or table
# name: "zent-cheap" | "zent-default" | "zent-quality"
# primary: "deepseek/..."
# fallback: "openai/..."
# max_input_tokens_cheap: int  # heuristic
```

Política v1 (simple, testeable):

1. Si org tiene `llm_model_override` → usarlo.
2. Si agent.model es un id de ruta (`zent-default`) → resolver.
3. Si el primary falla (exception o circuit open) → fallback una vez.
4. Registrar modelo **real** en usage_events, no el alias.

---

### Task 1: Router + tests

- [ ] **Step 1: Fake LLMProvider** que falla una vez y luego ok — el router usa fallback.
- [ ] **Step 2: Cheap vs complex** — query length o flag `complexity` del classify existente (`src/rag/retrieval/classify.py`) si es barato de cablear; si no, solo primary/fallback.
- [ ] **Step 3: Cablear** orchestrator RAG + agent run al router. Default = comportamiento actual (un modelo settings).

---

### Task 2: UI + docs

- [ ] Agent Builder: dropdown de rutas + “custom model” si entitlement `custom_models`.
- [ ] `docs/developers/chat.md` / agents — aliases vs provider models.
- [ ] Control Center (opcional): ver qué modelo se usó en usage (ya hay campo).

```bash
ruff check src/ tests/ sdk/python
pytest tests/test_llm_router.py tests/test_rag_query.py tests/test_agent_api.py -q
```

Expected: PASS

## Criterios de aceptación

- Caída del modelo primary no 500-a-todos si hay fallback configurado.
- Usage muestra el modelo real.
- Sin proxy extra en Docker.

## Riesgos residuales

- Routing “quality vs cost” es heurístico; no venderlo como magia.
- Doble factura si primary y fallback ambos se invocan: test de que usage cuenta ambos o solo el éxito — **elegir y documentar** (recomendado: ambos events, `status=error` + `completed`).
