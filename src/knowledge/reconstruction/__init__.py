# =============================================================================
# Knowledge OS — Semantic Reconstruction Layer
# =============================================================================
# SOURCE -> SOURCE ADAPTER -> RAW EXTRACTION -> SEMANTIC RECONSTRUCTION
#        -> SEMANTIC INTERMEDIATE REPRESENTATION -> QUALITY GATE
#        -> KNOWLEDGE COMPILER -> CANONICAL KNOWLEDGE
#
# El parser responde "¿qué encontré técnicamente?". Esta capa responde "¿qué
# estaba intentando representar la fuente?". No es un parche de PDF: es
# infraestructura universal y extensible de todo Knowledge OS.
# =============================================================================
from __future__ import annotations

from .adapters import (
    SourceAdapter,
    adapter_for,
    detect_source_kind,
    get_adapter,
    register_adapter,
    register_default_adapters,
    registered_kinds,
)
from .continuity import evaluate_pair, reconstruct_sequence, source_tokens
from .contracts import (
    KNOWLEDGE_STATUSES,
    NON_KNOWLEDGE_STATUSES,
    SCHEMA_VERSION,
    ConfidenceSignals,
    Continuation,
    ContinuityKind,
    ElementKind,
    FragmentKind,
    RawElement,
    RawExtraction,
    RawTable,
    ReconstructionStatus,
    SemanticField,
    SemanticRecord,
    SemanticRepresentation,
    SemanticTable,
    SemanticUnitIR,
    SourceKind,
    SourceProvenance,
    StructuralNode,
)
from .engine import (
    ReconstructionDraft,
    ReconstructionOutcome,
    apply_semantic_reconstruction,
    build_draft,
    ensure_reconstruction,
    finalize_draft,
    reconstruct_document,
    reconstruction_quality_issues,
    semantic_reconstruction_payload,
)
from .escalation import escalate_reconstruction
from .fragments import FragmentVerdict, evaluate_fragment, vocabulary_for
from .llm import (
    LLMDecision,
    LLMReconstructionProvider,
    ReconstructionModelProvider,
    ReconstructionUsage,
)
from .quality_gate import (
    GateDecision,
    TableGateDecision,
    gate_element,
    gate_table,
    quality_score,
)
from .report import live_learning_messages, observe_reconstruction, tech_view, tech_view_from_metadata

__all__ = [
    "KNOWLEDGE_STATUSES",
    "NON_KNOWLEDGE_STATUSES",
    "SCHEMA_VERSION",
    "ConfidenceSignals",
    "Continuation",
    "ContinuityKind",
    "ElementKind",
    "FragmentKind",
    "FragmentVerdict",
    "GateDecision",
    "LLMDecision",
    "LLMReconstructionProvider",
    "RawElement",
    "RawExtraction",
    "RawTable",
    "ReconstructionDraft",
    "ReconstructionModelProvider",
    "ReconstructionOutcome",
    "ReconstructionStatus",
    "ReconstructionUsage",
    "SemanticField",
    "SemanticRecord",
    "SemanticRepresentation",
    "SemanticTable",
    "SemanticUnitIR",
    "SourceAdapter",
    "SourceKind",
    "SourceProvenance",
    "StructuralNode",
    "TableGateDecision",
    "adapter_for",
    "apply_semantic_reconstruction",
    "build_draft",
    "detect_source_kind",
    "ensure_reconstruction",
    "escalate_reconstruction",
    "evaluate_fragment",
    "evaluate_pair",
    "finalize_draft",
    "gate_element",
    "gate_table",
    "get_adapter",
    "live_learning_messages",
    "observe_reconstruction",
    "quality_score",
    "reconstruct_document",
    "reconstruct_sequence",
    "reconstruction_quality_issues",
    "register_adapter",
    "register_default_adapters",
    "registered_kinds",
    "semantic_reconstruction_payload",
    "source_tokens",
    "tech_view",
    "tech_view_from_metadata",
    "vocabulary_for",
]
