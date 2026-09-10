# =============================================================================
# Question Generator — preguntas de negocio desde ambigüedad real (FASE 33D)
# =============================================================================
# Nunca preguntas genéricas: cada pregunta cita evidencia observada (valores,
# conflicto heurística/LLM, tablas variantes, columnas de impuestos, análisis
# LLM). La prioridad es explicable (sección 8) y no bombardea al cliente.
# =============================================================================
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from uuid import UUID

from src.catalog.store import PostgresCatalogStore
from src.core.config import get_settings
from src.core.domain.knowledge_learning import (
    QuestionPriority,
    QuestionType,
    compute_question_priority,
)
from src.infrastructure.observability.logging_config import get_logger
from src.platform.knowledge_learning.repository import (
    PostgresKnowledgeLearningRepository,
)

logger = get_logger(__name__)

_STATUS_HINTS = re.compile(
    r"(status|estado|state|tipo|type|flag|indicator|condicion|condition)", re.I
)
_TOTAL_HINTS = re.compile(r"(total|monto|amount|importe|subtotal|bruto|gross|neto|net)", re.I)
_TAX_HINTS = re.compile(r"(tax|impuesto|igv|iva|vat|tributo)", re.I)
_VARIANT_SUFFIX = re.compile(
    r"_(hist|history|historico|histórico|bk|backup|old|legacy|snapshot|"
    r"tmp|temp|copy|copia|archivo|archive|log)$",
    re.I,
)


@dataclass
class QuestionCandidate:
    question_key: str
    question_type: str
    title: str
    body: str = ""
    priority: str = QuestionPriority.MEDIUM.value
    priority_score: float = 0.0
    evidence: list[str] = field(default_factory=list)
    options: list[dict] = field(default_factory=list)
    answer_schema: dict = field(default_factory=dict)
    impact: dict = field(default_factory=dict)
    confidence_before: float | None = None
    catalog_table_id: UUID | None = None
    entity_id: UUID | None = None
    field_id: UUID | None = None
    column_id: UUID | None = None
    relationship_id: UUID | None = None


