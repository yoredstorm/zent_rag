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
from src.decision.batch import build_post_retrieval_questions
from src.decision.judgment import PHASE_EVIDENCE, JudgmentContext, call_phase_judge
from src.decision.questions import noul_is_no, noul_is_uncertain, noul_is_yes
from src.rag.adaptive.questions import build_evidence_questions, public_answers
from src.rag.adaptive.settings import AdaptiveRagSettings
from src.rag.retrieval.classify import normalize_query
from src.runtime.evidence import (
    ACTION_GENERATE,
    ACTION_RETRIEVE_MORE,
    DEFAULT_BUDGET_CHARS,
    evidence_state_text,
)

_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_CODE_RE = re.compile(r"\b[a-z]{1,4}[-\s]?\d{2,}\b", re.IGNORECASE)


def evidence_from_chunks(chunks: list[RetrievalChunk] | None) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for index, chunk in enumerate(chunks or []):
        meta = chunk.metadata or {}
        doc_id = str(chunk.document_id)
        section_path = meta.get("section_path")
        if isinstance(section_path, str):
            section_path = (section_path,)
        retrieval = str(meta.get("retrieval") or "")
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
                title=str(
                    meta.get("filename")
                    or meta.get("title")
                    or meta.get("external_id")
                    or meta.get("source")
                    or ""
                )
                or None,
                page=meta.get("page_start") if isinstance(meta.get("page_start"), int) else None,
                section_path=tuple(str(part) for part in (section_path or ()) if part),
                retrieval_method=retrieval,
                entity_pin=retrieval.startswith("entity"),
                authority=str(meta.get("authority") or "") or None,
                knowledge_type=str(meta.get("knowledge_type") or "") or None,
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


def entity_signals(
    query: str,
    items: list[EvidenceItem],
) -> dict[str, Any]:
    """Señales objetivas de entidades: qué pidió la pregunta y qué trae la evidencia.

    No es una inferencia: regex + contención de texto sobre los fragmentos
    recuperados. Devuelve cobertura 1.0 y `exact_entity_match` cuando TODAS las
    entidades pedidas aparecen en la evidencia.
    """
    try:
        from src.intelligence.response.entities import asked_entities, entity_covered
    except Exception:  # noqa: BLE001 — sin extractor, no se inventan señales
        return {}
    if not items:
        return {}
    entities = asked_entities(query)
    if not entities:
        return {}
    joined = "\n".join(item.content or "" for item in items)
    asked = [entity.label for entity in entities]
    covered = [entity.label for entity in entities if entity_covered(entity, joined)]
    missing = [label for label in asked if label not in covered]
    return {
        "entities_asked": tuple(asked),
        "entities_covered": tuple(covered),
        "missing_entities": tuple(missing),
        "entity_coverage": len(covered) / len(asked),
        "exact_entity_match": not missing,
    }


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
            has_evidence=False,
            recommended_action=ACTION_RETRIEVE_MORE,
            supporting_chunks=0,
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
    authority = any(
        str((item.metadata or {}).get("authority") or "").strip() for item in items
    )
    freshness = any(str(item.freshness or "").strip() for item in items)
    entity = entity_signals(evidence.query or "", items)
    entity_exact = bool(entity.get("exact_entity_match"))
    entity_coverage = entity.get("entity_coverage")
    if entity_exact:
        # La pregunta nombra «categoría 31 byte 105» y la evidencia los menciona:
        # regla determinística fuerte, JEV no la puede revertir (sólo pedir lo
        # que falte de OTRAS entidades).
        sufficient = True
        reason = "entity_match"
        quality = min(1.0, 0.65 + 0.35 * max_score)
    elif has_sql and max_score >= 0.99:
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
    if authority:
        quality = min(1.0, quality + 0.05)
    if freshness:
        quality = min(1.0, quality + 0.03)
    return EvidenceQuality(
        sufficient=sufficient,
        score=quality,
        max_retrieval_score=max_score,
        mean_retrieval_score=mean_score,
        coverage=coverage,
        source_diversity=len(docs),
        exact_match=exact,
        reason=reason,
        authority=authority,
        freshness=freshness,
        has_evidence=True,
        entity_coverage=entity_coverage,
        entities_asked=entity.get("entities_asked", ()),
        entities_covered=entity.get("entities_covered", ()),
        missing_entities=entity.get("missing_entities", ()),
        exact_entity_match=entity.get("exact_entity_match"),
        supporting_chunks=len(items),
        recommended_action=ACTION_GENERATE if sufficient else ACTION_RETRIEVE_MORE,
    )


