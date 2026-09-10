# =============================================================================
# Knowledge Learning Engine — capa de aprendizaje explícito (FASE 33)
# =============================================================================
# CONNECTION -> DISCOVERY -> PROFILING -> SEMANTIC ANALYSIS -> RELATIONSHIPS
# -> VALIDATION -> INDEXING -> EVALUATION -> READINESS
#
# Reutiliza: CatalogStore, Discovery Engine, SemanticInference,
# RelationshipDetector, IntelligenceStore, jobs durables, RBAC y realtime.
# =============================================================================
from src.platform.knowledge_learning.business_analyzer import BusinessAnalyzer
from src.platform.knowledge_learning.evaluation import (
    KnowledgeEvaluationService,
    generate_synthetic_questions,
)
from src.platform.knowledge_learning.events import (
    KnowledgeEventEmitter,
    knowledge_event_source,
)
from src.platform.knowledge_learning.knowledge_graph import KnowledgeGraphService
from src.platform.knowledge_learning.knowledge_score import KnowledgeScoreService
from src.platform.knowledge_learning.llm_analyzer import (
    LLMAnalyzer,
    LLMTableAnalysis,
    parse_llm_analysis,
    sanitize_llm_context,
)
from src.platform.knowledge_learning.question_generator import QuestionGenerator
from src.platform.knowledge_learning.relationship_analyzer import (
    RelationshipAnalyzer,
    RelationshipHypothesis,
)
from src.platform.knowledge_learning.repository import (
    ActiveRunExistsError,
    PostgresKnowledgeLearningRepository,
)
from src.platform.knowledge_learning.schema_analyzer import (
    SchemaAnalysis,
    SchemaAnalyzer,
    table_fingerprint,
)
from src.platform.knowledge_learning.validation_engine import (
    KnowledgeValidationEngine,
    QuestionAlreadyResolvedError,
)

__all__ = [
    "ActiveRunExistsError",
    "BusinessAnalyzer",
    "KnowledgeEvaluationService",
    "KnowledgeEventEmitter",
    "KnowledgeGraphService",
    "KnowledgeScoreService",
    "KnowledgeValidationEngine",
    "LLMAnalyzer",
    "LLMTableAnalysis",
    "PostgresKnowledgeLearningRepository",
    "QuestionAlreadyResolvedError",
    "QuestionGenerator",
    "RelationshipAnalyzer",
    "RelationshipHypothesis",
    "SchemaAnalysis",
    "SchemaAnalyzer",
    "generate_synthetic_questions",
    "knowledge_event_source",
    "parse_llm_analysis",
    "sanitize_llm_context",
    "table_fingerprint",
]
