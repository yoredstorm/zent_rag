# =============================================================================
# Fast path — extractive answer when evidence is highly reliable.
# =============================================================================
from __future__ import annotations

import re

from src.core.domain.adaptive import AdaptivePlan, EvidenceQuality, EvidenceSet

_CODE_RE = re.compile(r"\b[a-z]{1,4}[-\s]?\d{2,}\b", re.IGNORECASE)
_LOOKUP_RE = re.compile(
    r"\b(c[oó]digo|sku|id|identificador|carrier|clave|code)\b",
    re.IGNORECASE,
)


def should_fast_path(plan: AdaptivePlan, quality: EvidenceQuality) -> bool:
    if plan.path != "fast":
        return False
    if not quality.sufficient:
        return False
    if quality.exact_match:
        return True
    return quality.max_retrieval_score >= 0.85 and quality.coverage >= 0.4


def extract_answer(query: str, evidence: EvidenceSet) -> str | None:
    if not evidence.items:
        return None
    top = evidence.items[0]
    content = top.content or ""
    if not content.strip():
        return None
    code_in_query = _CODE_RE.search(query or "")
    if code_in_query:
        needle = code_in_query.group(0)
        for item in evidence.items[:4]:
            if needle.lower() in (item.content or "").lower():
                return _sentence_with(item.content, needle)
    if _LOOKUP_RE.search(query or ""):
        match = _CODE_RE.search(content)
        if match:
            return _sentence_with(content, match.group(0))
    snippet = " ".join(content.split())
    if len(snippet) <= 280:
        return snippet
    return None


def _sentence_with(content: str, needle: str) -> str:
    parts = re.split(r"(?<=[\.\!\?])\s+", content)
    for part in parts:
        if needle.lower() in part.lower():
            return part.strip()[:400]
    return " ".join(content.split())[:280]
