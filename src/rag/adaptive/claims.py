# =============================================================================
# Claim-level verification — draft → claims → evidencia → veredicto.
# =============================================================================
# El grounding determinístico sigue siendo el cheap first gate (overlap de
# tokens). JEV sólo juzga los claims de la banda incierta con preguntas
# atómicas ("¿la evidencia sostiene el claim?", "¿lo contradice?") y el código
# compone el veredicto:
#
#   supported | unsupported | contradicted | not_verifiable
#
# Frases no factuales (saludos, formato, opiniones, preguntas al usuario) no se
# penalizan: quedan `not_verifiable`. Los claims verificados se registran en el
# Claim Ledger existente (best-effort, sin chain-of-thought).
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

from src.core.domain.adaptive import EvidenceItem, EvidenceSet
from src.decision.batch import build_post_generation_questions, noul_for
from src.decision.judgment import PHASE_POST_GENERATION, JudgmentContext, call_phase_judge
from src.infrastructure.observability.logging_config import get_logger
from src.rag.adaptive.settings import AdaptiveRagSettings
from src.rag.grounding.service import extract_claims
from src.rag.retrieval.classify import normalize_query

logger = get_logger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")
_CODE_RE = re.compile(r"\b[a-z]{1,4}[-\s]?\d{2,}\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")

_STRONG_OVERLAP = 0.6
_PARTIAL_OVERLAP = 0.25

POLICY_ANSWER = "answer"
POLICY_REGENERATE = "regenerate_once"
POLICY_RETRY = "retry_retrieval"
POLICY_CONFLICT = "conflict"
POLICY_ABSTAIN = "abstain"

_NON_FACTUAL_PATTERNS: list[re.Pattern] = [
    re.compile(r"^\s*(hola|hello|hi|hey|buenas|buen d[ií]a|gracias|thanks|de nada)\b", re.I),
    re.compile(r"^\s*(¿|�?)?(te gustar[ií]a|quer[eé]s|podemos|necesit[aá]s|en qu[eé] m[aá]s)\b", re.I),
    re.compile(r"\b(creo que|en mi opini[oó]n|quiz[aá]s|tal vez|podr[ií]a ser)\b", re.I),
    re.compile(r"^\s*(\*\*|#|[-*]\s|referencias|fuentes|nota:)", re.I),
    re.compile(r"^\s*(no tengo|no hay|no existe|no encontr[eé])", re.I),
    re.compile(r"\?\s*$"),
]


class ClaimVerdict(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"
    NOT_VERIFIABLE = "not_verifiable"


@dataclass
class ClaimJudgment:
    text: str
    verdict: str = ClaimVerdict.NOT_VERIFIABLE.value
    confidence: float = 0.0
    factual: bool = True
    jev_used: bool = False
    reason: str = ""
    evidence_refs: tuple[str, ...] = ()
    support: bool | None = None
    contradiction: bool | None = None

    def to_public_dict(self) -> dict[str, Any]:
        """Sin CoT: claim, veredicto, señales y refs."""
        return {
            "text": self.text[:400],
            "verdict": self.verdict,
            "confidence": round(self.confidence, 4),
            "factual": self.factual,
            "jev_used": self.jev_used,
            "reason": self.reason,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass
class ClaimVerification:
    claims: list[ClaimJudgment] = field(default_factory=list)
    policy: str = POLICY_ANSWER
    jev_used: bool = False
    answers: dict[str, Any] = field(default_factory=dict)
    provider: str = "rules"
    model: str = ""
    latency_ms: float = 0.0

    @property
    def factual(self) -> list[ClaimJudgment]:
        return [c for c in self.claims if c.factual]

    @property
    def supported(self) -> list[ClaimJudgment]:
        return [c for c in self.claims if c.verdict == ClaimVerdict.SUPPORTED.value]

    @property
    def unsupported(self) -> list[ClaimJudgment]:
        return [c for c in self.claims if c.verdict == ClaimVerdict.UNSUPPORTED.value]

    @property
    def contradicted(self) -> list[ClaimJudgment]:
        return [c for c in self.claims if c.verdict == ClaimVerdict.CONTRADICTED.value]

    @property
    def not_verifiable(self) -> list[ClaimJudgment]:
        return [c for c in self.claims if c.verdict == ClaimVerdict.NOT_VERIFIABLE.value]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "jev_used": self.jev_used,
            "provider": self.provider,
            "model": self.model,
            "supported": len(self.supported),
            "unsupported": len(self.unsupported),
            "contradicted": len(self.contradicted),
            "not_verifiable": len(self.not_verifiable),
            "claims": [c.to_public_dict() for c in self.claims],
        }


def is_factual(text: str) -> bool:
    """Heurística: no penalizar saludos, formato, opiniones ni preguntas."""
    clean = (text or "").strip()
    if len(clean) < 8:
        return False
    if not _TOKEN_RE.search(normalize_query(clean)):
        return False
    return not any(pattern.search(clean) for pattern in _NON_FACTUAL_PATTERNS)


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(normalize_query(text)))


