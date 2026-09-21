# =============================================================================
# EvidenceItem / EvidenceSet / EvidenceEvaluator.
# Deterministic metrics first. JEV only when the band is uncertain.
# =============================================================================
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from src.core.domain.adaptive import EvidenceItem, EvidenceQuality, EvidenceSet
from src.core.domain.entities import RetrievalChunk, RetrievalContext
from src.decision.judgment import PHASE_EVIDENCE, JudgmentContext, call_judge
from src.decision.questions import noul_is_no, noul_is_uncertain, noul_is_yes
from src.rag.adaptive.questions import build_evidence_questions, public_answers
from src.rag.adaptive.settings import AdaptiveRagSettings
from src.rag.retrieval.classify import normalize_query

_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_CODE_RE = re.compile(r"\b[a-z]{1,4}[-\s]?\d{2,}\b", re.IGNORECASE)


def evidence_from_chunks(chunks: list[RetrievalChunk] | None) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for index, chunk in enumerate(chunks or []):
        meta = chunk.metadata or {}
        doc_id = str(chunk.document_id)
        items.append(
            EvidenceItem(
                source_type="qdrant",
                content=chunk.content or "",
                score=float(chunk.score or 0.0),
                source_id=str(meta.get("source_id") or "") or None,
                document_id=doc_id,
                chunk_id=str(meta.get("chunk_id") or doc_id),
                metadata={k: str(v)[:200] for k, v in list(meta.items())[:12]},
                freshness=str(meta.get("freshness") or meta.get("updated_at") or "") or None,
                citation=f"[Doc: {index + 1}]",
            )
        )
    return items


def evidence_from_sql(sql_result: Any | None) -> list[EvidenceItem]:
    if sql_result is None:
        return []
    error = getattr(sql_result, "error", None)
    if error:
        return []
    rows = list(getattr(sql_result, "rows", None) or [])
    columns = list(getattr(sql_result, "columns", None) or [])
    if not rows:
        return []
    preview_rows = rows[:8]
    lines = []
    header = ", ".join(str(c) for c in columns[:16])
    if header:
        lines.append(header)
    for row in preview_rows:
        lines.append(" | ".join(str(cell)[:80] for cell in list(row)[:16]))
    meta = getattr(sql_result, "metadata", None) or {}
    tables = meta.get("tables") if isinstance(meta, dict) else None
    table = None
    if isinstance(tables, list) and tables:
        table = str(tables[0])
    elif isinstance(tables, str):
        table = tables
    return [
        EvidenceItem(
            source_type="sql",
            content="\n".join(lines),
            score=1.0,
            table=table,
            row_ref=f"rows={int(getattr(sql_result, 'row_count', len(rows)) or 0)}",
            metadata={"strategy": str(meta.get("strategy") or "")} if isinstance(meta, dict) else {},
            citation="[SQL]",
        )
    ]


def build_evidence_set(
    *,
    query: str,
    retrieval: RetrievalContext | None,
    sql_result: Any | None = None,
) -> EvidenceSet:
    items = evidence_from_chunks(retrieval.chunks if retrieval is not None else None)
    items.extend(evidence_from_sql(sql_result))
    return EvidenceSet(items=items, query=query)


def _content_tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(normalize_query(text)))


