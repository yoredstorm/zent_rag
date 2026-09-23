# =============================================================================
# Response blueprints — la forma de explicar, no el contenido (§3, §10-§16).
# =============================================================================
# Un blueprint declara: para qué sirve, qué secciones usa, qué formato permite y
# cuándo conviene un ejemplo. Es un catálogo EXTENSIBLE: se agregan blueprints
# sin tocar el selector ni el contrato.
#
# El backend entrega el id (`technical_explanation`) y las secciones semánticas;
# el frontend traduce a lenguaje humano.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from src.core.domain.response import (
    DETAIL_DEEP,
    DETAIL_DETAILED,
    DETAIL_NORMAL,
    SECTION_CAUSE,
    SECTION_COMPARISON,
    SECTION_DATA_READING,
    SECTION_DEFINITION,
    SECTION_DIRECT_ANSWER,
    SECTION_DISCARDED_ALTERNATIVE,
    SECTION_EVIDENCE,
    SECTION_EXAMPLE,
    SECTION_LIMITATIONS,
    SECTION_MEANING,
    SECTION_PRACTICAL_EFFECT,
    SECTION_SEQUENCE,
    SECTION_STEPS,
    SECTION_SUMMARY,
    SECTION_USES,
    SECTION_WHAT_TO_CHECK,
    SECTION_WHERE_IT_APPLIES,
    SECTION_WHY,
)

DIRECT_FACT = "direct_fact"
DEFINITION_EXPLANATION = "definition_explanation"
TECHNICAL_EXPLANATION = "technical_explanation"
SCENARIO_ANALYSIS = "scenario_analysis"
DIAGNOSTIC = "diagnostic"
COMPARISON = "comparison"
PROCEDURE = "procedure"
DATA_INTERPRETATION = "data_interpretation"
EXECUTIVE_SUMMARY = "executive_summary"
TUTORIAL = "tutorial"


@dataclass(frozen=True, kw_only=True)
class Blueprint:
    """Forma de explicación. Inmutable y descriptiva."""

    id: str
    label: str
    purpose: str
    sections: tuple[str, ...]
    detail: str = DETAIL_NORMAL
    formatting: dict[str, bool] = field(default_factory=dict)
    evidence: dict[str, bool] = field(default_factory=dict)
    example_when: str = ""
    table_when: str = ""
    version: int = 1

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "label": self.label,
            "purpose": self.purpose,
            "sections": list(self.sections),
            "detail": self.detail,
            "formatting": dict(self.formatting),
            "evidence": dict(self.evidence),
            "version": self.version,
        }
        if self.example_when:
            payload["example_when"] = self.example_when
        if self.table_when:
            payload["table_when"] = self.table_when
        return payload


_FORMATTING_BASE = {
    "headings": True,
    "bold_key_concepts": True,
    "bullets": True,
    "numbered_steps": False,
    "table": False,
    "short_quotes": False,
}

_EVIDENCE_BASE = {
    "citations_required": True,
    "disclose_conflicts": True,
    "disclose_missing_information": True,
    "separate_fact_from_inference": True,
}


def _formatting(**overrides: bool) -> dict[str, bool]:
    return {**_FORMATTING_BASE, **overrides}


def _evidence(**overrides: bool) -> dict[str, bool]:
    return {**_EVIDENCE_BASE, **overrides}


