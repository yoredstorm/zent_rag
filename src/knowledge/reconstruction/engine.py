# =============================================================================
# Semantic Reconstruction Layer — motor (orquestador)
# =============================================================================
# SOURCE -> ADAPTER -> RAW EXTRACTION -> CONTINUIDAD -> FRAGMENT DETECTOR
#        -> QUALITY GATE -> SEMANTIC IR -> StructuredDocument reconstruido
#
# Determinista por defecto: el LLM es escalamiento opcional para ambigüedad
# real. Cada fuente (PDF, DOCX, TXT, Markdown, HTML, Excel, CSV, JSON, XML,
# base de datos, API, eventos...) converge al mismo modelo semántico.
# =============================================================================
from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from src.core.domain.knowledge_v2 import (
    StructuredBlock,
    StructuredDocument,
)
from src.knowledge.structure.base import content_hash, token_count

from .adapters import RawExtraction, SourceAdapter, adapter_for, detect_source_kind
from .continuity import (
    SequenceReconstruction,
    detect_repeated_table_headers,
    reconstruct_sequence,
    source_tokens,
)
from .contracts import (
    SCHEMA_VERSION,
    ConfidenceSignals,
    Continuation,
    ElementKind,
    RawElement,
    RawTable,
    ReconstructionStatus,
    SemanticField,
    SemanticRecord,
    SemanticRepresentation,
    SemanticTable,
    SemanticUnitIR,
    SourceProvenance,
    StructuralNode,
    normalize_term,
)
from .fragments import FragmentVerdict, evaluate_fragment
from .quality_gate import (
    GateDecision,
    TableGateDecision,
    gate_distribution,
    gate_element,
    gate_table,
    quality_score,
)

MAX_IR_UNITS = 1000
MAX_IR_TABLES = 200
MAX_IR_CONTINUATIONS = 500
MAX_IR_RECORDS_PER_TABLE = 5000

_PIPELINE = "source->adapter->raw->reconstruction->IR->gate"
_SKIP_INDEX_STATUSES = set(ReconstructionStatus) - {
    ReconstructionStatus.VALID,
    ReconstructionStatus.RECONSTRUCTED,
}


@dataclass
class ReconstructionDraft:
    """Estado intermedio entre extracción cruda y representación final."""

    document: StructuredDocument
    extraction: RawExtraction
    source_kind: str
    source_quality: float
    references: tuple[str, ...]
    vocabulary: frozenset[str]
    sequence: SequenceReconstruction
    table_decisions: list[TableGateDecision]
    ambiguous: list[Continuation]
    llm_decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    started: float = field(default_factory=time.perf_counter)


@dataclass
class ReconstructionOutcome:
    document: StructuredDocument
    representation: SemanticRepresentation
    report: dict[str, Any]
    decisions: list[GateDecision]
    verdicts: dict[UUID, FragmentVerdict]
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def payload(self) -> dict[str, Any]:
        return self.document.metadata.get("semantic_reconstruction") or {}


# ---------------------------------------------------------------------------
# Fase 1 — análisis determinista
# ---------------------------------------------------------------------------


def build_draft(
    document: StructuredDocument,
    *,
    raw_text: str | None = None,
    adapter: SourceAdapter | None = None,
    source_kind: str | None = None,
    source_quality: float | None = None,
) -> ReconstructionDraft:
    selected_kind, selected_adapter = adapter_for(
        document, raw_text=raw_text, preferred=source_kind
    )
    if adapter is not None:
        selected_adapter = adapter
        selected_kind = adapter.kind
    if selected_adapter is None:
        raise RuntimeError("no source adapter registered for document")
    extraction = selected_adapter.extract(document, raw_text=raw_text)
    if not extraction.elements and not extraction.tables:
        from .adapters.document import TextSourceAdapter

        fallback = TextSourceAdapter().extract(document, raw_text=raw_text)
        fallback.source_kind = selected_kind
        fallback.adapter = selected_adapter.name
        fallback.warnings.append("adapter produced no elements; used document blocks")
        extraction = fallback

    references = _reference_corpus(document, extraction)
    vocabulary = frozenset(source_tokens(references))
    sequence = reconstruct_sequence(
        list(extraction.elements), references=references, vocabulary=vocabulary
    )
    table_decisions = [
        gate_table(table, references=references, vocabulary=vocabulary)
        for table in extraction.tables
    ]
    quality = (
        float(source_quality)
        if source_quality is not None
        else _source_quality(document)
    )
    return ReconstructionDraft(
        document=document,
        extraction=extraction,
        source_kind=selected_kind,
        source_quality=quality,
        references=references,
        vocabulary=vocabulary,
        sequence=sequence,
        table_decisions=table_decisions,
        ambiguous=list(sequence.ambiguous) + _table_header_ambiguities(table_decisions),
        warnings=list(extraction.warnings),
    )


