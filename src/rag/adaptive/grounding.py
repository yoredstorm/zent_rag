# =============================================================================
# Grounding validator — citation coverage + token overlap. Optional JEV Noul.
# =============================================================================
from __future__ import annotations

import re

from src.core.domain.adaptive import EvidenceSet, GroundingResult
from src.decision.judgment import PHASE_GROUNDING, JudgmentContext, call_judge
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
) -> GroundingResult:
    if judge is None or result.reason in {"abstain", "no_evidence", "empty_answer"}:
        return result
    if result.grounded and result.score >= 0.5:
        return result
    state = {
        "user_request": evidence.query[:2000],
        "draft_answer": (answer or "")[:1500],
        "evidence_preview": evidence.preview(1200),
    }
    try:
        payload = await call_judge(
            judge,
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