def _key(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256(
        "|".join(str(p) for p in parts).encode("utf-8")
    ).hexdigest()[:32]
    return f"{prefix}:{digest}"


def _occurrence_total(values: list[dict]) -> int:
    return sum(int(v.get("occurrence_count") or 0) for v in values)


class QuestionGenerator:
    """Detecta ambigüedad real y persiste preguntas priorizadas."""

    def __init__(
        self,
        store: PostgresCatalogStore,
        repository: PostgresKnowledgeLearningRepository,
        *,
        intelligence_store=None,
    ) -> None:
        self._store = store
        self._repo = repository
        self._intel = intelligence_store

    async def generate(
        self,
        organization_id: UUID,
        *,
        source_id: UUID,
        run_id: UUID | None = None,
        llm_analyses: list[dict] | None = None,
        limit: int | None = None,
    ) -> dict:
        settings = get_settings()
        max_questions = limit or settings.RAG_KNOWLEDGE_QUESTIONS_MAX_PER_RUN
        candidates: list[QuestionCandidate] = []
        try:
            candidates.extend(
                await self._enum_questions(organization_id, source_id)
            )
            candidates.extend(
                await self._field_ambiguity_questions(organization_id, source_id)
            )
            candidates.extend(
                await self._table_variant_questions(organization_id, source_id)
            )
            candidates.extend(
                await self._tax_inclusion_questions(organization_id, source_id)
            )
            if (
                settings.RAG_KNOWLEDGE_AI_QUESTIONS_ENABLED
                and llm_analyses
            ):
                candidates.extend(
                    await self._llm_questions(
                        organization_id, source_id, llm_analyses
                    )
                )
        except Exception as exc:  # noqa: BLE001 — nunca romper el run
            logger.warning(
                "Question generation detection failed",
                organization_id=str(organization_id),
                error=str(exc)[:300],
            )

        # Prioriza y limita (no bombardear).
        candidates.sort(key=lambda c: c.priority_score, reverse=True)
        seen_keys: set[str] = set()
        unique: list[QuestionCandidate] = []
        for candidate in candidates:
            if candidate.question_key in seen_keys:
                continue
            seen_keys.add(candidate.question_key)
            unique.append(candidate)
        selected = unique[: max(1, max_questions)]

        created = 0
        updated = 0
        persisted: list[dict] = []
        for candidate in selected:
            existing = await self._get_by_key(
                organization_id, candidate.question_key
            )
            if existing is not None and existing.get("status") != "pending":
                continue  # nunca revivir una pregunta respondida/descartada
            question = await self._repo.upsert_question(
                organization_id,
                question_key=candidate.question_key,
                question_type=candidate.question_type,
                title=candidate.title,
                body=candidate.body,
                source_id=source_id,
                run_id=run_id,
                catalog_table_id=candidate.catalog_table_id,
                entity_id=candidate.entity_id,
                field_id=candidate.field_id,
                column_id=candidate.column_id,
                relationship_id=candidate.relationship_id,
                evidence=candidate.evidence,
                options=candidate.options,
                answer_schema=candidate.answer_schema,
                priority=candidate.priority,
                priority_score=candidate.priority_score,
                impact=candidate.impact,
                confidence_before=candidate.confidence_before,
            )
            if not question:
                continue
            if existing is None:
                created += 1
            else:
                updated += 1
            persisted.append(question)

        by_type: dict[str, int] = {}
        by_priority: dict[str, int] = {}
        for question in persisted:
            by_type[question["question_type"]] = (
                by_type.get(question["question_type"], 0) + 1
            )
            by_priority[question["priority"]] = (
                by_priority.get(question["priority"], 0) + 1
            )
        return {
            "candidates": len(unique),
            "questions": persisted,
            "generated": created,
            "updated": updated,
            "by_type": by_type,
            "by_priority": by_priority,
            "critical": by_priority.get(QuestionPriority.CRITICAL.value, 0),
            "high": by_priority.get(QuestionPriority.HIGH.value, 0),
        }

    async def _get_by_key(
        self, organization_id: UUID, question_key: str
    ) -> dict | None:
        return await self._repo.get_question_by_key(organization_id, question_key)

    # ------------------------------------------------------------------ enums
    async def _enum_questions(
        self, organization_id: UUID, source_id: UUID
    ) -> list[QuestionCandidate]:
        out: list[QuestionCandidate] = []
        tables = await self._store.list_tables(organization_id, source_id, limit=5000)
        relationships = await self._store.list_relationships(
            organization_id, source_id, limit=5000
        )
        for table in tables:
            table_id = UUID(table["id"])
            enum_values = await self._store.list_enum_values_for_table(
                organization_id, table_id
            )
            columns = {
                c["column_name"]: c
                for c in await self._store.list_columns(organization_id, table_id)
            }
            for column_name, values in enum_values.items():
                if not values:
                    continue
                if any(
                    v.get("status") == "approved" and v.get("documented_meaning")
                    for v in values
                ):
                    continue  # ya documentado: sin ambigüedad
                column = columns.get(column_name)
                if column is None:
                    continue
                top = sorted(
                    values, key=lambda v: -int(v.get("occurrence_count") or 0)
                )[:12]
                total = _occurrence_total(values)
                status_like = bool(_STATUS_HINTS.search(column_name))
                dependents = [
                    r
                    for r in relationships
                    if (r.get("from_table_id") == table["id"] and r.get("from_column") == column_name)
                    or (r.get("to_table_id") == table["id"] and r.get("to_column") == column_name)
                ]
                priority, score = compute_question_priority(
                    ambiguity=0.75 if status_like else 0.55,
                    business_impact=0.8 if status_like else 0.5,
                    retrieval_impact=0.7 if status_like else 0.5,
                    frequency=min(1.0, total / 10_000) if total else 0.35,
                    confidence=0.35,
                    dependents=min(1.0, len(dependents) / 3),
                )
                options = [
                    {
                        "value": str(v.get("value")),
                        "label": str(v.get("value")),
                        "occurrence_count": int(v.get("occurrence_count") or 0),
                    }
                    for v in top
                ]
                out.append(
                    QuestionCandidate(
                        question_key=_key(
                            "enum_meaning", table["id"], column_name
                        ),
                        question_type=QuestionType.ENUM_MEANING.value,
                        title=(
                            f"¿Qué significa {column_name} = "
                            + ", ".join(f'"{v.get("value")}"' for v in top[:4])
                            + f" en {table.get('qualified_name')}?"
                        ),
                        body=(
                            "Zent encontró valores categóricos sin significado "
                            "documentado. Este significado cambia cómo se "
                            "interpretan los reportes."
                        ),
                        priority=priority.value,
                        priority_score=score,
                        evidence=[
                            "valores observados: "
                            + ", ".join(
                                f"{v.get('value')} ({int(v.get('occurrence_count') or 0)} filas)"
                                for v in top[:8]
                            ),
                            f"columna {table.get('qualified_name')}.{column_name} "
                            "sin significado aprobado",
                            f"cardinalidad {len(values)}",
                        ],
                        options=options,
                        answer_schema={
                            "kind": "enum_mapping",
                            "column_id": column["id"],
                            "values": [str(v.get("value")) for v in top],
                        },
                        impact={
                            "reports": True,
                            "retrieval": len(dependents) > 0 or status_like,
                            "dependents": len(dependents),
                        },
                        confidence_before=0.35,
                        catalog_table_id=table_id,
                        column_id=UUID(column["id"]),
                    )
                )
        return out

    # ------------------------------------------------------- field ambiguity
    async def _field_ambiguity_questions(
        self, organization_id: UUID, source_id: UUID
    ) -> list[QuestionCandidate]:
        out: list[QuestionCandidate] = []
        tables = await self._store.list_tables(organization_id, source_id, limit=5000)
        table_ids = {t["id"] for t in tables}
        entities = await self._store.list_entities(organization_id, limit=2000)
        field_ids = [e["id"] for e in entities if e.get("mapped_table_id") in table_ids]
        for entity in entities:
            if entity["id"] not in field_ids:
                continue
            fields = await self._store.list_fields(organization_id, UUID(entity["id"]))
            for fld in fields:
                if fld.get("status") == "approved":
                    continue
                scores = fld.get("signal_scores") or {}
                if isinstance(scores, str):
                    try:
                        scores = json.loads(scores)
                    except (TypeError, ValueError):
                        scores = {}
                conflict = scores.get("llm_role_conflict")
                if not conflict:
                    continue
                priority, score = compute_question_priority(
                    ambiguity=0.7,
                    business_impact=0.65,
                    retrieval_impact=0.6,
                    frequency=0.4,
                    confidence=0.45,
                    dependents=0.3,
                )
                current_role = fld.get("role") or "UNKNOWN"
                out.append(
                    QuestionCandidate(
                        question_key=_key("field_ambiguity", fld["id"]),
                        question_type=QuestionType.FIELD_AMBIGUITY.value,
                        title=(
                            f"¿{fld.get('name')} es {current_role} o {conflict}?"
                        ),
                        body=(
                            "La heurística y el LLM discrepan sobre el rol de "
                            "este campo; elegir el correcto mejora la precisión."
                        ),
                        priority=priority.value,
                        priority_score=score,
                        evidence=[
                            f"heurística propone {current_role}",
                            f"LLM propone {conflict}",
                            f"campo {fld.get('name')} en {entity.get('name')}",
                        ],
                        options=[
                            {"value": current_role, "label": f"Mantener {current_role}"},
                            {"value": conflict, "label": f"Usar {conflict}"},
                        ],
                        answer_schema={
                            "kind": "role_choice",
                            "field_id": fld["id"],
                            "current_role": current_role,
                            "llm_role": conflict,
                        },
                        impact={"semantic_precision": True},
                        confidence_before=0.45,
                        entity_id=UUID(entity["id"]),
                        field_id=UUID(fld["id"]),
                    )
                )
        return out

    # --------------------------------------------------------- table variants
    async def _table_variant_questions(
        self, organization_id: UUID, source_id: UUID
    ) -> list[QuestionCandidate]:
        out: list[QuestionCandidate] = []
        tables = await self._store.list_tables(organization_id, source_id, limit=5000)
        by_base: dict[str, list[dict]] = {}
        for table in tables:
            base = _VARIANT_SUFFIX.sub("", table["table_name"]).lower()
            if base == table["table_name"].lower():
                continue
            by_base.setdefault(base, []).append(table)
        table_by_name = {t["table_name"].lower(): t for t in tables}
        for base, variants in by_base.items():
            base_table = table_by_name.get(base)
            for variant in variants:
                evidence = [
                    f"{variant.get('qualified_name')} tiene estructura similar a "
                    + (base_table.get("qualified_name") if base_table else base),
                ]
                if variant.get("row_count_approx") is not None:
                    evidence.append(f"filas aproximadas: {variant['row_count_approx']}")
                if base_table is not None and base_table.get("row_count_approx") is not None:
                    evidence.append(
                        f"filas aproximadas de {base_table.get('qualified_name')}: "
                        f"{base_table['row_count_approx']}"
                    )
                priority, score = compute_question_priority(
                    ambiguity=0.6,
                    business_impact=0.55,
                    retrieval_impact=0.75,
                    frequency=0.4,
                    confidence=0.4,
                    dependents=0.5 if base_table else 0.2,
                )
                out.append(
                    QuestionCandidate(
                        question_key=_key(
                            "table_variant", source_id, variant["id"]
                        ),
                        question_type=QuestionType.TABLE_VARIANT.value,
                        title=(
                            f"¿{variant.get('qualified_name')} contiene "
                            f"histórico de {base_table.get('qualified_name') if base_table else base}?"
                        ),
                        body=(
                            "La tabla parece una variante de otra. Confirmarlo "
                            "evita duplicar o mezclar información en reportes."
                        ),
                        priority=priority.value,
                        priority_score=score,
                        evidence=evidence,
                        options=[
                            {"value": "yes", "label": "Sí, contiene histórico"},
                            {"value": "no", "label": "No, es otra cosa"},
                        ],
                        answer_schema={
                            "kind": "boolean",
                            "field": "is_history",
                            "base_table": base,
                        },
                        impact={"retrieval": True, "dedupe": True},
                        confidence_before=0.4,
                        catalog_table_id=UUID(variant["id"]),
                    )
                )
        return out

    # ---------------------------------------------------------- tax inclusion
    async def _tax_inclusion_questions(
        self, organization_id: UUID, source_id: UUID
    ) -> list[QuestionCandidate]:
        out: list[QuestionCandidate] = []
        tables = await self._store.list_tables(organization_id, source_id, limit=5000)
        for table in tables:
            columns = await self._store.list_columns(
                organization_id, UUID(table["id"])
            )
            total_columns = [
                c["column_name"] for c in columns if _TOTAL_HINTS.search(c["column_name"])
            ]
            tax_columns = [
                c["column_name"] for c in columns if _TAX_HINTS.search(c["column_name"])
            ]
            if not total_columns or not tax_columns:
                continue
            total_col = total_columns[0]
            priority, score = compute_question_priority(
                ambiguity=0.7,
                business_impact=0.85,
                retrieval_impact=0.8,
                frequency=0.5,
                confidence=0.4,
                dependents=0.4,
            )
            out.append(
                QuestionCandidate(
                    question_key=_key("tax_inclusion", table["id"], total_col),
                    question_type=QuestionType.TAX_INCLUSION.value,
                    title=(
                        f"¿{total_col} incluye impuestos?"
                    ),
                    body=(
                        f"La tabla tiene columnas de impuestos "
                        f"({', '.join(tax_columns[:3])}); saber si {total_col} "
                        "los incluye cambia el cálculo de márgenes y totales."
                    ),
                    priority=priority.value,
                    priority_score=score,
                    evidence=[
                        f"columna de importe: {total_col}",
                        f"columnas de impuestos: {', '.join(tax_columns[:3])}",
                        f"tabla {table.get('qualified_name')}",
                    ],
                    options=[
                        {"value": "yes", "label": "Sí, incluye impuestos"},
                        {"value": "no", "label": "No, es neto"},
                        {"value": "partial", "label": "Depende del caso"},
                    ],
                    answer_schema={
                        "kind": "boolean",
                        "field": "includes_tax",
                        "column": total_col,
                        "tax_columns": tax_columns,
                    },
                    impact={"finance": True},
                    confidence_before=0.4,
                    catalog_table_id=UUID(table["id"]),
                )
            )
        return out

    # --------------------------------------------------------------- llm
    async def _llm_questions(
        self,
        organization_id: UUID,
        source_id: UUID,
        llm_analyses: list[dict],
    ) -> list[QuestionCandidate]:
        out: list[QuestionCandidate] = []
        tables = await self._store.list_tables(organization_id, source_id, limit=5000)
        tables_by_id = {t["id"]: t for t in tables}
        columns_by_table: dict[str, dict[str, dict]] = {}
        for table in tables:
            columns_by_table[table["id"]] = {
                c["column_name"]: c
                for c in await self._store.list_columns(
                    organization_id, UUID(table["id"])
                )
            }
        for analysis in llm_analyses or []:
            if analysis.get("status") not in ("completed", "cached"):
                continue
            table_id = analysis.get("table_id")
            table = tables_by_id.get(table_id or "")
            if table is None:
                continue
            result = analysis.get("result") or {}
            for raw in (result.get("questions") or [])[:20]:
                question_text = str(raw.get("question") or "").strip()
                if len(question_text) < 8:
                    continue
                target = str(raw.get("target") or "")
                column = columns_by_table.get(table_id, {}).get(target)
                impact_raw = str(raw.get("impact") or "medium").lower()
                confidence = float(raw.get("confidence") or 0.0)
                priority, score = compute_question_priority(
                    ambiguity=0.65,
                    business_impact=0.85 if impact_raw == "critical" else (
                        0.7 if impact_raw == "high" else 0.5
                    ),
                    retrieval_impact=0.6,
                    frequency=0.4,
                    confidence=confidence,
                    dependents=0.4 if column else 0.2,
                )
                options = [
                    {"value": str(option), "label": str(option)}
                    for option in (raw.get("options") or [])[:8]
                ]
                out.append(
                    QuestionCandidate(
                        question_key=_key(
                            "llm_question", table_id, question_text
                        ),
                        question_type=QuestionType.LLM_QUESTION.value,
                        title=question_text[:1000],
                        body=(
                            "El análisis semántico detectó esta ambigüedad; "
                            "tu respuesta queda como conocimiento validado."
                        ),
                        priority=priority.value,
                        priority_score=score,
                        evidence=[
                            f"análisis LLM: {analysis.get('model') or 'modelo'}",
                            f"tabla {table.get('qualified_name')}",
                            *[str(e)[:200] for e in (raw.get("evidence") or [])[:5]],
                        ],
                        options=options,
                        answer_schema={
                            "kind": "free_form",
                            "table_id": table_id,
                            "target": target,
                            "column_id": column["id"] if column else None,
                        },
                        impact={"llm": True, "impact": impact_raw},
                        confidence_before=confidence,
                        catalog_table_id=UUID(table_id),
                        column_id=UUID(column["id"]) if column else None,
                    )
                )
        return out
