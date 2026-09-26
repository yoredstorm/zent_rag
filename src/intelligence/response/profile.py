# =============================================================================
# Response profile — cómo debe responder un agente (§27-§29, §35, §36).
# =============================================================================
# El perfil es estructura, no un system prompt gigante: separa PURPOSE ("qué
# debe lograr") de RESPONSE PROFILE ("cómo debe explicarlo").
#
# Precedencia del contrato final:
#   blueprint (forma)  >  perfil del agente  >  default del sistema
# y una petición explícita del turno ("respóndeme corto") puede ajustar el
# nivel de detalle SIN cambiar el perfil guardado.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Mapping

from src.core.domain.response import (
    AUDIENCE_BUSINESS,
    AUDIENCE_EXPERT,
    AUDIENCE_TECHNICAL,
    DETAIL_BRIEF,
    DETAIL_DEEP,
    DETAIL_DETAILED,
    DETAIL_LEVELS,
    DETAIL_NORMAL,
    TECHNICAL_LEVEL_ADVANCED,
    TECHNICAL_LEVEL_BASIC,
    TECHNICAL_LEVEL_EXPERT,
    TECHNICAL_LEVEL_INTERMEDIATE,
    TONE_DIDACTIC,
    TONE_EXECUTIVE,
    TONE_NEUTRAL,
    TONE_PROFESSIONAL,
    ResponseProfile,
)

PROFILE_CONFIG_KEY = "response_profile"

#: Presets de Agent Studio (§29). El usuario elige y después ajusta.
#:
#: `balanced` es el estado "Auto" del Studio: equivale a los defaults del
#: dominio, así que un agente sin perfil guardado y uno con `balanced` se
#: comportan igual. El portal siempre persiste el perfil aplanado, no el preset:
#: un preset que el backend no conozca no degrada a valores equivocados.
RESPONSE_PROFILE_PRESETS: dict[str, ResponseProfile] = {
    "balanced": ResponseProfile(),
    "precise": ResponseProfile(
        tone=TONE_PROFESSIONAL,
        technical_level=TECHNICAL_LEVEL_ADVANCED,
        default_detail=DETAIL_NORMAL,
        audience=AUDIENCE_TECHNICAL,
        use_examples=False,
        use_tables=True,
        preserve_domain_terms=True,
    ),
    "clear_didactic": ResponseProfile(
        tone=TONE_DIDACTIC,
        technical_level=TECHNICAL_LEVEL_INTERMEDIATE,
        default_detail=DETAIL_DETAILED,
        audience=AUDIENCE_TECHNICAL,
        use_examples=True,
        show_practical_implications=True,
    ),
    "technical_detailed": ResponseProfile(
        tone=TONE_PROFESSIONAL,
        technical_level=TECHNICAL_LEVEL_ADVANCED,
        default_detail=DETAIL_DETAILED,
        audience=AUDIENCE_TECHNICAL,
        use_tables=True,
        use_examples=True,
        preserve_domain_terms=True,
    ),
    "executive": ResponseProfile(
        tone=TONE_EXECUTIVE,
        technical_level=TECHNICAL_LEVEL_BASIC,
        default_detail=DETAIL_NORMAL,
        audience=AUDIENCE_BUSINESS,
        use_examples=False,
        show_practical_implications=True,
        cite_sources=False,
    ),
    "concise": ResponseProfile(
        tone=TONE_NEUTRAL,
        technical_level=TECHNICAL_LEVEL_INTERMEDIATE,
        default_detail=DETAIL_BRIEF,
        audience=AUDIENCE_TECHNICAL,
        use_examples=False,
        show_practical_implications=False,
        cite_sources=False,
    ),
    "analytical": ResponseProfile(
        tone=TONE_PROFESSIONAL,
        technical_level=TECHNICAL_LEVEL_ADVANCED,
        default_detail=DETAIL_DEEP,
        audience=AUDIENCE_EXPERT,
        use_tables=True,
        use_examples=True,
        show_uncertainty=True,
    ),
    "evidence_first": ResponseProfile(
        tone=TONE_PROFESSIONAL,
        technical_level=TECHNICAL_LEVEL_INTERMEDIATE,
        default_detail=DETAIL_DETAILED,
        audience=AUDIENCE_TECHNICAL,
        cite_sources=True,
        show_uncertainty=True,
        show_practical_implications=True,
    ),
}

PRESET_LABELS: dict[str, str] = {
    "balanced": "Equilibrado",
    "precise": "Preciso",
    "clear_didactic": "Claro y didáctico",
    "technical_detailed": "Experto técnico",
    "executive": "Ejecutivo",
    "concise": "Conciso",
    "analytical": "Analítico",
    "evidence_first": "Con evidencia",
}


