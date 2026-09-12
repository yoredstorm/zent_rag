# =============================================================================
# Temporal + Conflict intelligence — dominio puro (Phase 5)
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from src.core.domain.evidence import ClaimRecord
from src.core.domain.temporal_conflict import (
    ClaimTemporalState,
    ConflictType,
    claim_temporal_state,
    classify_conflict,
    parse_temporal_window,
    propose_resolution,
)

_NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _claim(subject: str, predicate: str, object_value: str | None, **overrides) -> ClaimRecord:
    base = dict(
        organization_id=uuid4(),
        text=f"{subject} {predicate} {object_value or ''}".strip(),
        normalized_subject=subject,
        normalized_predicate=predicate,
        normalized_object=object_value,
    )
    base.update(overrides)
    return ClaimRecord(**base)


def test_parse_temporal_window_variants() -> None:
    year = parse_temporal_window("vigente 2024")
    assert year is not None
    assert year.valid_from == datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert year.valid_to == datetime(2024, 12, 31, tzinfo=timezone.utc)

    month = parse_temporal_window("enero 2025")
    assert month is not None and month.valid_from.month == 1

    iso_month = parse_temporal_window("2025-03")
    assert iso_month is not None and iso_month.valid_from.month == 3

    span = parse_temporal_window("2024-2026")
    assert span is not None
    assert span.valid_from.year == 2024 and span.valid_to.year == 2026

    since = parse_temporal_window("desde 2023")
    assert since is not None and since.valid_to is None

    until = parse_temporal_window("hasta 2024")
    assert until is not None and until.valid_from is None

    assert parse_temporal_window("sin fecha") is None
    assert parse_temporal_window(None) is None


def test_claim_temporal_state() -> None:
    historical = _claim("penalidad", "es", "5%", temporal_scope="2024")
    current = _claim("penalidad", "es", "7%", temporal_scope="2099")
    unknown = _claim("penalidad", "es", "9%")
    assert claim_temporal_state(historical, now=_NOW) is ClaimTemporalState.HISTORICAL
    assert claim_temporal_state(current, now=_NOW) is ClaimTemporalState.CURRENT
    assert claim_temporal_state(unknown, now=_NOW) is ClaimTemporalState.UNKNOWN


def test_classify_conflict_types() -> None:
    base = _claim("penalidad", "es", "5%", temporal_scope="2024")
    later = _claim("penalidad", "es", "7%", temporal_scope="2099")
    assert (
        classify_conflict(a=base, b=later) is ConflictType.TEMPORAL_UPDATE
    )

    same_window_a = _claim("penalidad", "es", "5%", temporal_scope="2024")
    same_window_b = _claim("penalidad", "es", "7%", temporal_scope="2024")
    assert (
        classify_conflict(a=same_window_a, b=same_window_b)
        is ConflictType.DIRECT_CONFLICT
    )

    ambiguous = _claim("penalidad", "es", None)
    assert (
        classify_conflict(a=base, b=ambiguous) is ConflictType.AMBIGUITY
    )

    duplicate = _claim("penalidad", "es", "5%")
    assert (
        classify_conflict(a=base, b=duplicate)
        is ConflictType.DUPLICATE_DIFFERENCE
    )

    assert (
        classify_conflict(
            a=same_window_a,
            b=same_window_b,
            source_a="contract.pdf",
            source_b="policy.pdf",
        )
        is ConflictType.SOURCE_DISAGREEMENT
    )


def test_propose_resolution_by_temporal_and_authority() -> None:
    old_id, new_id = uuid4(), uuid4()
    old_window = parse_temporal_window("2024")
    new_window = parse_temporal_window("2099")
    resolution = propose_resolution(
        conflict_type=ConflictType.TEMPORAL_UPDATE,
        claim_a_id=old_id,
        claim_b_id=new_id,
        window_a=old_window,
        window_b=new_window,
    )
    assert resolution.winning_claim_id == new_id
    assert resolution.losing_claim_id == old_id
    assert resolution.requires_review is True

    authority_win = propose_resolution(
        conflict_type=ConflictType.SOURCE_DISAGREEMENT,
        claim_a_id=old_id,
        claim_b_id=new_id,
        authority_a="authoritative",
        authority_b="informational",
    )
    assert authority_win.winning_claim_id == old_id
    assert authority_win.authority == "authoritative"
    assert authority_win.requires_review is True

    tie = propose_resolution(
        conflict_type=ConflictType.SOURCE_DISAGREEMENT,
        claim_a_id=old_id,
        claim_b_id=new_id,
        authority_a="approved",
        authority_b="approved",
    )
    assert tie.winning_claim_id is None
    assert tie.requires_review is True

    direct = propose_resolution(
        conflict_type=ConflictType.DIRECT_CONFLICT,
        claim_a_id=old_id,
        claim_b_id=new_id,
    )
    assert direct.winning_claim_id is None
    assert direct.requires_review is True
