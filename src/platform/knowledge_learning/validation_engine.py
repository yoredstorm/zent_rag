# =============================================================================
# Validation Engine — respuestas humanas -> conocimiento reutilizable (F33D)
# =============================================================================
# Una respuesta NO es solo conversación: se propaga al catálogo, léxico,
# reglas de negocio, enums, verified queries y relaciones. Después se recalcula
# el score/gate y, si no quedan preguntas bloqueantes, el run se completa.
#
# Human-in-the-loop: solo una persona puede marcar APPROVED; el motor nunca
# auto-aprueba interpretaciones de negocio.
# =============================================================================
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from src.catalog.store import PostgresCatalogStore
from src.core.domain.catalog import FieldRole
from src.core.domain.knowledge_learning import (
    FeedbackSource,
    KnowledgeEventType,
    KnowledgeGate,
    QuestionStatus,
    QuestionType,
)
from src.infrastructure.observability.logging_config import get_logger
from src.platform.knowledge_learning.events import KnowledgeEventEmitter
from src.platform.knowledge_learning.repository import (
    PostgresKnowledgeLearningRepository,
)

logger = get_logger(__name__)

_BLOCKING_PRIORITIES = ["critical", "high"]
_VALID_ROLES = {role.value for role in FieldRole}


class QuestionAlreadyResolvedError(RuntimeError):
    """La pregunta ya fue respondida, saltada o diferida."""