def _best_support(
    claim: str, items: list[EvidenceItem]
) -> tuple[float, EvidenceItem | None]:
    claim_tokens = _tokens(claim)
    if not claim_tokens:
        return 0.0, None
    best_ratio = 0.0
    best_item: EvidenceItem | None = None
    for item in items[:12]:
        content_tokens = _tokens(item.content or "")
        if not content_tokens:
            continue
        overlap = len(claim_tokens & content_tokens) / len(claim_tokens)
        if overlap > best_ratio:
            best_ratio = overlap
            best_item = item
    return best_ratio, best_item


def _numeric_mismatch(claim: str, item: EvidenceItem | None) -> bool:
    """Claim con números/códigos que el mejor candidato no contiene: no decide solo."""
    if item is None:
        return False
    codes = {code.lower() for code in _CODE_RE.findall(claim)}
    codes |= set(_NUMBER_RE.findall(claim))
    if not codes:
        return False
    content = (item.content or "").lower()
    return not all(code in content for code in codes)


def _refs(item: EvidenceItem | None) -> tuple[str, ...]:
    if item is None:
        return ()
    refs: list[str] = []
    if item.document_id:
        refs.append(f"doc:{item.document_id}")
    if item.chunk_id:
        refs.append(f"chunk:{item.chunk_id}")
    if item.citation:
        refs.append(item.citation)
    return tuple(refs[:4])


def deterministic_judgment(
    claim: str, items: list[EvidenceItem]
) -> ClaimJudgment:
    """Cheap first gate. Sólo decide los extremos; el medio va a JEV."""
    factual = is_factual(claim)
    if not factual:
        return ClaimJudgment(
            text=claim,
            verdict=ClaimVerdict.NOT_VERIFIABLE.value,
            factual=False,
            reason="non_factual",
            confidence=0.0,
        )
    if not items:
        return ClaimJudgment(
            text=claim,
            verdict=ClaimVerdict.UNSUPPORTED.value,
            factual=True,
            reason="no_evidence",
            confidence=0.0,
        )
    ratio, item = _best_support(claim, items)
    if ratio >= _STRONG_OVERLAP and not _numeric_mismatch(claim, item):
        return ClaimJudgment(
            text=claim,
            verdict=ClaimVerdict.SUPPORTED.value,
            factual=True,
            reason="deterministic_overlap",
            confidence=min(1.0, ratio),
            evidence_refs=_refs(item),
        )
    if _numeric_mismatch(claim, item):
        return ClaimJudgment(
            text=claim,
            verdict=ClaimVerdict.NOT_VERIFIABLE.value,
            factual=True,
            reason="numeric_mismatch",
            confidence=ratio,
            evidence_refs=_refs(item),
        )
    # Banda incierta: overlap parcial o nulo. JEV decide; sin JEV, la caída
    # determinística sólo promueve overlap parcial (nunca inventa soporte).
    return ClaimJudgment(
        text=claim,
        verdict=ClaimVerdict.NOT_VERIFIABLE.value,
        factual=True,
        reason="partial_overlap" if ratio >= _PARTIAL_OVERLAP else "uncertain_band",
        confidence=ratio,
        evidence_refs=_refs(item),
    )


def deterministic_fallback(judgment: ClaimJudgment) -> ClaimJudgment:
    """Sin JEV: el overlap parcial cuenta como soporte débil, nada más."""
    if (
        judgment.verdict == ClaimVerdict.NOT_VERIFIABLE.value
        and judgment.reason == "partial_overlap"
    ):
        judgment.verdict = ClaimVerdict.SUPPORTED.value
        judgment.reason = "deterministic_partial"
    return judgment


