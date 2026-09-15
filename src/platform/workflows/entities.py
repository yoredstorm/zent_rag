# =============================================================================
# Workflow Entities — referencias de entidad con identidad canónica existente
# (Cognitive Workflows, cierre D5).
#
# No crea un registro paralelo: intenta resolver la entidad contra el catálogo
# canónico (CanonicalKnowledgeRepository, kind=ENTITY). Si no existe, la ref
# queda label-only (sin inventar IDs). Sin I/O fuera de ese repositorio.
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import UUID

from src.core.domain.canonical import CanonicalKind, entity_natural_key

# Tipos de negocio aceptados; el natural key usa `kind` como entity_type para
# mantener estabilidad por tipo (customer ≠ supplier con el mismo nombre).
ENTITY_KINDS: tuple[str, ...] = (
    "customer",
    "supplier",
    "product",
    "contract",
    "policy",
    "invoice",
    "organization",
    "person",
    "entity",
    "concept",
)


def _canonical_repo() -> Any:
    """Getter con soporte de `app.dependency_overrides` (tests/DI)."""
    from src.api.deps import get_canonical_repo

    try:
        from src.api.main import app

        override = app.dependency_overrides.get(get_canonical_repo)
        if override is not None:
            return override()
    except Exception:  # noqa: BLE001 — fuera de FastAPI se usa el getter real
        pass
    return get_canonical_repo()


def entity_ref(
    *,
    kind: str,
    label: str,
    canonical_id: str | None = None,
    entity_id: str | None = None,
    source_node_id: str | None = None,
    confidence: float | None = None,
    resolution: str = "label_only",
) -> dict[str, Any]:
    """Ref de entidad JSON-safe; `resolution` documenta cómo se obtuvo."""
    ref: dict[str, Any] = {
        "kind": str(kind or "entity")[:40],
        "label": str(label or "").strip()[:200],
        "resolution": resolution,
    }
    if canonical_id:
        ref["canonical_id"] = str(canonical_id)
    if entity_id:
        ref["entity_id"] = str(entity_id)
    if source_node_id:
        ref["source_node_id"] = str(source_node_id)
    if confidence is not None:
        ref["confidence"] = round(float(confidence), 3)
    return ref


async def resolve_entity_ref(
    organization_id: UUID,
    *,
    kind: str,
    label: str,
    entity_id: str | None = None,
    source_node_id: str | None = None,
    confidence: float | None = None,
) -> dict[str, Any] | None:
    """Resuelve la entidad contra el catálogo canónico si existe.

    - Encontrada: `resolution="canonical"` + `canonical_id`.
    - No encontrada o error: `resolution="label_only"` (nunca inventa IDs).
    - Label vacío: None.
    """
    clean_label = str(label or "").strip()
    if not clean_label:
        return None
    clean_kind = str(kind or "entity").strip().lower() or "entity"
    base = entity_ref(
        kind=clean_kind,
        label=clean_label,
        entity_id=entity_id,
        source_node_id=source_node_id,
        confidence=confidence,
    )
    try:
        canonical = await _canonical_repo().get_by_natural_key(
            organization_id,
            CanonicalKind.ENTITY,
            entity_natural_key(clean_label, clean_kind),
        )
    except Exception:  # noqa: BLE001 — catálogo no disponible: label-only
        return base
    if canonical is None:
        return base
    return entity_ref(
        kind=clean_kind,
        label=clean_label,
        canonical_id=str(getattr(canonical, "canonical_id", "") or "") or None,
        entity_id=entity_id,
        source_node_id=source_node_id,
        confidence=confidence,
        resolution="canonical",
    )


__all__ = ["ENTITY_KINDS", "entity_ref", "resolve_entity_ref"]
