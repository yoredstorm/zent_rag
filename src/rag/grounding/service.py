# =============================================================================
# Claim Verification + Grounding service — Knowledge V2 (brief §18, §16)
# =============================================================================
# Extrae claims de la respuesta (heurística por oraciones), los verifica contra
# el AssembledContext (overlap de tokens determinista; LLM-judge opcional en un
# slice posterior) y ensambla el GroundedAnswer con citas y faltantes.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass

from src.rag.grounding.citations import build_citations, instrument_answer
from src.rag.grounding.models import (
    Citation,
    ClaimStatus,
    GroundedAnswer,
    GroundedClaim,
)
from src.rag.retrieval.structured import AssembledContext

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_TOKEN_SPLIT_RE = re.compile(r"[\W_]+", re.UNICODE)


@dataclass(frozen=True, kw_only=True)
class VerificationConfig:
    supported_ratio: float = 0.6
    partial_ratio: float = 0.25
    min_claim_chars: int = 8
    evidence_window: int = 12
    max_claims: int = 12


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_SPLIT_RE.split(text.lower()) if t}


def extract_claims(answer: str, *, max_claims: int = 12) -> list[str]:
    """Extrae afirmaciones factuales candidatas (oraciones heurísticas)."""
    claims: list[str] = []
    for sentence in _SENTENCE_RE.split(answer.strip()):
        clean = sentence.strip().strip("[],;")
        if len(clean) < 8:
            continue
        if clean.startswith(("**", "#", "-", "Referencias", "Fuentes")):
            continue
        claims.append(clean)
        if len(claims) >= max_claims:
            break
    return claims


def _best_support(
    claim_tokens: set[str], chunks
) -> tuple[float, object | None]:
    best_ratio = 0.0
    best_chunk = None
    for chunk in chunks:
        content_tokens = _tokens(chunk.content)
        if not content_tokens or not claim_tokens:
            continue
        overlap = len(claim_tokens & content_tokens) / len(claim_tokens)
        if overlap > best_ratio:
            best_ratio = overlap
            best_chunk = chunk
    return best_ratio, best_chunk


class ClaimVerifier:
    """Verificación determinista: cada claim debe tener soporte en el contexto."""

    def __init__(self, config: VerificationConfig | None = None) -> None:
        self._config = config or VerificationConfig()

    def verify(
        self,
        answer: str,
        assembled: AssembledContext,
        *,
        citations: list[Citation] | None = None,
    ) -> list[GroundedClaim]:
        verified: list[GroundedClaim] = []
        evidence_chunks = list(assembled.children) + list(assembled.parents)
        for claim_text in extract_claims(answer, max_claims=self._config.max_claims):
            ratio, supporting_chunk = _best_support(_tokens(claim_text), evidence_chunks)
            if ratio >= self._config.supported_ratio:
                status = ClaimStatus.SUPPORTED
            elif ratio >= self._config.partial_ratio:
                status = ClaimStatus.PARTIALLY_SUPPORTED
            else:
                status = ClaimStatus.UNSUPPORTED
            supporting: tuple[Citation, ...] = ()
            if (
                supporting_chunk is not None
                and status in (ClaimStatus.SUPPORTED, ClaimStatus.PARTIALLY_SUPPORTED)
            ):
                from src.rag.grounding.citations import citation_from_chunk

                supporting = (citation_from_chunk(supporting_chunk, relevance=ratio),)
            elif status is not ClaimStatus.UNSUPPORTED:
                # conservador: sin chunk ni citation → no afirmar soporte
                status = ClaimStatus.PARTIALLY_SUPPORTED
            verified.append(
                GroundedClaim(
                    text=claim_text,
                    status=status,
                    supporting_citations=supporting,
                    confidence=ratio,
                )
            )
        return verified


class GroundingService:
    """Ensambla el GroundedAnswer a partir del contexto estructurado (brief §16)."""

    def __init__(self, verifier: ClaimVerifier | None = None) -> None:
        self._verifier = verifier or ClaimVerifier()

    def ground(
        self,
        answer: str,
        assembled: AssembledContext,
        *,
        max_cites: int = 8,
    ) -> GroundedAnswer:
        citations = build_citations(assembled, limit=max_cites)
        claims = self._verifier.verify(answer, assembled, citations=citations)
        verdicts = [c.status for c in claims]
        supported_count = sum(1 for v in verdicts if v in (
            ClaimStatus.SUPPORTED,
            ClaimStatus.PARTIALLY_SUPPORTED,
        ))
        confidence = supported_count / len(verdicts) if verdicts else 0.0

        missing = tuple(c.text for c in claims if c.status is ClaimStatus.UNSUPPORTED)
        conflicts = tuple(
            c.text for c in claims if c.status is ClaimStatus.CONFLICTED
        )
        sources_used = tuple(
            dict.fromkeys(c.document_id for c in citations if c.document_id)
        )
        return GroundedAnswer(
            answer=answer,
            claims=tuple(claims),
            citations=tuple(citations),
            confidence=confidence,
            missing_information=missing,
            conflicts=conflicts,
            sources_used=sources_used,
        )

    def instrument(
        self,
        answer: str,
        citations: list[Citation],
        *,
        max_cites: int = 8,
    ) -> tuple[str, list[Citation]]:
        return instrument_answer(answer, citations, max_cites=max_cites)
