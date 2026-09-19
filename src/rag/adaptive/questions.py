# =============================================================================
# Adaptive RAG atomic JEV questions — decide, never generate.
# =============================================================================
# Official TypeSafe: one snap judgment per question; same state; compose in code.
# Evidence questions are a SECOND request: they depend on retrieved state.
# =============================================================================
from __future__ import annotations

MODALITY_CRITERIA: dict[str, str] = {
    "documents": "Unstructured documents, policies, manuals, PDFs, or knowledge-base text.",
    "structured_data": "Tables, SQL, CSV, Excel, metrics, counts, or row lookups.",
    "mixed": "Needs both documents and structured records.",
    "tool": "Needs an external tool or API call, not retrieval.",
    "workflow": "Needs starting or resuming a workflow.",
    "conversational": "Greeting, chit-chat, or meta talk with no retrieval.",
}

STRATEGY_CRITERIA: dict[str, str] = {
    "exact": "Identifier, SKU, code, email, or quoted string that should match exactly.",
    "lexical": "Keyword or sparse search should dominate.",
    "vector": "Natural-language semantic search should dominate.",
    "hybrid": "Blend lexical and vector retrieval.",
    "structured": "SQL or tabular lookup, not vector search.",
    "mixed": "Combine structured lookup with document retrieval.",
}


def build_query_questions() -> dict[str, dict]:
    """First JEV request: query understanding only. No evidence yet."""
    return {
        "modality": {
            "type": "choice",
            "instructions": "Which data modality does `user_request` need?",
            "criteria": MODALITY_CRITERIA,
        },
        "retrieval_strategy": {
            "type": "choice",
            "instructions": (
                "Which retrieval strategy should run for `user_request` "
                "given `classification_kind`?"
            ),
            "criteria": STRATEGY_CRITERIA,
        },
        "needs_rewrite": {
            "type": "noul",
            "instructions": (
                "Does `user_request` need reformulation before retrieval? "
                "Codes, SKUs, and already-specific questions do not."
            ),
        },
        "needs_reasoning": {
            "type": "noul",
            "instructions": (
                "Does `user_request` require multi-document comparison "
                "or contradiction analysis rather than a lookup?"
            ),
        },
    }


def build_evidence_questions() -> dict[str, dict]:
    """Second JEV request: depends on retrieved evidence_preview."""
    return {
        "evidence_sufficient": {
            "type": "noul",
            "instructions": (
                "Does `evidence_preview` contain enough information to answer "
                "`user_request` without inventing facts?"
            ),
        },
        "evidence_on_topic": {
            "type": "noul",
            "instructions": (
                "Does `evidence_preview` appear to belong to the topic of "
                "`user_request`?"
            ),
        },
        "evidence_direct": {
            "type": "noul",
            "instructions": (
                "Is there direct evidence in `evidence_preview` for the main "
                "claim implied by `user_request`?"
            ),
        },
        "evidence_quality": {
            "type": "score",
            "instructions": "Quality of `evidence_preview` for answering `user_request`.",
            "criteria": [
                "empty or off-topic",
                "weak or partial",
                "adequate",
                "strong and direct",
            ],
        },
    }


def build_grounding_questions() -> dict[str, dict]:
    return {
        "answer_grounded": {
            "type": "noul",
            "instructions": (
                "Are the factual claims in `draft_answer` supported by "
                "`evidence_preview`? If the answer says evidence is missing, yes."
            ),
        }
    }


def public_answers(raw: dict | None) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for key, val in raw.items():
        if not isinstance(val, dict):
            continue
        item = {"type": val.get("type")}
        for field in ("choice", "score", "noul", "confidence"):
            if field in val:
                item[field] = val[field]
        out[str(key)[:64]] = item
    return out