def evaluate_deterministic(
    evidence: EvidenceSet,
    settings: AdaptiveRagSettings,
) -> EvidenceQuality:
    items = evidence.items
    if not items:
        return EvidenceQuality(
            sufficient=False,
            score=0.0,
            reason="empty",
        )
    scores = [max(0.0, float(item.score)) for item in items]
    max_score = max(scores)
    mean_score = sum(scores) / len(scores)
    query_tokens = _content_tokens(evidence.query)
    joined = " ".join(item.content for item in items[:12])
    evidence_tokens = _content_tokens(joined)
    if query_tokens:
        coverage = len(query_tokens & evidence_tokens) / len(query_tokens)
    else:
        coverage = 0.0
    code_match = _CODE_RE.search(evidence.query or "")
    exact = False
    if code_match:
        needle = code_match.group(0).lower()
        exact = any(needle in (item.content or "").lower() for item in items[:6])
    docs = {item.document_id or item.table or item.source_type for item in items}
    has_sql = any(item.source_type == "sql" for item in items)
    if has_sql and max_score >= 0.99:
        sufficient = True
        reason = "structured"
        quality = 0.9
    elif exact and max_score >= settings.evidence_min_score:
        sufficient = True
        reason = "exact_match"
        quality = min(1.0, 0.55 + max_score * 0.4)
    elif max_score >= settings.evidence_min_score and coverage >= settings.evidence_min_coverage:
        sufficient = True
        reason = "coverage"
        quality = min(1.0, 0.4 * max_score + 0.4 * coverage + 0.2 * min(1.0, mean_score))
    elif max_score >= max(settings.evidence_min_score, 0.5) and mean_score >= 0.2:
        sufficient = True
        reason = "high_score"
        quality = min(1.0, max_score)
    else:
        sufficient = False
        reason = "weak"
        quality = min(1.0, 0.5 * max_score + 0.5 * coverage)
    return EvidenceQuality(
        sufficient=sufficient,
        score=quality,
        max_retrieval_score=max_score,
        mean_retrieval_score=mean_score,
        coverage=coverage,
        source_diversity=len(docs),
        exact_match=exact,
        reason=reason,
    )


class EvidenceEvaluator:
    def __init__(self, settings: AdaptiveRagSettings, *, judge=None) -> None:
        self._settings = settings
        self._judge = judge

    async def evaluate(
        self,
        evidence: EvidenceSet,
        *,
        organization_id: UUID | None = None,
        request_id: UUID | None = None,
    ) -> EvidenceQuality:
        quality = evaluate_deterministic(evidence, self._settings)
        if not self._settings.jev_evidence_enabled or self._judge is None:
            return quality
        if quality.reason in {"empty", "structured", "exact_match"}:
            return quality
        uncertain = noul_is_uncertain(
            quality.score, 0.7, 0.35
        ) or quality.reason == "weak"
        if not uncertain:
            return quality
        state = {
            "user_request": (evidence.query or "")[:2000],
            "evidence_preview": evidence.preview(1500),
            "n_items": evidence.size,
            "max_score": quality.max_retrieval_score,
            "coverage": quality.coverage,
            "organization_id": str(organization_id) if organization_id else "",
        }
        try:
            payload = await call_judge(
                self._judge,
                state=state,
                questions=build_evidence_questions(),
                context=JudgmentContext(
                    phase=PHASE_EVIDENCE,
                    organization_id=organization_id,
                    request_id=request_id,
                ),
            )
        except Exception:  # noqa: BLE001
            return quality
        if not isinstance(payload, dict):
            return quality
        answers = payload.get("answers") if isinstance(payload.get("answers"), dict) else payload
        if not isinstance(answers, dict):
            return quality
        sufficient_noul = _noul(answers.get("evidence_sufficient"))
        on_topic = _noul(answers.get("evidence_on_topic"))
        quality.jev_used = True
        quality.jev_answers = public_answers(answers)
        if sufficient_noul is not None and noul_is_no(sufficient_noul, self._settings.noul_no):
            quality.sufficient = False
            quality.reason = "jev_insufficient"
            quality.score = min(quality.score, 0.3)
        elif (
            sufficient_noul is not None
            and noul_is_yes(sufficient_noul, self._settings.noul_yes)
            and (on_topic is None or not noul_is_no(on_topic, self._settings.noul_no))
        ):
            quality.sufficient = True
            quality.reason = "jev_sufficient"
            quality.score = max(quality.score, 0.7)
        return quality


def _noul(raw: Any) -> float | None:
    if not isinstance(raw, dict):
        return None
    if "noul" not in raw:
        return None
    try:
        return float(raw["noul"])
    except (TypeError, ValueError):
        return None