def apply_passage_summary(quality: EvidenceQuality, passages: Any) -> None:
    """El evidence gate consume el Passage Judge sin sobrescribir reglas fuertes."""
    if passages is None:
        return
    from src.rag.adaptive.passages import summarize

    summary = summarize(passages)
    quality.passage_relevance = float(summary["passage_relevance"])
    quality.contradictions = int(summary["contradictions"])
    quality.injection_suspected = int(summary["injection_suspected"])
    quality.conflicting_chunks = int(summary["contradictions"])
    if quality.reason in {"structured", "exact_match", "entity_match"}:
        # Regla determinística fuerte: JEV/reglas de passage no la pisan. Si la
        # pregunta nombra «categoría 31 byte 105» y la evidencia los contiene, la
        # evidencia existe aunque el judge dude.
        return
    if summary["judged"] and summary["kept"] == 0:
        quality.sufficient = False
        quality.reason = "passages_dropped"
        quality.score = min(quality.score, 0.2)


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
        passages: Any = None,
        state_char_budget: int = DEFAULT_BUDGET_CHARS,
    ) -> EvidenceQuality:
        quality = evaluate_deterministic(evidence, self._settings)
        if passages is not None:
            apply_passage_summary(quality, passages)
        if not self._settings.jev_evidence_enabled or self._judge is None:
            return quality
        if quality.reason in {"empty", "structured", "exact_match", "entity_match"}:
            return quality
        uncertain = noul_is_uncertain(
            quality.score, 0.7, 0.35
        ) or quality.reason == "weak"
        if not uncertain:
            return quality
        # JEV ve la MISMA evidencia que verá el generador (fragmentos completos
        # elegidos por relevancia), no un preview de 240 chars por ítem: el
        # veredicto no puede degradarse por el recorte del juez.
        evidence_text, selection = evidence_state_text(
            evidence.items,
            evidence.query,
            budget_chars=max(500, int(state_char_budget or 0) or DEFAULT_BUDGET_CHARS),
        )
        state = {
            "user_request": (evidence.query or "")[:2000],
            "evidence": evidence_text or evidence.preview(1500),
            "evidence_index": "; ".join(
                f"{item.evidence_id} · {item.label}" for item in selection.items[:12]
            ),
            "n_items": evidence.size,
            "max_score": quality.max_retrieval_score,
            "coverage": quality.coverage,
            "organization_id": str(organization_id) if organization_id else "",
        }
        if quality.entity_coverage is not None:
            state["entity_coverage"] = quality.entity_coverage
            state["entities_asked"] = list(quality.entities_asked)[:6]
            state["entities_covered"] = list(quality.entities_covered)[:6]
            if quality.missing_entities:
                state["missing_entities"] = list(quality.missing_entities)[:6]
        batch_questions = None
        questions = build_evidence_questions()
        if passages is not None and getattr(passages, "candidates", None):
            # Una sola llamada POST_RETRIEVAL: evidence gate + passage judge.
            from src.rag.adaptive.passages import passage_state

            state = {
                **passage_state(evidence, passages),
                "evidence": evidence_text or state["evidence"],
                "max_score": quality.max_retrieval_score,
                "coverage": quality.coverage,
                "organization_id": str(organization_id) if organization_id else "",
            }
            questions = build_post_retrieval_questions(
                passages=passages.candidates
            ).to_jevy()
        try:
            payload = await call_phase_judge(
                self._judge,
                phase=PHASE_EVIDENCE,
                state=state,
                questions=questions,
                batch_questions=batch_questions,
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
        if passages is not None:
            passages.apply_jev_answers(payload)
            apply_passage_summary(quality, passages)
        answers = payload.get("answers") if isinstance(payload.get("answers"), dict) else payload
        if not isinstance(answers, dict):
            return quality
        sufficient_noul = _noul(answers.get("evidence_sufficient"))
        on_topic = _noul(answers.get("evidence_on_topic"))
        quality.jev_used = True
        quality.jev_answers = public_answers(answers)
        if sufficient_noul is not None and noul_is_no(sufficient_noul, self._settings.noul_no):
            if quality.exact_entity_match:
                # La pregunta y la evidencia coinciden en las entidades nombradas:
                # el veredicto negativo de JEV no puede borrar ese hecho medido.
                quality.reason = "entity_match"
                quality.sufficient = True
                return quality
            quality.sufficient = False
            quality.reason = "jev_insufficient"
            quality.score = min(quality.score, 0.3)
            quality.recommended_action = ACTION_RETRIEVE_MORE
        elif (
            sufficient_noul is not None
            and noul_is_yes(sufficient_noul, self._settings.noul_yes)
            and (on_topic is None or not noul_is_no(on_topic, self._settings.noul_no))
        ):
            quality.sufficient = True
            quality.reason = "jev_sufficient"
            quality.score = max(quality.score, 0.7)
            quality.recommended_action = ACTION_GENERATE
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
