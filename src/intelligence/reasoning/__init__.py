# =============================================================================
# Evidence Reasoning — razonamiento sobre hechos (extiende Intelligence)
# =============================================================================
# No es un segundo Cognitive OS: reutiliza AnalyticalReasoningEngine como
# estrategia, CompanyContextCompiler como fuente de contexto empresarial y
# CompanyAskService para las formas de grafo.
#
# Entrada:  UNDERSTAND -> COMPILE CONTEXT -> PLAN WHAT MUST BE PROVEN
# Salida:   escenario -> timeline -> transiciones -> hipótesis -> inferencias
#           -> gate de completitud -> blueprint
# =============================================================================
from src.intelligence.reasoning.assessment import (
    AnalysisCompletionGate,
    HypothesisEngine,
    InferenceVerifier,
)
from src.intelligence.reasoning.classifier import (
    ReasoningClassifier,
    atomic_questions,
    deterministic_shape,
    has_raw_scenario,
    shape_from_atomic_answers,
)
from src.intelligence.reasoning.coordinator import (
    SHAPE_COMPLETION,
    SHAPE_OPERATIONS,
    AnalyticalStrategy,
    EvidenceReasoningEngine,
    GraphReasoningStrategy,
    ReasoningStrategy,
    question_to_prove,
)
from src.intelligence.reasoning.scenario import (
    ResolvedSchema,
    ScenarioParser,
    ScenarioSchemaResolver,
    schema_from_facts,
)
from src.intelligence.reasoning.sequence import (
    StateTransitionAnalyzer,
    TimelineBuilder,
    chain_values,
    find_sequence_gaps,
)

__all__ = [
    "AnalysisCompletionGate",
    "AnalyticalStrategy",
    "EvidenceReasoningEngine",
    "GraphReasoningStrategy",
    "HypothesisEngine",
    "InferenceVerifier",
    "ReasoningClassifier",
    "ReasoningStrategy",
    "ResolvedSchema",
    "SHAPE_COMPLETION",
    "SHAPE_OPERATIONS",
    "ScenarioParser",
    "ScenarioSchemaResolver",
    "StateTransitionAnalyzer",
    "TimelineBuilder",
    "atomic_questions",
    "chain_values",
    "deterministic_shape",
    "find_sequence_gaps",
    "has_raw_scenario",
    "question_to_prove",
    "schema_from_facts",
    "shape_from_atomic_answers",
]
