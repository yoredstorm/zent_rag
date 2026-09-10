# =============================================================================
# Business Analyzer — fusión híbrida determinista + LLM (FASE 33B)
# =============================================================================
# Convierte la hipótesis semántica del LLM en enriquecimiento REAL del catálogo:
#   - entidades/campos draft: descripción, rol, synonyms, signal_scores, confianza
#   - sugerencias revisables: business_rule, metric_proposal, glossary_term,
#     relationship_candidate, field_mapping
#
# Reglas inquebrantables:
#   - NUNCA se toca conocimiento APPROVED (los métodos del store lo garantizan),
#   - NUNCA se auto-aprueba una interpretación de negocio,
#   - el LLM complementa la heurística; no la reemplaza ni la borra,
#   - si LLM y heurística discrepan, la confianza baja y se registra el conflicto.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from src.catalog.store import PostgresCatalogStore
from src.core.domain.catalog import (
    CatalogSuggestion,
    FieldRole,
    SuggestionType,
)
from src.infrastructure.observability.logging_config import get_logger
from src.platform.knowledge_learning.llm_analyzer import (
    PROMPT_VERSION,
    LLMTableAnalysis,
    TableContext,
)

logger = get_logger(__name__)

_MIN_ENRICH_CONFIDENCE = 0.5
_MAX_SUGGESTIONS_PER_TABLE = 12
_CONFIDENCE_LABEL = {"high": 2, "medium": 1, "low": 0}


