# =============================================================================
# Long-Context settings — inyectables (tests sin env), leídas de config RAG_*.
# =============================================================================
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from uuid import UUID

from src.decision.routing import in_canary

MODES = ("off", "shadow", "active", "canary")
PROFILES = ("economy", "balanced", "quality", "maximum_quality")


@dataclass(frozen=True, kw_only=True)
class ProfilePolicy:
    """Cuánto puede expandir cada perfil. Nunca cambia cuándo la evidencia basta."""

    max_expansions: int
    gain_min: float
    requirement_min: float
    start_tier: int


@dataclass(frozen=True, kw_only=True)
class LongContextSettings:
    mode: str = "off"
    #: Interruptor por tenant (`adaptive_context.enabled`). False apaga el loop
    #: sin importar el modo global.
    enabled_flag: bool = True
    canary_percentage: int = 0
    profile: str = "balanced"
    default_context_window: int = 32000
    model_windows: dict[str, int] = field(default_factory=dict)
    output_reserve: int = 2048
    system_reserve: int = 3000
    tool_reserve: int = 1500
    safety_margin: int = 2048
    tiers: tuple[int, ...] = (4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288)
    start_tier: int = 0
    max_tier: int = 7
    max_expansions: int = 6
    #: Base mínima de fragmentos para cerrar el loop en la primera pasada:
    #: coverage suficiente con pocos fragmentos no garantiza que el gate
    #: clásico (scores) vea evidencia. 0 = sin mínimo.
    min_initial_chunks: int = 5
    gain_min: float = 0.04
    requirement_min: float = 0.6
    #: Confianza mínima del evidence evaluator para cerrar el loop.
    confidence_min: float = 0.7
    #: Redundancia consecutiva antes de cortar (gain < gain_min N veces).
    redundant_streak: int = 2
    #: Integridad de unidades semánticas (tabla/nota/sección/procedimiento).
    preserve_semantic_units: bool = True
    #: Cuánto puede superar un tier una unidad completa antes de partirla
    #: (fracción del tier; el tope duro sigue siendo usable_context).
    unit_headroom_ratio: float = 0.5
    expansion_chunks: int = 6
    expansion_max_points: int = 6000
    expansion_max_ms: float = 2000.0
    request_token_limit: int = 0
    tenant_token_limit: int = 0
    #: Per-tenant: \"model\" = sin tope propio; >0 topa el contexto.
    max_context_tokens: int = 0
    #: Per-tenant: 0 = auto (tier inicial por complejidad).
    initial_budget_tokens: int = 0

    @property
    def effective_mode(self) -> str:
        mode = (self.mode or "off").strip().lower()
        return mode if mode in MODES else "off"

    @property
    def effective_profile(self) -> str:
        profile = (self.profile or "balanced").strip().lower()
        return profile if profile in PROFILES else "balanced"

    def enabled(self) -> bool:
        return self.enabled_flag and self.effective_mode != "off"

    def active(self) -> bool:
        return self.effective_mode in ("active",)

    def should_apply(self, request_id: UUID) -> bool:
        mode = self.effective_mode
        if mode in ("active", "shadow"):
            return True
        if mode == "canary":
            return in_canary(request_id, self.canary_percentage)
        return False

    def policy(self) -> ProfilePolicy:
        profile = self.effective_profile
        if profile == "economy":
            return ProfilePolicy(
                max_expansions=max(1, self.max_expansions - 3),
                gain_min=max(self.gain_min, 0.08),
                requirement_min=max(self.requirement_min, 0.7),
                start_tier=self.start_tier,
            )
        if profile == "quality":
            return ProfilePolicy(
                max_expansions=self.max_expansions + 2,
                gain_min=self.gain_min * 0.5,
                requirement_min=self.requirement_min,
                start_tier=self.start_tier,
            )
        if profile == "maximum_quality":
            return ProfilePolicy(
                max_expansions=self.max_expansions + 4,
                gain_min=0.0,
                requirement_min=self.requirement_min,
                start_tier=self.start_tier,
            )
        return ProfilePolicy(
            max_expansions=self.max_expansions,
            gain_min=self.gain_min,
            requirement_min=self.requirement_min,
            start_tier=self.start_tier,
        )

    def with_profile(self, profile: str) -> LongContextSettings:
        return replace(self, profile=(profile or "").strip().lower() or self.profile)

    def tier_index_for_tokens(self, tokens: int) -> int:
        """Índice del tier más chico que cubre `tokens` (el último si no alcanza)."""
        target = max(0, int(tokens or 0))
        for index, value in enumerate(self.tiers):
            if value >= target:
                return index
        return len(self.tiers) - 1


