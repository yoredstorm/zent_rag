# =============================================================================
# Roles de anchor — EVIDENCE OF RULE vs INPUT TO APPLY THE RULE
# =============================================================================
# El error conceptual que esto corrige: exigir que la documentación contenga
# el valor concreto del usuario («la documentación no menciona QNNF0SME»).
# La documentación debe explicar la REGLA y el CAMPO; el valor de ejemplo se
# evalúa APLICANDO la regla, no buscándolo en el PDF.
#
# Roles (compatibilidad):
#   RULE_ANCHOR      máscara/rango/patrón posicional: DEBE estar documentado.
#   FIELD_ANCHOR     nombre de campo/sigla: DEBE estar documentado.
#   REFERENCE        identificador citado (tabla, record): DEBE estar documentado.
#   ENTITY           entidad contextual («record 2», «byte 105»): documentada.
#   EXAMPLE_VALUE    valor del usuario («QNNF0SME»): NO exige match en fuentes;
#                    es la entrada sobre la que se aplica la regla documentada.
#
# Roles nuevos (QuerySemanticRole → AnchorRole, sin romper lo anterior):
#   RUNTIME_PATTERN  instancia de patrón que LLEGA en runtime («me viene &&&F»):
#                    la instancia no exige match literal; su gramática sí.
#   RUNTIME_VALUE    valor de runtime que no es ejemplo ni patrón.
#   OPTIONAL_CONTEXT contexto auxiliar («record 2» citado de pasada).
#
# La clasificación es contextual (forma + posición + cue words + intención):
# un sigla como `FCLAS` es FIELD_ANCHOR y `ASDFGRE` es EXAMPLE_VALUE en
# contextos distintos aunque compartan la misma silueta. Un provider de dominio
# puede fijar `Anchor.role` y `Anchor.semantic_hint` y manda.
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
    #: Instancia de patrón aportada en runtime (gramática documentada aparte).
    RUNTIME_PATTERN = "runtime_pattern"
    #: Valor de runtime sin semántica de ejemplo ni de patrón.
    RUNTIME_VALUE = "runtime_value"
    #: Contexto auxiliar que no exige match para responder.
    OPTIONAL_CONTEXT = "optional_context"


#: Roles que exigen aparecer en la documentación para considerar la evidencia
#: completa. EXAMPLE_VALUE está deliberadamente afuera (y también los roles de
#: runtime: su semántica se exige aparte, no su literalidad).
DOCUMENTABLE_ROLES: frozenset[str] = frozenset(
    {
        AnchorRole.RULE_ANCHOR.value,
        AnchorRole.FIELD_ANCHOR.value,
        AnchorRole.REFERENCE.value,
        AnchorRole.ENTITY.value,
    }
)

