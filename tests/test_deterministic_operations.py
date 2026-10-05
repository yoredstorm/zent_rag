# =============================================================================
# Deterministic operations — el registry seguro
# =============================================================================
# Nada de eval arbitrario: expresiones parseadas con ast y nodos whitelisted.
# El LLM no decide libremente un resultado que puede resolverse determinísticamente.
# =============================================================================
from __future__ import annotations

import pytest

from src.intelligence.reasoning.operations import (
    OperationRegistry,
    OperationStatus,
    OperationType,
    UnsafeExpression,
    evaluate_expression,
    run_arithmetic,
    run_boolean,
    run_comparison,
    run_date_arithmetic,
    run_date_comparison,
    run_enum_check,
    run_formula,
    run_range_check,
    run_set_membership,
    run_string_equality,
    run_unit_conversion,
)


class TestArithmetic:
    def test_add(self) -> None:
        assert run_arithmetic(a=100, b=20, op="add").value == 120

    def test_expression(self) -> None:
        result = run_arithmetic("base + surcharge", variables={"base": 100, "surcharge": 20})
        assert result.ok and result.value == 120

    def test_division_by_zero_is_error(self) -> None:
        assert run_arithmetic(a=1, b=0, op="div").status == OperationStatus.ERROR.value

    def test_unsafe_expression_rejected(self) -> None:
        with pytest.raises(UnsafeExpression):
            evaluate_expression("__import__('os').system('echo hi')")
        with pytest.raises(UnsafeExpression):
            evaluate_expression("(1).__class__")
        with pytest.raises(UnsafeExpression):
            evaluate_expression("open('/etc/passwd')")


class TestFormula:
    def test_documented_formula_with_user_values(self) -> None:
        result = run_formula(
            "total = price * (1 + tax_rate)",
            variables={"price": 100, "tax_rate": 0.18},
        )
        assert result.ok and result.value == 118

    def test_natural_formula(self) -> None:
        result = run_formula("base_amount + surcharge", variables={"base_amount": 100, "surcharge": 20})
        assert result.value == 120

    def test_unknown_variable_is_error(self) -> None:
        result = run_formula("price * (1 + tax_rate)", variables={"price": 100})
        assert result.status == OperationStatus.ERROR.value


class TestComparisonBoolean:
    @pytest.mark.parametrize(
        "a,b,op,expected",
        [
            (20, 18, "ge", True),
            (17, 18, "ge", False),
            (100, 100, "eq", True),
            ("ACTIVE", "active", "eq", True),
        ],
    )
    def test_comparison(self, a, b, op, expected) -> None:
        assert run_comparison(a, b, op=op).value is expected

    def test_boolean(self) -> None:
        result = run_boolean("age >= 18 and status == 'ACTIVE'", variables={"age": 20, "status": "ACTIVE"})
        assert result.ok and result.value is True


class TestSetAndEnum:
    def test_set_membership(self) -> None:
        assert run_set_membership("ACTIVE", ["ACTIVE", "PENDING"]).value is True
        assert run_set_membership("CLOSED", ["ACTIVE", "PENDING"]).value is False

    def test_enum_check_case_insensitive(self) -> None:
        assert run_enum_check("active", "ACTIVE, PENDING").value is True


class TestRange:
    def test_inside(self) -> None:
        assert run_range_check(20, minimum=18).value is True

    def test_outside(self) -> None:
        assert run_range_check(17, minimum=18).value is False

    def test_bounded(self) -> None:
        assert run_range_check(5, minimum=1, maximum=10).value is True
        assert run_range_check(11, minimum=1, maximum=10).value is False


class TestStringEquality:
    def test_case_insensitive(self) -> None:
        assert run_string_equality("FCLAS", "fclas").value is True

    def test_case_sensitive(self) -> None:
        assert run_string_equality("FCLAS", "fclas", case_sensitive=True).value is False


class TestDates:
    def test_comparison(self) -> None:
        assert run_date_comparison("2026-01-01", "2026-12-31", op="le").value is True

    def test_arithmetic(self) -> None:
        assert run_date_arithmetic("2026-01-31", months=1).value == "2026-02-28"

    def test_arithmetic_days(self) -> None:
        assert run_date_arithmetic("2026-10-04", days=10).value == "2026-10-14"


class TestUnits:
    def test_km_to_m(self) -> None:
        assert run_unit_conversion(1, from_unit="km", to_unit="m").value == 1000

    def test_celsius_to_fahrenheit(self) -> None:
        assert run_unit_conversion(100, from_unit="c", to_unit="f").value == 212

    def test_unsupported(self) -> None:
        assert run_unit_conversion(1, from_unit="x", to_unit="y").status == OperationStatus.ERROR.value


class TestRegistry:
    def test_all_initial_operations_registered(self) -> None:
        registry = OperationRegistry()
        expected = {
            "ARITHMETIC",
            "COMPARISON",
            "BOOLEAN",
            "SET_MEMBERSHIP",
            "STRING_EQUALITY",
            "POSITIONAL_MATCH",
            "RANGE_CHECK",
            "ENUM_CHECK",
            "DATE_COMPARISON",
            "DATE_ARITHMETIC",
            "UNIT_CONVERSION",
            "FORMULA_EVALUATION",
        }
        assert set(registry.available()) == expected

    def test_disabled_registry_refuses(self) -> None:
        registry = OperationRegistry(enabled=False)
        result = registry.run("ARITHMETIC", a=1, b=2)
        assert result.status == OperationStatus.UNSUPPORTED.value

    def test_positional_match_through_registry(self) -> None:
        from src.rag.longcontext.pattern import extract_pattern_semantics

        semantics = extract_pattern_semantics(
            "& represents one alphanumeric position. Matching is positional. "
            "The pattern and the value must have the same length."
        )
        result = OperationRegistry().run(
            "POSITIONAL_MATCH", value="ASDF", pattern="&&&F", semantics=semantics
        )
        assert result.ok and result.value == "MATCH"

    def test_operation_type_enum_matches_registry(self) -> None:
        assert set(OperationType) == {
            OperationType(name) for name in OperationRegistry().available()
        }
