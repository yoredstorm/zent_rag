# ruff: noqa: T201 - herramienta CLI: print es la salida
"""Evalua el gold set P19.1-06 contra el router determinista."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from src.platform.workflows.intent_route import classify_intent

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLDSET = ROOT / "tests" / "golden" / "p19_intent_goldset.json"


def _pairs(value: dict[str, str]) -> set[tuple[str, str]]:
    return {(str(key), str(item)) for key, item in value.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Intent gold set")
    parser.add_argument("--goldset", default=str(DEFAULT_GOLDSET))
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    payload = json.loads(Path(args.goldset).read_text(encoding="utf-8"))
    cases = payload["cases"]
    correct = 0
    tp = fp = fn = 0
    false_auth = 0
    per_intent: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    failures = []
    for case in cases:
        result = classify_intent(None, case["text"])
        expected = case["expected_intent"]
        ok = result.intent == expected
        correct += int(ok)
        per_intent[expected][0] += 1
        per_intent[expected][1] += int(ok)
        if ok:
            per_intent[expected][2] += 1
        expected_pairs = _pairs(case.get("expected_entities") or {})
        actual_pairs = _pairs(result.entities)
        tp += len(expected_pairs & actual_pairs)
        fp += len(actual_pairs - expected_pairs)
        fn += len(expected_pairs - actual_pairs)
        if case.get("requires_identity") and not result.requires_identity_verification:
            false_auth += 1
        if not ok:
            failures.append(
                {
                    "text": case["text"],
                    "expected": expected,
                    "actual": result.intent,
                    "reason": result.reason_codes,
                }
            )
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    slot_f1 = 2 * precision * recall / (precision + recall) if precision + recall else 1.0
    accuracy = correct / len(cases)
    f1s = []
    for _intent, (total, hits, _) in per_intent.items():
        precision_i = hits / total if total else 0.0
        recall_i = hits / total if total else 0.0
        f1s.append(
            2 * precision_i * recall_i / (precision_i + recall_i)
            if precision_i + recall_i
            else 0.0
        )
    macro_f1 = sum(f1s) / len(f1s) if f1s else 0.0
    result = {
        "schema": "zent.cert.intent-goldset-result/1",
        "cases": len(cases),
        "route_accuracy": round(accuracy, 4),
        "macro_f1": round(macro_f1, 4),
        "slot_precision": round(precision, 4),
        "slot_recall": round(recall, 4),
        "slot_f1": round(slot_f1, 4),
        "false_authorizations": false_auth,
        "thresholds": {
            "route_accuracy": 0.85,
            "macro_f1": 0.80,
            "slot_f1": 0.90,
            "false_authorizations": 0,
        },
        "failures": failures[:20],
    }
    result["pass"] = (
        accuracy >= 0.85
        and macro_f1 >= 0.80
        and slot_f1 >= 0.90
        and false_auth == 0
    )
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
