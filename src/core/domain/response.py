# =============================================================================
# Response Intelligence — dominio (qué forma tiene explicar la respuesta).
# =============================================================================
# Evidence Reasoning determina QUÉ PUEDE CONCLUIRSE.
# Response Intelligence determina CÓMO EXPLICARLO. Nunca cambia hechos.
#
# Pipeline:
#
#   Evidence -> Reasoning -> Verified Conclusion -> Response Blueprint
#   -> Response Contract -> Generator -> Claim Verification
#
# Tipos puros y observables: el contrato viaja al generador (como instrucción) y
# al flujo (como dato). Sin chain-of-thought en ninguna parte.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Nivel de detalle (§17): ordinal, no un número de palabras hardcodeado.
# ---------------------------------------------------------------------------

DETAIL_BRIEF = "brief"
DETAIL_NORMAL = "normal"
DETAIL_DETAILED = "detailed"
DETAIL_DEEP = "deep"

DETAIL_LEVELS: tuple[str, ...] = (DETAIL_BRIEF, DETAIL_NORMAL, DETAIL_DETAILED, DETAIL_DEEP)

#: Guía de extensión por nivel. Es una referencia para el generador, no un corte.
DETAIL_GUIDANCE: dict[str, str] = {
    DETAIL_BRIEF: "1 o 2 frases cuando alcance; sin secciones.",
    DETAIL_NORMAL: "respuesta directa + explicación breve; secciones sólo si ayudan.",
    DETAIL_DETAILED: "respuesta directa + significado + implicación práctica + ejemplo si aporta.",
    DETAIL_DEEP: "todo lo anterior con más profundidad, pasos o tabla cuando el caso lo pida.",
}

# ---------------------------------------------------------------------------
# Secciones semánticas: el frontend traduce, el backend no manda texto de UI.
# ---------------------------------------------------------------------------

SECTION_DIRECT_ANSWER = "direct_answer"
SECTION_MEANING = "meaning"
SECTION_PRACTICAL_EFFECT = "practical_effect"
SECTION_EXAMPLE = "example"
SECTION_SEQUENCE = "sequence"
SECTION_WHY = "why"
SECTION_DISCARDED_ALTERNATIVE = "discarded_alternative"
SECTION_WHAT_TO_CHECK = "what_to_check"
SECTION_CAUSE = "cause"
SECTION_EVIDENCE = "evidence"
SECTION_COMPARISON = "comparison"
SECTION_STEPS = "steps"
SECTION_DEFINITION = "definition"
SECTION_USES = "uses"
SECTION_WHERE_IT_APPLIES = "where_it_applies"
SECTION_DATA_READING = "data_reading"
SECTION_SUMMARY = "summary"
SECTION_LIMITATIONS = "limitations"
SECTION_SOURCES = "sources"

SECTION_ORDER: tuple[str, ...] = (
    SECTION_DIRECT_ANSWER,
    SECTION_MEANING,
    SECTION_PRACTICAL_EFFECT,
    SECTION_EXAMPLE,
    SECTION_SEQUENCE,
    SECTION_WHY,
    SECTION_DISCARDED_ALTERNATIVE,
    SECTION_WHAT_TO_CHECK,
    SECTION_CAUSE,
    SECTION_EVIDENCE,
    SECTION_COMPARISON,
    SECTION_STEPS,
    SECTION_DEFINITION,
    SECTION_USES,
    SECTION_WHERE_IT_APPLIES,
    SECTION_DATA_READING,
    SECTION_SUMMARY,
    SECTION_LIMITATIONS,
    SECTION_SOURCES,
)

# ---------------------------------------------------------------------------
# Perfil de respuesta (Agent Studio, §28): cómo debe explicar ESTE agente.
# ---------------------------------------------------------------------------

TONE_PROFESSIONAL = "professional"
TONE_DIDACTIC = "didactic"
TONE_EXECUTIVE = "executive"
TONE_NEUTRAL = "neutral"

TONES: tuple[str, ...] = (TONE_PROFESSIONAL, TONE_DIDACTIC, TONE_EXECUTIVE, TONE_NEUTRAL)

TECHNICAL_LEVEL_BASIC = "basic"
TECHNICAL_LEVEL_INTERMEDIATE = "intermediate"
TECHNICAL_LEVEL_ADVANCED = "advanced"
TECHNICAL_LEVEL_EXPERT = "expert"

TECHNICAL_LEVELS: tuple[str, ...] = (
    TECHNICAL_LEVEL_BASIC,
    TECHNICAL_LEVEL_INTERMEDIATE,
    TECHNICAL_LEVEL_ADVANCED,
    TECHNICAL_LEVEL_EXPERT,
)

#: Audiencia (§35): afecta cuánto contexto se explica.
AUDIENCE_BEGINNER = "beginner"
AUDIENCE_BUSINESS = "business"
AUDIENCE_TECHNICAL = "technical"
AUDIENCE_EXPERT = "expert"

AUDIENCES: tuple[str, ...] = (
    AUDIENCE_BEGINNER,
    AUDIENCE_BUSINESS,
    AUDIENCE_TECHNICAL,
    AUDIENCE_EXPERT,
)


