# =============================================================================
# Knowledge V2 — domain types + Phase B parse API (not wired into the engine)
# =============================================================================
from src.core.domain.knowledge_v2 import (
    KnowledgeCorpus,
    KnowledgeObjectStatus,
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
    inferred_is_not_approved,
)

__all__ = [
    "KnowledgeCorpus",
    "KnowledgeObjectStatus",
    "StructuredBlock",
    "StructuredBlockKind",
    "StructuredDocument",
    "inferred_is_not_approved",
]