class KnowledgeValidationEngine:
    """Aplica respuestas humanas y propaga el conocimiento resultante."""

    def __init__(
        self,
        store: PostgresCatalogStore,
        repository: PostgresKnowledgeLearningRepository,
        *,
        score_service=None,
        intelligence_store=None,
    ) -> None:
        self._store = store
        self._repo = repository
        self._score = score_service
        self._intel = intelligence_store
        self._events = KnowledgeEventEmitter(repository)

    # ------------------------------------------------------------------ answer
    async def answer(
        self,
        organization_id: UUID,
        question_id: UUID,
        *,
        answer_text: str,
        structured_answer: dict | None = None,
        answered_by: UUID | None = None,
    ) -> dict | None:
        question = await self._repo.get_question(organization_id, question_id)
        if question is None:
            return None
        if question.get("status") != QuestionStatus.PENDING.value:
            raise QuestionAlreadyResolvedError(question.get("status") or "resolved")
        structured = structured_answer or {}

        applied = await self._apply_knowledge(
            organization_id, question, structured, answered_by=answered_by
        )
        updated = await self._repo.update_question_status(
            organization_id,
            question_id,
            status=QuestionStatus.ANSWERED.value,
            answer={"text": answer_text, "options": structured.get("choice")},
            structured_answer=structured,
            answered_by=answered_by,
            confidence_after=1.0,
        )
        feedback = await self._repo.insert_feedback(
            organization_id,
            question_id=question_id,
            run_id=UUID(question["run_id"]) if question.get("run_id") else None,
            source_id=UUID(question["source_id"]) if question.get("source_id") else None,
            knowledge_type=question.get("question_type") or "question",
            knowledge_id=str(question.get("field_id") or question.get("column_id") or question_id),
            question=question.get("title") or "",
            answer=answer_text or "",
            structured_answer=structured,
            source=FeedbackSource.QUESTION.value,
            applied=bool(applied),
            applied_to=applied,
            created_by=answered_by,
        )
        await self._emit(
            organization_id,
            KnowledgeEventType.KNOWLEDGE_CONFIRMED,
            run_id=question.get("run_id"),
            source_id=question.get("source_id"),
            stage=None,
            message=(
                f"Conocimiento confirmado: {question.get('title')}"
                if not answer_text
                else f"Conocimiento confirmado: {answer_text[:160]}"
            ),
            payload={
                "question_id": str(question_id),
                "question_type": question.get("question_type"),
                "applied_to": applied,
            },
        )
        recalculation = await self._recalculate(
            organization_id, question, applied, answered_by=answered_by
        )
        return {
            "question": updated,
            "feedback": feedback,
            "applied_to": applied,
            "recalculation": recalculation,
        }

    # -------------------------------------------------------------- skip/defer
    async def skip(
        self,
        organization_id: UUID,
        question_id: UUID,
        *,
        reason: str | None = None,
        acted_by: UUID | None = None,
    ) -> dict | None:
        return await self._resolve_without_answer(
            organization_id,
            question_id,
            status=QuestionStatus.SKIPPED.value,
            reason=reason,
            acted_by=acted_by,
        )

    async def defer(
        self,
        organization_id: UUID,
        question_id: UUID,
        *,
        reason: str | None = None,
        acted_by: UUID | None = None,
    ) -> dict | None:
        return await self._resolve_without_answer(
            organization_id,
            question_id,
            status=QuestionStatus.DEFERRED.value,
            reason=reason,
            acted_by=acted_by,
        )

    async def _resolve_without_answer(
        self,
        organization_id: UUID,
        question_id: UUID,
        *,
        status: str,
        reason: str | None,
        acted_by: UUID | None,
    ) -> dict | None:
        question = await self._repo.get_question(organization_id, question_id)
        if question is None:
            return None
        if question.get("status") != QuestionStatus.PENDING.value:
            raise QuestionAlreadyResolvedError(question.get("status") or "resolved")
        updated = await self._repo.update_question_status(
            organization_id,
            question_id,
            status=status,
            structured_answer={"reason": reason} if reason else {},
            answered_by=acted_by,
        )
        feedback = await self._repo.insert_feedback(
            organization_id,
            question_id=question_id,
            run_id=UUID(question["run_id"]) if question.get("run_id") else None,
            source_id=UUID(question["source_id"]) if question.get("source_id") else None,
            knowledge_type=question.get("question_type") or "question",
            knowledge_id=str(question.get("id")),
            question=question.get("title") or "",
            answer=reason or status,
            structured_answer={"reason": reason} if reason else {},
            source=FeedbackSource.QUESTION.value,
            applied=False,
            applied_to=[],
            created_by=acted_by,
        )
        recalculation = await self._recalculate(
            organization_id, question, [], answered_by=acted_by
        )
        return {
            "question": updated,
            "feedback": feedback,
            "applied_to": [],
            "recalculation": recalculation,
        }

    # --------------------------------------------------------------- knowledge
    async def _apply_knowledge(
        self,
        organization_id: UUID,
        question: dict,
        structured: dict,
        *,
        answered_by: UUID | None,
    ) -> list[dict]:
        applied: list[dict] = []
        question_type = question.get("question_type") or QuestionType.OTHER.value

        # Memoria de léxico (aprendizaje continuo por tenant, sección 10).
        for token, meaning in _lexicon_pairs(structured):
            try:
                await self._store.upsert_lexicon_entry(
                    organization_id=organization_id,
                    token=token,
                    meaning=meaning,
                    role=str(structured.get("role") or "UNKNOWN")[:40],
                    status="approved",
                    created_by=answered_by,
                )
                applied.append(
                    {
                        "kind": "lexicon",
                        "token": token,
                        "meaning": meaning,
                        "detail": "término aprobado por respuesta humana",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Lexicon apply failed", error=str(exc)[:200])

        if question_type == QuestionType.ENUM_MEANING.value:
            applied.extend(
                await self._apply_enum_meaning(
                    organization_id, question, structured, answered_by=answered_by
                )
            )
        elif question_type == QuestionType.FIELD_AMBIGUITY.value:
            applied.extend(
                await self._apply_field_choice(
                    organization_id, question, structured
                )
            )
        elif question_type == QuestionType.TABLE_VARIANT.value:
            applied.extend(
                await self._apply_table_variant(
                    organization_id, question, structured, answered_by=answered_by
                )
            )
        elif question_type == QuestionType.TAX_INCLUSION.value:
            applied.extend(
                await self._apply_tax_inclusion(
                    organization_id, question, structured, answered_by=answered_by
                )
            )
        elif question_type == QuestionType.RELATIONSHIP_MEANING.value:
            applied.extend(
                await self._apply_relationship_meaning(
                    organization_id, question, structured
                )
            )
        else:
            applied.extend(
                await self._apply_generic_answer(
                    organization_id, question, structured, answered_by=answered_by
                )
            )
        return applied

    async def _apply_enum_meaning(
        self,
        organization_id: UUID,
        question: dict,
        structured: dict,
        *,
        answered_by: UUID | None,
    ) -> list[dict]:
        applied: list[dict] = []
        column_id = question.get("column_id") or (
            (question.get("answer_schema") or {}).get("column_id")
        )
        if not column_id:
            return applied
        mapping = structured.get("mapping") or structured.get("values") or {}
        if not isinstance(mapping, dict):
            mapping = {}
        single_meaning = structured.get("meaning")
        selected = structured.get("selected_values") or []
        if single_meaning and selected:
            mapping = {str(value): str(single_meaning) for value in selected}
        for value, meaning in mapping.items():
            if not meaning:
                continue
            try:
                await self._store.upsert_enum_meaning(
                    organization_id=organization_id,
                    column_id=UUID(str(column_id)),
                    value=str(value)[:200],
                    meaning=str(meaning)[:400],
                    reviewed_by=answered_by,
                )
                applied.append(
                    {
                        "kind": "enum_meaning",
                        "value": str(value),
                        "meaning": str(meaning),
                        "detail": "significado de valor aprobado",
                    }
                )
                await self._record_mapping_suggestion(
                    organization_id, UUID(str(column_id)), str(value), str(meaning)
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Enum meaning apply failed", error=str(exc)[:200])
        return applied

    async def _record_mapping_suggestion(
        self,
        organization_id: UUID,
        column_id: UUID,
        value: str,
        meaning: str,
    ) -> None:
        try:
            from src.core.domain.verified_query import (
                MappingSuggestion,
                MappingSuggestionStatus,
            )
            from src.intelligence.verified_query_store import (
                PostgresVerifiedQueryStore,
            )

            column = await self._store.get_column(organization_id, column_id)
            predicate = f"{(column or {}).get('column_name', 'col')} = '{value}'"
            await PostgresVerifiedQueryStore().upsert_mapping_suggestion(
                MappingSuggestion(
                    organization_id=organization_id,
                    concept=meaning,
                    entity_type="ENUM",
                    physical_predicate=predicate,
                    evidence_count=1,
                    evidence_sample=[value],
                    status=MappingSuggestionStatus.INFERRED,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Enum mapping suggestion skipped", error=str(exc)[:200])

    async def _apply_field_choice(
        self,
        organization_id: UUID,
        question: dict,
        structured: dict,
    ) -> list[dict]:
        applied: list[dict] = []
        field_id = question.get("field_id")
        if not field_id:
            return applied
        field = await self._store.get_field(organization_id, UUID(field_id))
        if field is None or field.get("status") == "approved":
            return applied
        chosen = str(
            structured.get("role")
            or structured.get("choice")
            or structured.get("value")
            or ""
        ).upper()
        role = chosen if chosen in _VALID_ROLES else None
        scores = dict(field.get("signal_scores") or {})
        if isinstance(scores, str):
            try:
                scores = json.loads(scores)
            except (TypeError, ValueError):
                scores = {}
        scores.pop("llm_role_conflict", None)
        scores["human_confirmed"] = 1.0
        synonyms = list(field.get("synonyms") or [])
        business_name = str(structured.get("business_name") or "").strip()
        if business_name and business_name not in synonyms:
            synonyms.append(business_name)
        updated = await self._store.update_field_semantics(
            organization_id,
            UUID(field_id),
            role=role,
            confidence="high",
            synonyms=synonyms,
            signal_scores=scores,
        )
        if updated:
            applied.append(
                {
                    "kind": "field_semantics",
                    "field_id": str(field_id),
                    "role": role,
                    "detail": "rol de campo confirmado por humano",
                }
            )
        return applied

    async def _apply_table_variant(
        self,
        organization_id: UUID,
        question: dict,
        structured: dict,
        *,
        answered_by: UUID | None,
    ) -> list[dict]:
        applied: list[dict] = []
        is_history = structured.get("is_history")
        if isinstance(is_history, str):
            is_history = is_history.strip().lower() in ("yes", "true", "1", "si", "sí")
        if not is_history:
            return applied
        table_id = question.get("catalog_table_id")
        table = (
            await self._store.get_table(organization_id, UUID(table_id))
            if table_id
            else None
        )
        note = str(structured.get("note") or "").strip()
        table_name = (table or {}).get("qualified_name") or "la tabla"
        definition = note or f"{table_name} contiene información histórica."
        rule = await self._repo.upsert_business_rule(
            organization_id,
            name=f"{table_name} contiene histórico",
            definition=definition,
            applies_to=[table_name],
            provenance="APPROVED",
            confidence="high",
            source="human_question",
            created_by=answered_by,
            learned_run_id=UUID(question["run_id"]) if question.get("run_id") else None,
        )
        applied.append(
            {
                "kind": "business_rule",
                "rule_id": rule["id"],
                "detail": "regla de histórico aprobada por humano",
            }
        )
        if table and table_id:
            entities = await self._store.list_entities(organization_id, limit=2000)
            entity = next(
                (e for e in entities if e.get("mapped_table_id") == str(table_id)),
                None,
            )
            if entity is not None and entity.get("status") != "approved":
                description = entity.get("description") or ""
                addition = f"{definition}"
                new_description = (
                    description
                    if addition in description
                    else (f"{description} {addition}".strip())[:4000]
                )
                await self._store.update_entity_semantics(
                    organization_id,
                    UUID(entity["id"]),
                    description=new_description,
                )
                applied.append(
                    {
                        "kind": "entity_description",
                        "entity_id": entity["id"],
                        "detail": "descripción enriquecida con contexto histórico",
                    }
                )
        return applied

    async def _apply_tax_inclusion(
        self,
        organization_id: UUID,
        question: dict,
        structured: dict,
        *,
        answered_by: UUID | None,
    ) -> list[dict]:
        applied: list[dict] = []
        raw = structured.get("includes_tax")
        if raw is None:
            return applied
        if isinstance(raw, str):
            normalized = raw.strip().lower()
            if normalized == "partial":
                includes = None
                detail = "depende del caso"
            else:
                includes = normalized in ("yes", "true", "1", "si", "sí")
                detail = "incluye impuestos" if includes else "no incluye impuestos"
        else:
            includes = bool(raw)
            detail = "incluye impuestos" if includes else "no incluye impuestos"
        schema = question.get("answer_schema") or {}
        column = schema.get("column") or "importe"
        tax_columns = schema.get("tax_columns") or []
        definition = (
            f"{column} {'incluye' if includes else 'no incluye'} impuestos"
            if includes is not None
            else f"{column} incluye impuestos según el caso"
        )
        rule = await self._repo.upsert_business_rule(
            organization_id,
            name=f"{column} incluye impuestos",
            definition=definition + ".",
            applies_to=[str(column), *[str(t) for t in tax_columns]],
            provenance="APPROVED",
            confidence="high",
            source="human_question",
            created_by=answered_by,
            learned_run_id=UUID(question["run_id"]) if question.get("run_id") else None,
        )
        applied.append(
            {
                "kind": "business_rule",
                "rule_id": rule["id"],
                "detail": detail,
            }
        )
        return applied

    async def _apply_relationship_meaning(
        self,
        organization_id: UUID,
        question: dict,
        structured: dict,
    ) -> list[dict]:
        applied: list[dict] = []
        rel_id = question.get("relationship_id")
        verb = str(structured.get("business_verb") or "").strip()
        if not rel_id or not verb:
            return applied
        updated = await self._store.update_relationship_business(
            organization_id,
            UUID(rel_id),
            business_verb=verb[:40],
            business_from=structured.get("business_from"),
            business_to=structured.get("business_to"),
        )
        if updated:
            applied.append(
                {
                    "kind": "relationship_business",
                    "relationship_id": str(rel_id),
                    "business_verb": verb,
                    "detail": "verbo de negocio confirmado",
                }
            )
        return applied

    async def _apply_generic_answer(
        self,
        organization_id: UUID,
        question: dict,
        structured: dict,
        *,
        answered_by: UUID | None,
    ) -> list[dict]:
        applied: list[dict] = []
        concept = str(structured.get("concept") or "").strip()
        definition = str(structured.get("definition") or "").strip()
        if concept and definition and self._intel is not None:
            try:
                await self._intel.upsert_definition(
                    organization_id=organization_id,
                    concept=concept,
                    definition=definition,
                    data_type=str(structured.get("data_type") or "concept"),
                    status="approved",
                    created_by=answered_by,
                    approved_by=answered_by,
                    provenance="APPROVED",
                )
                applied.append(
                    {
                        "kind": "glossary_term",
                        "concept": concept,
                        "detail": "definición aprobada por humano",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Definition apply failed", error=str(exc)[:200])
        rule_name = str(structured.get("rule") or "").strip()
        rule_definition = str(structured.get("rule_definition") or "").strip()
        if rule_name and rule_definition:
            rule = await self._repo.upsert_business_rule(
                organization_id,
                name=rule_name,
                definition=rule_definition,
                applies_to=structured.get("applies_to") or [],
                provenance="APPROVED",
                confidence="high",
                source="human_question",
                created_by=answered_by,
                learned_run_id=UUID(question["run_id"]) if question.get("run_id") else None,
            )
            applied.append(
                {
                    "kind": "business_rule",
                    "rule_id": rule["id"],
                    "detail": "regla aprobada por humano",
                }
            )
        return applied

    # -------------------------------------------------------- recalculations
    async def _recalculate(
        self,
        organization_id: UUID,
        question: dict,
        applied: list[dict],
        *,
        answered_by: UUID | None,
    ) -> dict:
        affected_columns = {
            str(entry.get("column_id"))
            for entry in applied
            if entry.get("column_id")
        }
        if question.get("column_id"):
            affected_columns.add(str(question["column_id"]))

        await self._boost_dependent_hypotheses(
            organization_id, question, applied
        )

        score_payload: dict | None = None
        source_id = question.get("source_id")
        if self._score is not None and source_id:
            try:
                result = await self._score.compute(
                    organization_id,
                    source_id=UUID(source_id),
                    run_id=UUID(question["run_id"]) if question.get("run_id") else None,
                    active_run={},
                    persist=True,
                )
                score_payload = result.to_dict()
                await self._emit(
                    organization_id,
                    KnowledgeEventType.SCORE_COMPUTED,
                    run_id=question.get("run_id"),
                    source_id=source_id,
                    stage=None,
                    message=(
                        f"Knowledge Readiness recalculado: "
                        f"{result.overall:.0f}% ({result.gate.value})."
                    ),
                    payload={
                        "overall": result.overall,
                        "gate": result.gate.value,
                        "trigger": "human_validation",
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Score recalculation failed", error=str(exc)[:200])

        run_completed = False
        pending_blocking = 0
        run_id = question.get("run_id")
        if run_id:
            pending_blocking = await self._repo.count_pending_questions(
                organization_id,
                run_id=UUID(run_id),
                priorities=_BLOCKING_PRIORITIES,
            )
            if pending_blocking == 0:
                run = await self._repo.get_run(organization_id, UUID(run_id))
                if run is not None and run.get("status") == "awaiting_validation":
                    gate = (
                        (score_payload or {}).get("gate")
                        or run.get("gate")
                        or KnowledgeGate.NOT_READY.value
                    )
                    await self._repo.update_run(
                        organization_id,
                        UUID(run_id),
                        status="completed",
                        current_stage="ready",
                        overall_progress=100,
                        stage_progress=100,
                        gate=gate,
                        finished_at=datetime.now(timezone.utc),
                    )
                    run_completed = True
                    await self._emit(
                        organization_id,
                        KnowledgeEventType.LEARNING_COMPLETED,
                        run_id=run_id,
                        source_id=source_id,
                        stage="ready",
                        message=(
                            "Validación humana completada: el run terminó "
                            f"con gate {gate}."
                        ),
                        severity="success",
                        payload={"source": "human_validation", "gate": gate},
                    )
        return {
            "score": score_payload,
            "pending_blocking_questions": pending_blocking,
            "run_completed": run_completed,
            "affected_columns": sorted(affected_columns),
            "answered_by": str(answered_by) if answered_by else None,
        }

    async def _boost_dependent_hypotheses(
        self,
        organization_id: UUID,
        question: dict,
        applied: list[dict],
    ) -> None:
        """Propaga la validación humana a campos y relaciones dependientes."""
        affected_field_ids = {
            str(entry.get("field_id"))
            for entry in applied
            if entry.get("kind") == "field_semantics" and entry.get("field_id")
        }
        affected_columns = {
            str(question.get("column_id")) if question.get("column_id") else None
        }
        affected_columns.discard(None)

        try:
            fields = await self._store.list_fields_all(organization_id, limit=5000)
        except Exception:  # noqa: BLE001
            fields = []
        for fld in fields:
            interested = str(fld["id"]) in affected_field_ids or (
                fld.get("mapped_column_id")
                and str(fld["mapped_column_id"]) in affected_columns
            )
            if not interested or fld.get("status") == "approved":
                continue
            scores = dict(fld.get("signal_scores") or {})
            if isinstance(scores, str):
                try:
                    scores = json.loads(scores)
                except (TypeError, ValueError):
                    scores = {}
            scores.pop("llm_role_conflict", None)
            scores["human_confirmed"] = 1.0
            await self._store.update_field_semantics(
                organization_id,
                UUID(fld["id"]),
                confidence="high",
                signal_scores=scores,
            )

        source_id = question.get("source_id")
        if not source_id:
            return
        try:
            relationships = await self._store.list_relationships(
                organization_id, UUID(source_id), limit=5000
            )
        except Exception:  # noqa: BLE001
            return
        affected_names = set()
        for entry in applied:
            if entry.get("value"):
                affected_names.add(str(entry["value"]).lower())
        for rel in relationships:
            if rel.get("provenance") in ("APPROVED", "REJECTED"):
                continue
            touched = (
                rel.get("from_column")
                and str(rel["from_column"]).lower() in affected_names
            ) or (
                rel.get("to_column") and str(rel["to_column"]).lower() in affected_names
            )
            if not touched:
                continue
            evidence = list(rel.get("evidence") or [])
            note = "validación humana"
            if note not in evidence:
                evidence.append(note)
            await self._store.update_relationship_intelligence(
                organization_id,
                UUID(rel["id"]),
                provenance=rel.get("provenance") or "INFERRED",
                confidence_score=min(
                    0.99, float(rel.get("confidence_score") or 0.0) + 0.03
                ),
                evidence=evidence,
                evidence_detail=list(rel.get("evidence_detail") or [])
                + [
                    {
                        "signal": "human_validation",
                        "weight": 0.03,
                        "detail": "confirmada por una persona",
                    }
                ],
                cardinality=rel.get("cardinality"),
                semantic_similarity=rel.get("semantic_similarity"),
            )

    async def _emit(
        self,
        organization_id: UUID,
        event_type: KnowledgeEventType,
        *,
        run_id: UUID | str | None,
        source_id: UUID | str | None,
        stage: str | None,
        message: str,
        severity: str = "success",
        payload: dict | None = None,
    ) -> None:
        try:
            await self._events.emit(
                organization_id=organization_id,
                event_type=event_type.value,
                message=message,
                run_id=UUID(run_id) if run_id else None,
                source_id=UUID(source_id) if source_id else None,
                stage=stage,
                severity=severity,
                payload=payload,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Validation event emit failed",
                event_type=event_type.value,
                error=str(exc)[:200],
            )


def _lexicon_pairs(structured: dict) -> list[tuple[str, str]]:
    raw = structured.get("lexicon")
    pairs: list[tuple[str, str]] = []
    if isinstance(raw, dict):
        for token, meaning in raw.items():
            if token and meaning:
                pairs.append((str(token), str(meaning)))
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("token") and item.get("meaning"):
                pairs.append((str(item["token"]), str(item["meaning"])))
    return pairs
