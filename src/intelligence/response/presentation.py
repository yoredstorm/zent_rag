# =============================================================================
# Presentation policy — el ritmo de la respuesta (legibilidad, no contenido).
# =============================================================================
# Response Intelligence decide la FORMA (blueprint) y el detalle. Esto decide
# cómo entra esa información al lector: capas, conceptos, enumeraciones y qué
# evidencia merece aparecer.
#
# Principios:
#   - Correcto no significa legible.
#   - Toda evidencia recuperada puede ser verdadera, pero no toda merece
#     aparecer en la respuesta (la evidencia NO se elimina del run: sólo se
#     decide qué se explica).
#   - Una idea principal por bloque visual.
#   - La estructura sigue la pregunta, no un template fijo.
#   - Presentation puede reordenar cómo se explica; nunca cambia hechos.
#
# Todo es determinista y observable: no hay scores inventados, sólo medidas
# (conceptos, enumeraciones, fragmentos explicados y fragmentos que quedan
# disponibles sin volcarse).
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping, Sequence

from src.core.domain.response import (
    DETAIL_BRIEF,
    DETAIL_DEEP,
    DETAIL_DETAILED,
    DETAIL_NORMAL,
    SECTION_DIRECT_ANSWER,
    SECTION_KEY_VALUES,
    SECTION_LIMITATIONS,
    ResponseContract,
)
from src.intelligence.response.entities import asked_concepts

#: Capas de lectura, en orden. No todas aplican a todos los casos.
LAYER_ANSWER = "answer"
LAYER_CONCEPTS = "concepts"
LAYER_DETAIL = "detail"
LAYER_PRACTICAL = "practical"
LAYER_LIMITS = "limits"

#: Enumeraciones: cantidad a partir de la cual conviene lista o tabla.
LIST_THRESHOLD = 3

#: Material que suele ser secundario para la pregunta (se explica si se pide).
_SECONDARY_RE = re.compile(
    r"\b(footnotes?|notas?\s+al\s+pie|appendix|ap[eé]ndice|alt\s*gen|"
    r"records?\s+\d|registros?\s+\d|permutaci\w+|anexo|glosario)\b",
    re.IGNORECASE,
)
#: Enumeración explícita en la evidencia: «Value 1», «Valor 2:», «Opción 3».
_ENUM_RE = re.compile(
    r"(?:^|\n)\s*(?:\*\*)?(?:value|valor|opci[oó]n|option|case|caso|step|paso)\s*"
    r"(\d{1,2})\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PresentationPolicy:
    """Cómo se presenta la respuesta. Datos, no prosa: se audita en el flujo."""

    concepts: tuple[str, ...] = ()
    multi_concept: bool = False
    layers: tuple[str, ...] = ()
    headings_budget: int = 1
    needs_list: bool = False
    enumeration_count: int = 0
    content_selected: int = 0
    content_omitted: int = 0
    secondary_count: int = 0
    secondary_labels: tuple[str, ...] = ()
    show_limitations: bool = False
    limitations_reason: str = ""
    followup_allowed: bool = False
    detail: str = DETAIL_NORMAL

    @property
    def explains_everything(self) -> bool:
        return self.content_omitted <= 0

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "concepts": list(self.concepts)[:6],
            "multi_concept": self.multi_concept,
            "layers": list(self.layers),
            "headings_budget": self.headings_budget,
            "needs_list": self.needs_list,
            "enumeration_count": self.enumeration_count,
            "content_selected": self.content_selected,
            "content_omitted": self.content_omitted,
            "followup_allowed": self.followup_allowed,
            "detail": self.detail,
        }
        # UNKNOWN != ZERO: lo no medido no se publica como 0.
        if self.secondary_count:
            payload["secondary_count"] = self.secondary_count
            if self.secondary_labels:
                payload["secondary_labels"] = list(self.secondary_labels)[:4]
        if self.show_limitations:
            payload["show_limitations"] = True
            if self.limitations_reason:
                payload["limitations_reason"] = self.limitations_reason
        return payload


def count_enumerations(evidence_text: str) -> int:
    """Cuántos elementos enumerados trae la evidencia (valores, opciones, casos)."""
    values = {match.group(1) for match in _ENUM_RE.finditer(evidence_text or "")}
    return len(values)


def _secondary_labels(text: str, concepts: Sequence[str], *, limit: int = 4) -> tuple[str, ...]:
    """Menciones de material secundario que la pregunta no pide.

    Sólo cuenta lo que NO contiene ninguno de los conceptos pedidos: si la
    pregunta va sobre un record, ese record no es secundario.
    """
    lowered = (text or "").lower()
    found: list[str] = []
    if any(concept.lower() in lowered for concept in concepts if concept):
        return ()
    for match in _SECONDARY_RE.finditer(text or ""):
        label = " ".join(match.group(0).split()).lower()
        if label and label not in found:
            found.append(label)
        if len(found) >= limit:
            break
    return tuple(found)


