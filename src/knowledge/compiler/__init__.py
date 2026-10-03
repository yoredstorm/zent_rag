# =============================================================================
# Knowledge Compiler — la única puerta de entrada al conocimiento canónico
# =============================================================================
# Cualquier fuente (PDF, DOCX, TXT, Markdown, Excel, CSV, JSON, XML, base de
# datos, API, eventos) entra por `KnowledgeCompiler` y sale como:
#
#   Knowledge Objects + Facts + Relationships + Rules + Evidence + Conflicts
#
# Los documentos y los chunks siguen existiendo, pero son FUENTES e ÍNDICES.
# El conocimiento es lo que queda compilado aquí.
# =============================================================================
from __future__ import annotations

from src.knowledge.compiler.conflicts import (
    classify_conflict,
    detect_conflicts,
    is_auto_resolvable,
    values_equivalent,
)
from src.knowledge.compiler.entities import (
    EntityResolver,
    discover_entities,
    infer_entity_type,
)
from src.knowledge.compiler.extract import (
    extract_semantic_units,
    extract_tabular_units,
    extracta_for,
)
from src.knowledge.compiler.facts import (
    build_facts,
    build_relationships,
    entity_facts,
)
from src.knowledge.compiler.model import (
    AliasType,
    CompilationResult,
    ConflictCandidate,
    ConflictMateriality,
    ConflictType,
    EntityAlias,
    EntityCandidate,
    EntityMerge,
    EntityType,
    EvidenceRef,
    EvidenceType,
    FactCandidate,
    FactKind,
    QualityIssue,
    RelationshipCandidate,
    RelationshipKind,
    RuleCandidate,
    SemanticUnit,
    SemanticUnitKind,
    SourceLocator,
    TemporalScope,
    normalize_term,
)
from src.knowledge.compiler.pipeline import KnowledgeCompiler
from src.knowledge.compiler.rules import detect_modality, extract_rules, rule_key
from src.knowledge.compiler.store import (
    CompilerStore,
    PostgresCompilerStore,
    assertion_type_for,
    object_kind_for_entity,
)
from src.knowledge.compiler.temporal import infer_temporal_scope, parse_date

__all__ = [
    "AliasType",
    "CompilationResult",
    "CompilerStore",
    "ConflictCandidate",
    "ConflictMateriality",
    "ConflictType",
    "EntityAlias",
    "EntityCandidate",
    "EntityMerge",
    "EntityResolver",
    "EntityType",
    "EvidenceRef",
    "EvidenceType",
    "FactCandidate",
    "FactKind",
    "KnowledgeCompiler",
    "PostgresCompilerStore",
    "QualityIssue",
    "RelationshipCandidate",
    "RelationshipKind",
    "RuleCandidate",
    "SemanticUnit",
    "SemanticUnitKind",
    "SourceLocator",
    "TemporalScope",
    "assertion_type_for",
    "build_facts",
    "build_relationships",
    "classify_conflict",
    "detect_conflicts",
    "detect_modality",
    "discover_entities",
    "entity_facts",
    "extract_rules",
    "extract_semantic_units",
    "extract_tabular_units",
    "extracta_for",
    "infer_entity_type",
    "infer_temporal_scope",
    "is_auto_resolvable",
    "normalize_term",
    "object_kind_for_entity",
    "parse_date",
    "rule_key",
    "values_equivalent",
]
