# =============================================================================
# Grounding contracts — Knowledge V2 (brief §16, §17, §18)
# =============================================================================
# GroundedAnswer / Citation / Claim con estados de verificación. Cada claim
# relevante entra con evidencia (Citation); NO se exige cita tras cada palabra,
# sí soporte para afirmaciones factuales. UNSUPPORTED nunca inventa citation.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class ClaimStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONFLICTED = "CONFLICTED"


@dataclass(frozen=True, kw_only=True)
class Citation:
    """Cita de primera clase: locator estable a page/section/block (brief §17)."""

    source_id: UUID | None = None
    document_id: UUID | None = None
    document_name: str = ""
    page: int | None = None
    section_path: tuple[str, ...] = ()
    block_id: UUID | None = None
    chunk_id: UUID | None = None
    excerpt: str = ""
    char_range: tuple[int, int] | None = None
    relevance: float = 0.0

    @property
    def locator(self) -> str:
        parts: list[str] = []
        if self.document_name:
            parts.append(self.document_name)
        if self.page is not None:
            parts.append(f"página {self.page}")
        if self.section_path:
            parts.append("Sección " + ".".join(self.section_path))
        return " · ".join(parts) if parts else ""


@dataclass(frozen=True, kw_only=True)
class GroundedClaim:
    """Afirmación factual con estado de verificación (brief §18)."""

    text: str
    status: ClaimStatus
    supporting_citations: tuple[Citation, ...] = ()
    confidence: float = 0.0

    @property
    def verified(self) -> bool:
        return self.status in (
            ClaimStatus.SUPPORTED,
            ClaimStatus.PARTIALLY_SUPPORTED,
        )


@dataclass(frozen=True, kw_only=True)
class GroundedAnswer:
    """Respuesta grounded: answer + claims + citations (brief §16)."""

    answer: str
    claims: tuple[GroundedClaim, ...] = ()
    citations: tuple[Citation, ...] = ()
    confidence: float = 0.0
    missing_information: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    sources_used: tuple[UUID, ...] = ()

    @property
    def unsupported_claims(self) -> tuple[str, ...]:
        return tuple(
            c.text for c in self.claims if c.status is ClaimStatus.UNSUPPORTED
        )

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "confidence": round(self.confidence, 3),
            "claims": [
                {"text": c.text, "status": c.status.value, "confidence": round(c.confidence, 3)}
                for c in self.claims
            ],
            "citations": [
                {
                    "document_name": c.document_name,
                    "document_id": str(c.document_id) if c.document_id else None,
                    "page": c.page,
                    "section_path": list(c.section_path),
                    "locator": c.locator,
                    "relevance": round(c.relevance, 3),
                    "excerpt": c.excerpt[:300],
                }
                for c in self.citations
            ],
            "missing_information": list(self.missing_information),
            "conflicts": list(self.conflicts),
            "sources_used": [str(s) for s in self.sources_used],
        }
