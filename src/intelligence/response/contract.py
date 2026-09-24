# =============================================================================
# Composición del contrato de respuesta (§6, §19-§22): el código decide.
# =============================================================================
# Entradas (todas datos, ninguna generación):
#   - selección de blueprint (determinista o JEV)
#   - respuestas del pack de composición (JEV, opcional)
#   - perfil del agente (Agent Studio)
#   - señales de verdad: inferencia sin resolver, conflictos de autoridad,
#     información faltante
#
# Salidas: un `ResponseContract` observable que se inyecta al generador como
# INSTRUCCIÓN de forma y se publica en el flujo. El contrato no aporta hechos:
# sólo dice cómo explicarlos.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Iterable, Mapping

from src.core.domain.response import (
    DETAIL_BRIEF,
    DETAIL_DEEP,
    DETAIL_GUIDANCE,
    DETAIL_LEVELS,
    DETAIL_NORMAL,
    SECTION_DIRECT_ANSWER,
    SECTION_EXAMPLE,
    SECTION_LIMITATIONS,
    SECTION_ORDER,
    SECTION_SOURCES,
    ResponseContract,
    ResponseProfile,
)
from src.intelligence.response.blueprints import (
    BLUEPRINTS,
    DIRECT_FACT,
    EXECUTIVE_SUMMARY,
    TECHNICAL_EXPLANATION,
    Blueprint,
    blueprint_ids,
    get_blueprint,
)
from src.intelligence.response.profile import (
    apply_turn_overrides,
    profile_prompt_block,
)
from src.intelligence.response.questions import CompositionAnswers
from src.intelligence.response.selector import (
    DECIDED_BY_JEV,
    BlueprintSelection,
    select_blueprint,
)

#: Secciones que el pack puede pedir: pregunta → sección.
_NEED_SECTIONS: dict[str, str] = {
    "needs_example": SECTION_EXAMPLE,
    "needs_definition": SECTION_DIRECT_ANSWER,
}

#: Formato que el pack puede habilitar.
_NEED_FORMATTING: dict[str, tuple[str, ...]] = {
    "needs_table": ("table",),
    "needs_step_by_step": ("numbered_steps",),
}


def _ordered_sections(blueprint: Blueprint, extra: Iterable[str]) -> tuple[str, ...]:
    sections = list(blueprint.sections)
    for section in extra:
        if section not in sections:
            sections.append(section)
    return tuple(sections)


