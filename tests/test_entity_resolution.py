"""Phase 27C — Entity Resolution."""
from __future__ import annotations

from src.catalog.entity_resolution import EntityResolutionEngine, normalize_name
from src.core.domain.entity_resolution import (
    EnterpriseEntity,
    EntityAlias,
    EntityMatchStatus,
)


def test_normalize_name_strips_legal_suffix() -> None:
    assert normalize_name("ACME S.A.C.") == normalize_name("ACME SAC")
    assert normalize_name("Acme") == "acme"


def test_exact_id_and_fuzzy_scoring() -> None:
    engine = EntityResolutionEngine()
    exact = engine.score_match(
        {"identifier_value": "10291", "display_name": "ACME"},
        {"identifier_value": "10291", "display_name": "Other"},
    )
    assert exact["signals"]["exact_id"] == 1.0
    assert exact["score"] >= 0.55

    fuzzy = engine.score_match(
        {"identifier_value": "a", "display_name": "ACME S.A.C."},
        {"identifier_value": "b", "display_name": "ACME SAC"},
    )
    assert fuzzy["signals"]["normalized_name"] >= 0.85
    assert fuzzy["score"] >= 0.5


def test_suggest_match_never_auto_approves() -> None:
    engine = EntityResolutionEngine()
    left = EntityAlias(
        source_system="SAP",
        identifier_type="customer_id",
        identifier_value="10291",
        display_name="ACME S.A.C.",
    )
    right = EntityAlias(
        source_system="CRM",
        identifier_type="account_id",
        identifier_value="CRM-8821",
        display_name="ACME SAC",
    )
    match = engine.suggest_match(left, right)
    assert match is not None
    assert match.status == EntityMatchStatus.SUGGESTED_MATCH
    assert match.auto_approved is False
    assert match.status != EntityMatchStatus.APPROVED_MATCH


def test_enterprise_entity_dataclass() -> None:
    ent = EnterpriseEntity(
        canonical_name="ACME",
        aliases=[
            EntityAlias(
                source_system="SAP",
                identifier_type="customer_id",
                identifier_value="10291",
                display_name="ACME S.A.C.",
            )
        ],
    )
    assert ent.to_dict()["canonical_name"] == "ACME"
    assert EntityMatchStatus.MATCHED_OBSERVED.value == "MATCHED_OBSERVED"
    assert EntityMatchStatus.REJECTED_MATCH.value == "REJECTED_MATCH"
