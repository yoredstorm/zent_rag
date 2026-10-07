# =============================================================================
# Authorized knowledge scope — el scope REAL del agente, no el de los chunks
# =============================================================================
# El fast path puede correr antes del retrieval principal: derivar el scope de
# `evidence_items` (vacío) dejaba a Rule Lane / Premise Closure buscando en toda
# la organización. Este módulo define el scope autorizado explícito desde la
# configuración del agente y verifica la provenance de reglas y evidencia.
#
# Reglas:
# - El scope NUNCA se amplía: intersección de la configuración autorizada.
# - Sin scope explícito (agente sin fuentes/KB/workspace), el fast path NO es
#   elegible: no se decide sobre un universo no declarado.
# - Una regla fuera de scope se EXCLUYE con razón auditable (OUT_OF_SCOPE_RULE).
# - Una regla ensamblada con provenance de dos documentos/fuentes distintas se
#   excluye salvo operación cross-source explícita (MIXED_SOURCES).
# =============================================================================
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

AUTHORIZED_SCOPE_VERSION = "authorized-scope-1"

IN_SCOPE = "IN_SCOPE"
OUT_OF_SCOPE = "OUT_OF_SCOPE"
SCOPE_UNVERIFIED = "SCOPE_UNVERIFIED"
MIXED_SOURCES = "MIXED_SOURCES"

OUT_OF_SCOPE_RULE = "OUT_OF_SCOPE_RULE"
RULE_PROVENANCE_UNVERIFIED = "RULE_PROVENANCE_UNVERIFIED"
MIXED_SOURCE_RULE = "MIXED_SOURCE_RULE"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _texts(value: Any) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        return (_text(value),) if _text(value) else ()
    if not isinstance(value, Sequence):
        return ()
    return tuple(
        text for item in value if (text := _text(item))
    )


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _payload(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    for method_name in ("to_public_dict", "to_dict"):
        method = getattr(value, method_name, None)
        if not callable(method):
            continue
        try:
            payload = method()
            return dict(payload) if isinstance(payload, Mapping) else {}
        except Exception:  # noqa: BLE001 — la observabilidad nunca rompe
            return {}
    return {}


@dataclass(frozen=True, kw_only=True)
class AuthorizedKnowledgeScope:
    """Alcance autorizado del agente. Inmutable y explícito."""

    organization_id: str = ""
    workspace_id: str = ""
    knowledge_base_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    role: str = "admin"
    user_id: str = ""
    groups: tuple[str, ...] = ()
    version: str = AUTHORIZED_SCOPE_VERSION

    @property
    def is_explicit(self) -> bool:
        """True sólo si el agente declaró fuentes/KB/workspace."""
        return bool(self.source_ids or self.knowledge_base_ids or self.workspace_id)

    def allows_source(self, value: Any) -> bool | None:
        """True/False si el scope lo decide; None si no hay dato que juzgar."""
        text = _text(value)
        if not text:
            return None
        if not self.is_explicit:
            return None
        if self.source_ids:
            return text in self.source_ids
        return None

    def allows_document(self, value: Any) -> bool | None:
        text = _text(value)
        if not text or not self.is_explicit:
            return None
        if self.document_ids:
            return text in self.document_ids
        return None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "organization_id": self.organization_id or None,
            "workspace_id": self.workspace_id or None,
            "knowledge_base_ids": list(self.knowledge_base_ids[:12]),
            "source_ids": list(self.source_ids[:24]),
            "document_ids": list(self.document_ids[:24]),
            "is_explicit": self.is_explicit,
            "role": self.role or None,
        }


def scope_from_agent_config(
    *,
    organization_id: Any,
    agent_config: Mapping[str, Any] | None = None,
    org_config: Mapping[str, Any] | None = None,
    role: str = "admin",
    user_id: Any = None,
    groups: Sequence[str] = (),
) -> AuthorizedKnowledgeScope:
    """Construye el scope autorizado desde la configuración REAL del agente.

    `org_config` es el scope ya angostado por el runtime (agente ∩ legacy); si
    está presente manda sobre la config cruda. No inventa ids ni amplía nada.
    """
    agent = dict(agent_config or {})
    org = dict(org_config or {})
    knowledge_scope = agent.get("knowledge_scope")
    knowledge_scope = (
        dict(knowledge_scope) if isinstance(knowledge_scope, Mapping) else {}
    )
    workspace_ids = _texts(org.get("knowledge_workspace_ids"))
    if not workspace_ids:
        workspace_ids = _texts(knowledge_scope.get("workspace_ids"))
    if not workspace_ids:
        workspace_ids = _texts(knowledge_scope.get("workspace_id"))
    source_ids = _texts(org.get("source_ids")) or _texts(agent.get("source_ids"))
    if not source_ids:
        source_ids = _texts(knowledge_scope.get("source_ids"))
    kb_ids = _texts(org.get("knowledge_base_ids")) or _texts(
        agent.get("knowledge_base_ids")
    )
    if not kb_ids:
        kb_ids = _texts(knowledge_scope.get("knowledge_base_ids"))
    document_ids = _texts(org.get("document_ids")) or _texts(
        agent.get("document_ids")
    )
    return AuthorizedKnowledgeScope(
        organization_id=_text(organization_id),
        workspace_id=workspace_ids[0] if workspace_ids else "",
        knowledge_base_ids=_unique(kb_ids),
        source_ids=_unique(source_ids),
        document_ids=_unique(document_ids),
        role=_text(role) or "admin",
        user_id=_text(user_id),
        groups=_unique([_text(group) for group in groups or () if _text(group)]),
    )