def compose_contract(
    *,
    question: str,
    profile: ResponseProfile | None = None,
    selection: BlueprintSelection | None = None,
    answers: CompositionAnswers | None = None,
    shape: str = "",
    intent: str = "",
    has_records: bool = False,
    has_data_rows: bool = False,
    unresolved: Iterable[str] = (),
    missing_information: Iterable[str] = (),
    source_conflict: bool = False,
    conflict_note: str = "",
) -> ResponseContract:
    """Compone el contrato de respuesta. Fail-soft y determinista."""
    base_profile = apply_turn_overrides(profile or ResponseProfile(), question)
    chosen = selection or select_blueprint(
        question=question,
        intent=intent,
        shape=shape,
        has_records=has_records,
        has_data_rows=has_data_rows,
        preferred_blueprints=base_profile.preferred_blueprints,
    )
    pack = answers or CompositionAnswers()

    blueprint_id = pack.blueprint or chosen.blueprint
    if blueprint_id not in BLUEPRINTS:
        blueprint_id = TECHNICAL_EXPLANATION
    blueprint = get_blueprint(blueprint_id)

    detail = _detail_for(blueprint, base_profile, pack, chosen)
    blueprint = _apply_detail(blueprint, detail)

    extra_sections: list[str] = []
    for need, section in _NEED_SECTIONS.items():
        if pack.needs_flag(need):
            extra_sections.append(section)
    if pack.needs_flag("needs_warning"):
        extra_sections.append(SECTION_LIMITATIONS)
    if pack.needs_flag("needs_source_explanation") and SECTION_SOURCES not in extra_sections:
        extra_sections.append(SECTION_SOURCES)

    formatting = dict(blueprint.formatting)
    for need, keys in _NEED_FORMATTING.items():
        if pack.needs_flag(need):
            for key in keys:
                formatting[key] = True
    if not base_profile.use_headings and blueprint.id in {DIRECT_FACT, EXECUTIVE_SUMMARY}:
        formatting["headings"] = False
    if not base_profile.use_bold:
        formatting["bold_key_concepts"] = False
    if not base_profile.use_tables and not pack.needs_flag("needs_table"):
        # El perfil puede apagar tablas, pero no puede ignorar al caso que las pide.
        formatting["table"] = False
    if base_profile.default_detail == DETAIL_BRIEF:
        for key in ("headings", "table", "numbered_steps"):
            formatting[key] = False

    evidence = dict(blueprint.evidence)
    evidence["citations_required"] = bool(
        evidence.get("citations_required") and (base_profile.cite_sources or pack.needs_flag("needs_citations"))
    )
    if pack.needs_flag("needs_citations"):
        evidence["citations_required"] = True

    unresolved_list = [str(item) for item in unresolved if str(item)][:6]
    missing_list = [str(item) for item in missing_information if str(item)][:6]
    hedging = bool(unresolved_list)
    if hedging or missing_list:
        evidence["disclose_missing_information"] = True
        if SECTION_LIMITATIONS not in extra_sections:
            extra_sections.append(SECTION_LIMITATIONS)
    if source_conflict:
        evidence["disclose_conflicts"] = True
        if conflict_note and SECTION_SOURCES not in extra_sections:
            extra_sections.append(SECTION_SOURCES)

    sections = _ordered_sections(blueprint, extra_sections)
    if not base_profile.conclusion_first:
        sections = tuple(
            section for section in sections if section != SECTION_DIRECT_ANSWER
        ) or (SECTION_DIRECT_ANSWER,)

    uncertainty_notes: list[str] = []
    if unresolved_list:
        uncertainty_notes.append("inference_unresolved")
    if missing_list:
        uncertainty_notes.append("missing_information")
    if source_conflict:
        uncertainty_notes.append("source_conflict")
    if pack.uncertain:
        uncertainty_notes.append("composition_uncertain")

    decided_by = pack.blueprint and DECIDED_BY_JEV or chosen.decided_by
    confidence = pack.blueprint_confidence if pack.blueprint else chosen.confidence
    ambiguous = bool(pack.blueprint_ambiguous or (not pack.blueprint and chosen.ambiguous))

    return ResponseContract(
        blueprint=blueprint.id,
        detail=detail,
        conclusion_first=base_profile.conclusion_first,
        sections=sections,
        formatting=formatting,
        evidence=evidence,
        language=base_profile.language,
        tone=base_profile.tone,
        technical_level=base_profile.technical_level,
        audience=base_profile.audience,
        preserve_domain_terms=base_profile.preserve_domain_terms,
        custom_instructions=base_profile.custom_instructions,
        decided_by=decided_by,
        confidence=confidence,
        ambiguous=ambiguous,
        hedging_required=hedging,
        uncertainty_notes=tuple(uncertainty_notes),
        source_conflict=source_conflict,
        missing_information=tuple(missing_list),
        runner_up=(pack.blueprint_runner_up or chosen.runner_up),
    )


def _detail_for(
    blueprint: Blueprint,
    profile: ResponseProfile,
    answers: CompositionAnswers,
    selection: BlueprintSelection,
) -> str:
    """Detalle: lo que el caso pide manda; el perfil sólo ajusta el default."""
    if answers.detail in DETAIL_LEVELS:
        return answers.detail
    detail = profile.default_detail if profile.default_detail in DETAIL_LEVELS else blueprint.detail
    if blueprint.id == DIRECT_FACT and profile.default_detail == DETAIL_DEEP:
        # Un dato puntual no se convierte en artículo por perfil del agente.
        return DETAIL_NORMAL
    return detail


def _apply_detail(blueprint: Blueprint, detail: str) -> Blueprint:
    if detail == DETAIL_BRIEF:
        # Con detalle breve no se arrastran secciones explicativas.
        return replace(
            blueprint,
            sections=tuple(blueprint.sections[:1]) or (SECTION_DIRECT_ANSWER,),
        )
    return blueprint


# ---------------------------------------------------------------------------
# Bloque para el generador (§7, §8, §9, §21): instrucción de forma y estilo.
# ---------------------------------------------------------------------------