def _bool(value: Any, default: bool) -> bool:
    return bool(value) if isinstance(value, bool) else default


def _choice(value: Any, allowed: tuple[str, ...], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else default


def profile_from_config(config: Mapping[str, Any] | None) -> ResponseProfile:
    """Perfil guardado del agente, con defaults seguros si falta o está roto."""
    data = dict(config or {})
    raw = data.get(PROFILE_CONFIG_KEY)
    if isinstance(raw, str) and raw in RESPONSE_PROFILE_PRESETS:
        return RESPONSE_PROFILE_PRESETS[raw]
    if not isinstance(raw, Mapping):
        return ResponseProfile()
    preset_name = str(raw.get("preset") or "")
    base = RESPONSE_PROFILE_PRESETS.get(preset_name, ResponseProfile())
    preferred = raw.get("preferred_blueprints")
    instructions = str(raw.get("custom_instructions") or "")[:800]
    return replace(
        base,
        language=str(raw.get("language") or base.language)[:16],
        tone=_choice(raw.get("tone"), (TONE_PROFESSIONAL, TONE_DIDACTIC, TONE_EXECUTIVE, TONE_NEUTRAL), base.tone),
        technical_level=_choice(
            raw.get("technical_level"),
            (
                TECHNICAL_LEVEL_BASIC,
                TECHNICAL_LEVEL_INTERMEDIATE,
                TECHNICAL_LEVEL_ADVANCED,
                TECHNICAL_LEVEL_EXPERT,
            ),
            base.technical_level,
        ),
        default_detail=_choice(raw.get("default_detail"), DETAIL_LEVELS, base.default_detail),
        audience=_choice(
            raw.get("audience"),
            (AUDIENCE_BUSINESS, AUDIENCE_TECHNICAL, AUDIENCE_EXPERT, "beginner"),
            base.audience,
        ),
        conclusion_first=_bool(raw.get("conclusion_first"), base.conclusion_first),
        use_headings=_bool(raw.get("use_headings"), base.use_headings),
        use_bold=_bool(raw.get("use_bold"), base.use_bold),
        use_tables=_bool(raw.get("use_tables"), base.use_tables),
        use_examples=_bool(raw.get("use_examples"), base.use_examples),
        cite_sources=_bool(raw.get("cite_sources"), base.cite_sources),
        show_uncertainty=_bool(raw.get("show_uncertainty"), base.show_uncertainty),
        show_practical_implications=_bool(
            raw.get("show_practical_implications"), base.show_practical_implications
        ),
        preserve_domain_terms=_bool(raw.get("preserve_domain_terms"), base.preserve_domain_terms),
        preferred_blueprints=tuple(str(item) for item in (preferred or ()) if isinstance(item, str))[:6],
        custom_instructions=instructions,
    )


# ---------------------------------------------------------------------------
# Overrides del turno (§36): "respóndeme corto" no cambia el perfil guardado.
# ---------------------------------------------------------------------------

_BRIEF_RE = re.compile(
    r"\b(resp[oó]ndeme corto|en una l[ií]nea|s[ée] breve|breve por favor|"
    r"short answer|keep it short|just the answer)\b",
    re.IGNORECASE,
)
_DEEP_RE = re.compile(
    r"\b(expl[ií]came (?:todo|en detalle|a fondo)|con m[aá]s detalle|paso a paso|"
    r"explain in detail|deep dive|from scratch)\b",
    re.IGNORECASE,
)
_EXPERT_RE = re.compile(
    r"\b(como experto|nivel experto|as an expert|for an expert|sin explicaciones b[aá]sicas)\b",
    re.IGNORECASE,
)
_BEGINNER_RE = re.compile(
    r"\b(como principiante|expl[ií]came como si (?:no supiera|fuera nuevo)|"
    r"no s[ée] nada del tema|explain like i'?m new)\b",
    re.IGNORECASE,
)
_EXECUTIVE_RE = re.compile(
    r"\b(resumen ejecutivo|para (?:el )?(?:gerente|jefe|director)|executive summary|"
    r"sin tecnicismos)\b",
    re.IGNORECASE,
)


def detect_turn_overrides(message: str) -> dict[str, Any]:
    """Ajustes pedidos explícitamente en el turno. No persisten."""
    text = str(message or "")
    overrides: dict[str, Any] = {}
    if _BRIEF_RE.search(text):
        overrides["default_detail"] = DETAIL_BRIEF
        overrides["use_examples"] = False
    elif _DEEP_RE.search(text):
        overrides["default_detail"] = DETAIL_DEEP
    if _EXPERT_RE.search(text):
        overrides["technical_level"] = TECHNICAL_LEVEL_EXPERT
        overrides["audience"] = AUDIENCE_EXPERT
    elif _BEGINNER_RE.search(text):
        overrides["technical_level"] = TECHNICAL_LEVEL_BASIC
        overrides["audience"] = "beginner"
    if _EXECUTIVE_RE.search(text):
        overrides["tone"] = TONE_EXECUTIVE
        overrides["audience"] = AUDIENCE_BUSINESS
        overrides["use_tables"] = False
    return overrides


def apply_turn_overrides(profile: ResponseProfile, message: str) -> ResponseProfile:
    """Perfil efectivo del turno: el guardado + lo que el usuario pidió hoy."""
    overrides = detect_turn_overrides(message)
    if not overrides:
        return profile
    return replace(profile, **overrides)


# ---------------------------------------------------------------------------
# Bloque para el generador (instrucción, no contenido)
# ---------------------------------------------------------------------------

_TONE_TEXT: dict[str, str] = {
    TONE_PROFESSIONAL: "profesional y directo",
    TONE_DIDACTIC: "didáctico: explica el porqué, no sólo el qué",
    TONE_EXECUTIVE: "ejecutivo: conclusión e impacto, sin detalle técnico",
    TONE_NEUTRAL: "neutro y preciso",
}

_LEVEL_TEXT: dict[str, str] = {
    TECHNICAL_LEVEL_BASIC: "sin asumir conocimiento técnico previo",
    TECHNICAL_LEVEL_INTERMEDIATE: "con terminología técnica habitual del dominio",
    TECHNICAL_LEVEL_ADVANCED: "con precisión técnica, sin explicar lo básico",
    TECHNICAL_LEVEL_EXPERT: "asumiendo expertise: sin definiciones básicas",
}

_AUDIENCE_TEXT: dict[str, str] = {
    "beginner": "principiante: más contexto y definiciones",
    AUDIENCE_BUSINESS: "negocio: impacto y decisiones",
    AUDIENCE_TECHNICAL: "técnico",
    AUDIENCE_EXPERT: "experto: densidad alta, cero relleno",
}


def profile_prompt_block(profile: ResponseProfile) -> str:
    """Instrucciones de estilo del agente. Nunca contiene hechos (§33)."""
    lines = ["## RESPONSE PROFILE"]
    lines.append(f"- idioma: {profile.language}")
    lines.append(f"- tono: {_TONE_TEXT.get(profile.tone, profile.tone)}")
    lines.append(f"- nivel: {_LEVEL_TEXT.get(profile.technical_level, profile.technical_level)}")
    lines.append(f"- audiencia: {_AUDIENCE_TEXT.get(profile.audience, profile.audience)}")
    if profile.conclusion_first:
        lines.append("- responde primero la conclusión; después explícala")
    if profile.preserve_domain_terms:
        lines.append(
            "- conserva la terminología del dominio (no la traduzcas si pierde "
            "significado); puedes glosarla una vez"
        )
    if profile.show_practical_implications:
        lines.append("- di qué implica en la práctica para el caso del usuario")
    if profile.use_tables:
        lines.append("- usa tabla cuando haya dos o más atributos comparables")
    if profile.use_examples:
        lines.append("- usa un ejemplo breve cuando aclare la explicación")
    if not profile.use_headings:
        lines.append("- sin encabezados: respuesta corrida")
    if not profile.use_bold:
        lines.append("- sin negritas")
    if profile.cite_sources:
        lines.append("- cita la fuente junto a la afirmación que sostiene")
    if profile.show_uncertainty:
        lines.append(
            "- si algo no está resuelto por la evidencia, dilo y explica qué falta; "
            "no especules"
        )
    if profile.custom_instructions:
        lines.append(f"- instrucciones del agente: {profile.custom_instructions}")
    return "\n".join(lines)


def public_presets() -> list[dict[str, Any]]:
    return [
        {
            "id": key,
            "label": PRESET_LABELS.get(key, key),
            "profile": profile.to_public_dict(),
        }
        for key, profile in RESPONSE_PROFILE_PRESETS.items()
    ]


__all__ = [
    "PRESET_LABELS",
    "PROFILE_CONFIG_KEY",
    "RESPONSE_PROFILE_PRESETS",
    "apply_turn_overrides",
    "detect_turn_overrides",
    "profile_from_config",
    "profile_prompt_block",
    "public_presets",
]
