# =============================================================================
# Relationship Intelligence — confianza, evidencia y provenance (FASE 33C)
# =============================================================================
# Combina señales reales para descubrir el modelo de negocio:
#   FK física + PK/ tipOS + cardinalidad + naming + convenciones + conocimiento
#   aprobado previamente + hipótesis del LLM.
#
# Clasificación explícita:
#   OBSERVED  FK física declarada (estructura verificable; se auto-confirma)
#   INFERRED  hipótesis (nunca se muestra como verdad confirmada)
#   APPROVED  validada por una persona
#   REJECTED  descartada por una persona
#
# Nunca se crean constraints físicos en bases del cliente.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field
from uuid import UUID

from src.catalog.relationships import _is_key_column, _normalize_column, _types_compatible
from src.catalog.store import PostgresCatalogStore
from src.core.domain.catalog import RelationshipProvenance, RelationshipStatus
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

# Pesos de las señales (suman 1.0). Se exponen en evidence_detail.
SIGNAL_WEIGHTS: dict[str, float] = {
    "fk_declared": 0.55,
    "types_compatible": 0.08,
    "target_key": 0.09,
    "naming_similarity": 0.12,
    "org_convention": 0.04,
    "llm_agreement": 0.12,
}

_OBSERVED_FLOOR = 0.95
_MAX_INFERRED = 0.92


@dataclass
class RelationshipHypothesis:
    """Hipótesis de relación con confianza numérica y evidencia trazable."""

    from_table_id: UUID
    from_table: str
    from_column: str
    to_table_id: UUID
    to_table: str
    to_column: str
    rel_id: UUID | None = None  # None => hipótesis nueva (no persistida)
    relation_type: str = "inferred"
    provenance: str = RelationshipProvenance.INFERRED.value
    status: str = RelationshipStatus.SUGGESTED.value
    confidence_score: float = 0.0
    semantic_similarity: float = 0.0
    cardinality: str | None = None
    evidence: list[str] = field(default_factory=list)
    evidence_detail: list[dict] = field(default_factory=list)
    llm_confidence: float | None = None

    def to_dict(self) -> dict:
        return {
            "id": str(self.rel_id) if self.rel_id else None,
            "from_table_id": str(self.from_table_id),
            "from_table": self.from_table,
            "from_column": self.from_column,
            "to_table_id": str(self.to_table_id),
            "to_table": self.to_table,
            "to_column": self.to_column,
            "relation_type": self.relation_type,
            "provenance": self.provenance,
            "status": self.status,
            "confidence": self.confidence_score,
            "semantic_similarity": self.semantic_similarity,
            "cardinality": self.cardinality,
            "evidence": list(self.evidence),
            "evidence_detail": list(self.evidence_detail),
        }


# -----------------------------------------------------------------------------
# Señales
# -----------------------------------------------------------------------------


def _table_similarity(from_column: str, to_table_name: str) -> float:
    """Similitud débil nombre-columna vs nombre-tabla (0..1)."""
    token = _normalize_column(from_column).lower()
    table = re.sub(r"^(tbl|dim|fct|stg|raw|d_|f_|dim_|fact_|stage_|staging_)", "", to_table_name.lower())
    table = table.replace("_", "")
    if not token or not table:
        return 0.0
    if token == table:
        return 1.0
    if table.startswith(token) or token.startswith(table):
        return 0.8
    if token in table or table in token:
        return 0.6
    return 0.0


def _estimate_cardinality(
    *, from_column: dict, to_column: dict
) -> str:
    from_is_pk = bool(from_column.get("is_primary_key"))
    to_is_pk = bool(to_column.get("is_primary_key"))
    if from_is_pk and to_is_pk:
        return "1:1"
    if to_is_pk:
        return "N:1"
    if from_is_pk:
        return "1:N"
    return "N:M"


def _declared_fk(
    *, from_column: str, to_table_name: str, from_table_name: str, deep: object | None
) -> bool:
    if deep is None:
        return False
    for table in getattr(deep, "tables", []):
        qualified = f"{table.schema}.{table.table_name}"
        if from_table_name not in (table.table_name, qualified):
            continue
        for fk in table.foreign_keys:
            if fk.from_column != from_column:
                continue
            if fk.to_table in (to_table_name, f"{table.schema}.{fk.to_table}"):
                return True
    return False


@dataclass
class _SignalResult:
    score: float
    similarity: float
    cardinality: str | None
    evidence: list[str]
    evidence_detail: list[dict]
    llm_confidence: float | None = None
    declared_fk: bool = False


