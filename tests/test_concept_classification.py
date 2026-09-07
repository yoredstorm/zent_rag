"""Phase 26A — BusinessObjectType concept classification."""
from __future__ import annotations

import pytest

from src.core.domain.semantic import (
    DEFINITIONAL_TYPES,
    BusinessObjectType,
    ClassifiedConcept,
)
from src.intelligence.concept_classification import ConceptClassifier


@pytest.fixture
def classifier() -> ConceptClassifier:
    return ConceptClassifier()


class TestBusinessObjectTypes:
    def test_definitional_types_are_exact_set(self) -> None:
        assert DEFINITIONAL_TYPES == frozenset(
            {
                BusinessObjectType.DERIVED_METRIC,
                BusinessObjectType.BUSINESS_TERM,
                BusinessObjectType.BUSINESS_RULE,
                BusinessObjectType.SEGMENT,
            }
        )


class TestConceptClassifierEntitiesAndFacts:
    def test_basic_entities_do_not_require_definition(
        self, classifier: ConceptClassifier
    ) -> None:
        for term in ("cliente", "clientes", "producto", "pedido", "order"):
            result = classifier.classify(term)
            assert result.object_type == BusinessObjectType.ENTITY
            assert result.requires_definition is False

    def test_sale_as_fact(self, classifier: ConceptClassifier) -> None:
        for term in ("venta", "ventas", "sale", "sales"):
            result = classifier.classify(term)
            assert result.object_type == BusinessObjectType.FACT
            assert result.requires_definition is False

    def test_dimensions(self, classifier: ConceptClassifier) -> None:
        for term in ("region", "región", "canal", "categoria", "categoría"):
            result = classifier.classify(term)
            assert result.object_type == BusinessObjectType.DIMENSION
            assert result.requires_definition is False

    def test_measures(self, classifier: ConceptClassifier) -> None:
        for term in ("amount", "cantidad", "monto", "quantity"):
            result = classifier.classify(term)
            assert result.object_type == BusinessObjectType.MEASURE
            assert result.requires_definition is False


class TestConceptClassifierDefinitional:
    def test_derived_metrics(self, classifier: ConceptClassifier) -> None:
        for term in ("margen", "gross_margin", "margen_bruto"):
            result = classifier.classify(term)
            assert result.object_type == BusinessObjectType.DERIVED_METRIC
            assert result.requires_definition is True

    def test_business_rules(self, classifier: ConceptClassifier) -> None:
        for term in ("activo", "activos", "rentable", "rentables", "moroso"):
            result = classifier.classify(term)
            assert result.object_type == BusinessObjectType.BUSINESS_RULE
            assert result.requires_definition is True

    def test_business_terms(self, classifier: ConceptClassifier) -> None:
        for term in ("premium", "prioridad", "urgencia", "vigente"):
            result = classifier.classify(term)
            assert result.object_type == BusinessObjectType.BUSINESS_TERM
            assert result.requires_definition is True

    def test_segments(self, classifier: ConceptClassifier) -> None:
        for term in ("corporativo", "corporativos"):
            result = classifier.classify(term)
            assert result.object_type == BusinessObjectType.SEGMENT
            assert result.requires_definition is True

    def test_enum_status_not_definitional_by_default(
        self, classifier: ConceptClassifier
    ) -> None:
        for term in ("estado", "status"):
            result = classifier.classify(term)
            assert result.object_type == BusinessObjectType.ENUM
            assert result.requires_definition is False


class TestConceptClassifierUnknownAndIntent:
    def test_unknown_defaults_to_entity_not_definitional(
        self, classifier: ConceptClassifier
    ) -> None:
        result = classifier.classify("dolor_de_cabeza")
        assert result.object_type == BusinessObjectType.ENTITY
        assert result.requires_definition is False

    def test_concept_definition_intent_marks_unknown_as_business_term(
        self, classifier: ConceptClassifier
    ) -> None:
        result = classifier.classify(
            "xyz_custom_policy", intent="concept_definition"
        )
        assert result.object_type == BusinessObjectType.BUSINESS_TERM
        assert result.requires_definition is True

    def test_compound_active_customer_is_business_rule(
        self, classifier: ConceptClassifier
    ) -> None:
        result = classifier.classify("cliente_activo")
        assert result.object_type == BusinessObjectType.BUSINESS_RULE
        assert result.requires_definition is True


class TestClassifyMany:
    def test_classify_many_returns_types_and_requires_definition(
        self, classifier: ConceptClassifier
    ) -> None:
        types, requires = classifier.classify_many(
            ["cliente", "ventas", "margen", "corporativo"]
        )
        assert types["cliente"] == BusinessObjectType.ENTITY.value
        assert types["ventas"] == BusinessObjectType.FACT.value
        assert types["margen"] == BusinessObjectType.DERIVED_METRIC.value
        assert types["corporativo"] == BusinessObjectType.SEGMENT.value
        assert requires == ["margen", "corporativo"]

    def test_classified_concept_dataclass(self, classifier: ConceptClassifier) -> None:
        result = classifier.classify("margen")
        assert isinstance(result, ClassifiedConcept)
        assert result.concept == "margen"
