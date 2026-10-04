# =============================================================================
# Knowledge OS — Dependency / Invalidation Graph
# =============================================================================
# Un único lugar responde: si cambió X, ¿qué artefactos quedan stale y qué
# acciones corresponden? Nada de repartir `if version != ...` por el repo.
#
#   SOURCE
#     -> PARSED_STRUCTURE
#       -> RECONSTRUCTION
#         -> ENRICHMENT
#           -> RETRIEVAL_REPRESENTATION
#             -> EMBEDDING
#               -> RETRIEVAL_ACCEPTANCE
#   COMPILATION (depende de ENRICHMENT/reconstruction; su cambio NO invalida
#                vectores: solo metadata/payload)
#
# Acciones: reparse | reconstruct | reenrich | recompile | reindex |
#           refresh_payload | reevaluate. Ninguna es destructiva por sí sola.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ArtifactKind(StrEnum):
    SOURCE = "SOURCE"
    PARSED_STRUCTURE = "PARSED_STRUCTURE"
    RECONSTRUCTION = "RECONSTRUCTION"
    ENRICHMENT = "ENRICHMENT"
    COMPILATION = "COMPILATION"
    RETRIEVAL_REPRESENTATION = "RETRIEVAL_REPRESENTATION"
    EMBEDDING = "EMBEDDING"
    RETRIEVAL_ACCEPTANCE = "RETRIEVAL_ACCEPTANCE"


# Grafo explícito: cada artefacto declara de qué depende.
_DEPENDENCIES: dict[ArtifactKind, tuple[ArtifactKind, ...]] = {
    ArtifactKind.SOURCE: (),
    ArtifactKind.PARSED_STRUCTURE: (ArtifactKind.SOURCE,),
    ArtifactKind.RECONSTRUCTION: (ArtifactKind.PARSED_STRUCTURE,),
    ArtifactKind.ENRICHMENT: (ArtifactKind.RECONSTRUCTION,),
    ArtifactKind.COMPILATION: (ArtifactKind.ENRICHMENT,),
    # La representación de retrieval se compone de enrichment; el conocimiento
    # compilado entra como metadata/PASS 2 (refresh_payload), NO re-embebe.
    ArtifactKind.RETRIEVAL_REPRESENTATION: (ArtifactKind.ENRICHMENT,),
    ArtifactKind.EMBEDDING: (ArtifactKind.RETRIEVAL_REPRESENTATION,),
    ArtifactKind.RETRIEVAL_ACCEPTANCE: (ArtifactKind.EMBEDDING,),
}

# Acciones por artefacto cambiado (no incluye las de sus dependientes).
_ACTIONS: dict[ArtifactKind, tuple[str, ...]] = {
    ArtifactKind.SOURCE: ("reparse",),
    ArtifactKind.PARSED_STRUCTURE: ("reparse",),
    ArtifactKind.RECONSTRUCTION: ("reconstruct",),
    ArtifactKind.ENRICHMENT: ("reenrich",),
    ArtifactKind.COMPILATION: ("recompile", "refresh_payload"),
    ArtifactKind.RETRIEVAL_REPRESENTATION: ("reindex",),
    ArtifactKind.EMBEDDING: ("reindex",),
    ArtifactKind.RETRIEVAL_ACCEPTANCE: ("reevaluate",),
}

#: Razón del fingerprint -> artefacto que cambió.
REASON_TO_ARTIFACT: dict[str, ArtifactKind] = {
    "content_changed": ArtifactKind.SOURCE,
    "parser_changed": ArtifactKind.PARSED_STRUCTURE,
    "reconstruction_changed": ArtifactKind.RECONSTRUCTION,
    "understanding_changed": ArtifactKind.RECONSTRUCTION,
    "enrichment_version_changed": ArtifactKind.ENRICHMENT,
    "chunking_changed": ArtifactKind.RETRIEVAL_REPRESENTATION,
    "contextualization_changed": ArtifactKind.RETRIEVAL_REPRESENTATION,
    "retrieval_representation_changed": ArtifactKind.RETRIEVAL_REPRESENTATION,
    "embedding_model_changed": ArtifactKind.EMBEDDING,
    "embedding_dimension_changed": ArtifactKind.EMBEDDING,
    "sparse_changed": ArtifactKind.EMBEDDING,
    "parent_representation_changed": ArtifactKind.RETRIEVAL_REPRESENTATION,
    "compiler_changed": ArtifactKind.COMPILATION,
    "missing_index": ArtifactKind.EMBEDDING,
    "manual": ArtifactKind.RETRIEVAL_REPRESENTATION,
    "nutrition_action": ArtifactKind.RETRIEVAL_REPRESENTATION,
    "representation_changed": ArtifactKind.RETRIEVAL_REPRESENTATION,
}


@dataclass(frozen=True, kw_only=True)
class InvalidationPlan:
    """Qué quedó stale y qué hacer. Orden: upstream a downstream."""

    changed: ArtifactKind
    stale: tuple[ArtifactKind, ...] = ()
    actions: tuple[str, ...] = ()
    requires_reembedding: bool = False
    requires_reparse: bool = False
    notes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "changed": self.changed.value,
            "stale": [kind.value for kind in self.stale],
            "actions": list(self.actions),
            "requires_reembedding": self.requires_reembedding,
            "requires_reparse": self.requires_reparse,
            "notes": dict(self.notes),
        }


def downstream_of(kind: ArtifactKind | str) -> tuple[ArtifactKind, ...]:
    """Dependientes transitivos en orden topológico (sin incluir `kind`)."""
    changed = ArtifactKind(kind)
    stale: list[ArtifactKind] = []
    frontier = [changed]
    while frontier:
        current = frontier.pop(0)
        for candidate, deps in _DEPENDENCIES.items():
            if candidate in stale or candidate is changed:
                continue
            if current in deps and candidate not in stale:
                stale.append(candidate)
                frontier.append(candidate)
    return tuple(stale)


def invalidation_plan(changed: ArtifactKind | str) -> InvalidationPlan:
    """Plan completo: stale transitivo + acciones deduplicadas en orden."""
    kind = ArtifactKind(changed)
    stale = downstream_of(kind)
    actions: list[str] = []
    for artifact in (kind, *stale):
        for action in _ACTIONS.get(artifact, ()):
            if action not in actions:
                actions.append(action)
    return InvalidationPlan(
        changed=kind,
        stale=stale,
        actions=tuple(actions),
        requires_reembedding=ArtifactKind.EMBEDDING in (kind, *stale),
        requires_reparse=ArtifactKind.PARSED_STRUCTURE in (kind, *stale),
        notes={"dependencies": {k.value: [d.value for d in v] for k, v in _DEPENDENCIES.items()}},
    )


def plan_for_reason(reason: str | None) -> InvalidationPlan | None:
    """Traduce una razón del fingerprint a un plan (None si no aplica)."""
    if not reason or reason == "unchanged":
        return None
    artifact = REASON_TO_ARTIFACT.get(reason)
    if artifact is None:
        return None
    return invalidation_plan(artifact)
