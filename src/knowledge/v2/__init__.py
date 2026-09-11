# =============================================================================
# Knowledge V2 — Phase A re-exports (not wired into the ingestion engine)
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