def response_policy(
    verification: ClaimVerification,
    *,
    regeneration_used: bool = False,
    retrieval_budget_left: int = 0,
    evidence_contradictions: int = 0,
) -> str:
    """Política de respuesta posterior a la verificación (sin loops infinitos)."""
    if evidence_contradictions > 0:
        # El Passage Judge marcó conflicto entre fuentes: nunca presentar como hecho.
        return POLICY_CONFLICT
    factual = verification.factual
    if not factual:
        return POLICY_ANSWER
    if verification.contradicted:
        return POLICY_CONFLICT
    unsupported = len(verification.unsupported)
    if unsupported == 0:
        return POLICY_ANSWER
    total = len(factual)
    ratio = unsupported / total if total else 0.0
    if unsupported <= 1 or ratio <= 0.25:
        return POLICY_ANSWER if regeneration_used else POLICY_REGENERATE
    if retrieval_budget_left > 0:
        return POLICY_RETRY
    return POLICY_ABSTAIN


def _claim_state(claims: list[str], evidence: EvidenceSet) -> dict[str, Any]:
    numbered = "\n".join(
        f"[{index}] {claim[:300]}" for index, claim in enumerate(claims)
    )
    return {
        "user_request": (evidence.query or "")[:2000],
        "claim_candidates": numbered[:3000],
        "evidence_preview": evidence.preview(2000),
        "n_items": evidence.size,
    }


async def verify_generation(
    *,
    judge: Any,
    answer: str,
    evidence: EvidenceSet,
    settings: AdaptiveRagSettings,
    organization_id: UUID | None = None,
    request_id: UUID | None = None,
    agent_id: UUID | None = None,
    cache: Any = None,
    grounding_answers: dict[str, Any] | None = None,
    regeneration_used: bool = False,
    retrieval_budget_left: int = 0,
    ask_grounding: bool = True,
    evidence_contradictions: int = 0,
) -> ClaimVerification:
    """Verifica el draft en UNA llamada POST_GENERATION (grounding + claims).

    Nunca lanza: sin JEV cae al veredicto determinístico y la política decide.
    """
    claims = [
        claim
        for claim in extract_claims(answer, max_claims=max(1, settings.claims_max))
        if claim
    ]
    verification = ClaimVerification(
        claims=[deterministic_judgment(claim, evidence.items) for claim in claims]
    )
    if not claims:
        return verification

    # Candidatos: claims factuales en banda incierta (el resto ya está resuelto).
    candidates = [
        c.text
        for c in verification.claims
        if c.factual and c.verdict == ClaimVerdict.NOT_VERIFIABLE.value
    ]
    answers = dict(grounding_answers or {})
    if judge is None or not settings.claims_enabled or (not candidates and not ask_grounding):
        for claim in verification.claims:
            deterministic_fallback(claim)
        verification.policy = response_policy(
            verification,
            regeneration_used=regeneration_used,
            retrieval_budget_left=retrieval_budget_left,
            evidence_contradictions=evidence_contradictions,
        )
        return verification

    phase = build_post_generation_questions(
        claims=candidates,
        include_presentation=bool(getattr(settings, "presentation_gate", True)),
    )
    state = _claim_state(candidates, evidence)
    questions = phase.to_jevy()
    try:
        payload = await call_phase_judge(
            judge,
            phase=PHASE_POST_GENERATION,
            state=state,
            questions=questions,
            context=JudgmentContext(
                phase=PHASE_POST_GENERATION,
                organization_id=organization_id,
                request_id=request_id,
                agent_id=agent_id,
            ),
            cache=cache,
        )
    except Exception:  # noqa: BLE001 — verificación nunca rompe el request
        payload = None
    if isinstance(payload, dict):
        answers = {**answers, **(payload.get("answers") or {})}
        verification.jev_used = True
        verification.provider = str(payload.get("provider") or "jev")
        verification.model = str(payload.get("model") or "")
        verification.latency_ms = float(payload.get("latency_ms") or 0.0)
        verification.answers = {
            key: value
            for key, value in answers.items()
            if str(key).startswith("claim_") or key == "answer_grounded"
        }
        for index, candidate in enumerate(candidates):
            judgment = next(c for c in verification.claims if c.text == candidate)
            support = noul_for(payload, f"claim_{index}_supported", default=None)
            contradiction = noul_for(
                payload, f"claim_{index}_contradicted", default=None
            )
            if support is None and contradiction is None:
                continue
            judgment.jev_used = True
            judgment.support = None if support is None else support >= 0.5
            judgment.contradiction = (
                None if contradiction is None else contradiction >= 0.5
            )
            if judgment.contradiction:
                judgment.verdict = ClaimVerdict.CONTRADICTED.value
                judgment.reason = "jev_contradicted"
                judgment.confidence = max(0.5, float(contradiction or 0.0))
            elif judgment.support:
                judgment.verdict = ClaimVerdict.SUPPORTED.value
                judgment.reason = "jev_supported"
                judgment.confidence = max(judgment.confidence, float(support or 0.0))
            elif judgment.support is False:
                judgment.verdict = ClaimVerdict.UNSUPPORTED.value
                judgment.reason = "jev_unsupported"
                judgment.confidence = max(judgment.confidence, 0.5)

    verification.policy = response_policy(
        verification,
        regeneration_used=regeneration_used,
        retrieval_budget_left=retrieval_budget_left,
        evidence_contradictions=evidence_contradictions,
    )
    _record_metrics(verification)
    return verification


