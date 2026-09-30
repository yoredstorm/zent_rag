# =============================================================================
# Model Capability Registry — la capacidad REAL del modelo, no supuestos
# =============================================================================
# Nunca asumir 32K. Nunca asumir 1M. El presupuesto consulta este registry:
#   1. override de configuración (RAG_MODEL_CONTEXT_WINDOWS) gana;
#   2. mapa builtin de familias conocidas (orientativo, conservador);
#   3. default configurado del deployment (RAG_MODEL_DEFAULT_CONTEXT_WINDOW).
# Los valores builtin son techos documentados por proveedor a 2026-09 y se
# pueden pisar sin tocar código.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class ModelCapability:
    model_name: str
    context_window: int
    max_output_tokens: int | None = None
    supports_long_context: bool = False
    supports_reasoning: bool = False
    cost_input: float | None = None
    cost_output: float | None = None
    provider: str = ""
    source: str = "default"

    @property
    def long_context_threshold(self) -> int:
        """Umbral a partir del cual la ventana cuenta como long context."""
        return 128_000

    def to_public_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self.model_name,
            "context_window": self.context_window,
            "supports_long_context": self.supports_long_context,
            "source": self.source,
        }
        if self.max_output_tokens is not None:
            payload["max_output_tokens"] = self.max_output_tokens
        if self.supports_reasoning:
            payload["supports_reasoning"] = True
        if self.provider:
            payload["provider"] = self.provider
        return payload


#: Familias conocidas. Claves en minúscula; el match es exacto y luego por
#: prefijo (la entrada más larga gana). Valores conservadores y configurables.
def _cap(
    name: str,
    window: int,
    *,
    max_out: int | None = None,
    provider: str = "",
    reasoning: bool = False,
    cost_in: float | None = None,
    cost_out: float | None = None,
) -> ModelCapability:
    return ModelCapability(
        model_name=name,
        context_window=window,
        max_output_tokens=max_out,
        supports_long_context=window >= 128_000,
        supports_reasoning=reasoning,
        cost_input=cost_in,
        cost_output=cost_out,
        provider=provider,
    )