#: Punto de partida por complejidad (PLAN decide; son INICIOS, no límites).
_COMPLEXITY_TARGET_TOKENS: dict[str, int] = {
    "fast": 4096,
    "trivial": 4096,
    "simple": 8192,
    "standard": 8192,
    "simple_fact": 8192,
    "lookup": 16384,
    "technical_lookup": 16384,
    "technical": 32768,
    "technical_reasoning": 32768,
    "reasoning": 32768,
    "complex": 32768,
    "multi_document": 32768,
    "multi": 32768,
    "deep_analysis": 65536,
    "deep": 65536,
}

#: Multi-documento exige al menos este inicio.
_MULTI_DOCUMENT_MIN_TOKENS = 32768


def start_tier_for_complexity(
    settings: LongContextSettings,
    *,
    path: str = "",
    complexity: str = "",
    intent: str = "",
    multi_document: bool = False,
) -> int:
    """Tier inicial sugerido por el planner. Nunca es un límite final."""
    if settings.initial_budget_tokens > 0:
        return settings.tier_index_for_tokens(settings.initial_budget_tokens)
    target = 0
    for key in (path, complexity, intent):
        value = str(key or "").strip().lower().replace(" ", "_")
        if not value:
            continue
        for name, tokens in _COMPLEXITY_TARGET_TOKENS.items():
            if name in value:
                target = max(target, tokens)
    if multi_document:
        target = max(target, _MULTI_DOCUMENT_MIN_TOKENS)
    if target <= 0:
        return settings.start_tier
    return settings.tier_index_for_tokens(target)


def _coerce_positive_int(value: object, default: int = 0) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def settings_from_org(
    config_json: dict | None,
    base: LongContextSettings | None = None,
) -> LongContextSettings:
    """Integra `organization.config_json["adaptive_context"]` con settings globales.

    Claves soportadas: enabled, quality_profile, initial_budget ("auto"|tokens),
    soft_budget_levels (lista), max_context ("model"|tokens),
    reserve_output_tokens ("auto"|tokens), min_information_gain,
    max_expansion_rounds, preserve_semantic_units.
    """
    resolved = base or settings_from_app()
    if not isinstance(config_json, dict):
        return resolved
    block = config_json.get("adaptive_context")
    if not isinstance(block, dict) or not block:
        return resolved
    changes: dict[str, object] = {}

    if "enabled" in block:
        changes["enabled_flag"] = bool(block.get("enabled"))
    if block.get("quality_profile"):
        changes["profile"] = str(block.get("quality_profile"))
    initial = block.get("initial_budget")
    if isinstance(initial, (int, float)) and int(initial) > 0:
        changes["initial_budget_tokens"] = int(initial)
    elif str(initial or "").strip().lower() == "auto":
        changes["initial_budget_tokens"] = 0
    levels = block.get("soft_budget_levels")
    if isinstance(levels, list) and levels:
        parsed: list[int] = []
        for value in levels:
            number = _coerce_positive_int(value)
            if number and number not in parsed:
                parsed.append(number)
        if parsed:
            changes["tiers"] = tuple(sorted(parsed))
    max_context = block.get("max_context")
    if isinstance(max_context, (int, float)) and int(max_context) > 0:
        changes["max_context_tokens"] = int(max_context)
    elif str(max_context or "").strip().lower() == "model":
        changes["max_context_tokens"] = 0
    reserve = block.get("reserve_output_tokens")
    if isinstance(reserve, (int, float)) and int(reserve) >= 0:
        changes["output_reserve"] = int(reserve)
    elif str(reserve or "").strip().lower() == "auto":
        pass
    gain = block.get("min_information_gain")
    if isinstance(gain, (int, float)) and 0.0 <= float(gain) <= 1.0:
        changes["gain_min"] = float(gain)
    rounds = block.get("max_expansion_rounds")
    if isinstance(rounds, (int, float)) and int(rounds) >= 0:
        changes["max_expansions"] = int(rounds)
    if "preserve_semantic_units" in block:
        changes["preserve_semantic_units"] = bool(block.get("preserve_semantic_units"))
    if "confidence_min" in block:
        confidence = block.get("confidence_min")
        if isinstance(confidence, (int, float)) and 0.0 <= float(confidence) <= 1.0:
            changes["confidence_min"] = float(confidence)
    if "redundant_streak" in block:
        streak = _coerce_positive_int(block.get("redundant_streak"))
        if streak:
            changes["redundant_streak"] = streak
    if not changes:
        return resolved
    try:
        return replace(resolved, **changes)
    except TypeError:
        return resolved


