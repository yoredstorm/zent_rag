# =============================================================================
# Semantic Rule Compiler — Document Rule Understanding
# =============================================================================
# Responsabilidad diferenciada de Semantic Reconstruction:
#
#   Semantic Reconstruction  -> problemas ESTRUCTURALES (fragmentos, tablas,
#                               headers, continuación).
#   Semantic Rule Compiler   -> SEMÁNTICA NORMATIVA: reglas, definiciones,
#                               restricciones, excepciones, fórmulas, con
#                               verificación y provenance por propiedad.
#
# El LLM puede PROPONER; nunca establece semántica en silencio.
# =============================================================================
from .candidates import (
    MAX_CANDIDATES,
    RuleContextItem,
    build_candidates,
    context_items_from_generic,
    context_items_from_units,
)
from .compiler import SemanticRuleCompiler
from .evaluate import (
    EVALUATION_VERSION,
    RequirementState,
    RuleCheck,
    RuleEvaluation,
    RuleEvaluationStatus,
    RuleRequirement,
    evaluate_rule,
    evaluate_rules,
    rule_premises,
)
from .fabric import FABRIC_RULE_PROJECTION_VERSION, project_rules_to_fabric
from .language import StatementAnalysis, analyze_statement, classify_statement_kind, detect_formula
from .merge import merge_distributed_rules, merge_rule_pair, rules_compatible
from .model import (
    EVIDENCE_ID_PREFIX,
    RULE_COMPILER_VERSION,
    CandidateRule,
    CanonicalRule,
    RuleArgument,
    RuleCompilation,
    RuleConflict,
    RuleEnumerationSpec,
    RuleEvidence,
    RuleFormulaSpec,
    RuleProperty,
    RuleScope,
    RuleTemporalSpec,
    stable_id,
)
from .pattern_bridge import pattern_semantics_from_rule
from .verify import detect_rule_conflicts, recompute_execution, verify_candidate

__all__ = [
    "CandidateRule",
    "CanonicalRule",
    "EVALUATION_VERSION",
    "EVIDENCE_ID_PREFIX",
    "FABRIC_RULE_PROJECTION_VERSION",
    "MAX_CANDIDATES",
    "RULE_COMPILER_VERSION",
    "RequirementState",
    "RuleArgument",
    "RuleCheck",
    "RuleCompilation",
    "RuleConflict",
    "RuleContextItem",
    "RuleEnumerationSpec",
    "RuleEvaluation",
    "RuleEvaluationStatus",
    "RuleEvidence",
    "RuleFormulaSpec",
    "RuleProperty",
    "RuleRequirement",
    "RuleScope",
    "RuleTemporalSpec",
    "SemanticRuleCompiler",
    "StatementAnalysis",
    "analyze_statement",
    "build_candidates",
    "classify_statement_kind",
    "context_items_from_generic",
    "context_items_from_units",
    "detect_formula",
    "detect_rule_conflicts",
    "evaluate_rule",
    "evaluate_rules",
    "merge_distributed_rules",
    "merge_rule_pair",
    "pattern_semantics_from_rule",
    "project_rules_to_fabric",
    "recompute_execution",
    "rule_premises",
    "rules_compatible",
    "stable_id",
    "verify_candidate",
]
