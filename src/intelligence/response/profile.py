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
    ANALYSIS_DEPTHS,
    AUDIENCE_BEGINNER,
    AUDIENCE_BUSINESS,
    AUDIENCE_EXPERT,
    AUDIENCE_TECHNICAL,
    COMMUNICATION_STRATEGIES,
    DETAIL_BRIEF,
    DETAIL_BUDGETS,
    DETAIL_DEEP,
    DETAIL_DETAILED,
    DETAIL_LEVELS,
    DETAIL_NORMAL,
    EXAMPLE_POLICIES,
    PROFILE_VERSION,
    SOURCE_PRESENTATION_POLICIES,
    STRATEGY_ANSWER_ONLY,
    STRATEGY_CLAIM_EVIDENCE,
    STRATEGY_DECISION_FIRST,
    STRATEGY_DECOMPOSE_COMPARE,
    STRATEGY_DEFINITION_SCOPE,
    STRATEGY_IMPLEMENTATION_FIRST,
    STRATEGY_PROGRESSIVE,
    STRUCTURE_POLICIES,
    TECHNICAL_LEVEL_ADVANCED,
    TECHNICAL_LEVEL_BASIC,
    TECHNICAL_LEVEL_EXPERT,
    TECHNICAL_LEVEL_INTERMEDIATE,
    TERMINOLOGY_POLICIES,
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
        profile_id="precise",
        tone=TONE_PROFESSIONAL,
        technical_level=TECHNICAL_LEVEL_ADVANCED,
        default_detail=DETAIL_NORMAL,
        audience=AUDIENCE_TECHNICAL,
        conclusion_first=True,
        use_examples=False,
        use_tables=True,
        preserve_domain_terms=True,
        communication_strategy=STRATEGY_DEFINITION_SCOPE,
        detail_budget="tight",
        structure_policy="definition_scope",
        example_policy="never",
        analysis_depth="surface_exact",
        terminology_policy="exact",
        source_presentation_policy="inline_required",
        audience_assumptions="Ya conoce el dominio; necesita el alcance exacto del término o condición.",
    ),
    "clear_didactic": ResponseProfile(
        profile_id="clear_didactic",
        tone=TONE_DIDACTIC,
        technical_level=TECHNICAL_LEVEL_INTERMEDIATE,
        default_detail=DETAIL_DETAILED,
        audience=AUDIENCE_BEGINNER,
        conclusion_first=False,
        use_examples=True,
        show_practical_implications=True,
        communication_strategy=STRATEGY_PROGRESSIVE,
        detail_budget="guided",
        structure_policy="progressive",
        example_policy="minimal_supported",
        analysis_depth="progressive",
        terminology_policy="plain_with_domain_terms",
        source_presentation_policy="inline_when_used",
        audience_assumptions="Aprende el concepto; necesita progresión y un ejemplo mínimo sustentado.",
    ),
    "technical_detailed": ResponseProfile(
        profile_id="technical_detailed",
        tone=TONE_PROFESSIONAL,
        technical_level=TECHNICAL_LEVEL_ADVANCED,
        default_detail=DETAIL_DETAILED,
        audience=AUDIENCE_EXPERT,
        conclusion_first=True,
        use_examples=False,
        use_tables=True,
        preserve_domain_terms=True,
        communication_strategy=STRATEGY_IMPLEMENTATION_FIRST,
        detail_budget="deep",
        structure_policy="implementation",
        example_policy="minimal",
        analysis_depth="implementation",
        terminology_policy="exact",
        source_presentation_policy="inline_required",
        audience_assumptions="Expertise técnica: no explicar fundamentos ni definiciones básicas.",
    ),
    "executive": ResponseProfile(
        profile_id="executive",
        tone=TONE_EXECUTIVE,
        technical_level=TECHNICAL_LEVEL_BASIC,
        default_detail=DETAIL_NORMAL,
        audience=AUDIENCE_BUSINESS,
        conclusion_first=True,
        use_examples=False,
        use_tables=False,
        cite_sources=True,
        show_practical_implications=True,
        communication_strategy=STRATEGY_DECISION_FIRST,
        detail_budget="compact",
        structure_policy="decision_impact_next_action",
        example_policy="never",
        analysis_depth="impact_only",
        terminology_policy="business",
        source_presentation_policy="on_request",
        audience_assumptions="Decide: necesita decisión, impacto, riesgo y siguiente acción.",
    ),
    "concise": ResponseProfile(
        profile_id="concise",
        tone=TONE_NEUTRAL,
        technical_level=TECHNICAL_LEVEL_INTERMEDIATE,
        default_detail=DETAIL_BRIEF,
        audience=AUDIENCE_TECHNICAL,
        conclusion_first=True,
        use_headings=False,
        use_bold=False,
        use_tables=False,
        use_examples=False,
        cite_sources=True,
        show_practical_implications=False,
        communication_strategy=STRATEGY_ANSWER_ONLY,
        detail_budget="minimal",
        structure_policy="answer_only",
        example_policy="never",
        analysis_depth="answer_only",
        terminology_policy="plain",
        source_presentation_policy="only_when_required",
        audience_assumptions="Quiere la respuesta mínima suficiente, sin contexto secundario.",
    ),
    "analytical": ResponseProfile(
        profile_id="analytical",
        tone=TONE_PROFESSIONAL,
        technical_level=TECHNICAL_LEVEL_ADVANCED,
        default_detail=DETAIL_DEEP,
        audience=AUDIENCE_EXPERT,
        conclusion_first=False,
        use_tables=True,
        use_examples=True,
        show_uncertainty=True,
        communication_strategy=STRATEGY_DECOMPOSE_COMPARE,
        detail_budget="deep",
        structure_policy="problem_alternatives_criteria_conclusion",
        example_policy="when_useful",
        analysis_depth="hypothesis_and_tradeoffs",
        terminology_policy="exact",
        source_presentation_policy="inline_required",
        audience_assumptions="Evalúa alternativas; necesita hipótesis, criterios y una conclusión razonada.",
    ),
    "evidence_first": ResponseProfile(
        profile_id="evidence_first",
        tone=TONE_PROFESSIONAL,
        technical_level=TECHNICAL_LEVEL_INTERMEDIATE,
        default_detail=DETAIL_DETAILED,
        audience=AUDIENCE_TECHNICAL,
        conclusion_first=True,
        cite_sources=True,
        show_uncertainty=True,
        show_practical_implications=True,
        communication_strategy=STRATEGY_CLAIM_EVIDENCE,
        detail_budget="standard",
        structure_policy="claim_evidence_inference",
        example_policy="when_useful",
        analysis_depth="evidence_first",
        terminology_policy="domain_aware",
        source_presentation_policy="inline_required",
        audience_assumptions="Necesita trazabilidad: qué está acreditado, qué es inferencia y qué falta.",
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

PRESET_HINTS: dict[str, str] = {
    "balanced": "Estructura adaptativa; profundidad proporcional al problema.",
    "precise": "Definiciones exactas, condiciones y alcance; sin explicaciones pedagógicas.",
    "clear_didactic": "Progresión, lenguaje accesible y ejemplos mínimos sustentados.",
    "technical_detailed": "Implementación, contratos y detalles avanzados; sin fundamentos.",
    "executive": "Decisión, impacto, riesgos y siguiente acción.",
    "concise": "La menor cantidad de palabras suficiente para responder bien.",
    "analytical": "Descompone, compara alternativas y termina con una conclusión razonada.",
    "evidence_first": "Afirmaciones verificables, fuentes e inferencias separadas.",
}


def _bool(value: Any, default: bool) -> bool:
    return bool(value) if isinstance(value, bool) else default


def _choice(value: Any, allowed: tuple[str, ...], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else default


_PROFILE_RAW_MARKERS = frozenset(
    {
        "preset",
        "profile_id",
        "communication_strategy",
        "detail_budget",
        "structure_policy",
        "example_policy",
        "analysis_depth",
        "terminology_policy",
        "source_presentation_policy",
        "audience_assumptions",
        "default_detail",
        "use_examples",
        "use_headings",
        "preferred_blueprints",
        "custom_instructions",
    }
)

_PROFILE_OVERRIDE_KEYS = frozenset(
    {
        "language",
        "tone",
        "technical_level",
        "default_detail",
        "audience",
        "conclusion_first",
        "use_headings",
        "use_bold",
        "use_tables",
        "use_examples",
        "cite_sources",
        "show_uncertainty",
        "show_practical_implications",
        "preserve_domain_terms",
        "preferred_blueprints",
        "custom_instructions",
        "communication_strategy",
        "detail_budget",
        "structure_policy",
        "example_policy",
        "analysis_depth",
        "terminology_policy",
        "source_presentation_policy",
        "audience_assumptions",
    }
)


def profile_from_config(config: Mapping[str, Any] | None) -> ResponseProfile:
    """Perfil guardado del agente, con defaults seguros si falta o está roto.

    Acepta el config completo del agente (`{"response_profile": {...}}`) o el
    sub-dict del perfil. El segundo caso evita el doble `get` que hacía que el
    runtime RAG ignorara el perfil.
    """
    data = dict(config or {})
    raw = data.get(PROFILE_CONFIG_KEY)
    if raw is None and bool(_PROFILE_RAW_MARKERS & set(data.keys())):
        raw = data
    if isinstance(raw, str):
        raw = {"preset": raw}
    if not isinstance(raw, Mapping):
        return ResponseProfile()
    preset_name = str(raw.get("preset") or raw.get("profile_id") or "")
    base = RESPONSE_PROFILE_PRESETS.get(preset_name, ResponseProfile())
    explicit_preset = preset_name in RESPONSE_PROFILE_PRESETS
    has_explicit_fields = bool(_PROFILE_OVERRIDE_KEYS & set(raw.keys()))
    profile_id = (
        preset_name
        if explicit_preset
        else ("custom" if has_explicit_fields else "balanced")
    )
    preferred = raw.get("preferred_blueprints")
    instructions = str(raw.get("custom_instructions") or "")[:800]
    return replace(
        base,
        profile_id=profile_id,
        profile_version=PROFILE_VERSION,
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
            (AUDIENCE_BUSINESS, AUDIENCE_TECHNICAL, AUDIENCE_EXPERT, AUDIENCE_BEGINNER),
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
        communication_strategy=_choice(
            raw.get("communication_strategy"), COMMUNICATION_STRATEGIES, base.communication_strategy
        ),
        detail_budget=_choice(raw.get("detail_budget"), DETAIL_BUDGETS, base.detail_budget),
        structure_policy=_choice(
            raw.get("structure_policy"), STRUCTURE_POLICIES, base.structure_policy
        ),
        example_policy=_choice(raw.get("example_policy"), EXAMPLE_POLICIES, base.example_policy),
        analysis_depth=_choice(raw.get("analysis_depth"), ANALYSIS_DEPTHS, base.analysis_depth),
        terminology_policy=_choice(
            raw.get("terminology_policy"), TERMINOLOGY_POLICIES, base.terminology_policy
        ),
        source_presentation_policy=_choice(
            raw.get("source_presentation_policy"),
            SOURCE_PRESENTATION_POLICIES,
            base.source_presentation_policy,
        ),
        audience_assumptions=str(raw.get("audience_assumptions") or base.audience_assumptions)[:240],
        override_origin="agent_config",
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
    return replace(profile, **overrides, override_origin="turn_override")


def profile_hash(profile: ResponseProfile) -> str:
    """Hash estable del perfil efectivo (sin secretos ni instrucciones libres)."""
    import hashlib
    import json

    payload = profile.to_public_dict()
    payload.pop("override_origin", None)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


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

_STRATEGY_TEXT: dict[str, str] = {
    "adaptive": "estructura adaptativa; profundidad proporcional al problema",
    "definition_scope": "define con exactitud, delimita condiciones y alcance; no des rodeos pedagógicos",
    "progressive": "avanza de lo simple a lo complejo y conecta causa con efecto",
    "implementation_first": "prioriza contratos, estructuras y detalles de implementación; omite fundamentos",
    "decision_first": "abre con la decisión; después impacto, riesgos y siguiente acción",
    "answer_only": "responde sólo lo necesario; sin introducción, secciones ni reiteración",
    "decompose_compare": (
        "descompone el problema, compara alternativas, examina hipótesis y "
        "cierra con una conclusión razonada"
    ),
    "claim_evidence": "organiza la respuesta por afirmaciones verificables; separa evidencia directa de inferencia",
}

_DETAIL_BUDGET_TEXT: dict[str, str] = {
    "adaptive": "el necesario para responder bien, sin relleno",
    "tight": "ajustado: sólo lo imprescindible para precisar el alcance",
    "guided": "guiado: suficiente para aprender sin convertirlo en un artículo",
    "deep": "profundo: cubre matices, alternativas y consecuencias",
    "compact": "compacto: una lectura breve de decisión",
    "minimal": "mínimo: la menor cantidad de palabras suficiente",
    "standard": "estándar: respuesta completa pero sin digresiones",
}

_STRUCTURE_TEXT: dict[str, str] = {
    "adaptive": "la que pida el caso; sin plantilla fija",
    "definition_scope": "definición → condiciones → alcance → excepciones",
    "progressive": "idea simple → porqué → ejemplo mínimo → comprobación breve",
    "implementation": "contrato/estructura → flujo → detalles → límites de implementación",
    "decision_impact_next_action": "decisión → impacto → riesgo → siguiente acción",
    "answer_only": "respuesta directa, sin apartados",
    "problem_alternatives_criteria_conclusion": "problema → alternativas → criterios → conclusión razonada",
    "claim_evidence_inference": "afirmación → evidencia → inferencia → qué falta por acreditar",
}

_EXAMPLE_POLICY_TEXT: dict[str, str] = {
    "when_useful": "usa un ejemplo breve sólo cuando aclare la explicación",
    "never": "no agregues ejemplos",
    "minimal_supported": "usa un ejemplo mínimo y sustentado por la evidencia",
    "minimal": "como máximo un ejemplo mínimo, sólo si es imprescindible",
    "direct_only": "no agregues ejemplos ni analogías",
}

_ANALYSIS_TEXT: dict[str, str] = {
    "proportional": "profundidad proporcional a la pregunta",
    "surface_exact": "qué es, cuándo aplica y qué queda fuera; sin desarrollo pedagógico",
    "progressive": "construye el concepto paso a paso",
    "implementation": "cómo funciona y cómo se implementa",
    "impact_only": "sólo implicaciones para decidir",
    "answer_only": "sólo el resultado, sin análisis secundario",
    "hypothesis_and_tradeoffs": "hipótesis, restricciones, criterios y trade-offs",
    "evidence_first": "qué está acreditado, qué se infiere y qué no se sabe",
}

_TERMINOLOGY_TEXT: dict[str, str] = {
    "domain_aware": "conserva los términos del dominio y glosa sólo si hace falta",
    "exact": "usa el término exacto; no lo sustituyas por aproximaciones",
    "plain_with_domain_terms": "lenguaje accesible, conservando el término técnico cuando importa",
    "business": "vocabulario de negocio; evita jerga técnica innecesaria",
    "plain": "lenguaje llano y directo",
}

_SOURCE_PRESENTATION_TEXT: dict[str, str] = {
    "inline_required": "cita la fuente junto a cada afirmación que la necesite",
    "inline_when_used": "cita cuando uses una fuente; no inventes citas decorativas",
    "on_request": "cita sólo si la decisión o la pregunta lo exige; nunca omitas una cita obligatoria",
    "only_when_required": "cita únicamente cuando la evidencia o la política lo exijan; nunca inventes fuentes",
}


def profile_prompt_block(profile: ResponseProfile) -> str:
    """Instrucciones de estilo del agente. Nunca contiene hechos (§33)."""
    lines = ["## RESPONSE PROFILE"]
    lines.append(f"- idioma: {profile.language}")
    lines.append(f"- tono: {_TONE_TEXT.get(profile.tone, profile.tone)}")
    lines.append(f"- nivel: {_LEVEL_TEXT.get(profile.technical_level, profile.technical_level)}")
    lines.append(f"- audiencia: {_AUDIENCE_TEXT.get(profile.audience, profile.audience)}")
    strategy = _STRATEGY_TEXT.get(
        profile.communication_strategy, profile.communication_strategy
    )
    lines.append(f"- estrategia de comunicación: {strategy}")
    lines.append(
        f"- presupuesto de detalle: {_DETAIL_BUDGET_TEXT.get(profile.detail_budget, profile.detail_budget)}"
    )
    lines.append(
        f"- estructura: {_STRUCTURE_TEXT.get(profile.structure_policy, profile.structure_policy)}"
    )
    lines.append(
        f"- ejemplos: {_EXAMPLE_POLICY_TEXT.get(profile.example_policy, profile.example_policy)}"
    )
    lines.append(
        f"- profundidad de análisis: {_ANALYSIS_TEXT.get(profile.analysis_depth, profile.analysis_depth)}"
    )
    lines.append(
        f"- terminología: {_TERMINOLOGY_TEXT.get(profile.terminology_policy, profile.terminology_policy)}"
    )
    source_presentation = _SOURCE_PRESENTATION_TEXT.get(
        profile.source_presentation_policy, profile.source_presentation_policy
    )
    lines.append(f"- fuentes: {source_presentation}")
    if profile.audience_assumptions:
        lines.append(f"- supuestos de audiencia: {profile.audience_assumptions}")
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
            "hint": PRESET_HINTS.get(key, ""),
            "profile": profile.to_public_dict(),
        }
        for key, profile in RESPONSE_PROFILE_PRESETS.items()
    ]


__all__ = [
    "PRESET_HINTS",
    "PRESET_LABELS",
    "PROFILE_CONFIG_KEY",
    "RESPONSE_PROFILE_PRESETS",
    "apply_turn_overrides",
    "detect_turn_overrides",
    "profile_from_config",
    "profile_hash",
    "profile_prompt_block",
    "public_presets",
]
