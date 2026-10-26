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
#: Enumeraciones (valores, opciones, casos): cuando hay 3+ conviene lista o
#: tabla en lugar de una frase que los encadene (legibilidad, no contenido).
SECTION_KEY_VALUES = "key_values"

SECTION_ORDER: tuple[str, ...] = (
    SECTION_DIRECT_ANSWER,
    SECTION_MEANING,
    SECTION_KEY_VALUES,
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


PROFILE_VERSION = 2

#: Estrategias de comunicación V2. Son instrucciones operativas, no etiquetas:
#: cada una se traduce a una línea concreta en el prompt del generador.
STRATEGY_ADAPTIVE = "adaptive"
STRATEGY_DEFINITION_SCOPE = "definition_scope"
STRATEGY_PROGRESSIVE = "progressive"
STRATEGY_IMPLEMENTATION_FIRST = "implementation_first"
STRATEGY_DECISION_FIRST = "decision_first"
STRATEGY_ANSWER_ONLY = "answer_only"
STRATEGY_DECOMPOSE_COMPARE = "decompose_compare"
STRATEGY_CLAIM_EVIDENCE = "claim_evidence"

COMMUNICATION_STRATEGIES: tuple[str, ...] = (
    STRATEGY_ADAPTIVE,
    STRATEGY_DEFINITION_SCOPE,
    STRATEGY_PROGRESSIVE,
    STRATEGY_IMPLEMENTATION_FIRST,
    STRATEGY_DECISION_FIRST,
    STRATEGY_ANSWER_ONLY,
    STRATEGY_DECOMPOSE_COMPARE,
    STRATEGY_CLAIM_EVIDENCE,
)

DETAIL_BUDGET_ADAPTIVE = "adaptive"
DETAIL_BUDGETS: tuple[str, ...] = (
    "adaptive",
    "tight",
    "guided",
    "deep",
    "compact",
    "minimal",
    "standard",
)

STRUCTURE_POLICIES: tuple[str, ...] = (
    "adaptive",
    "definition_scope",
    "progressive",
    "implementation",
    "decision_impact_next_action",
    "answer_only",
    "problem_alternatives_criteria_conclusion",
    "claim_evidence_inference",
)

EXAMPLE_POLICIES: tuple[str, ...] = ("when_useful", "never", "minimal_supported", "minimal", "direct_only")

ANALYSIS_DEPTHS: tuple[str, ...] = (
    "proportional",
    "surface_exact",
    "progressive",
    "implementation",
    "impact_only",
    "answer_only",
    "hypothesis_and_tradeoffs",
    "evidence_first",
)

TERMINOLOGY_POLICIES: tuple[str, ...] = (
    "domain_aware",
    "exact",
    "plain_with_domain_terms",
    "business",
    "plain",
)

SOURCE_PRESENTATION_POLICIES: tuple[str, ...] = (
    "inline_required",
    "inline_when_used",
    "on_request",
    "only_when_required",
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
    #: Las tablas no se prohíben por defecto: el blueprint decide cuándo una
    #: comparación las justifica (`table_when`). Un perfil puede vetarlas.
    use_tables: bool = True
    use_examples: bool = True
    cite_sources: bool = True
    show_uncertainty: bool = True
    show_practical_implications: bool = True
    preserve_domain_terms: bool = True
    preferred_blueprints: tuple[str, ...] = ()
    custom_instructions: str = ""
    #: V2: identidad y estrategia observable. Los defaults son `balanced`, de
    #: modo que un perfil ausente sigue siendo idéntico a `ResponseProfile()`.
    profile_id: str = "balanced"
    profile_version: int = PROFILE_VERSION
    communication_strategy: str = STRATEGY_ADAPTIVE
    detail_budget: str = DETAIL_BUDGET_ADAPTIVE
    structure_policy: str = "adaptive"
    example_policy: str = "when_useful"
    analysis_depth: str = "proportional"
    terminology_policy: str = "domain_aware"
    source_presentation_policy: str = "inline_required"
    audience_assumptions: str = ""
    override_origin: str = "agent_config"

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "preset": self.profile_id,
            "language": self.language,
            "tone": self.tone,
            "technical_level": self.technical_level,
            "default_detail": self.default_detail,
            "audience": self.audience,
            "preferred_blueprints": list(self.preferred_blueprints),
            "communication_strategy": self.communication_strategy,
            "detail_budget": self.detail_budget,
            "structure_policy": self.structure_policy,
            "example_policy": self.example_policy,
            "analysis_depth": self.analysis_depth,
            "terminology_policy": self.terminology_policy,
            "source_presentation_policy": self.source_presentation_policy,
            "audience_assumptions": self.audience_assumptions,
            "override_origin": self.override_origin,
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
    #: Capas de lectura que el generador debe respetar (ritmo de presentación).
    layers: tuple[str, ...] = ()
    #: Política de presentación observada: conceptos, enumeraciones, cuánta
    #: evidencia se explica y cuánta queda disponible sin volcarse.
    presentation: dict[str, Any] = field(default_factory=dict)
    #: Los límites se declaran sólo cuando son materialmente relevantes.
    show_limitations: bool = False
    #: V2: perfil efectivo que produjo este contrato, con procedencia y hash.
    profile_id: str = "balanced"
    profile_version: int = PROFILE_VERSION
    communication_strategy: str = STRATEGY_ADAPTIVE
    detail_budget: str = DETAIL_BUDGET_ADAPTIVE
    structure_policy: str = "adaptive"
    example_policy: str = "when_useful"
    analysis_depth: str = "proportional"
    terminology_policy: str = "domain_aware"
    source_presentation_policy: str = "inline_required"
    audience_assumptions: str = ""
    override_origin: str = "agent_config"
    effective_profile_hash: str = ""
    turn_overrides: tuple[str, ...] = ()
    style_degraded: bool = False
    style_degradation_reason: str = ""
    #: P15: intención del usuario e identidad persistente del agente.
    request_intent: str = ""
    request_intent_confidence: float = 0.0
    identity_id: str = ""
    identity_version: int = 1
    identity_hash: str = ""
    identity_voice: str = ""
    identity_mode: str = "preserve"
    identity_preserved: bool = True
    identity_conflicts: tuple[str, ...] = ()

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
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "communication_strategy": self.communication_strategy,
            "detail_budget": self.detail_budget,
            "structure_policy": self.structure_policy,
            "example_policy": self.example_policy,
            "analysis_depth": self.analysis_depth,
            "terminology_policy": self.terminology_policy,
            "source_presentation_policy": self.source_presentation_policy,
            "override_origin": self.override_origin,
        }
        if self.audience_assumptions:
            payload["audience_assumptions"] = self.audience_assumptions
        if self.request_intent:
            payload["request_intent"] = self.request_intent
            payload["request_intent_confidence"] = round(float(self.request_intent_confidence), 4)
        if self.identity_id or self.identity_voice:
            payload["identity_id"] = self.identity_id
            payload["identity_version"] = self.identity_version
            payload["identity_hash"] = self.identity_hash
            payload["identity_voice"] = self.identity_voice[:240]
            payload["identity_mode"] = self.identity_mode
            payload["identity_preserved"] = bool(self.identity_preserved)
            if self.identity_conflicts:
                payload["identity_conflicts"] = list(self.identity_conflicts)
        if self.effective_profile_hash:
            payload["effective_profile_hash"] = self.effective_profile_hash
        if self.turn_overrides:
            payload["turn_overrides"] = list(self.turn_overrides)
        if self.style_degraded:
            payload["style_degraded"] = True
            if self.style_degradation_reason:
                payload["style_degradation_reason"] = self.style_degradation_reason
        if self.layers:
            payload["layers"] = list(self.layers)
        if self.presentation:
            payload["presentation"] = dict(self.presentation)
        if self.show_limitations:
            payload["show_limitations"] = True
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
    "ANALYSIS_DEPTHS",
    "AUDIENCES",
    "AUDIENCE_BEGINNER",
    "AUDIENCE_BUSINESS",
    "AUDIENCE_EXPERT",
    "AUDIENCE_TECHNICAL",
    "COMMUNICATION_STRATEGIES",
    "DETAIL_BRIEF",
    "DETAIL_BUDGETS",
    "DETAIL_DEEP",
    "DETAIL_DETAILED",
    "DETAIL_GUIDANCE",
    "DETAIL_NORMAL",
    "EXAMPLE_POLICIES",
    "PROFILE_VERSION",
    "ResponseContract",
    "ResponseProfile",
    "SOURCE_PRESENTATION_POLICIES",
    "STRUCTURE_POLICIES",
    "TERMINOLOGY_POLICIES",
    "SECTION_CAUSE",
    "SECTION_COMPARISON",
    "SECTION_DATA_READING",
    "SECTION_DEFINITION",
    "SECTION_DIRECT_ANSWER",
    "SECTION_DISCARDED_ALTERNATIVE",
    "SECTION_EVIDENCE",
    "SECTION_EXAMPLE",
    "SECTION_KEY_VALUES",
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