def _record_metrics(verification: ClaimVerification) -> None:
    try:
        import src.infrastructure.observability.metrics as m

        for claim in verification.claims:
            m.zent_adaptive_claim_verdict_total.labels(verdict=claim.verdict).inc()
    except Exception:  # noqa: BLE001
        pass


# -----------------------------------------------------------------------------
# Claim Ledger — reutiliza ClaimRecord / ClaimLedgerRepository
# -----------------------------------------------------------------------------


def _normalized_parts(text: str) -> tuple[str, str]:
    """Sujeto/predicado heurísticos para el ledger (no es NLP)."""
    tokens = [t for t in normalize_query(text).split() if t]
    if not tokens:
        return "", ""
    subject = " ".join(tokens[:3])[:120]
    predicate = " ".join(tokens[3:])[:200] or subject
    return subject, predicate


def _ledger_status(verdict: str):
    from src.core.domain.evidence import ClaimVerificationStatus

    if verdict == ClaimVerdict.SUPPORTED.value:
        return ClaimVerificationStatus.SUPPORTED
    if verdict == ClaimVerdict.UNSUPPORTED.value:
        return ClaimVerificationStatus.UNSUPPORTED
    if verdict == ClaimVerdict.CONTRADICTED.value:
        return ClaimVerificationStatus.CONFLICTED
    return ClaimVerificationStatus.PROPOSED


async def record_claims_in_ledger(
    verification: ClaimVerification,
    *,
    organization_id: UUID,
    request_id: UUID | None = None,
    agent_id: UUID | None = None,
    repo: Any = None,
) -> int:
    """Upsert de claims verificados en el Claim Ledger existente.

    El repo llega por DI (el hook lo resuelve en la composición): `rag/` no
    importa adaptadores. Best-effort: un ledger caído nunca rompe el request.
    Guarda texto, veredicto, confianza, refs de evidencia y metadata de juicio;
    nunca chain-of-thought.
    """
    if not verification.claims:
        return 0
    if repo is None:
        _ledger_metric("unavailable")
        return 0
    try:
        from src.core.domain.catalog import CatalogProvenance
        from src.core.domain.evidence import ClaimRecord
    except Exception:  # noqa: BLE001
        _ledger_metric("unavailable")
        return 0
    written = 0
    for claim in verification.claims:
        if not claim.factual or claim.verdict == ClaimVerdict.NOT_VERIFIABLE.value:
            continue
        subject, predicate = _normalized_parts(claim.text)
        if not subject or not predicate:
            continue
        try:
            record = ClaimRecord(
                organization_id=organization_id,
                text=claim.text[:2000],
                normalized_subject=subject,
                normalized_predicate=predicate,
                status=_ledger_status(claim.verdict),
                confidence=min(1.0, max(0.0, float(claim.confidence))),
                provenance=CatalogProvenance.INFERRED,
                agent_id=agent_id,
                task_id=request_id,
                metadata={
                    "source": "adaptive_claim_verification",
                    "verdict": claim.verdict,
                    "reason": claim.reason,
                    "evidence_refs": list(claim.evidence_refs),
                    "provider": verification.provider,
                    "model": verification.model,
                    "jev_used": claim.jev_used,
                },
            )
            await repo.upsert(record)
            written += 1
        except Exception as exc:  # noqa: BLE001 — un claim fallido no corta el resto
            logger.warning("claim ledger upsert failed", error=str(exc)[:200])
            continue
    _ledger_metric("written" if written else "skipped")
    return written


def _ledger_metric(outcome: str) -> None:
    try:
        import src.infrastructure.observability.metrics as m

        m.zent_adaptive_claims_ledger_total.labels(outcome=outcome).inc()
    except Exception:  # noqa: BLE001
        pass