#: Roles de escenario: jamás cuentan como evidencia documental faltante.
RUNTIME_ROLES: frozenset[str] = frozenset(
    {
        AnchorRole.EXAMPLE_VALUE.value,
        AnchorRole.RUNTIME_PATTERN.value,
        AnchorRole.RUNTIME_VALUE.value,
        AnchorRole.OPTIONAL_CONTEXT.value,
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
    "user_input": AnchorRole.EXAMPLE_VALUE.value,
    "runtime_value": AnchorRole.RUNTIME_VALUE.value,
    "runtime_pattern": AnchorRole.RUNTIME_PATTERN.value,
    "pattern_instance": AnchorRole.RUNTIME_PATTERN.value,
    "optional": AnchorRole.OPTIONAL_CONTEXT.value,
    "optional_context": AnchorRole.OPTIONAL_CONTEXT.value,
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

#: QuerySemanticRole → AnchorRole (compatibilidad con todos los consumidores).
_SEMANTIC_TO_ANCHOR: dict[str, str] = {
    "SOURCE_REQUIREMENT": AnchorRole.REFERENCE.value,
    "RULE_REQUIREMENT": AnchorRole.RULE_ANCHOR.value,
    "FIELD_REQUIREMENT": AnchorRole.FIELD_ANCHOR.value,
    "DEFINITION_REQUIREMENT": AnchorRole.REFERENCE.value,
    "REFERENCE": AnchorRole.REFERENCE.value,
    "DOMAIN_ENTITY": AnchorRole.ENTITY.value,
    "USER_INPUT": AnchorRole.EXAMPLE_VALUE.value,
    "USER_EXAMPLE": AnchorRole.EXAMPLE_VALUE.value,
    "RUNTIME_VALUE": AnchorRole.RUNTIME_VALUE.value,
    "RUNTIME_PATTERN": AnchorRole.RUNTIME_PATTERN.value,
    "RUNTIME_PARAMETER": AnchorRole.RUNTIME_VALUE.value,
    "OPTIONAL_CONTEXT": AnchorRole.OPTIONAL_CONTEXT.value,
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


def is_runtime_role(role: str) -> bool:
    return role in RUNTIME_ROLES


def has_evaluation_cue(query: str) -> bool:
    return bool(_EVALUATION_CUE_RE.search(query or ""))


def semantic_role_to_anchor_role(semantic_role: str, anchor: Anchor) -> str:
    """Traduce el rol semántico nuevo al vocabulario de anchor existente."""
    role = str(semantic_role or "")
    if role == "DEFINITION_REQUIREMENT":
        kind = str(getattr(anchor, "kind", ""))
        if kind == "sigla":
            return AnchorRole.FIELD_ANCHOR.value
        return AnchorRole.REFERENCE.value
    return _SEMANTIC_TO_ANCHOR.get(role, "")


def _legacy_classify(anchor: Anchor, *, query: str, has_rule_or_field: bool) -> str:
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


def classify_role(
    anchor: Anchor,
    *,
    query: str = "",
    has_rule_or_field: bool = False,
) -> str:
    """Rol del anchor: provider manda; después clasificador contextual; después
    la heurística histórica por forma.

    La FORMA es una feature, no la autoridad: `ASDFGRE` puede ser EXAMPLE_VALUE
    («mi farebasis ASDFGRE») o REFERENCE («¿dónde aparece ASDFGRE?»).
    """
    provider = normalize_role(getattr(anchor, "role", "") or "")
    if provider:
        return provider
    try:
        from src.intelligence.query_semantics import classify_query_semantics

        semantics = classify_query_semantics(query or "", [anchor])
        objects = semantics.objects
        if objects:
            mapped = semantic_role_to_anchor_role(objects[0].semantic_role, anchor)
            if mapped:
                return mapped
    except Exception:  # noqa: BLE001 — la clasificación nunca rompe el retrieval
        pass
    return _legacy_classify(anchor, query=query, has_rule_or_field=has_rule_or_field)


def assign_roles(query: str, anchors: list[Anchor] | tuple[Anchor, ...]) -> list[Anchor]:
    """Devuelve los anchors con `role` completado, sin duplicar valores.

    Usa el clasificador contextual UNA vez para todos los anchors (el contexto
    de la oración decide). Fail-soft a la heurística histórica.
    """
    anchors = list(anchors or ())
    if not anchors:
        return []
    result: list[Anchor] = []
    try:
        from src.intelligence.query_semantics import classify_query_semantics

        semantics = classify_query_semantics(query or "", anchors)
        semantic_by_value = {
            str(obj.value).strip().lower(): obj.semantic_role
            for obj in semantics.objects
        }
    except Exception:  # noqa: BLE001
        semantic_by_value = {}
    has_rule_or_field = any(
        role_for_kind(anchor)
        in (AnchorRole.RULE_ANCHOR.value, AnchorRole.FIELD_ANCHOR.value)
        for anchor in anchors
    )
    for anchor in anchors:
        provider = normalize_role(getattr(anchor, "role", "") or "")
        if provider:
            role = provider
        else:
            semantic = semantic_by_value.get(str(anchor.value or "").strip().lower(), "")
            role = semantic_role_to_anchor_role(semantic, anchor) if semantic else ""
            if not role:
                role = classify_role(
                    anchor, query=query, has_rule_or_field=has_rule_or_field
                )
        result.append(anchor if anchor.role == role else dataclasses.replace(anchor, role=role))
    return result


__all__ = [
    "AnchorRole",
    "DOCUMENTABLE_ROLES",
    "RUNTIME_ROLES",
    "assign_roles",
    "classify_role",
    "has_evaluation_cue",
    "is_documentable",
    "is_runtime_role",
    "normalize_role",
    "role_for_kind",
    "semantic_role_to_anchor_role",
]