def build_presentation_policy(
    *,
    question: str,
    detail: str = DETAIL_NORMAL,
    evidence_text: str = "",
    evidence_titles: Sequence[str] = (),
    selected_count: int = 0,
    omitted_count: int = 0,
    missing_information: Iterable[str] = (),
    unresolved: Iterable[str] = (),
    source_conflict: bool = False,
) -> PresentationPolicy:
    """Política de presentación del caso. Determinista y sin LLM."""
    concepts = asked_concepts(question or "")
    multi = len(concepts) >= 2
    enumerations = count_enumerations(evidence_text)
    needs_list = enumerations >= LIST_THRESHOLD

    missing = [str(item) for item in missing_information if str(item)]
    open_inference = [str(item) for item in unresolved if str(item)]
    show_limits = bool(missing or open_inference or source_conflict)
    if source_conflict:
        limits_reason = "source_conflict"
    elif missing:
        limits_reason = "missing_information"
    elif open_inference:
        limits_reason = "inference_unresolved"
    else:
        limits_reason = ""

    titulos = " ".join(str(title) for title in evidence_titles if title)
    secondary = _secondary_labels(evidence_text or titulos, concepts)
    secondary_count = len(secondary) or (1 if omitted_count and titulos else 0)

    # Encabezados: los que el caso pida. Cada concepto suma uno; una lista de
    # valores suma otro; el detalle profundo suma uno más. Sin tope fijo.
    headings = 1
    if multi:
        headings = min(4, 1 + len(concepts))
    elif detail in {DETAIL_DETAILED, DETAIL_DEEP}:
        headings = 2
    if needs_list:
        headings += 1
    if detail == DETAIL_DEEP:
        headings += 1
    if detail == DETAIL_BRIEF:
        headings = 1
    headings = max(1, min(6, headings))

    layers: list[str] = [LAYER_ANSWER]
    if detail != DETAIL_BRIEF:
        # La capa de conceptos entra cuando hay varios conceptos o cuando el
        # detalle pedido justifica ubicarlos por separado.
        if multi or detail in {DETAIL_DETAILED, DETAIL_DEEP}:
            layers.append(LAYER_CONCEPTS)
        if needs_list or detail in {DETAIL_DETAILED, DETAIL_DEEP}:
            layers.append(LAYER_DETAIL)
        layers.append(LAYER_PRACTICAL)
    if show_limits:
        layers.append(LAYER_LIMITS)

    return PresentationPolicy(
        concepts=concepts,
        multi_concept=multi,
        layers=tuple(layers),
        headings_budget=headings,
        needs_list=needs_list,
        enumeration_count=enumerations,
        content_selected=max(0, int(selected_count or 0)),
        content_omitted=max(0, int(omitted_count or 0)),
        secondary_count=secondary_count,
        secondary_labels=secondary,
        show_limitations=show_limits,
        limitations_reason=limits_reason,
        followup_allowed=bool(secondary_count or int(omitted_count or 0)),
        detail=detail,
    )


def render_presentation_block(policy: PresentationPolicy) -> str:
    """Instrucción de ritmo para el generador. Forma, nunca hechos."""
    conceptos = ", ".join(policy.concepts) if policy.concepts else ""
    lines: list[str] = ["## RITMO DE LA RESPUESTA (legibilidad, no contenido)"]
    lines.append(
        "- escribí como una explicación humana bien editada: ni un formulario de "
        "secciones rotuladas ni un bloque continuo de texto"
    )
    lines.append(
        "- una idea por párrafo: si un párrafo mezcla dos ideas, partilo; "
        "evitá los párrafos de más de cuatro o cinco líneas"
    )
    if LAYER_ANSWER in policy.layers:
        lines.append(
            "capa 1 — respuesta: empezá con la respuesta en una o dos frases, "
            "sin preámbulo"
        )
    if LAYER_CONCEPTS in policy.layers:
        if policy.multi_concept and conceptos:
            lines.append(
                f"capa 2 — conceptos: la pregunta nombra varios conceptos ({conceptos}); "
                "cada concepto con su propio encabezado corto (título natural, dos a "
                "cinco palabras) en lugar de mezclarlos en un mismo párrafo"
            )
        else:
            lines.append(
                "capa 2 — concepto: después de la respuesta, el qué y el para qué; "
                "un encabezado corto sólo si ayuda a ubicarse"
            )
    if LAYER_DETAIL in policy.layers:
        if policy.needs_list:
            lines.append(
                f"capa 3 — detalle: la evidencia enumera {policy.enumeration_count} "
                "valores u opciones; usá viñetas o tabla, un ítem por valor con su "
                "significado en la misma línea (negrita en el número o el nombre, no "
                "en la explicación). No los encadenes en una sola frase"
            )
        else:
            lines.append(
                "capa 3 — detalle: sólo el detalle que la pregunta pide; si aparece "
                "una enumeración de tres o más elementos, usá viñetas o tabla"
            )
    if LAYER_PRACTICAL in policy.layers:
        lines.append(
            "capa 4 — práctica: cerrá con qué implica en la práctica o un ejemplo "
            "mínimo, sólo si la evidencia lo sostiene"
        )
    if LAYER_LIMITS in policy.layers:
        lines.append(
            "capa 5 — límites: declarales en una frase al final, sin sección propia"
        )
    else:
        lines.append(
            "no agregues una sección de límites ni advertencias: la respuesta está "
            "respaldada y completa; si algo no está en la evidencia, ya lo dice la "
            "regla de grounding"
        )
    if policy.content_omitted > 0:
        lines.append(
            f"- relevancia: de {policy.content_selected + policy.content_omitted} "
            f"fragmentos recuperados, para ESTA pregunta alcanzan "
            f"{policy.content_selected}; no expliques el material secundario "
            "(notas al pie, registros auxiliares, permutaciones, apéndices) salvo "
            "que el usuario lo pida"
        )
    else:
        lines.append(
            "- relevancia: contá sólo lo que la pregunta pide; que un dato sea "
            "correcto no significa que deba aparecer"
        )
    lines.append(
        f"- encabezados: hasta {policy.headings_budget} si aportan navegación; "
        "títulos naturales tomados del contenido, nunca rótulos internos"
    )
    lines.append(
        "- no conviertas una lista de valores u opciones en jerarquía, ranking ni "
        "orden de prioridad: si la fuente no lo dice, no existe"
    )
    lines.append(
        "- no escribas una sección «Fuentes» ni «Referencias» al final: citá en la "
        "línea ([Doc: N]) junto a la afirmación que sostiene; la interfaz ya muestra "
        "las fuentes"
    )
    if policy.followup_allowed:
        lines.append(
            "- si el contenido ofrece una continuación natural (por ejemplo, el "
            "detalle de algunos valores o una comparación), ofrecé una continuación "
            "concreta en una frase. Es opcional: si no hay nada útil que ofrecer, no "
            "la escribas, y nunca cierres con una pregunta de cortesía"
        )
    return "\n".join(lines)