def _parse_tiers(raw: str) -> tuple[int, ...]:
    tiers: list[int] = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except ValueError:
            continue
        if value > 0 and value not in tiers:
            tiers.append(value)
    return tuple(sorted(tiers)) or LongContextSettings().tiers


def _parse_windows(raw: str) -> dict[str, int]:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    windows: dict[str, int] = {}
    for key, value in payload.items():
        try:
            window = int(value)
        except (TypeError, ValueError):
            continue
        if window > 0:
            windows[str(key).strip().lower()] = window
    return windows


def settings_from_app() -> LongContextSettings:
    from src.core.config import get_settings

    s = get_settings()
    return LongContextSettings(
        mode=str(getattr(s, "RAG_LONG_CONTEXT_MODE", "off") or "off"),
        canary_percentage=int(getattr(s, "RAG_LONG_CONTEXT_CANARY_PERCENTAGE", 0) or 0),
        profile=str(getattr(s, "RAG_CONTEXT_PROFILE", "balanced") or "balanced"),
        default_context_window=int(
            getattr(s, "RAG_MODEL_DEFAULT_CONTEXT_WINDOW", 32000) or 32000
        ),
        model_windows=_parse_windows(
            str(getattr(s, "RAG_MODEL_CONTEXT_WINDOWS", "") or "")
        ),
        output_reserve=int(getattr(s, "RAG_CONTEXT_OUTPUT_RESERVE", 2048) or 0),
        system_reserve=int(getattr(s, "RAG_CONTEXT_SYSTEM_RESERVE", 3000) or 0),
        tool_reserve=int(getattr(s, "RAG_CONTEXT_TOOL_RESERVE", 1500) or 0),
        safety_margin=int(getattr(s, "RAG_CONTEXT_SAFETY_MARGIN", 2048) or 0),
        tiers=_parse_tiers(str(getattr(s, "RAG_LONG_CONTEXT_TIERS", "") or "")),
        start_tier=int(getattr(s, "RAG_LONG_CONTEXT_START_TIER", 0) or 0),
        max_tier=int(getattr(s, "RAG_LONG_CONTEXT_MAX_TIER", 7) or 0),
        max_expansions=int(getattr(s, "RAG_LONG_CONTEXT_MAX_EXPANSIONS", 6) or 0),
        min_initial_chunks=int(
            getattr(s, "RAG_LONG_CONTEXT_MIN_INITIAL_CHUNKS", 5) or 0
        ),
        gain_min=float(getattr(s, "RAG_LONG_CONTEXT_GAIN_MIN", 0.04) or 0.0),
        requirement_min=float(
            getattr(s, "RAG_LONG_CONTEXT_REQUIREMENT_MIN", 0.6) or 0.0
        ),
        expansion_chunks=int(
            getattr(s, "RAG_LONG_CONTEXT_EXPANSION_CHUNKS", 6) or 6
        ),
        expansion_max_points=int(
            getattr(s, "RAG_LONG_CONTEXT_EXPANSION_MAX_POINTS", 6000) or 6000
        ),
        expansion_max_ms=float(
            getattr(s, "RAG_LONG_CONTEXT_EXPANSION_MAX_MS", 2000.0) or 2000.0
        ),
        confidence_min=float(
            getattr(s, "RAG_LONG_CONTEXT_CONFIDENCE_MIN", 0.7) or 0.0
        ),
        redundant_streak=int(
            getattr(s, "RAG_LONG_CONTEXT_REDUNDANT_STREAK", 2) or 2
        ),
        preserve_semantic_units=str(
            getattr(s, "RAG_LONG_CONTEXT_PRESERVE_UNITS", "on")
        ).lower()
        not in ("off", "0", "false"),
        unit_headroom_ratio=max(
            0.0,
            min(
                2.0,
                float(getattr(s, "RAG_LONG_CONTEXT_UNIT_HEADROOM", 0.5) or 0.0),
            ),
        ),
    )


__all__ = [
    "LongContextSettings",
    "MODES",
    "PROFILES",
    "ProfilePolicy",
    "settings_from_app",
    "settings_from_org",
    "start_tier_for_complexity",
]