def _label_for(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"


def _merge_confidence(current: str, llm_score: float, *, agrees: bool) -> str:
    base = _CONFIDENCE_LABEL.get(current, 0)
    llm_label = _CONFIDENCE_LABEL.get(_label_for(llm_score), 0)
    if agrees:
        return ("low", "medium", "high")[max(base, llm_label)]
    # Desacuerdo: nunca subir, y bajar si el LLM está muy seguro.
    if llm_score >= 0.8 and base == 2:
        return "medium"
    return current


def _merge_synonyms(existing: list[str], new_values: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for value in [*(existing or []), *(new_values or [])]:
        text = str(value).strip()[:160]
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            merged.append(text)
    return merged[:20]


@dataclass
class BusinessAnalysisOutcome:
    entity_enriched: bool = False
    fields_enriched: int = 0
    field_updates: list[dict] = field(default_factory=list)
    suggestions_created: int = 0
    suggestions_by_type: dict[str, int] = field(default_factory=dict)
    questions_detected: int = 0
    ambiguities_detected: int = 0

    def to_metrics(self) -> dict:
        return {
            "entity_enriched": self.entity_enriched,
            "fields_enriched": self.fields_enriched,
            "suggestions_created": self.suggestions_created,
            "suggestions_by_type": dict(self.suggestions_by_type),
            "questions_detected": self.questions_detected,
            "ambiguities_detected": self.ambiguities_detected,
        }


class BusinessAnalyzer:
    """Aplica el análisis LLM sobre el catálogo semántico existente."""

    def __init__(self, store: PostgresCatalogStore) -> None:
        self._store = store

    async def apply(
        self,
        organization_id: UUID,
        *,
        source_id: UUID,
        run_id: UUID | None,
        analysis: dict,
        context: TableContext,
    ) -> BusinessAnalysisOutcome:
        outcome = BusinessAnalysisOutcome()
        try:
            parsed = LLMTableAnalysis.model_validate(analysis or {}).normalize()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Business analysis payload invalid", error=str(exc)[:200])
            return outcome

        table_id = UUID(context.table["id"])
        entity = await self._entity_for_table(organization_id, table_id)

        if entity is not None:
            outcome.entity_enriched = await self._enrich_entity(
                organization_id, entity, parsed
            )
        else:
            created = await self._suggest_entity(organization_id, source_id, parsed)
            outcome.suggestions_created += created

        if entity is not None:
            field_outcome = await self._enrich_fields(
                organization_id,
                source_id,
                entity_id=UUID(entity["id"]),
                table_columns=context.columns,
                parsed=parsed,
            )
            outcome.fields_enriched += field_outcome["enriched"]
            outcome.field_updates.extend(field_outcome["updates"])
            outcome.suggestions_created += field_outcome["suggestions"]
            outcome.suggestions_by_type["field_mapping"] = field_outcome["suggestions"]

        rules = await self._create_business_rules(
            organization_id, source_id, parsed
        )
        outcome.suggestions_by_type["business_rule"] = rules

        metrics = await self._create_metric_proposals(
            organization_id, source_id, parsed
        )
        outcome.suggestions_by_type["metric_proposal"] = metrics

        glossary = await self._create_glossary_suggestions(
            organization_id, source_id, parsed
        )
        outcome.suggestions_by_type["glossary_term"] = glossary

        rels = await self._create_relationship_suggestions(
            organization_id, source_id, context, parsed
        )
        outcome.suggestions_by_type["relationship_candidate"] = rels

        outcome.suggestions_created += rules + metrics + glossary + rels
        outcome.questions_detected = len(parsed.questions)
        outcome.ambiguities_detected = len(parsed.ambiguities)
        return outcome

    # ------------------------------------------------------------------ entity
    async def _entity_for_table(
        self, organization_id: UUID, table_id: UUID
    ) -> dict | None:
        try:
            entities = await self._store.list_entities(organization_id, limit=1000)
        except Exception:  # noqa: BLE001
            return None
        for entity in entities:
            if entity.get("mapped_table_id") == str(table_id):
                return entity
        return None

    async def _enrich_entity(
        self,
        organization_id: UUID,
        entity: dict,
        parsed: LLMTableAnalysis,
    ) -> bool:
        if entity.get("status") == "approved":
            return False  # nunca tocar conocimiento aprobado
        llm_entity = parsed.entity
        if llm_entity is None or llm_entity.confidence < _MIN_ENRICH_CONFIDENCE:
            return False

        existing_name = entity.get("name", "")
        display = entity.get("display_name") or existing_name
        new_display = llm_entity.business_name.strip() or display
        description = entity.get("description") or ""
        # Solo reemplazar descripciones genéricas o vacías.
        is_generic = (not description) or description.startswith("Entidad inferida")
        new_description = (
            llm_entity.description.strip()[:4000] if is_generic and llm_entity.description else None
        )
        agrees = llm_entity.business_name.lower().replace(" ", "") == existing_name.lower().replace(" ", "")
        confidence = _merge_confidence(entity.get("confidence") or "low", llm_entity.confidence, agrees=agrees)
        evidence = _merge_synonyms(
            list(entity.get("evidence") or []),
            [
                f"llm:{PROMPT_VERSION}:{llm_entity.reasoning_summary[:160]}"
                if llm_entity.reasoning_summary
                else f"llm:{PROMPT_VERSION}",
                *[f"llm_evidence:{e[:150]}" for e in llm_entity.evidence[:6]],
            ],
        )
        return await self._store.update_entity_semantics(
            organization_id,
            UUID(entity["id"]),
            display_name=new_display[:160],
            description=new_description,
            confidence=confidence,
            evidence=evidence,
        )

    async def _suggest_entity(
        self,
        organization_id: UUID,
        source_id: UUID,
        parsed: LLMTableAnalysis,
    ) -> int:
        llm_entity = parsed.entity
        if llm_entity is None or not llm_entity.name.strip():
            return 0
        if llm_entity.confidence < _MIN_ENRICH_CONFIDENCE:
            return 0
        await self._store.create_suggestion(
            CatalogSuggestion(
                organization_id=organization_id,
                type=SuggestionType.ENTITY_IDENTIFICATION,
                title=f"El LLM propone la entidad '{llm_entity.name[:120]}' para esta tabla.",
                description=(
                    llm_entity.description
                    or llm_entity.business_purpose
                    or "Hipótesis semántica del LLM sobre metadata; requiere revisión humana."
                )[:1000],
                evidence=[
                    f"llm:{PROMPT_VERSION}",
                    *[e[:150] for e in llm_entity.evidence[:6]],
                ],
                confidence=_label_for(llm_entity.confidence),
                payload={
                    "source": "llm",
                    "prompt_version": PROMPT_VERSION,
                    "entity_name": llm_entity.name,
                    "business_name": llm_entity.business_name,
                    "business_purpose": llm_entity.business_purpose,
                    "confidence_score": llm_entity.confidence,
                    "reasoning_summary": llm_entity.reasoning_summary,
                },
                affected_sources=[str(source_id)],
            )
        )
        return 1

    # ------------------------------------------------------------------ fields
    async def _enrich_fields(
        self,
        organization_id: UUID,
        source_id: UUID,
        *,
        entity_id: UUID,
        table_columns: list[dict],
        parsed: LLMTableAnalysis,
    ) -> dict:
        updates: list[dict] = []
        suggestions = 0
        if not parsed.fields:
            return {"enriched": 0, "updates": updates, "suggestions": 0}

        columns_by_name = {c.get("column_name", ""): c for c in table_columns}
        try:
            existing_fields = await self._store.list_fields(organization_id, entity_id)
        except Exception:  # noqa: BLE001
            existing_fields = []
        fields_by_column = {
            f.get("mapped_column_id"): f
            for f in existing_fields
            if f.get("mapped_column_id")
        }
        fields_by_name = {f.get("name", "").lower(): f for f in existing_fields}
        valid_roles = {role.value for role in FieldRole}

        for llm_field in parsed.fields[:200]:
            if llm_field.confidence < _MIN_ENRICH_CONFIDENCE:
                continue
            column = columns_by_name.get(llm_field.physical_column)
            if column is None:
                continue  # el LLM no puede inventar columnas
            commercial_name = (llm_field.business_name or "").replace(" ", "")
            existing = fields_by_column.get(column["id"]) or fields_by_name.get(
                commercial_name.lower()
            )

            if existing is None:
                if commercial_name:
                    await self._store.create_suggestion(
                        CatalogSuggestion(
                            organization_id=organization_id,
                            type=SuggestionType.FIELD_MAPPING,
                            title=(
                                f"El LLM propone '{commercial_name[:120]}' "
                                f"para la columna {llm_field.physical_column}."
                            ),
                            description=llm_field.description[:1000]
                            or "Hipótesis de campo del LLM; requiere revisión humana.",
                            evidence=[
                                f"llm:{PROMPT_VERSION}",
                                *[e[:150] for e in llm_field.evidence[:5]],
                            ],
                            confidence=_label_for(llm_field.confidence),
                            payload={
                                "source": "llm",
                                "column_id": column["id"],
                                "mapped_column_id": column["id"],
                                "physical_name": llm_field.physical_column,
                                "business_name": commercial_name,
                                "role": llm_field.role,
                                "confidence_score": llm_field.confidence,
                                "reasoning_summary": llm_field.reasoning_summary,
                            },
                            affected_sources=[str(source_id)],
                        )
                    )
                    suggestions += 1
                continue

            if existing.get("status") == "approved":
                continue

            existing_role = (existing.get("role") or "UNKNOWN").upper()
            llm_role = llm_field.role.upper() if llm_field.role else ""
            role_agrees = (
                existing_role == llm_role
                or existing_role == "UNKNOWN"
                or llm_role not in valid_roles
            )
            confidence = _merge_confidence(
                existing.get("confidence") or "low",
                llm_field.confidence,
                agrees=role_agrees,
            )
            scores = dict(existing.get("signal_scores") or {})
            scores["llm"] = round(llm_field.confidence, 3)
            scores["llm_prompt_version"] = PROMPT_VERSION
            if llm_role and llm_role in valid_roles and existing_role not in ("UNKNOWN", llm_role):
                scores["llm_role_conflict"] = llm_role
            new_role = None
            if existing_role == "UNKNOWN" and llm_role in valid_roles:
                new_role = llm_role

            description = existing.get("description") or ""
            is_generic = not description or description.startswith("Campo inferido")
            new_description = (
                llm_field.description[:4000]
                if is_generic and llm_field.description
                else None
            )
            synonyms = _merge_synonyms(
                list(existing.get("synonyms") or []),
                [commercial_name] if commercial_name else [],
            )
            updated = await self._store.update_field_semantics(
                organization_id,
                UUID(existing["id"]),
                description=new_description,
                role=new_role,
                confidence=confidence,
                synonyms=synonyms,
                signal_scores=scores,
            )
            if updated:
                updates.append(
                    {
                        "field_id": existing["id"],
                        "column": llm_field.physical_column,
                        "confidence": confidence,
                        "role": new_role or existing_role,
                        "conflict": scores.get("llm_role_conflict") is not None,
                        "reasoning_summary": llm_field.reasoning_summary[:300],
                    }
                )
        return {
            "enriched": len(updates),
            "updates": updates,
            "suggestions": suggestions,
        }

    # ------------------------------------------------------- knowledge proposals
    async def _pending_titles(
        self, organization_id: UUID, suggestion_type: str
    ) -> set[str]:
        try:
            pending = await self._store.list_suggestions(
                organization_id,
                status="pending",
                type=suggestion_type,
                limit=1000,
            )
        except Exception:  # noqa: BLE001
            return set()
        return {(_normalize(s.get("title", ""))) for s in pending}

    async def _create_business_rules(
        self,
        organization_id: UUID,
        source_id: UUID,
        parsed: LLMTableAnalysis,
    ) -> int:
        created = 0
        existing = await self._pending_titles(organization_id, "business_rule")
        for rule in parsed.business_rules[:_MAX_SUGGESTIONS_PER_TABLE]:
            if not rule.name.strip() or rule.confidence < _MIN_ENRICH_CONFIDENCE:
                continue
            key = _normalize(f"regla de negocio: {rule.name}")
            if key in existing:
                continue
            await self._store.create_suggestion(
                CatalogSuggestion(
                    organization_id=organization_id,
                    type=SuggestionType.BUSINESS_RULE,
                    title=f"Regla de negocio propuesta: {rule.name[:200]}",
                    description=rule.definition[:2000]
                    or "Regla inferida por el LLM; requiere validación humana.",
                    evidence=[
                        f"llm:{PROMPT_VERSION}",
                        *[e[:150] for e in rule.evidence[:6]],
                    ],
                    confidence=_label_for(rule.confidence),
                    payload={
                        "source": "llm",
                        "rule": rule.name,
                        "definition": rule.definition,
                        "applies_to": rule.applies_to,
                        "confidence_score": rule.confidence,
                    },
                    affected_sources=[str(source_id)],
                )
            )
            existing.add(key)
            created += 1
        return created

    async def _create_metric_proposals(
        self,
        organization_id: UUID,
        source_id: UUID,
        parsed: LLMTableAnalysis,
    ) -> int:
        created = 0
        existing = await self._pending_titles(organization_id, "metric_proposal")
        for metric in parsed.possible_metrics[:_MAX_SUGGESTIONS_PER_TABLE]:
            if not metric.name.strip() or metric.confidence < _MIN_ENRICH_CONFIDENCE:
                continue
            key = _normalize(f"métrica propuesta: {metric.name}")
            if key in existing:
                continue
            await self._store.create_suggestion(
                CatalogSuggestion(
                    organization_id=organization_id,
                    type=SuggestionType.METRIC_PROPOSAL,
                    title=f"Métrica propuesta: {metric.name[:200]}",
                    description=metric.definition[:2000]
                    or "Métrica sugerida por el LLM; requiere validación humana.",
                    evidence=[
                        f"llm:{PROMPT_VERSION}",
                        *[e[:150] for e in metric.evidence[:6]],
                    ],
                    confidence=_label_for(metric.confidence),
                    payload={
                        "source": "llm",
                        "metric_name": metric.name,
                        "definition": metric.definition,
                        "formula": metric.formula,
                        "confidence_score": metric.confidence,
                    },
                    affected_sources=[str(source_id)],
                )
            )
            existing.add(key)
            created += 1
        return created

    async def _create_glossary_suggestions(
        self,
        organization_id: UUID,
        source_id: UUID,
        parsed: LLMTableAnalysis,
    ) -> int:
        created = 0
        existing = await self._pending_titles(organization_id, "glossary_term")
        for dimension in parsed.dimensions[:_MAX_SUGGESTIONS_PER_TABLE]:
            if not dimension.name.strip() or dimension.confidence < 0.7:
                continue
            key = _normalize(f"término propuesto: {dimension.name}")
            if key in existing:
                continue
            await self._store.create_suggestion(
                CatalogSuggestion(
                    organization_id=organization_id,
                    type=SuggestionType.GLOSSARY_TERM,
                    title=f"Término propuesto: {dimension.name[:200]}",
                    description=(
                        f"Dimensión de negocio derivada de {dimension.source_column[:120]}."
                        if dimension.source_column
                        else "Dimensión de negocio propuesta por el LLM."
                    ),
                    evidence=[
                        f"llm:{PROMPT_VERSION}",
                        *[e[:150] for e in dimension.evidence[:5]],
                    ],
                    confidence=_label_for(dimension.confidence),
                    payload={
                        "source": "llm",
                        "concept": dimension.name,
                        "data_type": "dimension",
                        "source_column": dimension.source_column,
                        "confidence_score": dimension.confidence,
                    },
                    affected_sources=[str(source_id)],
                )
            )
            existing.add(key)
            created += 1
        return created

    async def _create_relationship_suggestions(
        self,
        organization_id: UUID,
        source_id: UUID,
        context: TableContext,
        parsed: LLMTableAnalysis,
    ) -> int:
        created = 0
        existing = await self._pending_titles(
            organization_id, "relationship_candidate"
        )
        table_name = context.table.get("qualified_name") or context.table.get(
            "table_name", ""
        )
        for rel in parsed.relationships[:20]:
            if rel.confidence < _MIN_ENRICH_CONFIDENCE:
                continue
            if not rel.from_column or not rel.to_table:
                continue
            title = (
                f"Relación inferida por LLM: {rel.from_column} -> "
                f"{rel.to_table}.{rel.to_column or '?'}"
            )
            key = _normalize(title)
            if key in existing:
                continue
            await self._store.create_suggestion(
                CatalogSuggestion(
                    organization_id=organization_id,
                    type=SuggestionType.RELATIONSHIP_CANDIDATE,
                    title=title[:300],
                    description=(
                        f"El LLM propone que {table_name}.{rel.from_column} "
                        f"referencia {rel.to_table}.{rel.to_column or '?'}"
                        + (f" ({rel.business_verb})." if rel.business_verb else ".")
                    )[:2000],
                    evidence=[
                        f"llm:{PROMPT_VERSION}",
                        *[e[:150] for e in rel.evidence[:6]],
                    ],
                    confidence=_label_for(rel.confidence),
                    payload={
                        "source": "llm",
                        "from_table": table_name,
                        "from_column": rel.from_column,
                        "to_table": rel.to_table,
                        "to_column": rel.to_column,
                        "business_verb": rel.business_verb,
                        "confidence_score": rel.confidence,
                        "reasoning_summary": rel.reasoning_summary,
                    },
                    affected_sources=[str(source_id)],
                )
            )
            existing.add(key)
            created += 1
        return created


def _normalize(text: str) -> str:
    return " ".join((text or "").lower().split())[:200]
