# =============================================================================
# Embeddings — multi-representación + late chunking (Fase 10)
# =============================================================================
from __future__ import annotations

from .late_chunking import (
    LATE_CHUNKING_MODES,
    LATE_CHUNKING_VERSION,
    LateChunkingBatch,
    can_late_chunk,
    configured_late_chunking_models,
    embed_late_chunking_batches,
    late_chunking_mode,
    plan_late_chunking_batches,
)
from .registry import EmbeddingCapability, resolve_embedding_capability
from .representations import (
    REPRESENTATION_MODES,
    EmbeddingRepresentation,
    EmbeddingTextPlanner,
)

__all__ = [
    "LATE_CHUNKING_MODES",
    "LATE_CHUNKING_VERSION",
    "REPRESENTATION_MODES",
    "EmbeddingCapability",
    "EmbeddingRepresentation",
    "EmbeddingTextPlanner",
    "LateChunkingBatch",
    "can_late_chunk",
    "configured_late_chunking_models",
    "embed_late_chunking_batches",
    "late_chunking_mode",
    "plan_late_chunking_batches",
    "resolve_embedding_capability",
]
