# =============================================================================
# Roles de anchor — EVIDENCE OF RULE vs INPUT TO APPLY THE RULE
# =============================================================================
# El error conceptual que esto corrige: exigir que la documentación contenga
# el valor concreto del usuario («la documentación no menciona QNNF0SME»).
# La documentación debe explicar la REGLA y el CAMPO; el valor de ejemplo se
# evalúa APLICANDO la regla, no buscándolo en el PDF.
#
# Roles:
#   RULE_ANCHOR    máscara/rango/patrón posicional: DEBE estar documentado.
#   FIELD_ANCHOR   nombre de campo/sigla: DEBE estar documentado.
#   REFERENCE      identificador citado (tabla, record): DEBE estar documentado.
#   ENTITY         entidad contextual («record 2», «byte 105»): documentada.
#   EXAMPLE_VALUE  valor del usuario («QNNF0SME»): NO exige match en fuentes;
#                  es la entrada sobre la que se aplica la regla documentada.
#
# La clasificación es genérica (forma + pistas de pregunta). Un provider de
# dominio puede fijar `Anchor.role` y `Anchor.semantic_hint` y manda.
# =============================================================================
from __future__ import annotations

import dataclasses
import re
from enum import StrEnum

from src.intelligence.response.anchors import Anchor


class AnchorRole(StrEnum):
    RULE_ANCHOR = "rule_anchor"
    FIELD_ANCHOR = "field_anchor"
    EXAMPLE_VALUE = "example_value"
    ENTITY = "entity"
    REFERENCE = "reference"


#: Roles que exigen aparecer en la documentación para considerar la evidencia
#: completa. EXAMPLE_VALUE está deliberadamente afuera.
DOCUMENTABLE_ROLES: frozenset[str] = frozenset(
    {
        AnchorRole.RULE_ANCHOR.value,
        AnchorRole.FIELD_ANCHOR.value,
        AnchorRole.REFERENCE.value,
        AnchorRole.ENTITY.value,
    }
)

#: «role» declarado por un plugin: vocabulario laxo, se normaliza.
_PROVIDER_ROLES: dict[str, str] = {
    "rule": AnchorRole.RULE_ANCHOR.value,
    "rule_anchor": AnchorRole.RULE_ANCHOR.value,
    "mask": AnchorRole.RULE_ANCHOR.value,
    "mascara": AnchorRole.RULE_ANCHOR.value,
    "pattern": AnchorRole.RULE_ANCHOR.value,
    "patron": AnchorRole.RULE_ANCHOR.value,
    "range": AnchorRole.RULE_ANCHOR.value,
    "rango": AnchorRole.RULE_ANCHOR.value,
    "field": AnchorRole.FIELD_ANCHOR.value,
    "field_anchor": AnchorRole.FIELD_ANCHOR.value,
    "campo": AnchorRole.FIELD_ANCHOR.value,
    "example": AnchorRole.EXAMPLE_VALUE.value,
    "example_value": AnchorRole.EXAMPLE_VALUE.value,
    "value": AnchorRole.EXAMPLE_VALUE.value,
    "valor": AnchorRole.EXAMPLE_VALUE.value,
    "input": AnchorRole.EXAMPLE_VALUE.value,
    "entity": AnchorRole.ENTITY.value,
    "entidad": AnchorRole.ENTITY.value,
    "reference": AnchorRole.REFERENCE.value,
    "referencia": AnchorRole.REFERENCE.value,
    "code": AnchorRole.REFERENCE.value,
    "codigo": AnchorRole.REFERENCE.value,
    "identifier": AnchorRole.REFERENCE.value,
    "identificador": AnchorRole.REFERENCE.value,
}

#: La pregunta evalúa/aplica una regla a un valor («¿acepta X?», «¿cumple?»).
_EVALUATION_CUE_RE = re.compile(
    r"\b(acepta|aceptar[aá]?|aceptar[ií]a|admite|admitir[aá]?|"
    r"cumple|cumplir[aá]?|cumplir[ií]a|"
    r"v[aá]lid[oa]|valid|validar|"
    r"coincide|coincidir[aá]?|matchea|matchear|match(?:es|ea)?|"
    r"aplica|aplicar[aá]?|corresponde|equivale|"
    r"interpreta|quiero decir|quiere decir|significa|"
    r"does|will|would|should|is it)\b",
    re.IGNORECASE,
)

_KIND_ROLES: dict[str, str] = {
    "mascara": AnchorRole.RULE_ANCHOR.value,
    "rango": AnchorRole.RULE_ANCHOR.value,
    "sigla": AnchorRole.FIELD_ANCHOR.value,
    "codigo": AnchorRole.REFERENCE.value,
}


def normalize_role(role: str) -> str:
    value = str(role or "").strip().lower().replace(" ", "_")
    return _PROVIDER_ROLES.get(value, "")


def role_for_kind(anchor: Anchor) -> str:
    """Rol por forma, sin mirar la pregunta (fallback estable)."""
    provider = normalize_role(getattr(anchor, "role", "") or "")
    if provider:
        return provider
    return _KIND_ROLES.get(str(getattr(anchor, "kind", "")), "")


def is_documentable(role: str) -> bool:
    return role in DOCUMENTABLE_ROLES


def has_evaluation_cue(query: str) -> bool:
    return bool(_EVALUATION_CUE_RE.search(query or ""))


def classify_role(
    anchor: Anchor,
    *,
    query: str = "",
    has_rule_or_field: bool = False,
) -> str:
    """Rol del anchor: provider manda; si no, forma + pistas de la pregunta.

    Un código mixto (letras+dígitos) en una pregunta de evaluación («¿acepta?»,
    «¿cumple?») junto a una regla o campo es el VALOR DEL USUARIO; sin esas
    señales es una REFERENCIA que sí debe estar documentada.
    """
    provider = normalize_role(getattr(anchor, "role", "") or "")
    if provider:
        return provider
    kind = str(getattr(anchor, "kind", ""))
    if kind in ("mascara", "rango"):
        return AnchorRole.RULE_ANCHOR.value
    if kind == "sigla":
        return AnchorRole.FIELD_ANCHOR.value
    if kind == "codigo":
        if has_rule_or_field and has_evaluation_cue(query):
            return AnchorRole.EXAMPLE_VALUE.value
        return AnchorRole.REFERENCE.value
    return AnchorRole.REFERENCE.value


def assign_roles(query: str, anchors: list[Anchor] | tuple[Anchor, ...]) -> list[Anchor]:
    """Devuelve los anchors con `role` completado, sin duplicar valores."""
    anchors = list(anchors or ())
    has_rule_or_field = any(
        role_for_kind(anchor)
        in (AnchorRole.RULE_ANCHOR.value, AnchorRole.FIELD_ANCHOR.value)
        for anchor in anchors
    )
    result: list[Anchor] = []
    for anchor in anchors:
        role = classify_role(
            anchor, query=query, has_rule_or_field=has_rule_or_field
        )
        result.append(anchor if anchor.role == role else dataclasses.replace(anchor, role=role))
    return result


__all__ = [
    "AnchorRole",
    "DOCUMENTABLE_ROLES",
    "assign_roles",
    "classify_role",
    "has_evaluation_cue",
    "is_documentable",
    "normalize_role",
    "role_for_kind",
]