def evaluate_relationship_signals(
    *,
    from_column: dict | None,
    to_column: dict | None,
    from_table_name: str,
    to_table_name: str,
    declared_fk: bool,
    approved_convention: bool,
    llm_confidence: float | None,
) -> _SignalResult:
    """Evalúa señales y produce score, cardinalidad y evidencia explicable."""
    evidence: list[str] = []
    detail: list[dict] = []
    score = 0.0
    similarity = _table_similarity(
        (from_column or {}).get("column_name", ""), to_table_name
    )

    def add(signal: str, satisfied: bool, note: str, *, ratio: float = 1.0) -> None:
        nonlocal score
        if not satisfied:
            return
        weight = SIGNAL_WEIGHTS.get(signal, 0.0) * max(0.0, min(1.0, ratio))
        score += weight
        evidence.append(note)
        detail.append({"signal": signal, "weight": round(weight, 4), "detail": note})

    add(
        "fk_declared",
        declared_fk,
        "FK física declarada en el esquema.",
    )
    types_ok = _types_compatible(
        (from_column or {}).get("data_type", ""), (to_column or {}).get("data_type", "")
    )
    add(
        "types_compatible",
        types_ok and bool(from_column and to_column),
        f"Tipos compatibles ({(from_column or {}).get('data_type', '?')} / "
        f"{(to_column or {}).get('data_type', '?')}).",
    )
    target_is_key = bool((to_column or {}).get("is_primary_key")) or _is_key_column(
        (to_column or {}).get("column_name", "")
    )
    add(
        "target_key",
        target_is_key and bool(to_column),
        "La columna destino es clave (PK/identificador).",
    )
    add(
        "naming_similarity",
        similarity >= 0.6,
        f"Naming similar: {from_table_name}.{(from_column or {}).get('column_name', '?')} "
        f"~ {to_table_name}.",
        ratio=similarity,
    )
    add(
        "org_convention",
        approved_convention,
        "Convención de la organización: existen relaciones aprobadas con el mismo patrón.",
    )
    add(
        "llm_agreement",
        llm_confidence is not None and llm_confidence >= 0.5,
        f"Acuerdo del LLM (confianza {round((llm_confidence or 0) * 100)}%).",
        ratio=float(llm_confidence or 0.0),
    )

    cardinality = None
    if from_column and to_column:
        cardinality = _estimate_cardinality(from_column=from_column, to_column=to_column)
        detail.append(
            {
                "signal": "cardinality",
                "weight": 0.0,
                "detail": f"Cardinalidad estimada {cardinality}.",
            }
        )
        evidence.append(f"Cardinalidad {cardinality}.")
    return _SignalResult(
        score=round(min(1.0, score), 4),
        similarity=round(similarity, 4),
        cardinality=cardinality,
        evidence=evidence,
        evidence_detail=detail,
        llm_confidence=llm_confidence,
        declared_fk=declared_fk,
    )


# -----------------------------------------------------------------------------
# Analyzer
# -----------------------------------------------------------------------------


