# =============================================================================
# Adaptive RAG runtime settings (injectable; tests do not need env).
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from src.core.domain.adaptive import POLICY_VERSION, AdaptiveMode
from src.decision.routing import in_canary


@dataclass(frozen=True, kw_only=True)
class AdaptiveRagSettings:
    mode: str = AdaptiveMode.OFF.value
    canary_percentage: int = 0
    max_retrieval_attempts: int = 3
    top_k_min: int = 3
    top_k_max: int = 12
    top_k_lookup: int = 3
    top_k_compare: int = 8
    top_k_multi: int = 12
    evidence_min_score: float = 0.25
    evidence_min_coverage: float = 0.25
    cache_ttl_seconds: int = 600
    jev_evidence_enabled: bool = True
    fast_path_enabled: bool = True
    rewrite_enabled: bool = True
    passage_judge_enabled: bool = True
    passage_judge_max: int = 5
    claims_enabled: bool = True
    claims_max: int = 6
    claims_ledger_enabled: bool = True
    noul_yes: float = 0.65
    noul_no: float = 0.35
    estimated_cost_per_1k: float = 0.0005
    policy_version: str = POLICY_VERSION

    @property
    def effective_mode(self) -> str:
        mode = (self.mode or AdaptiveMode.OFF.value).strip().lower()
        allowed = {m.value for m in AdaptiveMode}
        return mode if mode in allowed else AdaptiveMode.OFF.value

    def enabled(self) -> bool:
        return self.effective_mode != AdaptiveMode.OFF.value

    def should_apply(self, request_id: UUID) -> bool:
        mode = self.effective_mode
        if mode == AdaptiveMode.ACTIVE.value:
            return True
        if mode == AdaptiveMode.CANARY.value:
            return in_canary(request_id, self.canary_percentage)
        return False


def settings_from_app() -> AdaptiveRagSettings:
    from src.core.config import get_settings

    s = get_settings()
    return AdaptiveRagSettings(
        mode=s.ADAPTIVE_RAG_MODE,
        canary_percentage=s.ADAPTIVE_RAG_CANARY_PERCENTAGE,
        max_retrieval_attempts=s.ADAPTIVE_RAG_MAX_RETRIEVAL_ATTEMPTS,
        top_k_min=s.ADAPTIVE_RAG_TOP_K_MIN,
        top_k_max=s.ADAPTIVE_RAG_TOP_K_MAX,
        top_k_lookup=s.ADAPTIVE_RAG_TOP_K_LOOKUP,
        top_k_compare=s.ADAPTIVE_RAG_TOP_K_COMPARE,
        top_k_multi=s.ADAPTIVE_RAG_TOP_K_MULTI,
        evidence_min_score=s.ADAPTIVE_RAG_EVIDENCE_MIN_SCORE,
        evidence_min_coverage=s.ADAPTIVE_RAG_EVIDENCE_MIN_COVERAGE,
        cache_ttl_seconds=s.ADAPTIVE_RAG_CACHE_TTL_SECONDS,
        jev_evidence_enabled=s.ADAPTIVE_RAG_JEV_EVIDENCE,
        fast_path_enabled=s.ADAPTIVE_RAG_FAST_PATH,
        rewrite_enabled=s.ADAPTIVE_RAG_REWRITE,
        passage_judge_enabled=s.DECISION_PASSAGE_JUDGE,
        passage_judge_max=s.DECISION_PASSAGE_MAX,
        claims_enabled=s.DECISION_CLAIMS,
        claims_max=s.DECISION_CLAIMS_MAX,
        claims_ledger_enabled=s.DECISION_CLAIMS_LEDGER,
        noul_yes=s.DECISION_NOUL_YES,
        noul_no=s.DECISION_NOUL_NO,
    )