def refresh_contract_presentation(
    contract: ResponseContract | None,
    policy: PresentationPolicy,
) -> ResponseContract | None:
    """Devuelve el contrato con la política enriquecida (misma forma y detalle).

    El contrato se compone antes del retrieval; cuando llega la evidencia, la
    política gana enumeraciones, material secundario y conteos. Nada más cambia:
    blueprint, detalle, tono y reglas de grounding se conservan.
    """
    if contract is None:
        return None
    sections = tuple(
        section
        for section in contract.sections
        if section != SECTION_LIMITATIONS or policy.show_limitations
    )
    if policy.show_limitations and SECTION_LIMITATIONS not in sections:
        sections = (*sections, SECTION_LIMITATIONS)
    if policy.needs_list and SECTION_KEY_VALUES not in sections:
        orden: list[str] = []
        for section in sections:
            orden.append(section)
            if section == SECTION_DIRECT_ANSWER and SECTION_KEY_VALUES not in orden:
                orden.append(SECTION_KEY_VALUES)
        if SECTION_KEY_VALUES not in orden:
            orden.append(SECTION_KEY_VALUES)
        sections = tuple(orden)
    return replace(
        contract,
        sections=sections,
        layers=policy.layers,
        presentation=policy.to_public_dict(),
        show_limitations=policy.show_limitations,
    )


def presentation_from_selection(
    *,
    question: str,
    detail: str = DETAIL_NORMAL,
    selected_items: Sequence[Any] = (),
    registry_items: Sequence[Any] = (),
    missing_information: Iterable[str] = (),
    unresolved: Iterable[str] = (),
    source_conflict: bool = False,
) -> PresentationPolicy:
    """Política a partir de la evidencia seleccionada del run.

    `registry_items` es la evidencia completa del run (puede ser mayor): la
    diferencia con lo seleccionado es lo que queda disponible sin volcarse.
    """
    textos: list[str] = []
    etiquetas: list[str] = []
    for item in list(selected_items) + list(registry_items):
        content = str(getattr(item, "content", "") or "")
        if content:
            textos.append(content)
        label = str(getattr(item, "label", "") or getattr(item, "title", "") or "")
        if label:
            etiquetas.append(label)
    return build_presentation_policy(
        question=question,
        detail=detail,
        evidence_text="\n".join(textos),
        evidence_titles=tuple(dict.fromkeys(etiquetas)),
        selected_count=len(list(selected_items)),
        omitted_count=max(len(list(registry_items)) - len(list(selected_items)), 0),
        missing_information=missing_information,
        unresolved=unresolved,
        source_conflict=source_conflict,
    )


def presentation_facts(policy: Mapping[str, Any] | None) -> dict[str, Any]:
    """Lectura defensiva de la política publicada en el flujo."""
    if not isinstance(policy, Mapping):
        return {}
    return {str(key): value for key, value in policy.items()}


__all__ = [
    "LAYER_ANSWER",
    "LAYER_CONCEPTS",
    "LAYER_DETAIL",
    "LAYER_LIMITS",
    "LAYER_PRACTICAL",
    "LIST_THRESHOLD",
    "PresentationPolicy",
    "build_presentation_policy",
    "count_enumerations",
    "presentation_facts",
    "presentation_from_selection",
    "refresh_contract_presentation",
    "render_presentation_block",
]
