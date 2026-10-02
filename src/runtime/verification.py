# =============================================================================
# AnswerVerifier — verificación determinista de la respuesta (S9, C4).
# =============================================================================
# Extrae claims por oración y las contrasta con el paquete de evidencia por
# overlap de tokens. Declara soporte, conflicto y desactualización; NUNCA
# reescribe la respuesta (el enforcement de políticas es C5).
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass

from src.runtime.evidence_assembly import EvidencePackage

DEFAULT_SUPPORT_THRESHOLD = 0.6
DEFAULT_PARTIAL_THRESHOLD = 0.25
MAX_CLAIMS = 12

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+")
_TOKEN_RE = re.compile(r"[\wÁÉÍÓÚÑáéíóúñ]{3,}", re.UNICODE)


@dataclass(frozen=True)
class ClaimVerdict:
    text: str
    status: str
    support: float
    unit_ids: tuple[str, ...] = ()
    reason: str = ""

    def to_public_dict(self) -> dict:
        return {
            "text": self.text[:200],
            "status": self.status,
            "support": round(float(self.support), 4),
            "unit_ids": list(self.unit_ids),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class AnswerVerification:
    verdicts: tuple[ClaimVerdict, ...] = ()
    action: str = "approve"
    supported: int = 0
    partially_supported: int = 0
    unsupported: int = 0
    conflicted: int = 0
    outdated: int = 0

    def to_public_dict(self, *, max_claims: int = 8) -> dict:
        return {
            "action": self.action,
            "count": len(self.verdicts),
            "supported": self.supported,
            "partially_supported": self.partially_supported,
            "unsupported": self.unsupported,
            "conflicted": self.conflicted,
            "outdated": self.outdated,
            "claims": [
                verdict.to_public_dict()
                for verdict in self.verdicts[: max(0, max_claims)]
            ],
        }


def extract_claims(answer: str, *, max_claims: int = MAX_CLAIMS) -> tuple[str, ...]:
    """Claims por oración, determinista, sin duplicados ni vacíos."""
    claims: list[str] = []
    seen: set[str] = set()
    for raw in _SENTENCE_SPLIT.split(answer or ""):
        text = " ".join(raw.split())
        if len(text) < 12:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        claims.append(text)
        if len(claims) >= max(0, int(max_claims)):
            break
    return tuple(claims)


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text or "")}


def support_ratio(text: str, evidence_texts: list[str]) -> float:
    """Overlap de tokens del claim contra el mejor fragmento (0..1)."""
    claim_tokens = _tokens(text)
    if not claim_tokens:
        return 0.0
    best = 0.0
    for evidence in evidence_texts:
        evidence_tokens = _tokens(evidence)
        if not evidence_tokens:
            continue
        overlap = len(claim_tokens & evidence_tokens) / len(claim_tokens)
        if overlap > best:
            best = overlap
    return best


def _classify(
    claim: str,
    package: EvidencePackage,
    *,
    support_threshold: float,
    partial_threshold: float,
) -> ClaimVerdict:
    scored: list[tuple[float, object]] = []
    for unit in package.units:
        ratio = support_ratio(claim, [unit.text])
        if ratio > 0:
            scored.append((ratio, unit))
    scored.sort(key=lambda entry: (-entry[0], str(getattr(entry[1], "unit_id", ""))))
    if not scored:
        return ClaimVerdict(claim, "unsupported", 0.0, reason="sin_evidencia")
    best_ratio, best_unit = scored[0]
    best_ids = tuple(
        str(getattr(unit, "unit_id", ""))
        for ratio, unit in scored
        if ratio >= partial_threshold
    )
    if best_ratio < partial_threshold:
        return ClaimVerdict(
            claim, "unsupported", best_ratio, reason="overlap_insuficiente"
        )
    if best_ratio < support_threshold:
        return ClaimVerdict(
            claim, "partially_supported", best_ratio, unit_ids=best_ids, reason="parcial"
        )
    conflict_units = [
        unit for ratio, unit in scored
        if ratio >= support_threshold and bool(getattr(unit, "conflict", False))
    ]
    if conflict_units:
        return ClaimVerdict(
            claim, "conflicted", best_ratio, unit_ids=best_ids, reason="conflicto_retenido"
        )
    if str(getattr(best_unit, "validity", "") or "") == "historical":
        has_current = any(
            ratio >= partial_threshold
            and str(getattr(unit, "validity", "") or "") == "current"
            for ratio, unit in scored
        )
        if not has_current:
            return ClaimVerdict(
                claim,
                "outdated",
                best_ratio,
                unit_ids=best_ids,
                reason="solo_evidencia_historica",
            )
    return ClaimVerdict(
        claim, "supported", best_ratio, unit_ids=best_ids, reason="overlap"
    )


def verify_answer(
    answer: str,
    package: EvidencePackage,
    *,
    support_threshold: float = DEFAULT_SUPPORT_THRESHOLD,
    partial_threshold: float = DEFAULT_PARTIAL_THRESHOLD,
) -> AnswerVerification:
    """Veredicto por claim + acción sugerida. No modifica la respuesta."""
    claims = extract_claims(answer)
    if not claims:
        return AnswerVerification()
    verdicts = tuple(
        _classify(
            claim,
            package,
            support_threshold=support_threshold,
            partial_threshold=partial_threshold,
        )
        for claim in claims
    )
    supported = sum(1 for verdict in verdicts if verdict.status == "supported")
    partially = sum(1 for verdict in verdicts if verdict.status == "partially_supported")
    unsupported = sum(1 for verdict in verdicts if verdict.status == "unsupported")
    conflicted = sum(1 for verdict in verdicts if verdict.status == "conflicted")
    outdated = sum(1 for verdict in verdicts if verdict.status == "outdated")
    total = len(verdicts)
    unsupported_ratio = unsupported / total
    if total >= 3 and supported == 0:
        action = "abstain"
    elif unsupported_ratio > 0.5:
        action = "revise"
    elif conflicted or outdated or unsupported:
        action = "answer_with_limits"
    else:
        action = "approve"
    return AnswerVerification(
        verdicts=verdicts,
        action=action,
        supported=supported,
        partially_supported=partially,
        unsupported=unsupported,
        conflicted=conflicted,
        outdated=outdated,
    )