def _table_header_ambiguities(
    decisions: list[TableGateDecision],
) -> list[Continuation]:
    """Headers rechazados que podrían repararse con contexto adicional."""
    ambiguous: list[Continuation] = []
    for decision in decisions:
        for header in decision.rejected_headers:
            ambiguous.append(
                Continuation(
                    id=f"header:{decision.table_id}:{normalize_term(header)}",
                    kind="TABLE_HEADER",
                    left_id=UUID(int=0),
                    right_id=UUID(int=0),
                    merged_text=header,
                    confidence=0.4,
                    reason="table_header_fragment",
                    ambiguity=True,
                    evidence={"table_id": decision.table_id, "header": header},
                )
            )
    return ambiguous


# ---------------------------------------------------------------------------
# Fase 2 — finalización determinista (o con decisiones LLM ya aplicadas)
# ---------------------------------------------------------------------------


def finalize_draft(draft: ReconstructionDraft) -> ReconstructionOutcome:
    document = draft.document
    elements = list(draft.sequence.elements)
    absorbed = draft.sequence.absorbed
    absorbed_texts = {normalize_term(item.text) for item in absorbed.values()}
    elements_by_id = {element.id: element for element in elements}
    continuation_by_element: dict[UUID, Continuation] = {}
    for continuation in draft.sequence.continuations:
        continuation_by_element[continuation.left_id] = continuation
        continuation_by_element[continuation.right_id] = continuation
    ambiguous_by_element: dict[UUID, Continuation] = {}
    for continuation in draft.sequence.ambiguous:
        ambiguous_by_element[continuation.left_id] = continuation
        ambiguous_by_element[continuation.right_id] = continuation

    verdicts: dict[UUID, FragmentVerdict] = {}
    decisions: list[GateDecision] = []
    seen_texts: set[str] = set()
    for element in elements:
        continuity = continuation_by_element.get(element.id)
        ambiguous = ambiguous_by_element.get(element.id)
        has_repair_neighbor = bool(ambiguous) or _adjacent_fragment_neighbor(
            elements, element, draft
        )
        if continuity is not None and element.id in draft.sequence.merged_from:
            verdict = FragmentVerdict(
                element_id=element.id,
                status=ReconstructionStatus.RECONSTRUCTED.value,
                fragment_kinds=("CONTINUATION",),
                reasons=(continuity.reason,),
                signals=ConfidenceSignals.compute(
                    structure_confidence=0.9,
                    continuity_confidence=continuity.confidence,
                    semantic_completeness=0.88,
                    source_quality=draft.source_quality,
                ),
            )
        else:
            verdict = evaluate_fragment(
                element,
                references=draft.references,
                vocabulary=draft.vocabulary,
                seen_texts=seen_texts,
                absorbed_texts=absorbed_texts,
                continuity=ambiguous,
                has_repair_neighbor=has_repair_neighbor,
                source_quality=draft.source_quality,
            )
        seen_texts.add(normalize_term(element.text))
        verdicts[element.id] = verdict
        decisions.append(gate_element(verdict))

    for absorbed_element in absorbed.values():
        verdicts[absorbed_element.id] = FragmentVerdict(
            element_id=absorbed_element.id,
            status=ReconstructionStatus.DUPLICATE.value,
            reasons=("absorbed_by_continuation",),
            signals=ConfidenceSignals.compute(
                structure_confidence=0.4,
                continuity_confidence=1.0,
                source_quality=draft.source_quality,
            ),
        )

    representation = _build_representation(draft, elements, decisions)
    report = _build_report(draft, representation, decisions)
    updated = _apply_to_document(draft, elements, absorbed, decisions, report)
    representation.document_id = updated.id
    representation.organization_id = updated.organization_id
    representation.source_id = updated.source_id
    return ReconstructionOutcome(
        document=updated,
        representation=representation,
        report=report,
        decisions=decisions,
        verdicts=verdicts,
    )