@dataclass(frozen=True)
class ResponseProfile:
    """Cómo responde un agente. Estructura, no un system prompt gigante (§27)."""

    language: str = "es"
    tone: str = TONE_PROFESSIONAL
    technical_level: str = TECHNICAL_LEVEL_INTERMEDIATE
    default_detail: str = DETAIL_NORMAL
    audience: str = AUDIENCE_TECHNICAL
    conclusion_first: bool = True
    use_headings: bool = True
    use_bold: bool = True
    use_tables: bool = False
    use_examples: bool = True
    cite_sources: bool = True
    show_uncertainty: bool = True
    show_practical_implications: bool = True
    preserve_domain_terms: bool = True
    preferred_blueprints: tuple[str, ...] = ()
    custom_instructions: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "language": self.language,
            "tone": self.tone,
            "technical_level": self.technical_level,
            "default_detail": self.default_detail,
            "audience": self.audience,
            "preferred_blueprints": list(self.preferred_blueprints),
        }
        for key in (
            "conclusion_first",
            "use_headings",
            "use_bold",
            "use_tables",
            "use_examples",
            "cite_sources",
            "show_uncertainty",
            "show_practical_implications",
            "preserve_domain_terms",
        ):
            payload[key] = bool(getattr(self, key))
        if self.custom_instructions:
            payload["custom_instructions"] = self.custom_instructions[:800]
        return payload


# ---------------------------------------------------------------------------
# Contrato de respuesta (§6, §51): observable, sin razonamiento privado.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResponseContract:
    """Instrucción de composición + dato auditable. El código la compone."""

    blueprint: str
    detail: str = DETAIL_NORMAL
    conclusion_first: bool = True
    sections: tuple[str, ...] = ()
    formatting: dict[str, bool] = field(default_factory=dict)
    evidence: dict[str, bool] = field(default_factory=dict)
    language: str = "es"
    tone: str = TONE_PROFESSIONAL
    technical_level: str = TECHNICAL_LEVEL_INTERMEDIATE
    audience: str = AUDIENCE_TECHNICAL
    preserve_domain_terms: bool = True
    custom_instructions: str = ""
    decided_by: str = "deterministic"
    confidence: float | None = None
    ambiguous: bool = False
    #: Señales que obligan a matizar (§21): inferencias sin resolver, conflictos.
    hedging_required: bool = False
    uncertainty_notes: tuple[str, ...] = ()
    source_conflict: bool = False
    missing_information: tuple[str, ...] = ()
    runner_up: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "blueprint": self.blueprint,
            "detail": self.detail,
            "conclusion_first": bool(self.conclusion_first),
            "sections": list(self.sections),
            "formatting": dict(self.formatting),
            "evidence": dict(self.evidence),
            "language": self.language,
            "tone": self.tone,
            "technical_level": self.technical_level,
            "audience": self.audience,
            "decided_by": self.decided_by,
        }
        if self.confidence is not None:
            payload["confidence"] = round(float(self.confidence), 4)
        if self.ambiguous:
            payload["ambiguous"] = True
        if self.runner_up:
            payload["runner_up"] = self.runner_up
        if self.preserve_domain_terms:
            payload["preserve_domain_terms"] = True
        if self.hedging_required:
            payload["hedging_required"] = True
        if self.uncertainty_notes:
            payload["uncertainty_notes"] = list(self.uncertainty_notes)[:6]
        if self.source_conflict:
            payload["source_conflict"] = True
        if self.missing_information:
            payload["missing_information"] = list(self.missing_information)[:6]
        if self.custom_instructions:
            payload["custom_instructions"] = self.custom_instructions[:600]
        return payload


__all__ = [
    "AUDIENCES",
    "AUDIENCE_BEGINNER",
    "AUDIENCE_BUSINESS",
    "AUDIENCE_EXPERT",
    "AUDIENCE_TECHNICAL",
    "DETAIL_BRIEF",
    "DETAIL_DEEP",
    "DETAIL_DETAILED",
    "DETAIL_GUIDANCE",
    "DETAIL_NORMAL",
    "ResponseContract",
    "ResponseProfile",
    "SECTION_CAUSE",
    "SECTION_COMPARISON",
    "SECTION_DATA_READING",
    "SECTION_DEFINITION",
    "SECTION_DIRECT_ANSWER",
    "SECTION_DISCARDED_ALTERNATIVE",
    "SECTION_EVIDENCE",
    "SECTION_EXAMPLE",
    "SECTION_LIMITATIONS",
    "SECTION_MEANING",
    "SECTION_ORDER",
    "SECTION_PRACTICAL_EFFECT",
    "SECTION_SEQUENCE",
    "SECTION_SOURCES",
    "SECTION_STEPS",
    "SECTION_SUMMARY",
    "SECTION_USES",
    "SECTION_WHAT_TO_CHECK",
    "SECTION_WHY",
    "SECTION_WHERE_IT_APPLIES",
    "TECHNICAL_LEVELS",
    "TECHNICAL_LEVEL_ADVANCED",
    "TECHNICAL_LEVEL_BASIC",
    "TECHNICAL_LEVEL_EXPERT",
    "TECHNICAL_LEVEL_INTERMEDIATE",
    "TONES",
    "TONE_DIDACTIC",
    "TONE_EXECUTIVE",
    "TONE_NEUTRAL",
    "TONE_PROFESSIONAL",
]