_BUILTIN: dict[str, ModelCapability] = {
    # OpenAI
    "gpt-4o": _cap("gpt-4o", 128_000, max_out=16_384, provider="openai", cost_in=2.5, cost_out=10.0),
    "gpt-4o-mini": _cap("gpt-4o-mini", 128_000, max_out=16_384, provider="openai", cost_in=0.15, cost_out=0.6),
    "gpt-4-turbo": _cap("gpt-4-turbo", 128_000, max_out=4_096, provider="openai", cost_in=10.0, cost_out=30.0),
    "gpt-4.1": _cap("gpt-4.1", 1_047_576, max_out=32_768, provider="openai", cost_in=2.0, cost_out=8.0),
    "gpt-4.1-mini": _cap("gpt-4.1-mini", 1_047_576, max_out=32_768, provider="openai", cost_in=0.4, cost_out=1.6),
    "gpt-4.1-nano": _cap("gpt-4.1-nano", 1_047_576, max_out=32_768, provider="openai", cost_in=0.1, cost_out=0.4),
    "o1": _cap("o1", 200_000, max_out=100_000, provider="openai", reasoning=True),
    "o3": _cap("o3", 200_000, max_out=100_000, provider="openai", reasoning=True),
    "o4-mini": _cap("o4-mini", 200_000, max_out=100_000, provider="openai", reasoning=True),
    # Anthropic
    "claude-3-5-sonnet": _cap(
        "claude-3-5-sonnet", 200_000, max_out=8_192,
        provider="anthropic", cost_in=3.0, cost_out=15.0,
    ),
    "claude-3-5-haiku": _cap(
        "claude-3-5-haiku", 200_000, max_out=8_192,
        provider="anthropic", cost_in=0.8, cost_out=4.0,
    ),
    "claude-3-7-sonnet": _cap(
        "claude-3-7-sonnet", 200_000, max_out=64_000,
        provider="anthropic", reasoning=True, cost_in=3.0, cost_out=15.0,
    ),
    "claude-sonnet-4": _cap(
        "claude-sonnet-4", 200_000, max_out=64_000,
        provider="anthropic", reasoning=True, cost_in=3.0, cost_out=15.0,
    ),
    "claude-opus-4": _cap(
        "claude-opus-4", 200_000, max_out=32_000,
        provider="anthropic", reasoning=True, cost_in=15.0, cost_out=75.0,
    ),
    # Google
    "gemini-1.5-pro": _cap("gemini-1.5-pro", 2_097_152, max_out=8_192, provider="google"),
    "gemini-1.5-flash": _cap("gemini-1.5-flash", 1_048_576, max_out=8_192, provider="google"),
    "gemini-2.0-flash": _cap("gemini-2.0-flash", 1_048_576, max_out=8_192, provider="google"),
    "gemini-2.5-pro": _cap("gemini-2.5-pro", 1_048_576, max_out=65_536, provider="google", reasoning=True),
    "gemini-2.5-flash": _cap("gemini-2.5-flash", 1_048_576, max_out=65_536, provider="google", reasoning=True),
    # DeepSeek
    "deepseek-chat": _cap("deepseek-chat", 128_000, max_out=8_192, provider="deepseek", cost_in=0.27, cost_out=1.1),
    "deepseek-reasoner": _cap(
        "deepseek-reasoner", 128_000, max_out=64_000,
        provider="deepseek", reasoning=True, cost_in=0.55, cost_out=2.19,
    ),
    # Meta / Mistral / Qwen / Cohere
    "llama-3": _cap("llama-3", 128_000, max_out=8_192, provider="meta"),
    "llama-4": _cap("llama-4", 1_048_576, max_out=16_384, provider="meta"),
    "mistral-large": _cap("mistral-large", 128_000, max_out=8_192, provider="mistral"),
    "qwen": _cap("qwen", 131_072, max_out=8_192, provider="alibaba"),
    "command-r": _cap("command-r", 128_000, max_out=4_096, provider="cohere"),
}


def _normalize(model: str) -> str:
    value = (model or "").strip().lower()
    if "/" in value:  # litellm usa prefijo de proveedor: "openai/gpt-4o-mini"
        value = value.split("/", 1)[1]
    return value


def _match_builtin(model: str) -> ModelCapability | None:
    normalized = _normalize(model)
    if not normalized:
        return None
    exact = _BUILTIN.get(normalized)
    if exact is not None:
        return exact
    best: tuple[int, ModelCapability] | None = None
    for key, capability in _BUILTIN.items():
        if normalized.startswith(key):
            score = len(key)
            if best is None or score > best[0]:
                best = (score, capability)
    return best[1] if best else None


def resolve_model_capability(
    model: str,
    *,
    overrides: dict[str, int] | None = None,
    provider: str = "",
    default_window: int = 32000,
) -> ModelCapability:
    """Capacidad del modelo: config gana, luego builtin, luego default."""
    normalized = _normalize(model) or "unknown"
    for key, window in (overrides or {}).items():
        if _normalize(key) == normalized and int(window) > 0:
            return ModelCapability(
                model_name=model or normalized,
                context_window=int(window),
                supports_long_context=int(window) >= 128_000,
                provider=provider,
                source="config",
            )
    builtin = _match_builtin(model)
    if builtin is not None:
        return ModelCapability(
            model_name=model or builtin.model_name,
            context_window=builtin.context_window,
            max_output_tokens=builtin.max_output_tokens,
            supports_long_context=builtin.supports_long_context,
            supports_reasoning=builtin.supports_reasoning,
            cost_input=builtin.cost_input,
            cost_output=builtin.cost_output,
            provider=provider or builtin.provider,
            source="builtin",
        )
    window = max(int(default_window or 0), 1000)
    return ModelCapability(
        model_name=model or normalized,
        context_window=window,
        supports_long_context=window >= 128_000,
        provider=provider,
        source="default",
    )


__all__ = ["ModelCapability", "resolve_model_capability"]
