# =============================================================================
# P19.1-06 - Gold set sintetico de intencion (80 casos).
# =============================================================================
from __future__ import annotations

import json
from pathlib import Path

from src.platform.workflows.intent_route import classify_intent

ROOT = Path(__file__).resolve().parent.parent
GOLDSET = ROOT / "tests" / "golden" / "p19_intent_goldset.json"


def _pairs(value: dict[str, str]) -> set[tuple[str, str]]:
    return {(str(key), str(item)) for key, item in value.items()}


def test_intent_goldset_meets_thresholds() -> None:
    payload = json.loads(GOLDSET.read_text(encoding="utf-8"))
    cases = payload["cases"]
    assert len(cases) == 80

    correct = 0
    tp = fp = fn = 0
    false_authorizations = 0
    for case in cases:
        result = classify_intent(None, case["text"])
        correct += int(result.intent == case["expected_intent"])
        expected = _pairs(case.get("expected_entities") or {})
        actual = _pairs(result.entities)
        tp += len(expected & actual)
        fp += len(actual - expected)
        fn += len(expected - actual)
        if case.get("requires_identity") and not result.requires_identity_verification:
            false_authorizations += 1

    accuracy = correct / len(cases)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    slot_f1 = 2 * precision * recall / (precision + recall) if precision + recall else 1.0
    assert accuracy >= 0.85
    assert slot_f1 >= 0.90
    assert false_authorizations == 0
