# =============================================================================
# Progressive Semantic Ingestion — paquete (Fases 1-3)
# =============================================================================
# Manifiesto de cobertura por fuente + planner de ventanas semánticas soft +
# comprensión local por ventana + SemanticState con carry-forward selectivo.
# No reemplaza chunks ni compiler: alimenta la capa de significado.
# =============================================================================
from __future__ import annotations

from .contracts import (
    COVERAGE_WEIGHTS,
    SEMANTIC_INGESTION_VERSION,
    SEMANTIC_STATE_VERSION,
    STAGE_FLAGS,
    STATE_SELECTOR_VERSION,
    WINDOW_ITEM_KINDS,
    WINDOW_PLAN_VERSION,
    WINDOW_RESULT_STATUSES,
    WINDOW_UNDERSTANDING_VERSION,
    IngestionStage,
    SemanticState,
    SemanticStateSlice,
    SemanticWindowPlan,
    SemanticWindowResult,
    SemanticWindowSpec,
    SourceIngestionManifest,
    StageStatus,
    WindowItem,
    manifest_with,
    set_stage,
    window_result_from_dict,
)
from .extract import extract_window_items
from .fabric import (
    FABRIC_EDGE_TYPES,
    FABRIC_NODE_TYPES,
    FABRIC_VERSION,
    IDENTITY_STATUSES,
    FabricEdge,
    FabricNode,
    FabricProjection,
    FabricRetrievalContext,
    IdentityCandidate,
    SemanticFabricBuilder,
    build_retrieval_context,
    projection_fingerprint,
)
from .global_model import (
    GLOBAL_MODEL_VERSION,
    GlobalModelBuilder,
    GlobalSemanticModel,
)
from .llm import LLMWindowProvider, WindowLLMResult, WindowUnderstandingProvider
from .planner import SemanticWindowPlanner, WindowBudget, indexable_blocks
from .processor import SemanticWindowProcessor, WindowProcessingOutcome
from .regional import (
    REGIONAL_VERSION,
    RegionalModelBuilder,
    RegionalSemanticModel,
)
from .selector import SemanticStateSelector
from .service import SemanticIngestionService, raw_fingerprint, semantic_versions
from .state import StateCaps, build_state
from .stitcher import (
    STITCH_RELATION_TYPES,
    STITCH_VERSION,
    SemanticStitcher,
    StitchedUnit,
    StitchOutcome,
    StitchRelation,
    stitch_fingerprint,
)
from .store import PostgresSemanticIngestionStore
from .threads import (
    OPENABLE_TYPES,
    THREAD_VERSION,
    SemanticThread,
    ThreadStats,
    ThreadStatus,
    ThreadType,
    advance_threads,
    cap_open_threads,
    open_threads_from_result,
    rollback_threads,
)

__all__ = [
    "COVERAGE_WEIGHTS",
    "DEPENDENCY_TYPES",
    "FABRIC_EDGE_TYPES",
    "FABRIC_NODE_TYPES",
    "FABRIC_VERSION",
    "FabricEdge",
    "FabricNode",
    "FabricProjection",
    "FabricRetrievalContext",
    "GLOBAL_MODEL_VERSION",
    "GlobalModelBuilder",
    "GlobalSemanticModel",
    "IDENTITY_STATUSES",
    "IdentityCandidate",
    "SEMANTIC_INGESTION_VERSION",
    "SEMANTIC_STATE_VERSION",
    "STAGE_FLAGS",
    "STATE_SELECTOR_VERSION",
    "STITCH_RELATION_TYPES",
    "STITCH_VERSION",
    "SemanticFabricBuilder",
    "THREAD_VERSION",
    "WINDOW_ITEM_KINDS",
    "WINDOW_PLAN_VERSION",
    "WINDOW_RESULT_STATUSES",
    "WINDOW_UNDERSTANDING_VERSION",
    "IngestionStage",
    "LLMWindowProvider",
    "OPENABLE_TYPES",
    "PostgresSemanticIngestionStore",
    "REGIONAL_VERSION",
    "RegionalModelBuilder",
    "RegionalSemanticModel",
    "SemanticIngestionService",
    "SemanticState",
    "SemanticStateSelector",
    "SemanticStateSlice",
    "SemanticStitcher",
    "SemanticThread",
    "SemanticWindowPlan",
    "SemanticWindowPlanner",
    "SemanticWindowProcessor",
    "SemanticWindowResult",
    "SemanticWindowSpec",
    "SourceIngestionManifest",
    "StageStatus",
    "StateCaps",
    "StitchOutcome",
    "StitchRelation",
    "StitchedUnit",
    "ThreadStats",
    "ThreadStatus",
    "ThreadType",
    "WindowBudget",
    "WindowItem",
    "WindowLLMResult",
    "WindowProcessingOutcome",
    "WindowUnderstandingProvider",
    "advance_threads",
    "build_state",
    "build_retrieval_context",
    "cap_open_threads",
    "extract_window_items",
    "indexable_blocks",
    "manifest_with",
    "open_threads_from_result",
    "projection_fingerprint",
    "raw_fingerprint",
    "rollback_threads",
    "semantic_versions",
    "set_stage",
    "stitch_fingerprint",
    "window_result_from_dict",
]
