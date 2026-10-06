# =============================================================================
# Regresión: el Rule Lane DEBE consultar el kind con el que se persiste
# =============================================================================
# Bug de producción: el compilador persiste `kind='business_rule'`
# (CanonicalKind.BUSINESS_RULE) y el Rule Lane consultaba `'BUSINESS_RULE'`.
# Resultado: 0 candidatas SIEMPRE, aunque hubiera reglas SUPPORTED/ejecutables.
#
# Estos tests fijan el contrato sin necesitar Postgres: el kind del retrieval
# es el mismo valor del dominio y la comparación es case-insensitive.
# =============================================================================
from __future__ import annotations

import inspect

from src.core.domain.canonical import CanonicalKind
from src.runtime import cache_fingerprint, rule_retrieval


class TestRuleObjectKind:
    def test_rule_kind_matches_persisted_kind(self) -> None:
        assert rule_retrieval.RULE_OBJECT_KIND == "business_rule"
        assert rule_retrieval.RULE_OBJECT_KIND == CanonicalKind.BUSINESS_RULE.value

    def test_kind_clause_is_case_insensitive(self) -> None:
        assert "LOWER(kind)" in rule_retrieval._RULE_KIND_CLAUSE
        assert ":rule_kind" in rule_retrieval._RULE_KIND_CLAUSE

    def test_retrieval_sql_does_not_use_uppercase_literal(self) -> None:
        source = inspect.getsource(rule_retrieval)
        assert "kind = 'BUSINESS_RULE'" not in source
        assert "kind = :kind" not in source
        assert "LOWER(kind) = :rule_kind" in source

    def test_cache_fingerprint_uses_lowercase_kind(self) -> None:
        source = inspect.getsource(cache_fingerprint)
        assert "LOWER(kind) = 'business_rule'" in source
        assert "kind = 'BUSINESS_RULE'" not in source
