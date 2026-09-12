# =============================================================================
# Domain Layer — Shadow evaluation (Phase 8)
# =============================================================================
# Compara el resultado del baseline single-specialist contra el pipeline
# cognitivo completo (brief §64/§79). La respuesta visible NO cambia: el
# veredicto es una señal de promoción, no una decisión automática.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from src.core.domain.cognitive import ComplexityLevel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ShadowVerdict(StrEnum):
    COGNITIVE_BETTER = "cognitive_better"
    BASELINE_BETTER = "baseline_better"
    TIE = "tie"


@dataclass(frozen=True, kw_only=True)
class ShadowMetrics:
    """Métricas comparables de una ejecución (sin contenido sensible)."""

    evidence_count: int = 0
    claims: int = 0
    supported: int = 0
    partial: int = 0
    unsupported: int = 0
    outdated: int = 0
    conflicted: int = 0
    conflicts: int = 0
    critique_issues: int = 0
    debate_outcomes: int = 0
    llm_calls: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    has_answer: bool = False

    @property
    def supported_ratio(self) -> float:
        if self.claims <= 0:
            return 0.0
        return (self.supported + self.partial) / self.claims

    def to_dict(self) -> dict:
        return {
            "evidence_count": self.evidence_count,
            "claims": self.claims,
            "supported": self.supported,
            "partial": self.partial,
            "unsupported": self.unsupported,
            "outdated": self.outdated,
            "conflicted": self.conflicted,
            "conflicts": self.conflicts,
            "critique_issues": self.critique_issues,
            "debate_outcomes": self.debate_outcomes,
            "llm_calls": self.llm_calls,
            "tokens": self.tokens,
            "cost_usd": self.cost_usd,
            "latency_ms": round(self.latency_ms, 2),
            "has_answer": self.has_answer,
            "supported_ratio": round(self.supported_ratio, 4),
        }


@dataclass(frozen=True, kw_only=True)
class ShadowComparison:
    organization_id: UUID
    query: str
    level: ComplexityLevel
    baseline: ShadowMetrics
    cognitive: ShadowMetrics
    verdict: ShadowVerdict
    reasons: tuple[str, ...] = ()
    id: UUID = field(default_factory=uuid4)
    workspace_id: UUID | None = None
    baseline_run_id: UUID | None = None
    cognitive_run_id: UUID | None = None
    created_at: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "query": self.query,
            "level": self.level.value,
            "baseline": self.baseline.to_dict(),
            "cognitive": self.cognitive.to_dict(),
            "verdict": self.verdict.value,
            "reasons": list(self.reasons),
            "baseline_run_id": (
                str(self.baseline_run_id) if self.baseline_run_id else None
            ),
            "cognitive_run_id": (
                str(self.cognitive_run_id) if self.cognitive_run_id else None
            ),
            "created_at": self.created_at.isoformat(),
        }


def compare_shadow(
    *,
    baseline: ShadowMetrics,
    cognitive: ShadowMetrics,
    grounding_margin: float = 0.05,
) -> tuple[ShadowVerdict, tuple[str, ...]]:
    """Deterministic shadow verdict used as a promotion signal only.

    Rules (evaluated in order):
      1. Grounding margin favors cognitive → cognitive_better.
      2. Grounding margin favors baseline → baseline_better.
      3. Equal grounding: more detected conflicts → cognitive_better.
      4. Equal grounding/conflicts and clear cost blow-up → baseline_better.
      5. Otherwise tie.
    """
    reasons: list[str] = []
    delta = cognitive.supported_ratio - baseline.supported_ratio
    if delta > grounding_margin:
        reasons.append(f"supported_ratio +{round(delta, 4)}")
        return ShadowVerdict.COGNITIVE_BETTER, tuple(reasons)
    if -delta > grounding_margin:
        reasons.append(f"supported_ratio {round(delta, 4)}")
        return ShadowVerdict.BASELINE_BETTER, tuple(reasons)
    if cognitive.conflicts > baseline.conflicts:
        reasons.append(
            f"más conflictos detectados ({cognitive.conflicts} vs "
            f"{baseline.conflicts})"
        )
        return ShadowVerdict.COGNITIVE_BETTER, tuple(reasons)
    if baseline.latency_ms > 0 and cognitive.latency_ms > baseline.latency_ms * 2:
        reasons.append(
            f"latencia {round(cognitive.latency_ms)}ms vs "
            f"{round(baseline.latency_ms)}ms"
        )
        return ShadowVerdict.BASELINE_BETTER, tuple(reasons)
    reasons.append("sin diferencia significativa")
    return ShadowVerdict.TIE, tuple(reasons)