def _adjacent_fragment_neighbor(
    elements: list[RawElement], element: RawElement, draft: ReconstructionDraft
) -> bool:
    """¿Existe al lado una pieza que esperaba reparación?"""
    try:
        index = elements.index(element)
    except ValueError:
        return False
    neighbors: list[RawElement] = []
    if index > 0:
        neighbors.append(elements[index - 1])
    if index + 1 < len(elements):
        neighbors.append(elements[index + 1])
    for neighbor in neighbors:
        if any(
            continuation.left_id == neighbor.id or continuation.right_id == neighbor.id
            for continuation in draft.sequence.ambiguous
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Fase 3 — IR y mutación del documento
# ---------------------------------------------------------------------------


def _build_representation(
    draft: ReconstructionDraft,
    elements: list[RawElement],
    decisions: list[GateDecision],
) -> SemanticRepresentation:
    document = draft.document
    units = [_unit_for(element, decision) for element, decision in zip(elements, decisions, strict=False)]
    units.extend(_absorbed_units(draft))
    tables = _semantic_tables(draft, elements)
    units.extend(_table_units(tables))
    status = _aggregate_status(decisions)
    representation = SemanticRepresentation(
        organization_id=document.organization_id,
        source_id=document.source_id,
        document_id=document.id,
        source_kind=draft.source_kind,
        adapter=draft.extraction.adapter,
        title=draft.extraction.title or document.title,
        status=status,
        nodes=_structural_nodes(elements),
        units=units,
        tables=tables,
        continuations=list(draft.sequence.continuations)[:MAX_IR_CONTINUATIONS],
        references=_references(draft, elements),
        warnings=list(draft.warnings),
    )
    return representation


def _unit_for(element: RawElement, decision: GateDecision) -> SemanticUnitIR:
    label = _element_label(element)
    kind = element.kind
    return SemanticUnitIR(
        id=element.id,
        key=f"{kind}:{normalize_term(label)}",
        kind=kind,
        label=label,
        text=element.text,
        status=decision.status,
        provenance=element.provenance,
        confidence=decision.signals,
        method=str(element.attributes.get("method") or "deterministic"),
        source_element_ids=(element.id,),
        continuation_id=str(
            element.attributes.get("continuation_id") or ""
        ) or None,
        attributes={
            key: value
            for key, value in element.attributes.items()
            if key not in {"method"}
        },
    )


def _element_label(element: RawElement) -> str:
    line = (element.text or "").splitlines()[0].strip() if element.text else element.kind
    return line[:120]


def _absorbed_units(draft: ReconstructionDraft) -> list[SemanticUnitIR]:
    """Los bloques absorbidos siguen en la IR con provenance (DUPLICATE)."""
    units: list[SemanticUnitIR] = []
    for element in draft.sequence.absorbed.values():
        units.append(
            SemanticUnitIR(
                id=element.id,
                key=f"{element.kind}:{normalize_term(_element_label(element))}",
                kind=element.kind,
                label=_element_label(element),
                text=element.text,
                status=ReconstructionStatus.DUPLICATE.value,
                provenance=element.provenance,
                confidence=ConfidenceSignals.compute(
                    structure_confidence=0.4,
                    continuity_confidence=1.0,
                    semantic_completeness=0.5,
                    source_quality=draft.source_quality,
                ),
                attributes={"absorbed_by_continuation": True},
            )
        )
    return units


def _structural_nodes(elements: list[RawElement]) -> list[StructuralNode]:
    return [
        StructuralNode(
            id=element.id,
            kind=element.kind,
            text=_element_label(element),
            order=element.order,
            depth=element.depth,
            parent_id=element.parent_id,
            provenance=element.provenance,
            confidence=element.confidence,
            attributes={"heading_path": list(element.heading_path)},
        )
        for element in elements
    ]


def _semantic_tables(
    draft: ReconstructionDraft, elements: list[RawElement]
) -> list[SemanticTable]:
    by_table: dict[str, list[RawElement]] = {}
    for element in elements:
        if element.kind == ElementKind.FIELD.value and element.provenance.table:
            by_table.setdefault(str(element.provenance.table), []).append(element)
    tables: list[SemanticTable] = []
    for raw_table, decision in zip(
        draft.extraction.tables, draft.table_decisions, strict=False
    ):
        fields = [
            _semantic_field(element)
            for element in by_table.get(raw_table.name, [])
        ]
        if not fields:
            fields = [
                SemanticField(
                    id=f"{raw_table.id}:{position}",
                    name=str(header),
                    inferred_type=str(
                        raw_table.metadata.get("data_types", {}).get(str(header), "unknown")
                    ),
                    status=(
                        ReconstructionStatus.REQUIRES_REPAIR.value
                        if header in decision.rejected_headers
                        else ReconstructionStatus.VALID.value
                    ),
                    position=position,
                    provenance=raw_table.provenance,
                )
                for position, header in enumerate(raw_table.headers, start=1)
                if str(header).strip()
            ]
        records = [
            SemanticRecord(
                id=f"{raw_table.id}:row:{position}",
                table_id=raw_table.id,
                values={
                    str(header): str(row[column]) if column < len(row) else ""
                    for column, header in enumerate(raw_table.headers)
                },
                physical_row=_physical_row(raw_table, position),
                provenance=dataclasses.replace(
                    raw_table.provenance,
                    row=_physical_row(raw_table, position),
                ),
            )
            for position, row in enumerate(raw_table.rows[:MAX_IR_RECORDS_PER_TABLE])
            if any(str(cell).strip() for cell in row)
        ]
        tables.append(
            SemanticTable(
                id=raw_table.id,
                name=raw_table.name,
                headers=tuple(str(header) for header in raw_table.headers),
                rows=tuple(tuple(str(cell) for cell in row) for row in raw_table.rows[:MAX_IR_RECORDS_PER_TABLE]),
                records=tuple(records),
                fields=tuple(fields),
                header_depth=raw_table.header_depth,
                merged_cells=tuple(raw_table.merged_cells[:50]),
                formulas=tuple(raw_table.formulas[:50]),
                status=decision.status,
                confidence=decision.signals,
                provenance=raw_table.provenance,
                metadata={
                    **raw_table.metadata,
                    "rejected_headers": list(decision.rejected_headers),
                    "repeated_header_rows": list(decision.repeated_header_rows),
                },
            )
        )
    return tables[:MAX_IR_TABLES]


def _semantic_field(element: RawElement) -> SemanticField:
    attributes = element.attributes
    unique_ratio = attributes.get("unique_ratio")
    possible_key = bool(
        unique_ratio is not None
        and float(unique_ratio or 0.0) >= 0.95
        and not bool(attributes.get("nullable", True))
    )
    metadata = {
        key: attributes.get(key)
        for key in ("excel_letter", "type_confidence", "null_ratio", "unique_ratio")
        if attributes.get(key) is not None
    }
    metadata["possible_key"] = possible_key
    return SemanticField(
        id=str(element.id),
        name=element.text,
        normalized_name=str(attributes.get("normalized_name") or normalize_term(element.text)),
        inferred_type=str(attributes.get("inferred_type") or "unknown"),
        semantic_type=str(attributes.get("semantic_type") or "unknown"),
        description=str(attributes.get("description") or ""),
        nullable=bool(attributes.get("nullable", True)),
        position=attributes.get("physical_index") or attributes.get("position"),
        header_path=tuple(attributes.get("header_path") or ()),
        aliases=tuple(attributes.get("aliases") or ()),
        sample_values=tuple(attributes.get("sample_values") or ()),
        status=ReconstructionStatus.VALID.value,
        provenance=element.provenance,
        metadata=metadata,
    )


def _table_units(tables: list[SemanticTable]) -> list[SemanticUnitIR]:
    units: list[SemanticUnitIR] = []
    for table in tables:
        units.append(
            SemanticUnitIR(
                id=_stable_unit_id(table.id),
                key=f"table:{normalize_term(table.name)}",
                kind=ElementKind.TABLE.value,
                label=table.name,
                text=" | ".join(table.headers[:40]),
                status=table.status,
                provenance=table.provenance,
                confidence=table.confidence,
                attributes={"row_count": len(table.rows), "field_count": len(table.fields)},
            )
        )
    return units


def _stable_unit_id(value: str) -> UUID:
    import hashlib

    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return UUID(bytes=bytes.fromhex(digest[:32]))


def _physical_row(table: RawTable, position: int) -> int | None:
    header_rows = table.metadata.get("header_rows") or []
    if header_rows:
        return int(max(header_rows)) + position + 1
    return position + 1


def _references(draft: ReconstructionDraft, elements: list[RawElement]) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for element in elements[:200]:
        attributes = element.attributes or {}
        if attributes.get("json_path") or attributes.get("xpath") or attributes.get("references"):
            references.append(
                {
                    "element_id": str(element.id),
                    "kind": element.kind,
                    "target": attributes.get("json_path") or attributes.get("xpath"),
                    "path": attributes.get("json_path") or attributes.get("xpath"),
                    "provenance": element.provenance.to_dict(),
                }
            )
    return references


# ---------------------------------------------------------------------------
# Aplicación al StructuredDocument (provenance viva)
# ---------------------------------------------------------------------------


def _apply_to_document(
    draft: ReconstructionDraft,
    elements: list[RawElement],
    absorbed: dict,
    decisions: list[GateDecision],
    report: dict[str, Any],
) -> StructuredDocument:
    document = draft.document
    decision_by_element = {decision.element_id: decision for decision in decisions}
    verdicts = {element.id: decision_by_element.get(element.id) for element in elements}
    element_by_block: dict[UUID, RawElement] = {}
    element_by_id: dict[UUID, RawElement] = {}
    for element in elements:
        element_by_id[element.id] = element
        block_id = element.provenance.block_id
        if block_id is not None:
            element_by_block[block_id] = element
    absorbed_by_block = {
        element.provenance.block_id: element for element in absorbed.values() if element.provenance.block_id
    }

    blocks: list[StructuredBlock] = []
    for block in document.blocks:
        if block.id in absorbed_by_block:
            absorbed_element = absorbed_by_block[block.id]
            root_element_id = draft.sequence.merged_into.get(absorbed_element.id)
            root_element = element_by_id.get(root_element_id) if root_element_id else None
            meta = dict(block.metadata)
            meta["superseded"] = True
            meta["superseded_into"] = (
                str(root_element.provenance.block_id)
                if root_element is not None and root_element.provenance.block_id
                else (str(root_element_id) if root_element_id else None)
            )
            meta["index_semantic"] = False
            meta["reconstruction_status"] = ReconstructionStatus.DUPLICATE.value
            meta["reconstruction"] = {"stage": "continuation_absorbed"}
            blocks.append(dataclasses.replace(block, metadata=meta))
            continue
        element = element_by_block.get(block.id)
        if element is None:
            blocks.append(block)
            continue
        decision = verdicts.get(element.id)
        status = decision.status if decision is not None else ReconstructionStatus.VALID.value
        meta = dict(block.metadata)
        meta["reconstruction_status"] = status
        meta["reconstruction_confidence"] = (
            decision.signals.to_dict() if decision is not None else None
        )
        if status in {item.value for item in _SKIP_INDEX_STATUSES}:
            meta["index_semantic"] = False
        text = element.text if element.text else block.text
        continuation = draft.sequence.continuation_for(element.id)
        if continuation is not None and element.id in draft.sequence.merged_from:
            meta["reconstruction"] = {
                "stage": "continuation_merged",
                "kind": continuation.kind,
                "confidence": continuation.confidence,
                "method": continuation.method,
                "merged_from": [
                    str(value) for value in draft.sequence.merged_from.get(element.id, ())
                ],
            }
            meta["reflowed"] = True
        blocks.append(
            dataclasses.replace(
                block,
                text=text,
                token_count=token_count(text),
                content_hash=content_hash(text),
                metadata=meta,
            )
        )

    tables = []
    for table in document.tables:
        table_decision = next(
            (
                decision
                for decision, raw in zip(draft.table_decisions, draft.extraction.tables, strict=False)
                if raw.provenance.table == (table.caption or f"table-{document.tables.index(table)}")
            ),
            None,
        )
        if table_decision is None:
            tables.append(table)
            continue
        meta = dict(table.metadata)
        meta["semantic_reconstruction"] = {
            "status": table_decision.status,
            "rejected_headers": list(table_decision.rejected_headers),
            "repeated_header_rows": list(table_decision.repeated_header_rows),
        }
        tables.append(dataclasses.replace(table, metadata=meta))

    rejected_terms = sorted(
        {
            normalize_term(decision_label)
            for decision, decision_label in _decision_labels(elements, decisions)
            if decision.status in {item.value for item in _SKIP_INDEX_STATUSES}
        }
        | {
            normalize_term(header)
            for table_decision in draft.table_decisions
            for header in table_decision.rejected_headers
        }
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "pipeline": _PIPELINE,
        "source_kind": draft.source_kind,
        "adapter": draft.extraction.adapter,
        "status": report.get("status"),
        "stats": report.get("stats") or {},
        "quality": report.get("quality") or {},
        "units": [
            unit.compact()
            for unit in _all_units(draft, elements, decisions) + _absorbed_units(draft)
        ][:MAX_IR_UNITS],
        "tables": [table.compact() for table in _semantic_tables(draft, elements)][:MAX_IR_TABLES],
        "nodes": [
            {
                "id": str(node.id),
                "kind": node.kind,
                "text": node.text[:200],
                "order": node.order,
                "depth": node.depth,
                "parent_id": str(node.parent_id) if node.parent_id else None,
                "page": node.provenance.page,
                "heading_path": list(node.provenance.section_path[:8]),
            }
            for node in _structural_nodes(elements)[:MAX_IR_UNITS]
        ],
        "continuations": [
            continuation.to_dict() for continuation in draft.sequence.continuations[:MAX_IR_CONTINUATIONS]
        ],
        "pending_decisions": _pending_decisions(draft, elements),
        "rejected_terms": rejected_terms,
        "warnings": list(draft.warnings),
        "elapsed_ms": report.get("elapsed_ms"),
        "llm": {
            "calls": 0,
            "repairs": 0,
            "assisted": False,
        },
    }
    metadata = {**document.metadata, "semantic_reconstruction": payload}
    return dataclasses.replace(document, blocks=tuple(blocks), tables=tuple(tables), metadata=metadata)


def _all_units(
    draft: ReconstructionDraft, elements: list[RawElement], decisions: list[GateDecision]
) -> list[SemanticUnitIR]:
    units = [
        _unit_for(element, decision)
        for element, decision in zip(elements, decisions, strict=False)
    ]
    units.extend(_table_units(_semantic_tables(draft, elements)))
    return units


def _decision_labels(elements: list[RawElement], decisions: list[GateDecision]):
    by_id = {element.id: element for element in elements}
    for decision in decisions:
        element = by_id.get(decision.element_id)
        if element is not None:
            yield decision, _element_label(element)


def _pending_decisions(draft: ReconstructionDraft, elements: list[RawElement]) -> list[dict[str, Any]]:
    by_id = {element.id: element for element in elements}
    pending: list[dict[str, Any]] = []
    for continuation in draft.sequence.ambiguous:
        left = by_id.get(continuation.left_id)
        right = by_id.get(continuation.right_id)
        if left is None or right is None:
            continue
        pending.append(
            {
                "decision_id": continuation.id,
                "kind": continuation.kind,
                "confidence": continuation.confidence,
                "left_element_id": str(left.id),
                "right_element_id": str(right.id),
                "left_block_id": str(left.provenance.block_id) if left.provenance.block_id else None,
                "right_block_id": str(right.provenance.block_id) if right.provenance.block_id else None,
                "left_text": left.text[:600],
                "right_text": right.text[:600],
                "evidence": continuation.evidence,
                "reason": continuation.reason,
            }
        )
    for table_decision in draft.table_decisions:
        for header in table_decision.rejected_headers:
            pending.append(
                {
                    "decision_id": f"header:{table_decision.table_id}:{normalize_term(header)}",
                    "kind": "TABLE_HEADER",
                    "confidence": 0.4,
                    "table_id": table_decision.table_id,
                    "header": header,
                    "evidence": {"rejected_header": header},
                    "reason": "table_header_fragment",
                }
            )
    return pending


# ---------------------------------------------------------------------------
# Reporte
# ---------------------------------------------------------------------------


def _build_report(
    draft: ReconstructionDraft,
    representation: SemanticRepresentation,
    decisions: list[GateDecision],
) -> dict[str, Any]:
    distribution = gate_distribution(decisions)
    reconstructed = distribution.get(ReconstructionStatus.RECONSTRUCTED.value, 0)
    rejected = sum(
        distribution.get(status, 0)
        for status in (
            ReconstructionStatus.REJECTED.value,
            ReconstructionStatus.LOW_QUALITY.value,
            ReconstructionStatus.INCOMPLETE.value,
            ReconstructionStatus.STRUCTURAL_ARTIFACT.value,
            ReconstructionStatus.DUPLICATE.value,
        )
    )
    ambiguous = distribution.get(ReconstructionStatus.AMBIGUOUS.value, 0) + distribution.get(
        ReconstructionStatus.REQUIRES_REPAIR.value, 0
    )
    tables = representation.tables
    schemas_inferred = sum(
        1
        for table in tables
        if any(field.inferred_type != "unknown" for field in table.fields)
    )
    elapsed_ms = round((time.perf_counter() - draft.started) * 1000, 2)
    stats = {
        "raw_elements": len(draft.extraction.elements),
        "semantic_units": len(decisions),
        "units_reconstructed": reconstructed,
        "continuations_detected": len(draft.sequence.continuations)
        + len(draft.sequence.ambiguous),
        "merged_continuations": len(draft.sequence.continuations),
        "fragments_rejected": rejected,
        "tables_detected": len(draft.extraction.tables),
        "tables_reconstructed": sum(
            1 for decision in draft.table_decisions if decision.status != ReconstructionStatus.VALID.value
        ),
        "schemas_inferred": schemas_inferred,
        "sheets": int(draft.extraction.stats.get("sheets") or 0),
        "rows": int(draft.extraction.stats.get("rows") or 0),
        "columns": int(draft.extraction.stats.get("columns") or 0),
        "ambiguous_units": ambiguous,
        "rejected_units": distribution.get(ReconstructionStatus.REJECTED.value, 0)
        + distribution.get(ReconstructionStatus.INCOMPLETE.value, 0)
        + distribution.get(ReconstructionStatus.LOW_QUALITY.value, 0),
        "deterministic_repairs": reconstructed,
        "llm_repairs": 0,
        "quality_score": quality_score(decisions),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "pipeline": _PIPELINE,
        "source_kind": draft.source_kind,
        "adapter": draft.extraction.adapter,
        "status": representation.status,
        "stats": stats,
        "quality": {
            "score": stats["quality_score"],
            "distribution": distribution,
        },
        "warnings": list(draft.warnings),
        "elapsed_ms": elapsed_ms,
    }


def _aggregate_status(decisions: list[GateDecision]) -> str:
    if not decisions:
        return ReconstructionStatus.REJECTED.value
    knowledge = sum(1 for decision in decisions if decision.knowledge)
    ratio = knowledge / len(decisions)
    if ratio >= 0.9:
        if any(
            decision.status == ReconstructionStatus.RECONSTRUCTED.value
            for decision in decisions
        ):
            return ReconstructionStatus.RECONSTRUCTED.value
        return ReconstructionStatus.VALID.value
    if ratio >= 0.5:
        return ReconstructionStatus.RECONSTRUCTED.value
    if ratio > 0:
        return ReconstructionStatus.LOW_QUALITY.value
    return ReconstructionStatus.REJECTED.value


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


def reconstruct_document(
    document: StructuredDocument,
    *,
    raw_text: str | None = None,
    adapter: SourceAdapter | None = None,
    source_kind: str | None = None,
    source_quality: float | None = None,
) -> ReconstructionOutcome:
    """Pipeline determinista completo (sin LLM)."""
    draft = build_draft(
        document,
        raw_text=raw_text,
        adapter=adapter,
        source_kind=source_kind,
        source_quality=source_quality,
    )
    return finalize_draft(draft)


def ensure_reconstruction(
    document: StructuredDocument,
    *,
    raw_text: str | None = None,
) -> tuple[StructuredDocument, list[dict[str, Any]]]:
    """Reconstruye si falta el payload. Devuelve (documento, quality issues).

    Es la puerta obligatoria del Knowledge Compiler: ningún documento entra
    crudo. Idempotente por `schema_version`.
    """
    payload = document.metadata.get("semantic_reconstruction")
    if isinstance(payload, dict) and payload.get("schema_version") == SCHEMA_VERSION:
        return document, reconstruction_quality_issues(document)
    outcome = reconstruct_document(document, raw_text=raw_text)
    return outcome.document, reconstruction_quality_issues(outcome.document)


def apply_semantic_reconstruction(
    document: StructuredDocument,
    *,
    raw_text: str | None = None,
) -> StructuredDocument:
    return ensure_reconstruction(document, raw_text=raw_text)[0]


def semantic_reconstruction_payload(document: StructuredDocument) -> dict[str, Any]:
    payload = document.metadata.get("semantic_reconstruction")
    return payload if isinstance(payload, dict) else {}


def reconstruction_quality_issues(document: StructuredDocument) -> list[dict[str, Any]]:
    """Convierte la cuarentena de reconstruction en issues de INGESTION_QUALITY."""
    payload = semantic_reconstruction_payload(document)
    issues: list[dict[str, Any]] = []
    for unit in payload.get("units") or []:
        status = str(unit.get("status") or "")
        if status in {item.value for item in _SKIP_INDEX_STATUSES}:
            issues.append(
                {
                    "kind": "INGESTION_QUALITY",
                    "subject": str(unit.get("label") or unit.get("key") or "")[:300],
                    "detail": {
                        "stage": "semantic_reconstruction",
                        "classification": status,
                        "fragment_kinds": unit.get("attributes", {}).get("fragment_kinds"),
                        "source_kind": payload.get("source_kind"),
                    },
                    "confidence": (unit.get("confidence") or {}).get("reconstruction_confidence"),
                }
            )
        if len(issues) >= 500:
            break
    for table in payload.get("tables") or []:
        for header in table.get("metadata", {}).get("rejected_headers") or []:
            issues.append(
                {
                    "kind": "INGESTION_QUALITY",
                    "subject": str(header)[:300],
                    "detail": {
                        "stage": "semantic_reconstruction",
                        "classification": ReconstructionStatus.REQUIRES_REPAIR.value,
                        "table": table.get("name"),
                        "fragment_kinds": ["TABLE_FRAGMENT"],
                    },
                }
            )
    return issues


def _source_quality(document: StructuredDocument) -> float:
    confidences = [
        float(page.metadata.get("text_confidence"))
        for page in document.pages
        if isinstance(page.metadata.get("text_confidence"), (int, float))
    ]
    if confidences:
        return round(sum(confidences) / len(confidences), 4)
    return 0.8


def _reference_corpus(
    document: StructuredDocument, extraction: RawExtraction
) -> tuple[str, ...]:
    """Textos completos de la fuente para detectar fragmentos y reponer piezas."""
    references: list[str] = []
    if document.title:
        references.append(document.title)
    if extraction.title and extraction.title != document.title:
        references.append(extraction.title)
    for element in extraction.elements[:2000]:
        text = (element.text or "").strip()
        if text and len(text) <= 20_000:
            references.append(text)
    for section in document.sections[:800]:
        heading = (section.heading or "").strip()
        if heading:
            references.append(heading)
    return tuple(references)


def detect_repeated_headers(document: StructuredDocument) -> list[Continuation]:
    """Atajo de auditoría para headers repetidos en tablas del documento."""
    found: list[Continuation] = []
    for table in document.tables:
        found.extend(
            detect_repeated_table_headers(
                RawTable(
                    id=str(table.id),
                    name=table.caption or str(table.id),
                    headers=tuple(table.headers),
                    rows=tuple(tuple(row) for row in table.rows),
                    provenance=SourceProvenance(),
                )
            )
        )
    return found


def source_kind_of(document: StructuredDocument, raw_text: str | None = None) -> str:
    return detect_source_kind(document, raw_text)


__all__ = [
    "ReconstructionDraft",
    "ReconstructionOutcome",
    "apply_semantic_reconstruction",
    "build_draft",
    "ensure_reconstruction",
    "finalize_draft",
    "reconstruct_document",
    "reconstruction_quality_issues",
    "semantic_reconstruction_payload",
    "source_kind_of",
]