_SECTION_TEXT: dict[str, str] = {
    "direct_answer": "responde la pregunta directamente, sin preámbulo",
    "meaning": "explica qué significa formalmente",
    "practical_effect": "explica qué implica en la práctica para este caso",
    "example": "si la evidencia trae un caso, un ejemplo mínimo que haga visible la regla",
    "sequence": "muestra la secuencia de lo que ocurre, en orden",
    "why": "explica por qué, sólo con inferencias respaldadas",
    "discarded_alternative": "menciona la explicación alternativa descartada y por qué",
    "what_to_check": "di qué conviene verificar si queda algo abierto",
    "cause": "nombra la causa principal que la evidencia sostiene",
    "evidence": "muestra la evidencia que sostiene la conclusión",
    "comparison": "contrasta los criterios relevantes",
    "steps": "enumera los pasos en orden, cada uno con su resultado esperado",
    "definition": "define el concepto en una frase",
    "uses": "di para qué sirve",
    "where_it_applies": "di dónde interviene",
    "data_reading": "lee los datos y di qué muestran",
    "summary": "resume la conclusión y su impacto, sin detalle técnico",
    "limitations": "declara límites, excepciones o lo que todavía no puede afirmarse",
    "sources": "nombra la fuente que sostiene cada afirmación relevante",
}

#: Regla que no se negocia: sin esto, pedir forma invita a inventar contenido.
GROUNDING_RULE = (
    "- regla dura: sólo podés afirmar lo que la evidencia sostiene. Si un aspecto del "
    "orden de la información no está en la evidencia, omitelo y declaralo en los límites; "
    "nunca lo completes con conocimiento propio ni inventes cifras, porcentajes, nombres "
    "de categorías, campos, registros ni ejemplos"
)


def _sections_prose(sections: tuple[str, ...]) -> str:
    """Orden de la información en una sola frase, sin claves internas.

    Las claves viven en el contrato (dato auditable), no en el prompt: cuando el
    modelo las ve escritas las copia como rótulos y la respuesta se parte en
    cinco bloques sueltos.
    """
    parts = [_SECTION_TEXT[section] for section in sections if section in _SECTION_TEXT]
    if not parts:
        return ""
    return "; ".join(parts) + "."


def prompt_block(contract: ResponseContract, *, profile: ResponseProfile | None = None) -> str:
    """Bloque compacto de composición para el generador.

    Es una instrucción de forma: no contiene hechos ni conclusiones, y nunca
    expone las claves internas de las secciones.
    """
    blueprint = get_blueprint(contract.blueprint)
    lines: list[str] = ["## FORMA DE LA RESPUESTA (cómo explicarlo, no qué decir)"]
    lines.append(f"- forma: {blueprint.label.lower()} — {blueprint.purpose}")
    lines.append(f"- nivel de detalle: {contract.detail} — {DETAIL_GUIDANCE.get(contract.detail, '')}")
    if contract.conclusion_first:
        lines.append("- empieza por la conclusión; el contexto va después de la respuesta")
    prose = _sections_prose(contract.sections)
    if prose:
        lines.append(f"- orden de la información: {prose}")
        lines.append(
            "- escribí una sola explicación conectada: ese orden dice cómo entra la "
            "información, no son secciones rotuladas ni una lista de puntos"
        )
    lines.append(
        "- no escribas etiquetas internas (nombres de sección en inglés), ni repitas "
        "el orden al final: el lector no las conoce"
    )
    # Va antes que la forma: pedir forma sin grounding invita a rellenar de memoria.
    lines.append(GROUNDING_RULE)
    allowed = [
        name
        for name, enabled in (
            ("encabezados", contract.formatting.get("headings")),
            ("negritas para conceptos y valores clave", contract.formatting.get("bold_key_concepts")),
            ("viñetas", contract.formatting.get("bullets")),
            ("pasos numerados", contract.formatting.get("numbered_steps")),
            ("tabla", contract.formatting.get("table")),
        )
        if enabled
    ]
    if allowed:
        lines.append(f"- formato permitido: {', '.join(allowed)}")
    if contract.formatting.get("headings"):
        lines.append(
            "- si usás encabezados, que sean títulos naturales en el idioma del lector "
            "y no más de dos o tres: la respuesta se lee de corrido, no como un formulario"
        )
    forbidden = [
        name
        for name, enabled in (
            ("encabezados", contract.formatting.get("headings")),
            ("tablas", contract.formatting.get("table")),
        )
        if enabled is False
    ]
    if forbidden:
        lines.append(f"- no usar: {', '.join(forbidden)}")
    lines.append("- negritas sólo en valores, conceptos y conclusiones clave (no en media respuesta)")
    if contract.evidence.get("citations_required"):
        lines.append("- cita la fuente junto a la afirmación, no toda al final")
    if contract.evidence.get("separate_fact_from_inference"):
        lines.append(
            "- distingue hecho documentado de conclusión derivada (\"la especificación indica\" "
            "vs \"en tu escenario se concluye\")"
        )
    if contract.evidence.get("disclose_conflicts"):
        lines.append(
            "- si dos fuentes se contradicen, dilo y nombra ambas; no las fusiones en silencio"
        )
    if contract.evidence.get("disclose_missing_information"):
        lines.append("- declara qué información falta antes de cualquier especulación")
    if contract.hedging_required:
        lines.append(
            "- hay inferencias sin resolver: prohibido el lenguaje definitivo; di exactamente "
            "qué falta para poder concluir"
        )
    if contract.preserve_domain_terms:
        lines.append("- conserva los términos técnicos del dominio (puedes glosarlos una vez)")
    if contract.missing_information:
        lines.append(f"- información faltante a declarar: {', '.join(list(contract.missing_information)[:4])}")
    if contract.custom_instructions:
        lines.append(f"- instrucciones del agente: {contract.custom_instructions}")
    lines.append("- nada de relleno: si algo no aporta, no lo escribas")
    block = "\n".join(line for line in lines if line.strip())
    if profile is not None:
        block = f"{profile_prompt_block(profile)}\n\n{block}"
    return block