class RelationshipAnalyzer:
    """Enriquece relaciones persistidas y agrega hipótesis del LLM."""

    def __init__(self, store: PostgresCatalogStore) -> None:
        self._store = store

    async def analyze(
        self,
        organization_id: UUID,
        source_id: UUID,
        *,
        deep: object | None = None,
        llm_analyses: list[dict] | None = None,
        run_id: UUID | None = None,
    ) -> dict:
        """Calcula hipótesis para relaciones existentes + LLM. No persiste."""
        tables = await self._store.list_tables(
            organization_id, source_id, limit=5000
        )
        table_by_id: dict[str, dict] = {t["id"]: t for t in tables}
        table_by_name: dict[str, dict] = {}
        for table in tables:
            table_by_name[table["table_name"]] = table
            table_by_name[table.get("qualified_name") or table["table_name"]] = table
        columns_by_table: dict[str, list[dict]] = {}
        column_index: dict[tuple[str, str], dict] = {}
        for table in tables:
            columns = await self._store.list_columns(organization_id, UUID(table["id"]))
            columns_by_table[table["id"]] = columns
            for col in columns:
                column_index[(table["id"], col["column_name"])] = col

        persisted = await self._store.list_relationships(
            organization_id, source_id, limit=5000
        )
        approved_conventions = {
            _normalize_column(rel["from_column"]).lower()
            for rel in persisted
            if rel.get("provenance") == RelationshipProvenance.APPROVED.value
        }
        llm_matches = _index_llm_hypotheses(
            llm_analyses or [], table_by_id=table_by_id, table_by_name=table_by_name
        )
        matched_llm: set[tuple[str, str, str, str]] = set()

        hypotheses: list[RelationshipHypothesis] = []
        for rel in persisted:
            from_table = table_by_id.get(rel["from_table_id"])
            to_table = table_by_id.get(rel["to_table_id"])
            if from_table is None or to_table is None:
                continue
            from_column = column_index.get(
                (rel["from_table_id"], rel["from_column"])
            )
            to_column = column_index.get((rel["to_table_id"], rel["to_column"]))
            llm_key = (
                rel["from_table_id"],
                rel["from_column"],
                rel["to_table_id"],
                rel["to_column"],
            )
            llm_conf = llm_matches.get(llm_key)
            if llm_conf is not None:
                matched_llm.add(llm_key)
            declared = rel.get("relation_type") == "foreign_key" or _declared_fk(
                from_column=rel["from_column"],
                to_table_name=to_table["table_name"],
                from_table_name=from_table["table_name"],
                deep=deep,
            )
            convention = _normalize_column(rel["from_column"]).lower() in approved_conventions
            signals = evaluate_relationship_signals(
                from_column=from_column,
                to_column=to_column,
                from_table_name=from_table["table_name"],
                to_table_name=to_table["table_name"],
                declared_fk=declared,
                approved_convention=convention,
                llm_confidence=llm_conf,
            )
            provenance = _resolve_provenance(
                existing=rel.get("provenance"),
                declared_fk=declared,
            )
            score = _resolve_score(
                provenance=provenance,
                computed=signals.score,
                existing=float(rel.get("confidence_score") or 0.0),
            )
            status = (
                RelationshipStatus.CONFIRMED.value
                if provenance
                in (
                    RelationshipProvenance.OBSERVED.value,
                    RelationshipProvenance.APPROVED.value,
                )
                else (
                    RelationshipStatus.REJECTED.value
                    if provenance == RelationshipProvenance.REJECTED.value
                    else RelationshipStatus.SUGGESTED.value
                )
            )
            hypotheses.append(
                RelationshipHypothesis(
                    rel_id=UUID(rel["id"]),
                    from_table_id=UUID(rel["from_table_id"]),
                    from_table=from_table.get("qualified_name") or from_table["table_name"],
                    from_column=rel["from_column"],
                    to_table_id=UUID(rel["to_table_id"]),
                    to_table=to_table.get("qualified_name") or to_table["table_name"],
                    to_column=rel["to_column"],
                    relation_type=rel.get("relation_type") or "inferred",
                    provenance=provenance,
                    status=status,
                    confidence_score=score,
                    semantic_similarity=signals.similarity,
                    cardinality=signals.cardinality or rel.get("cardinality"),
                    evidence=signals.evidence,
                    evidence_detail=signals.evidence_detail,
                    llm_confidence=llm_conf,
                )
            )

        # Hipótesis solo-LLM (no existían como relación persistida).
        new_hypotheses: list[RelationshipHypothesis] = []
        for key, llm_conf in llm_matches.items():
            if key in matched_llm:
                continue
            from_table_id, from_column, to_table_id, to_column = key
            from_table = table_by_id.get(from_table_id)
            to_table = table_by_id.get(to_table_id)
            if from_table is None or to_table is None:
                continue
            from_col_meta = column_index.get((from_table_id, from_column))
            to_col_meta = column_index.get((to_table_id, to_column))
            if from_col_meta is None or to_col_meta is None:
                continue
            convention = _normalize_column(from_column).lower() in approved_conventions
            signals = evaluate_relationship_signals(
                from_column=from_col_meta,
                to_column=to_col_meta,
                from_table_name=from_table["table_name"],
                to_table_name=to_table["table_name"],
                declared_fk=False,
                approved_convention=convention,
                llm_confidence=llm_conf,
            )
            score = min(_MAX_INFERRED, round(0.35 + signals.score * 0.6, 4))
            new_hypotheses.append(
                RelationshipHypothesis(
                    from_table_id=UUID(from_table_id),
                    from_table=from_table.get("qualified_name") or from_table["table_name"],
                    from_column=from_column,
                    to_table_id=UUID(to_table_id),
                    to_table=to_table.get("qualified_name") or to_table["table_name"],
                    to_column=to_column,
                    relation_type="inferred",
                    provenance=RelationshipProvenance.INFERRED.value,
                    status=RelationshipStatus.SUGGESTED.value,
                    confidence_score=score,
                    semantic_similarity=signals.similarity,
                    cardinality=signals.cardinality,
                    evidence=signals.evidence,
                    evidence_detail=signals.evidence_detail,
                    llm_confidence=llm_conf,
                )
            )

        all_hypotheses = hypotheses + new_hypotheses
        by_provenance: dict[str, int] = {}
        for hyp in all_hypotheses:
            by_provenance[hyp.provenance] = by_provenance.get(hyp.provenance, 0) + 1
        avg_confidence = (
            round(
                sum(h.confidence_score for h in all_hypotheses) / len(all_hypotheses),
                4,
            )
            if all_hypotheses
            else 0.0
        )
        return {
            "hypotheses": all_hypotheses,
            "llm_hypotheses": new_hypotheses,
            "totals": {
                "relationships_total": len(all_hypotheses),
                "existing": len(hypotheses),
                "llm_new": len(new_hypotheses),
                "by_provenance": by_provenance,
                "avg_confidence": avg_confidence,
            },
        }

    async def apply(
        self,
        organization_id: UUID,
        source_id: UUID,
        *,
        deep: object | None = None,
        llm_analyses: list[dict] | None = None,
        run_id: UUID | None = None,
    ) -> dict:
        """Persiste el enriquecimiento y crea hipótesis LLM como INFERRED."""
        result = await self.analyze(
            organization_id,
            source_id,
            deep=deep,
            llm_analyses=llm_analyses,
            run_id=run_id,
        )
        enriched = 0
        created = 0
        for hypothesis in result["hypotheses"]:
            if hypothesis.rel_id is None:
                rel_id = await self._store.upsert_relationship(
                    organization_id=organization_id,
                    source_id=source_id,
                    from_table_id=hypothesis.from_table_id,
                    from_column=hypothesis.from_column,
                    to_table_id=hypothesis.to_table_id,
                    to_column=hypothesis.to_column,
                    relation_type="inferred",
                    confidence=_label_for_score(hypothesis.confidence_score),
                    confidence_score=hypothesis.confidence_score,
                    semantic_similarity=hypothesis.semantic_similarity,
                    cardinality=hypothesis.cardinality,
                    provenance=hypothesis.provenance,
                    status=RelationshipStatus.SUGGESTED,
                    evidence=hypothesis.evidence,
                    evidence_detail=hypothesis.evidence_detail,
                    learned_run_id=run_id,
                )
                if rel_id:
                    created += 1
                continue
            updated = await self._store.update_relationship_intelligence(
                organization_id,
                hypothesis.rel_id,
                provenance=hypothesis.provenance,
                confidence_score=hypothesis.confidence_score,
                evidence=hypothesis.evidence,
                evidence_detail=hypothesis.evidence_detail,
                cardinality=hypothesis.cardinality,
                semantic_similarity=hypothesis.semantic_similarity,
                learned_run_id=run_id,
            )
            if updated:
                enriched += 1

        totals = dict(result["totals"])
        totals["enriched"] = enriched
        totals["created"] = created
        totals["created_hypotheses"] = [
            h.to_dict() for h in result["hypotheses"] if h.rel_id is None
        ]
        return totals


