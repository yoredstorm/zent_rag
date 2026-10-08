# =============================================================================
# Decision Evidence Resolver — hidrata refs del DecisionEnvelope
# =============================================================================
# En fast path no hubo retrieval principal: el envelope puede tener
# `evidence_refs` y el registry estar vacío. Este resolver hace LOOKUP por
# id/provenance (chunk_id, point id, document_id, source_id) contra el store
# canónico; NUNCA un segundo retrieval semántico.
#
# - Respeta el AuthorizedKnowledgeScope: evidencia fuera de scope no se hidrata.
# - Marca cada item como `decision_evidence` (main retrieval != decision evidence).
# - Las refs que no resuelven quedan explícitas en `unresolved` (jamás se
#   inventa contenido).
# =============================================================================
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

DECISION_EVIDENCE_VERSION = "decision-evidence-1"
MAX_REFS = 32

_IDENTITY_KEYS = (
    "source_id",
    "document_id",
    "chunk_id",
    "workspace_id",
    "knowledge_base_id",
    "external_id",
    "content_hash",
    "filename",
    "title",
    "parser_version",
    "canonical_version",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _payload(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    to_public = getattr(value, "to_public_dict", None)
    if callable(to_public):
        try:
            payload = to_public()
            return dict(payload) if isinstance(payload, Mapping) else {}
        except Exception:  # noqa: BLE001 — la observabilidad nunca rompe
            return {}
    return {}


@dataclass(kw_only=True)
class DecisionEvidenceResolution:
    items: list[Any] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    resolved_basis: dict[str, str] = field(default_factory=dict)
    out_of_scope: list[str] = field(default_factory=list)
    version: str = DECISION_EVIDENCE_VERSION

    @property
    def resolved_count(self) -> int:
        return len(self.items)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "resolved": self.resolved_count,
            "unresolved": list(self.unresolved[:12]),
            "out_of_scope": list(self.out_of_scope[:8]),
            "basis": dict(list(self.resolved_basis.items())[:12]),
        }


class DecisionEvidenceResolver:
    """Lookup determinista de refs de decisión contra el store canónico."""

    def __init__(
        self,
        *,
        organization_id: Any,
        scope: Any = None,
        vector_store: Any = None,
        role: str = "admin",
        user_id: Any = None,
        groups: Sequence[str] = (),
    ) -> None:
        self._organization_id = organization_id
        self._scope = scope
        self._store = vector_store
        self._role = str(role or "admin")
        self._user_id = user_id
        self._groups = [str(group) for group in groups or ()]
        self.last_errors: list[str] = []

    def _get_store(self) -> Any:
        if self._store is not None:
            return self._store
        try:
            from src.runtime import dependencies as deps_module

            self._store = deps_module.get_vector_store()
        except Exception as exc:  # noqa: BLE001 — sin store se declara unresolved
            self.last_errors.append(f"vector_store_unavailable:{type(exc).__name__}")
            self._store = None
        return self._store

    def _scope_allows(self, metadata: Mapping[str, Any]) -> bool:
        scope = self._scope
        if scope is None or not bool(getattr(scope, "is_explicit", False)):
            return True
        source = _text(metadata.get("source_id"))
        document = _text(metadata.get("document_id"))
        allowed_source = (
            scope.allows_source(source) if hasattr(scope, "allows_source") else None
        )
        if allowed_source is False:
            return False
        allowed_document = (
            scope.allows_document(document)
            if hasattr(scope, "allows_document")
            else None
        )
        if allowed_document is False:
            return False
        return True

    def _item_from_chunk(self, ref: str, chunk: Any) -> Any | None:
        from src.core.domain.adaptive import EvidenceItem

        metadata = getattr(chunk, "metadata", None)
        metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
        content = str(getattr(chunk, "content", "") or "")
        if not content.strip():
            return None
        if not self._scope_allows(metadata):
            return None
        section_path = metadata.get("section_path") or metadata.get("heading_path") or ()
        if isinstance(section_path, str):
            section_path = (section_path,)
        if not isinstance(section_path, (list, tuple)):
            section_path = ()
        page = metadata.get("page_start") or metadata.get("page")
        if not isinstance(page, int):
            page = None
        title = _text(metadata.get("title") or metadata.get("filename")) or None
        identity = {
            key: metadata[key]
            for key in _IDENTITY_KEYS
            if metadata.get(key) not in (None, "", [], {})
        }
        return EvidenceItem(
            source_type="decision_ref",
            content=content,
            source_id=_text(metadata.get("source_id")) or None,
            document_id=_text(metadata.get("document_id")) or None,
            chunk_id=_text(metadata.get("chunk_id")) or ref,
            title=title,
            page=page,
            section_path=tuple(str(part) for part in section_path if str(part).strip()),
            retrieval_method="decision_lookup",
            authority="decision",
            evidence_id=ref,
            metadata={**identity, "decision_evidence": True},
        )

    async def resolve(self, refs: Sequence[Any]) -> DecisionEvidenceResolution:
        """Resuelve refs por chunk_id → point id → document_id/source_id."""
        wanted: list[str] = []
        for value in refs or ():
            text = _text(value)
            if text and text not in wanted:
                wanted.append(text)
        wanted = wanted[:MAX_REFS]
        resolution = DecisionEvidenceResolution()
        if not wanted:
            return resolution
        store = self._get_store()
        if store is None:
            resolution.unresolved = list(wanted)
            return resolution

        found: dict[str, Any] = {}

        async def _try(call: Any, basis: str) -> None:
            remaining = [ref for ref in wanted if ref not in found]
            if not remaining:
                return
            try:
                context = await call(remaining)
            except Exception as exc:  # noqa: BLE001 — lookup fail-soft
                self.last_errors.append(f"{basis}:{type(exc).__name__}")
                return
            chunks = list(getattr(context, "chunks", None) or [])
            if not chunks:
                return
            for chunk in chunks:
                metadata = getattr(chunk, "metadata", None)
                metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
                keys = [
                    _text(metadata.get("chunk_id")),
                    _text(getattr(chunk, "document_id", "")),
                    _text(metadata.get("document_id")),
                    _text(metadata.get("source_id")),
                ]
                for key in keys:
                    if key and key in wanted and key not in found:
                        item = self._item_from_chunk(key, chunk)
                        if item is None:
                            if not self._scope_allows(metadata):
                                resolution.out_of_scope.append(key)
                            continue
                        found[key] = item
                        resolution.resolved_basis[key] = basis

        # 1) chunk_id (las refs de regla suelen ser chunk ids).
        by_chunk = getattr(store, "get_documents_by_chunk_ids", None)
        if callable(by_chunk):
            await _try(
                lambda ids: by_chunk(
                    self._organization_id,
                    ids,
                    role=self._role,
                    user_id=self._user_id,
                    groups=self._groups,
                ),
                "chunk_id",
            )
        # 2) point id (documento/índice Qdrant).
        by_point = getattr(store, "get_documents", None)
        if callable(by_point):
            await _try(
                lambda ids: by_point(
                    self._organization_id,
                    [value for value in ids if _looks_uuid(value)],
                    role=self._role,
                    user_id=self._user_id,
                    groups=self._groups,
                ),
                "point_id",
            )
        # 3) metadata document/source (lookup scoped, no semántico).
        by_meta = getattr(store, "get_documents_by_metadata", None)
        if callable(by_meta):
            remaining = [ref for ref in wanted if ref not in found]
            if remaining:
                for kwargs in (
                    {"document_ids": remaining},
                    {"source_ids": remaining},
                ):
                    await _try(
                        lambda ids, _kwargs=kwargs: by_meta(
                            self._organization_id,
                            limit=2,
                            role=self._role,
                            user_id=self._user_id,
                            groups=self._groups,
                            **_kwargs,
                        ),
                        "metadata",
                    )
                    if all(ref in found for ref in remaining):
                        break

        for ref in wanted:
            item = found.get(ref)
            if item is not None:
                resolution.items.append(item)
            elif ref not in resolution.out_of_scope:
                resolution.unresolved.append(ref)
        return resolution


def _looks_uuid(value: str) -> bool:
    try:
        from uuid import UUID

        UUID(str(value))
        return True
    except (TypeError, ValueError):
        return False


__all__ = [
    "DECISION_EVIDENCE_VERSION",
    "DecisionEvidenceResolution",
    "DecisionEvidenceResolver",
]
