# =============================================================================
# Grounding validator — citation coverage + token overlap. Optional JEV Noul.
# =============================================================================
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from src.core.domain.adaptive import EvidenceSet, GroundingResult
from src.decision.batch import noul_for
from src.decision.judgment import (
    PHASE_GROUNDING,
    JudgmentContext,
    call_phase_judge,
)
from src.decision.questions import noul_is_no
from src.rag.adaptive.questions import build_grounding_questions
from src.rag.adaptive.settings import AdaptiveRagSettings
from src.rag.retrieval.classify import normalize_query

_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")
_INSUFFICIENT_HINTS = (
    "no existe suficiente evidencia",
    "no tengo suficiente información",
    "not enough evidence",
    "insufficient evidence",
)


def evaluate_grounding(
    *,
    answer: str,
    evidence: EvidenceSet,
    settings: AdaptiveRagSettings,
) -> GroundingResult:
    text = (answer or "").strip()
    if not text:
        return GroundingResult(grounded=False, score=0.0, reason="empty_answer")
    lowered = text.lower()
    if any(hint in lowered for hint in _INSUFFICIENT_HINTS):
        return GroundingResult(grounded=True, score=1.0, reason="abstain")
    if not evidence.items:
        return GroundingResult(grounded=False, score=0.0, reason="no_evidence")
    answer_tokens = set(_TOKEN_RE.findall(normalize_query(text)))
    evidence_tokens = set(
        _TOKEN_RE.findall(normalize_query(" ".join(item.content for item in evidence.items[:12])))
    )
    if not answer_tokens:
        return GroundingResult(grounded=False, score=0.0, reason="no_tokens")
    overlap = len(answer_tokens & evidence_tokens) / len(answer_tokens)
    cited = 1.0 if any(item.citation and item.citation in text for item in evidence.items) else overlap
    score = min(1.0, 0.7 * overlap + 0.3 * cited)
    grounded = score >= 0.25 or overlap >= settings.evidence_min_coverage
    return GroundingResult(
        grounded=grounded,
        score=score,
        citation_coverage=cited,
        reason="overlap" if grounded else "weak_alignment",
    )


async def maybe_jev_grounding(
    result: GroundingResult,
    *,
    answer: str,
    evidence: EvidenceSet,
    settings: AdaptiveRagSettings,
    judge=None,
    context: JudgmentContext | None = None,
    claims_enabled: bool | None = None,
    organization_id: UUID | None = None,
    request_id: UUID | None = None,
    agent_id: UUID | None = None,
    cache: Any = None,
    claims_ledger: Any = None,
    regeneration_used: bool = False,
    retrieval_budget_left: int = 0,
    evidence_contradictions: int = 0,
) -> GroundingResult:
    if judge is None or result.reason in {"abstain", "no_evidence", "empty_answer"}:
        return result
    use_claims = (
        bool(settings.claims_enabled) if claims_enabled is None else bool(claims_enabled)
    )
    if use_claims:
        return await _claim_grounding(
            result,
            answer=answer,
            evidence=evidence,
            settings=settings,
            judge=judge,
            organization_id=organization_id,
            request_id=request_id,
            agent_id=agent_id,
            cache=cache,
            ledger=claims_ledger,
            regeneration_used=regeneration_used,
            retrieval_budget_left=retrieval_budget_left,
            evidence_contradictions=evidence_contradictions,
        )
    if result.grounded and result.score >= 0.5:
        return result
    state = {
        "user_request": evidence.query[:2000],
        "draft_answer": (answer or "")[:1500],
        "evidence_preview": evidence.preview(1200),
    }
    try:
        payload = await call_phase_judge(
            judge,
            phase=PHASE_GROUNDING,
            state=state,
            questions=build_grounding_questions(),
            context=context or JudgmentContext(phase=PHASE_GROUNDING),
        )
    except Exception:  # noqa: BLE001
        return result
    answers = payload.get("answers") if isinstance(payload, dict) else None
    if not isinstance(answers, dict):
        return result
    raw = answers.get("answer_grounded")
    noul = None
    if isinstance(raw, dict) and "noul" in raw:
        try:
            noul = float(raw["noul"])
        except (TypeError, ValueError):
            noul = None
    result.jev_used = True
    if noul is not None and noul_is_no(noul, settings.noul_no):
        result.grounded = False
        result.reason = "jev_ungrounded"
        result.score = min(result.score, 0.2)
    return result


async def _claim_grounding(
    result: GroundingResult,
    *,
    answer: str,
    evidence: EvidenceSet,
    settings: AdaptiveRagSettings,
    judge,
    organization_id: UUID | None,
    request_id: UUID | None,
    agent_id: UUID | None,
    cache: Any,
    ledger: Any,
    regeneration_used: bool,
    retrieval_budget_left: int,
    evidence_contradictions: int,
) -> GroundingResult:
    """Grounding + verificación de claims en UNA llamada POST_GENERATION."""
    from src.rag.adaptive.claims import (
        record_claims_in_ledger,
        verify_generation,
    )

    grounding_uncertain = not (result.grounded and result.score >= 0.5)
    verification = await verify_generation(
        judge=judge,
        answer=answer,
        evidence=evidence,
        settings=settings,
        organization_id=organization_id,
        request_id=request_id,
        agent_id=agent_id,
        cache=cache,
        regeneration_used=regeneration_used,
        retrieval_budget_left=retrieval_budget_left,
        ask_grounding=grounding_uncertain,
        evidence_contradictions=evidence_contradictions,
    )
    result.claim_verdicts = [claim.to_public_dict() for claim in verification.claims]
    result.claims_summary = {
        "supported": len(verification.supported),
        "unsupported": len(verification.unsupported),
        "contradicted": len(verification.contradicted),
        "not_verifiable": len(verification.not_verifiable),
        "jev_used": verification.jev_used,
    }
    result.policy = verification.policy
    result.jev_used = result.jev_used or verification.jev_used
    noul = noul_for(verification.answers, "answer_grounded", default=None)
    if noul is not None and noul_is_no(noul, settings.noul_no):
        result.grounded = False
        result.reason = "jev_ungrounded"
        result.score = min(result.score, 0.2)
    if (
        verification.jev_used
        and organization_id is not None
        and settings.claims_ledger_enabled
    ):
        await record_claims_in_ledger(
            verification,
            organization_id=organization_id,
            request_id=request_id,
            agent_id=agent_id,
            repo=ledger,
        )
    return result
