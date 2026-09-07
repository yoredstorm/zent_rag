"""Phase 30 — Calibration metrics and domain policies."""
from __future__ import annotations

from src.intelligence.calibration import (
    IMMUTABLE_CONTROLS,
    apply_policy_controls,
    build_confusion_matrix,
    empirical_threshold_tune,
    false_answer_rate,
    policy_for_domain,
)


def test_false_answer_rate_and_confusion_matrix() -> None:
    samples = [
        {"ground_truth_answerable": True, "zent_answered": True},   # TP
        {"ground_truth_answerable": False, "zent_answered": True},  # FP
        {"ground_truth_answerable": True, "zent_answered": False},  # FN
        {"ground_truth_answerable": False, "zent_answered": False}, # TN
        {"ground_truth_answerable": False, "zent_answered": True},  # FP
    ]
    matrix = build_confusion_matrix(samples)
    assert matrix.to_dict() == {"tp": 1, "fp": 2, "fn": 1, "tn": 1}
    # FAR = FP/(TP+FP) = 2/3
    assert abs(false_answer_rate(matrix) - (2 / 3)) < 1e-6


def test_empirical_threshold_tune() -> None:
    samples = [
        {"raw_signal_score": 0.9, "ground_truth_answerable": True},
        {"raw_signal_score": 0.85, "ground_truth_answerable": True},
        {"raw_signal_score": 0.4, "ground_truth_answerable": False},
        {"raw_signal_score": 0.35, "ground_truth_answerable": False},
        {"raw_signal_score": 0.55, "ground_truth_answerable": False},
    ]
    result = empirical_threshold_tune(samples, max_far=0.0)
    assert "threshold" in result
    assert result["false_answer_rate"] <= 0.0 + 1e-9
    assert result["threshold"] >= 0.55


def test_finance_strict_never_disables_acl() -> None:
    policy = policy_for_domain("Finance")
    assert policy.level.value == "strict"
    assert policy.acl_enforced is True
    assert policy.min_score >= 0.7

    patched = apply_policy_controls(policy, requested_disable=["acl", "rbac", "llm_critic"])
    assert patched.acl_enforced is True
    assert "acl" not in patched.disabled_controls
    assert "rbac" not in patched.disabled_controls
    assert "llm_critic" in patched.disabled_controls
    assert "acl" in IMMUTABLE_CONTROLS