def contract_headline(contract: ResponseContract) -> str:
    """Etiqueta corta para la historia (el frontend traduce el id)."""
    blueprint = get_blueprint(contract.blueprint)
    return f"{blueprint.id}:{contract.detail}"


#: Claves que nunca deben verse en la respuesta (son del contrato, no del lector).
_SECTION_LABELS = "|".join(
    sorted((re.escape(section) for section in SECTION_ORDER), key=len, reverse=True)
)
#: El cierre de negrita puede ir antes o después de los dos puntos.
_LABEL_TOKEN = rf"\*{{0,2}}(?:{_SECTION_LABELS})\*{{0,2}}[ \t]*:\*{{0,2}}"
_LABEL_TOKEN_RE = re.compile(_LABEL_TOKEN, re.IGNORECASE)
#: Rótulo al principio de una línea (con viñeta opcional), uno o varios seguidos.
_LINE_LABEL_RE = re.compile(rf"(?im)^[ \t]*(?:(?:[>*-][ \t]*)?{_LABEL_TOKEN}[ \t]*)+")
#: Rótulo pegado al final de un párrafo ("… (pricing). **direct_answer:** …").
_INLINE_LABEL_RE = re.compile(rf"[ \t]+(?:{_LABEL_TOKEN}[ \t]*)+")


def strip_section_labels(text: str) -> tuple[str, int]:
    """Quita los rótulos internos filtrados a la respuesta.

    Devuelve `(texto, cuántos rótulos se quitaron)`. Sólo toca las claves del
    contrato: cualquier otro texto (incluidos encabezados en español) queda igual.
    Es idempotente: si no hay rótulos, el texto no cambia.
    """
    if not text:
        return text, 0
    if not _LABEL_TOKEN_RE.search(text):
        return text, 0
    # Cada etiqueta cuenta por separado: varias pueden venir en la misma corrida.
    removed = len(_LABEL_TOKEN_RE.findall(text))
    cleaned = _LINE_LABEL_RE.sub("", text)
    cleaned = _INLINE_LABEL_RE.sub(" ", cleaned)
    cleaned = re.sub(r"(?m)^[ \t]+", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned).strip()
    return cleaned, removed


def blueprint_options() -> tuple[str, ...]:
    return blueprint_ids()


def contract_from_public(payload: Mapping[str, Any] | None) -> ResponseContract | None:
    """Reconstruye un contrato desde el flujo (lectura defensiva)."""
    if not isinstance(payload, Mapping) or not payload.get("blueprint"):
        return None
    sections = payload.get("sections")
    formatting = payload.get("formatting")
    evidence = payload.get("evidence")
    return ResponseContract(
        blueprint=str(payload.get("blueprint")),
        detail=str(payload.get("detail") or DETAIL_NORMAL),
        conclusion_first=bool(payload.get("conclusion_first", True)),
        sections=tuple(str(item) for item in (sections or ()) if isinstance(item, str)),
        formatting={str(k): bool(v) for k, v in (formatting or {}).items()} if isinstance(formatting, Mapping) else {},
        evidence={str(k): bool(v) for k, v in (evidence or {}).items()} if isinstance(evidence, Mapping) else {},
        language=str(payload.get("language") or "es"),
        tone=str(payload.get("tone") or "professional"),
        decided_by=str(payload.get("decided_by") or "deterministic"),
    )


__all__ = [
    "blueprint_options",
    "compose_contract",
    "contract_from_public",
    "contract_headline",
    "prompt_block",
    "strip_section_labels",
]
