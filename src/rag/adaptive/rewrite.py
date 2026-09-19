# =============================================================================
# Conditional query rewrite. Codes never rewrite. JEV Noul only if rules unsure.
# =============================================================================
from __future__ import annotations

import re

from src.decision.questions import noul_is_yes
from src.rag.adaptive.settings import AdaptiveRagSettings
from src.rag.retrieval.classify import classify_query

_PRONOUN_RE = re.compile(
    r"\b(eso|esto|esa|esta|ese|aquel|aquella|that|this|those|these|it)\b",
    re.IGNORECASE,
)
_CODE_RE = re.compile(r"\b[a-z]{1,4}[-\s]?\d{2,}\b", re.IGNORECASE)


def rules_need_rewrite(query: str) -> bool | None:
    """True / False when rules are certain. None = ask JEV if available."""
    text = (query or "").strip()
    if not text:
        return False
    if _CODE_RE.search(text):
        return False
    kind = classify_query(text).kind
    if kind == "lexical":
        return False
    tokens = text.split()
    if _PRONOUN_RE.search(text) and len(tokens) <= 12:
        return True
    if len(tokens) <= 2 and kind == "semantic":
        return True
    if kind == "semantic" and len(tokens) >= 4:
        return False
    return None


def rewrite_needed_from_jev(noul_value: float | None, settings: AdaptiveRagSettings) -> bool:
    if noul_value is None:
        return False
    return noul_is_yes(noul_value, settings.noul_yes)


_REWRITE_PROMPT = """Reformulate the user question for document retrieval.
Keep the same language. Do not answer. Output only the rewritten question.
Question: {query}
"""


async def maybe_rewrite(
    query: str,
    *,
    needed: bool,
    llm=None,
    model: str | None = None,
) -> str | None:
    if not needed or llm is None:
        return None
    prompt = _REWRITE_PROMPT.format(query=(query or "")[:1500])
    try:
        response = await llm.generate(
            prompt=prompt,
            model=model,
            max_tokens=80,
            temperature=0.0,
            system_prompt="You rewrite retrieval queries. Never answer the question.",
        )
    except Exception:  # noqa: BLE001
        return None
    text = (getattr(response, "content", None) or "").strip()
    if not text or text.lower() == (query or "").strip().lower():
        return None
    return text[:500]