def _label_for_score(score: float) -> str:
    if score >= 0.85:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"


def _resolve_provenance(existing: str | None, *, declared_fk: bool) -> str:
    if existing in (
        RelationshipProvenance.APPROVED.value,
        RelationshipProvenance.REJECTED.value,
    ):
        return str(existing)
    if declared_fk:
        return RelationshipProvenance.OBSERVED.value
    return RelationshipProvenance.INFERRED.value


def _resolve_score(*, provenance: str, computed: float, existing: float) -> float:
    if provenance == RelationshipProvenance.APPROVED.value:
        return max(existing, 1.0)
    if provenance == RelationshipProvenance.REJECTED.value:
        return existing
    if provenance == RelationshipProvenance.OBSERVED.value:
        return max(_OBSERVED_FLOOR, min(1.0, computed))
    return min(_MAX_INFERRED, max(existing, computed))


def _index_llm_hypotheses(
    analyses: list[dict],
    *,
    table_by_id: dict[str, dict],
    table_by_name: dict[str, dict],
) -> dict[tuple[str, str, str, str], float]:
    """Extrae hipótesis de relación de los análisis LLM persistidos."""
    index: dict[tuple[str, str, str, str], float] = {}
    for analysis in analyses:
        if analysis.get("status") not in ("completed", "cached"):
            continue
        result = analysis.get("result") or {}
        source_table = table_by_id.get(analysis.get("table_id") or "")
        for rel in result.get("relationships") or []:
            from_table = (
                table_by_name.get(rel.get("from_table") or "")
                or source_table
            )
            to_table = table_by_name.get(rel.get("to_table") or "")
            if from_table is None or to_table is None:
                continue
            confidence = rel.get("confidence")
            if not isinstance(confidence, (int, float)):
                continue
            key = (
                from_table["id"],
                str(rel.get("from_column") or ""),
                to_table["id"],
                str(rel.get("to_column") or ""),
            )
            if not key[1] or not key[3]:
                continue
            index[key] = max(index.get(key, 0.0), float(confidence))
    return index