def rule_provenance(rule: Any) -> dict[str, Any]:
    """Provenance de una CanonicalRule: documentos, fuentes, páginas, parser.

    Sólo lee lo publicado por el compilador; no recalcula ni reinterpreta.
    """
    scope = _payload(getattr(rule, "scope", None))
    documents: list[str] = []
    sources: list[str] = []
    pages: list[int] = []
    excerpts: list[str] = []
    titles: list[str] = []
    parser_engine = ""
    parser_version = ""
    document_id = _text(scope.get("document_id"))
    if document_id:
        documents.append(document_id)
    title = _text(scope.get("document_title"))
    if title:
        titles.append(title)
    for evidence in list(getattr(rule, "provenance", ()) or ()):
        payload = _payload(evidence)
        locator = _payload(payload.get("locator"))
        doc = _text(locator.get("document_id")) or _text(payload.get("document_id"))
        source = _text(locator.get("source_id")) or _text(payload.get("source_id"))
        if doc and doc not in documents:
            documents.append(doc)
        if source and source not in sources:
            sources.append(source)
        page = locator.get("page") or locator.get("page_start")
        if isinstance(page, int) and page not in pages:
            pages.append(page)
        locator_title = _text(locator.get("document_title"))
        if locator_title and locator_title not in titles:
            titles.append(locator_title)
        excerpt = _text(payload.get("excerpt"))
        if excerpt and len(excerpts) < 4:
            excerpts.append(excerpt[:240])
        parser_engine = parser_engine or _text(
            locator.get("parser_engine") or payload.get("parser_engine")
        )
        parser_version = parser_version or _text(
            locator.get("parser_version") or payload.get("parser_version")
        )
    return {
        "rule_id": _text(getattr(rule, "rule_id", "")),
        "document_ids": tuple(documents[:8]),
        "source_ids": tuple(sources[:8]),
        "pages": tuple(sorted(pages)[:12]),
        "document_title": titles[0] if titles else "",
        "parser_engine": parser_engine,
        "parser_version": parser_version,
        "excerpts": tuple(excerpts),
        "content_hash": _text(scope.get("content_hash")) or "",
    }


def classify_rule_scope(rule: Any, scope: AuthorizedKnowledgeScope) -> str:
    """IN_SCOPE | OUT_OF_SCOPE | SCOPE_UNVERIFIED para una regla."""
    if not scope.is_explicit:
        return IN_SCOPE
    provenance = rule_provenance(rule)
    documents = provenance["document_ids"]
    sources = provenance["source_ids"]
    decisions: list[bool] = []
    for source in sources:
        allowed = scope.allows_source(source)
        if allowed is not None:
            decisions.append(allowed)
    for document in documents:
        allowed = scope.allows_document(document)
        if allowed is not None:
            decisions.append(allowed)
    if not decisions:
        return SCOPE_UNVERIFIED
    return IN_SCOPE if any(decisions) else OUT_OF_SCOPE


def filter_rules_for_scope(
    rules: Sequence[Any],
    scope: AuthorizedKnowledgeScope | None,
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Filtra reglas por scope autorizado y consistencia de provenance.

    Devuelve (reglas_kept, exclusiones). Una regla excluida SIEMPRE lleva su
    razón y su provenance: la decisión de excluir es auditable.
    """
    kept: list[Any] = []
    excluded: list[dict[str, Any]] = []
    for rule in rules or ():
        provenance = rule_provenance(rule)
        rule_id = provenance["rule_id"]
        # P0.3: provenance de dos documentos distintos = reingestas mezcladas.
        if len(provenance["document_ids"]) > 1:
            excluded.append(
                {
                    "rule_id": rule_id,
                    "reason": MIXED_SOURCE_RULE,
                    "documents": list(provenance["document_ids"]),
                }
            )
            continue
        if scope is not None and scope.is_explicit:
            classification = classify_rule_scope(rule, scope)
            if classification == OUT_OF_SCOPE:
                excluded.append(
                    {
                        "rule_id": rule_id,
                        "reason": OUT_OF_SCOPE_RULE,
                        "sources": list(provenance["source_ids"]),
                        "documents": list(provenance["document_ids"]),
                    }
                )
                continue
            if classification == SCOPE_UNVERIFIED:
                excluded.append(
                    {
                        "rule_id": rule_id,
                        "reason": RULE_PROVENANCE_UNVERIFIED,
                    }
                )
                continue
        kept.append(rule)
    return kept, excluded


def rule_is_within_scope(rule: Any, scope: AuthorizedKnowledgeScope | None) -> bool:
    if scope is None or not scope.is_explicit:
        return True
    return classify_rule_scope(rule, scope) == IN_SCOPE


__all__ = [
    "AUTHORIZED_SCOPE_VERSION",
    "AuthorizedKnowledgeScope",
    "IN_SCOPE",
    "MIXED_SOURCES",
    "MIXED_SOURCE_RULE",
    "OUT_OF_SCOPE",
    "OUT_OF_SCOPE_RULE",
    "RULE_PROVENANCE_UNVERIFIED",
    "SCOPE_UNVERIFIED",
    "classify_rule_scope",
    "filter_rules_for_scope",
    "rule_is_within_scope",
    "rule_provenance",
    "scope_from_agent_config",
]
