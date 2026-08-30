# AI Gateway (interno)

Router de plataforma encima de LiteLLM in-process. No hay contenedor proxy extra.

## Aliases

| Alias | Primary |
|---|---|
| `zent-cheap` | `RAG_GATEWAY_CHEAP_MODEL` o `RAG_LITELLM_DEFAULT_MODEL` |
| `zent-default` | `RAG_LITELLM_DEFAULT_MODEL` |
| `zent-quality` | `RAG_GATEWAY_QUALITY_MODEL` o default |

Cualquier otro string se trata como modelo real del provider.

## Política v1

1. `organization.llm_model_override` gana (alias `override`).
2. Si el agente/request usa `zent-*`, se resuelve.
3. Si el primary falla (excepción o circuit open) se intenta **una vez** `RAG_GATEWAY_FALLBACK_MODEL` si está definido.
4. `usage_events.model` es el **modelo real del intento que completó**. El fallo del primary se loguea; no se duplica el usage del request. Quota pre-flight usa el alias/override pedido.

No es magia quality-vs-cost: `zent-cheap` / `zent-quality` son labels de configuración.

## API

`GET /api/v1/gateway/routes` — catálogo de aliases (requiere tenant auth). No hay surface OpenAI `/v1/chat/completions` en esta fase.

## UI

Agent Builder → pestaña Model: dropdown de rutas. Campo custom solo con entitlement `custom_models`.
