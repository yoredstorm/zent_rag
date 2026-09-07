"""Phase 26B — Business Semantic AST + SemanticCompiler."""
from __future__ import annotations

from src.core.domain.intelligence import BusinessDefinition, QueryUnderstanding
from src.core.domain.semantic import (
    BusinessObjectType,
    BusinessSemanticAST,
    SemanticCompileResult,
    SemanticGapCode,
)
from src.intelligence.semantic_compiler import SemanticCompiler


def _understanding(**kwargs) -> QueryUnderstanding:
    base = dict(
        intent="business_metric",
        concepts=["ventas", "margen", "corporativo"],
        concept_types={
            "ventas": BusinessObjectType.FACT.value,
            "margen": BusinessObjectType.DERIVED_METRIC.value,
            "corporativo": BusinessObjectType.SEGMENT.value,
        },
        requires_definition=["margen", "corporativo"],
        resolved_concepts={"ventas": False, "margen": False, "corporativo": False},
        entities=["Aeroméxico"],
        time_scope="past",
        requires_structured_data=True,
        extraction_source="deterministic",
    )
    base.update(kwargs)
    return QueryUnderstanding(**base)


class TestBusinessSemanticAST:
    def test_ast_has_no_physical_table_fields_by_default(self) -> None:
        ast = BusinessSemanticAST(
            query_type="metric_query",
            metrics=[{"name": "margen", "version": None}],
            entities=[{"type": "customer", "value": "Aeroméxico"}],
            segments=["corporativo"],
            time={"scope": "past"},
        )
        payload = ast.to_dict()
        assert "table" not in payload
        assert "tables" not in payload
        assert payload["metrics"][0]["name"] == "margen"
        assert payload["entities"][0]["value"] == "Aeroméxico"


class TestSemanticCompilerBuildAst:
    def setup_method(self) -> None:
        self.compiler = SemanticCompiler()

    def test_compile_builds_ast_from_understanding(self) -> None:
        result = self.compiler.compile(_understanding())
        assert isinstance(result, SemanticCompileResult)
        assert isinstance(result.semantic_ast, BusinessSemanticAST)
        assert result.semantic_ast.query_type == "metric_query"
        metric_names = [m["name"] for m in result.semantic_ast.metrics]
        assert "margen" in metric_names
        assert "ventas" not in metric_names  # FACT, not metric
        assert any(e["value"] == "Aeroméxico" for e in result.semantic_ast.entities)
        assert "corporativo" in result.semantic_ast.segments
        assert result.semantic_ast.time.get("scope") == "past"

    def test_unresolved_definitionals_emit_context_missing(self) -> None:
        result = self.compiler.compile(_understanding())
        unresolved_names = {u["name"] for u in result.unresolved_objects}
        assert "margen" in unresolved_names
        assert "corporativo" in unresolved_names
        assert "ventas" not in unresolved_names
        codes = {u["code"] for u in result.unresolved_objects}
        assert SemanticGapCode.CONTEXT_MISSING.value in codes
        assert result.has_blocking_gaps is True

    def test_approved_definition_resolves_without_physical_invention(self) -> None:
        from uuid import uuid4

        defs = [
            BusinessDefinition(
                id=uuid4(),
                organization_id=__import__("uuid").UUID(int=1),
                concept="margen",
                definition="Ventas - COGS",
                expression="revenue - cogs",
                status="approved",
            )
        ]
        result = self.compiler.compile(
            _understanding(
                resolved_concepts={
                    "ventas": False,
                    "margen": True,
                    "corporativo": False,
                }
            ),
            definitions=defs,
        )
        resolved_names = {r["name"] for r in result.resolved_objects}
        assert "margen" in resolved_names
        unresolved_names = {u["name"] for u in result.unresolved_objects}
        assert "margen" not in unresolved_names
        assert "corporativo" in unresolved_names
        # Physical candidates only from known definition expression — no invented tables
        for cand in result.physical_candidates:
            assert "A1672" not in str(cand)
            assert cand.get("source") in ("definition_expression", "definition")

    def test_never_invents_sql_or_joins_when_essential_missing(self) -> None:
        result = self.compiler.compile(_understanding())
        assert result.required_metrics  # margen needed
        assert not any("JOIN" in w.upper() for w in result.warnings)
        assert result.to_dict()["semantic_ast"]["filters"] == []

    def test_document_intent_query_type(self) -> None:
        result = self.compiler.compile(
            _understanding(
                intent="document_policy",
                concepts=["devolucion"],
                concept_types={"devolucion": BusinessObjectType.FACT.value},
                requires_definition=[],
                resolved_concepts={},
                entities=[],
                requires_structured_data=False,
            )
        )
        assert result.semantic_ast.query_type == "document_query"
