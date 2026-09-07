# =============================================================================
# Intelligence Calibration — FAR, confusion matrix, thresholds (Phase 30)
# =============================================================================
# Domain policies (Finance=strict) nunca desactivan ACL / security controls.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable


class DomainPolicyLevel(StrEnum):
    STRICT = "strict"
    MODERATE = "moderate"
    PERMISSIVE = "permissive"


# Never disable ACL regardless of policy level
IMMUTABLE_CONTROLS = frozenset(
    {"acl", "rbac", "permission_check", "access_blocked", "security"}
)

DOMAIN_POLICIES: dict[str, DomainPolicyLevel] = {
    "finance": DomainPolicyLevel.STRICT,
    "legal": DomainPolicyLevel.STRICT,
    "internal_faq": DomainPolicyLevel.MODERATE,
    "brainstorming": DomainPolicyLevel.PERMISSIVE,
}


@dataclass
class ConfusionMatrix:
    tp: int = 0  # answered & answerable
    fp: int = 0  # answered & not answerable  ← false answers
    fn: int = 0  # abstained & answerable
    tn: int = 0  # abstained & not answerable

    def to_dict(self) -> dict[str, int]:
        return {"tp": self.tp, "fp": self.fp, "fn": self.fn, "tn": self.tn}


def false_answer_rate(matrix: ConfusionMatrix | dict[str, int]) -> float:
    """Zent respondió sin evidencia suficiente: FP / (TP + FP)."""
    if isinstance(matrix, ConfusionMatrix):
        tp, fp = matrix.tp, matrix.fp
    else:
        tp, fp = int(matrix.get("tp", 0)), int(matrix.get("fp", 0))
    denom = tp + fp
    if denom == 0:
        return 0.0
    return round(fp / denom, 6)


def build_confusion_matrix(
    samples: Iterable[dict[str, Any]],
) -> ConfusionMatrix:
    """samples: ground_truth_answerable (bool), zent_answered (bool)."""
    m = ConfusionMatrix()
    for s in samples:
        gt = bool(s.get("ground_truth_answerable"))
        answered = bool(s.get("zent_answered"))
        if answered and gt:
            m.tp += 1
        elif answered and not gt:
            m.fp += 1
        elif (not answered) and gt:
            m.fn += 1
        else:
            m.tn += 1
    return m


def empirical_threshold_tune(
    samples: list[dict[str, Any]],
    *,
    thresholds: list[float] | None = None,
    maximize: str = "far_min",
    max_far: float = 0.05,
) -> dict[str, Any]:
    """Elige umbral empírico sobre raw_signal_score vs human verdict.

    sample keys: raw_signal_score, ground_truth_answerable
    Predicción: answer if score >= threshold.
    """
    candidates = thresholds or [round(x * 0.05, 2) for x in range(2, 19)]
    best: dict[str, Any] | None = None
    for thr in candidates:
        preds = []
        for s in samples:
            score = float(s.get("raw_signal_score", 0.0))
            preds.append(
                {
                    "ground_truth_answerable": bool(s.get("ground_truth_answerable")),
                    "zent_answered": score >= thr,
                }
            )
        matrix = build_confusion_matrix(preds)
        far = false_answer_rate(matrix)
        answered = matrix.tp + matrix.fp
        recall = (
            matrix.tp / (matrix.tp + matrix.fn) if (matrix.tp + matrix.fn) else 0.0
        )
        row = {
            "threshold": thr,
            "false_answer_rate": far,
            "confusion": matrix.to_dict(),
            "answer_recall": round(recall, 6),
            "answered_count": answered,
        }
        if far > max_far:
            continue
        if best is None:
            best = row
            continue
        if maximize == "far_min":
            if row["false_answer_rate"] < best["false_answer_rate"] or (
                row["false_answer_rate"] == best["false_answer_rate"]
                and row["answer_recall"] > best["answer_recall"]
            ):
                best = row
        elif maximize == "recall":
            if row["answer_recall"] > best["answer_recall"]:
                best = row
    if best is None and candidates:
        # Fallback: highest threshold (most conservative)
        thr = max(candidates)
        preds = [
            {
                "ground_truth_answerable": bool(s.get("ground_truth_answerable")),
                "zent_answered": float(s.get("raw_signal_score", 0.0)) >= thr,
            }
            for s in samples
        ]
        matrix = build_confusion_matrix(preds)
        best = {
            "threshold": thr,
            "false_answer_rate": false_answer_rate(matrix),
            "confusion": matrix.to_dict(),
            "answer_recall": 0.0,
            "answered_count": matrix.tp + matrix.fp,
            "note": "fallback_max_threshold",
        }
    return best or {"threshold": 0.6, "false_answer_rate": 0.0, "confusion": {}}


@dataclass
class DomainPolicy:
    domain: str
    level: DomainPolicyLevel
    min_score: float
    allow_llm_only: bool = False
    # ACL always enforced
    acl_enforced: bool = True
    disabled_controls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "level": self.level.value,
            "min_score": self.min_score,
            "allow_llm_only": self.allow_llm_only,
            "acl_enforced": self.acl_enforced,
            "disabled_controls": list(self.disabled_controls),
        }


def policy_for_domain(domain: str) -> DomainPolicy:
    key = (domain or "general").strip().lower().replace(" ", "_")
    level = DOMAIN_POLICIES.get(key, DomainPolicyLevel.MODERATE)
    min_score = {
        DomainPolicyLevel.STRICT: 0.75,
        DomainPolicyLevel.MODERATE: 0.60,
        DomainPolicyLevel.PERMISSIVE: 0.45,
    }[level]
    return DomainPolicy(
        domain=key,
        level=level,
        min_score=min_score,
        allow_llm_only=level == DomainPolicyLevel.PERMISSIVE,
        acl_enforced=True,
        disabled_controls=[],  # never strip ACL
    )


def apply_policy_controls(
    policy: DomainPolicy, requested_disable: Iterable[str] | None = None
) -> DomainPolicy:
    """Aplica disables solicitados pero IMMUTABLE_CONTROLS siempre activos."""
    disabled: list[str] = []
    for ctrl in requested_disable or []:
        if ctrl.strip().lower() in IMMUTABLE_CONTROLS:
            continue
        disabled.append(ctrl)
    return DomainPolicy(
        domain=policy.domain,
        level=policy.level,
        min_score=policy.min_score,
        allow_llm_only=policy.allow_llm_only,
        acl_enforced=True,
        disabled_controls=disabled,
    )