BLUEPRINTS: dict[str, Blueprint] = {
    DIRECT_FACT: Blueprint(
        id=DIRECT_FACT,
        label="Dato directo",
        purpose="Responder un dato puntual sin rodeos.",
        sections=(SECTION_DIRECT_ANSWER,),
        formatting=_formatting(headings=False, bullets=False),
        evidence=_evidence(citations_required=False),
    ),
    DEFINITION_EXPLANATION: Blueprint(
        id=DEFINITION_EXPLANATION,
        label="Definición explicada",
        purpose="Definir un concepto y ubicarlo.",
        sections=(SECTION_DEFINITION, SECTION_USES, SECTION_WHERE_IT_APPLIES),
        detail=DETAIL_NORMAL,
        example_when="cuando un caso concreto aclara el concepto",
    ),
    TECHNICAL_EXPLANATION: Blueprint(
        id=TECHNICAL_EXPLANATION,
        label="Explicación técnica",
        purpose="Explicar qué significa un campo, valor o mecanismo y qué implica.",
        sections=(
            SECTION_DIRECT_ANSWER,
            SECTION_MEANING,
            SECTION_PRACTICAL_EFFECT,
            SECTION_EXAMPLE,
            SECTION_LIMITATIONS,
        ),
        detail=DETAIL_DETAILED,
        formatting=_formatting(table=True),
        example_when="cuando una tabla o un caso mínimo hacen visible la regla",
        table_when="cuando hay componentes o valores comparables",
    ),
    SCENARIO_ANALYSIS: Blueprint(
        id=SCENARIO_ANALYSIS,
        label="Análisis de escenario",
        purpose="Concluir sobre una secuencia de registros o eventos.",
        sections=(
            SECTION_DIRECT_ANSWER,
            SECTION_SEQUENCE,
            SECTION_WHY,
            SECTION_DISCARDED_ALTERNATIVE,
            SECTION_WHAT_TO_CHECK,
            SECTION_EVIDENCE,
        ),
        detail=DETAIL_DETAILED,
        formatting=_formatting(numbered_steps=True),
    ),
    DIAGNOSTIC: Blueprint(
        id=DIAGNOSTIC,
        label="Diagnóstico",
        purpose="Explicar por qué ocurrió algo, con la evidencia que lo sostiene.",
        sections=(
            SECTION_CAUSE,
            SECTION_EVIDENCE,
            SECTION_SEQUENCE,
            SECTION_WHAT_TO_CHECK,
            SECTION_LIMITATIONS,
        ),
        detail=DETAIL_DETAILED,
        evidence=_evidence(separate_fact_from_inference=True),
    ),
    COMPARISON: Blueprint(
        id=COMPARISON,
        label="Comparación",
        purpose="Contrastar opciones sobre los mismos criterios.",
        sections=(SECTION_COMPARISON, SECTION_PRACTICAL_EFFECT, SECTION_EVIDENCE),
        detail=DETAIL_NORMAL,
        formatting=_formatting(table=True, bullets=False),
        table_when="cuando hay dos o más atributos comparables",
    ),
    PROCEDURE: Blueprint(
        id=PROCEDURE,
        label="Procedimiento",
        purpose="Indicar cómo hacer algo, paso a paso.",
        sections=(SECTION_STEPS, SECTION_WHAT_TO_CHECK, SECTION_LIMITATIONS),
        detail=DETAIL_DETAILED,
        formatting=_formatting(numbered_steps=True, table=False),
    ),
    DATA_INTERPRETATION: Blueprint(
        id=DATA_INTERPRETATION,
        label="Lectura de datos",
        purpose="Leer un conjunto de datos y decir qué muestra.",
        sections=(SECTION_DIRECT_ANSWER, SECTION_DATA_READING, SECTION_PRACTICAL_EFFECT),
        detail=DETAIL_NORMAL,
        formatting=_formatting(table=True),
    ),
    EXECUTIVE_SUMMARY: Blueprint(
        id=EXECUTIVE_SUMMARY,
        label="Resumen ejecutivo",
        purpose="Dar la conclusión y su impacto, sin detalle técnico.",
        sections=(SECTION_SUMMARY, SECTION_PRACTICAL_EFFECT, SECTION_LIMITATIONS),
        detail=DETAIL_NORMAL,
        formatting=_formatting(headings=True, bullets=True),
        evidence=_evidence(citations_required=False),
    ),
    TUTORIAL: Blueprint(
        id=TUTORIAL,
        label="Tutorial",
        purpose="Enseñar un tema desde los fundamentos, con ejemplos.",
        sections=(
            SECTION_DIRECT_ANSWER,
            SECTION_MEANING,
            SECTION_EXAMPLE,
            SECTION_STEPS,
            SECTION_WHERE_IT_APPLIES,
        ),
        detail=DETAIL_DEEP,
        formatting=_formatting(numbered_steps=True, table=True),
        example_when="siempre que un ejemplo haga avanzar la comprensión",
    ),
}

#: Orden estable para prompts y UI.
BLUEPRINT_ORDER: tuple[str, ...] = tuple(BLUEPRINTS)


def register_blueprint(blueprint: Blueprint) -> Blueprint:
    """Extiende el catálogo sin tocar el selector ni el contrato (§3)."""
    BLUEPRINTS[blueprint.id] = blueprint
    return blueprint


def get_blueprint(blueprint_id: str | None) -> Blueprint:
    """Blueprint por id, con `technical_explanation` como forma por defecto."""
    if blueprint_id and blueprint_id in BLUEPRINTS:
        return BLUEPRINTS[blueprint_id]
    return BLUEPRINTS[TECHNICAL_EXPLANATION]


def blueprint_ids() -> tuple[str, ...]:
    return tuple(BLUEPRINTS)


def public_blueprints() -> list[dict[str, Any]]:
    """Catálogo público: orden estable para los conocidos, extensible después."""
    ordered = [key for key in BLUEPRINT_ORDER if key in BLUEPRINTS]
    ordered.extend(key for key in BLUEPRINTS if key not in ordered)
    return [BLUEPRINTS[key].to_public_dict() for key in ordered]


def describe_blueprints() -> dict[str, str]:
    """Criterios para el Choice de JEV: id → cuándo elegirlo."""
    return {blueprint.id: blueprint.purpose for blueprint in BLUEPRINTS.values()}


def with_section(blueprint_id: str, section: str) -> Blueprint:
    """Copia con una sección extra (el contrato agrega, no reescribe)."""
    blueprint = get_blueprint(blueprint_id)
    if section in blueprint.sections:
        return blueprint
    return replace(blueprint, sections=(*blueprint.sections, section))


__all__ = [
    "BLUEPRINTS",
    "BLUEPRINT_ORDER",
    "Blueprint",
    "COMPARISON",
    "DATA_INTERPRETATION",
    "DEFINITION_EXPLANATION",
    "DIAGNOSTIC",
    "DIRECT_FACT",
    "EXECUTIVE_SUMMARY",
    "PROCEDURE",
    "SCENARIO_ANALYSIS",
    "TECHNICAL_EXPLANATION",
    "TUTORIAL",
    "blueprint_ids",
    "describe_blueprints",
    "get_blueprint",
    "public_blueprints",
    "register_blueprint",
    "with_section",
]
