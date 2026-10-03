# =============================================================================
# Knowledge Compiler — SOURCE UNDERSTANDING y STRUCTURE DISCOVERY
# =============================================================================
# Convierte el árbol StructuredDocument (y su representación tabular) en
# SEMANTIC UNITS con evidencia localizable. No inventa: si un término no está
# en la fuente, no existe.
#
# Fuentes de unidades:
#   1. `document.metadata["understanding"]` (definiciones, campos técnicos,
#      literales exactos, referencias cruzadas, relaciones) — el trabajo del
#      Document Understanding, ya persistido junto al documento.
#   2. Bloques con rol (procedimiento, nota, advertencia, ejemplo, referencia).
#   3. Tablas del documento (DocumentTable) y el árbol tabular (Excel/CSV).
# =============================================================================
from __future__ import annotations

import re
from uuid import UUID

from src.core.domain.knowledge_v2 import StructuredBlockKind, StructuredDocument
from src.knowledge.compiler.model import (
    EvidenceRef,
    EvidenceType,
    SemanticUnit,
    SemanticUnitKind,
    SourceLocator,
    normalize_term,
)
from src.knowledge.quality.fragments import TextQualityStatus, analyze_text_quality
from src.knowledge.quality.ingestion import QualityCollector, QualityKind
from src.knowledge.reconstruction.contracts import NON_KNOWLEDGE_STATUSES

_MIN_TEXT = 2
_MAX_UNITS_PER_DOCUMENT = 20_000

_DEFINITION_LINE = re.compile(r"^(?P<term>.{1,60}?)\s*(?::|—|–|\s-\s)\s*(?P<body>\S.{1,600})$")
_FIELD_NAME_LINE = re.compile(
    r"^(?:field|campo|name|nombre)\s*:\s*(?P<name>.+?)(?:\s*[—–:|-]\s*(?P<body>.+))?$",
    flags=re.IGNORECASE,
)
_FIELD_POSITION_RANGE = re.compile(r"(?P<start>\d{1,4})\s*[-–]\s*(?P<end>\d{1,4})")
_TABLE_ROW_SEPARATOR = re.compile(r"\s*\|\s*|\t+|\s{3,}")
_NAME_WITH_ALIAS = re.compile(
    r"^(?P<name>[^()\[\]]{2,120}?)\s*[\(\[](?P<alias>[^()\[\]]{2,60})[\)\]]\s*$"
)


def _parse_definition_line(text: str) -> tuple[str, str] | None:
    """`Término: definición` (con o sin espacio antes de los dos puntos)."""
    first = text.strip().splitlines()[0].strip()
    match = _DEFINITION_LINE.match(first)
    if match is None:
        return None
    term = match.group("term").strip(" .,:;|-–—")
    body = match.group("body").strip()
    if len(term) < _MIN_TEXT or len(body) < _MIN_TEXT:
        return None
    # Un párrafo no es una definición solo por tener dos puntos: el término
    # debe parecer un término (corto, sin puntuación de oración).
    if "." in term or "," in term or len(term.split()) > 8:
        return None
    if len(text.strip().splitlines()) > 1:
        body = text.strip()
    return term, body


def _parse_field_line(text: str) -> dict | None:
    """`Byte 105 | 3 | Currency Code | ISO 4217` -> campo técnico posicional."""
    first = text.strip().splitlines()[0].strip()
    named = _FIELD_NAME_LINE.match(first)
    if named is not None and len(named.group("name").strip()) >= _MIN_TEXT:
        name = named.group("name").strip(" .,:;|-–—")
        body = (named.group("body") or "").strip()
        attributes = _position_attributes(text)
        return {"name": name, "description": body, "attributes": attributes}

    cells = [cell.strip() for cell in _TABLE_ROW_SEPARATOR.split(first) if cell.strip()]
    if len(cells) >= 2:
        name = cells[0].strip(" .,:;|-–—")
        if len(name) >= _MIN_TEXT and len(name) <= 80:
            attributes = _position_attributes(text)
            for cell in cells[1:-1]:
                if _FIELD_POSITION_RANGE.fullmatch(cell):
                    continue
                try:
                    attributes.setdefault("length", int(cell))
                except ValueError:
                    attributes.setdefault("label", cell)
            return {
                "name": name,
                "description": cells[-1],
                "attributes": attributes,
            }

    range_match = _FIELD_POSITION_RANGE.search(first)
    if range_match is not None:
        remainder = first[range_match.end() :].strip()
        if len(remainder) >= _MIN_TEXT:
            name = remainder.split("  ")[0].strip(" .,:;|-–—")[:80]
            attributes = _position_attributes(first)
            return {
                "name": name,
                "description": remainder[len(name) :].strip(),
                "attributes": attributes,
            }
    return None


def _position_attributes(text: str) -> dict:
    attributes: dict = {}
    match = _FIELD_POSITION_RANGE.search(text)
    if match is None:
        return attributes
    start, end = int(match.group("start")), int(match.group("end"))
    attributes["start_position"] = start
    attributes["end_position"] = end
    if end >= start:
        attributes["length"] = end - start + 1
    return attributes


def _understood_payload(document: StructuredDocument) -> dict:
    payload = document.metadata.get("understanding")
    return payload if isinstance(payload, dict) else {}


def _rejected_terms(document: StructuredDocument) -> frozenset[str]:
    """Términos que Semantic Reconstruction puso en cuarentena."""
    payload = document.metadata.get("semantic_reconstruction")
    if not isinstance(payload, dict):
        return frozenset()
    return frozenset(str(value) for value in payload.get("rejected_terms") or ())


def _reconstruction_blocked(block) -> bool:
    """Un bloque reconstruido como no-conocimiento no alimenta al compilador."""
    if block.metadata.get("index_semantic") is False:
        return True
    status = str(block.metadata.get("reconstruction_status") or "")
    return status in NON_KNOWLEDGE_STATUSES


def _reference_corpus(document: StructuredDocument) -> tuple[str, ...]:
    """Textos completos observados en la fuente, para detectar fragmentos.

    Incluye título, bloques y secciones. NO incluye las tablas: el propio texto
    de la tabla puede estar fragmentado, y usarlo como referencia convertiría
    el fragmento en "palabra válida".
    """
    references: list[str] = []
    if document.title:
        references.append(document.title)
    for block in document.blocks[:2000]:
        text = (block.text or "").strip()
        if text and len(text) <= 20_000:
            references.append(text)
    for section in document.sections[:800]:
        heading = (section.heading or "").strip()
        if heading:
            references.append(heading)
    return tuple(references)


def _is_title_banner(term: str, document: StructuredDocument) -> bool:
    """¿El 'término' es en realidad el título repetido de la fuente?

    También rechaza rótulos estructurales que no son términos ("Example 1",
    "KEY", "Figure 3"): un ejemplo o una leyenda no definen un concepto.
    """
    term_key = normalize_term(term)
    title_key = normalize_term(document.title or "")
    if not term_key:
        return False
    if term_key.isdigit():
        return True
    if term_key in {
        "example", "note", "key", "figure", "fig", "table", "tabla",
        "step", "paso", "chapter", "section",
    }:
        return True
    first = re.split(r"[\s:;.,=|/]+", term_key, maxsplit=1)[0]
    if first in {"example", "note", "key", "figure", "fig", "step", "paso"}:
        return True
    if not title_key or term_key == title_key:
        return False
    if term_key in title_key or title_key in term_key:
        return True
    return False


def _label_quality(
    label: str, references: tuple[str, ...], *, max_words: int = 16
):
    """Calidad de un nombre candidato (entidad, columna, término)."""
    return analyze_text_quality(
        label,
        references=references,
        min_length=3,
        allow_code=True,
        max_words=max_words,
        max_length=160,
    )


def extracta_for(document: StructuredDocument) -> dict:
    """Semánticas extraídas del documento.

    Usa el payload persistido por el Document Understanding; si el documento
    llegó sin pasar por él (conectores crudos, tests), las deriva aquí para que
    el compilador nunca dependa de que un flag haya estado activo.
    """
    payload = _understood_payload(document)
    if payload.get("definitions") is not None or payload.get("technical_fields"):
        return {
            "definitions": payload.get("definitions") or [],
            "technical_fields": payload.get("technical_fields") or [],
            "exact_literals": payload.get("exact_literals") or [],
            "cross_references": payload.get("cross_references") or [],
            "relations": payload.get("relations") or [],
        }
    try:
        from src.knowledge.understanding.enrich import derive_document_semantics

        _document, derived = derive_document_semantics(document)
        return derived
    except Exception:  # noqa: BLE001 — sin semánticas el compilador sigue
        return {
            "definitions": [],
            "technical_fields": [],
            "exact_literals": [],
            "cross_references": [],
            "relations": [],
        }


class _LocatorIndex:
    """Resuelve block_id -> (página, section_path) sin recorrer el árbol N veces."""

    def __init__(self, document: StructuredDocument) -> None:
        self.document = document
        self.section_paths: dict[str, tuple[str, ...]] = {
            str(section.id): tuple(section.section_path) for section in document.sections
        }
        self.block_section: dict[str, str] = {}
        for block in document.blocks:
            section_id = block.metadata.get("parent_section_id")
            if section_id:
                self.block_section[str(block.id)] = str(section_id)
        self.block_page: dict[str, int | None] = {
            str(block.id): block.page for block in document.blocks
        }
        self.block_hash: dict[str, str | None] = {
            str(block.id): block.content_hash for block in document.blocks
        }

    def section_path(self, section_id: object) -> tuple[str, ...]:
        if section_id in (None, ""):
            return ()
        return self.section_paths.get(str(section_id), ())

    def locator(
        self,
        *,
        block_id: object = None,
        section_id: object = None,
        page: int | None = None,
        table_reference: str | None = None,
        row_reference: str | None = None,
        cell_reference: str | None = None,
    ) -> SourceLocator:
        document = self.document
        resolved_block = str(block_id) if block_id else None
        if page is None and resolved_block:
            page = self.block_page.get(resolved_block)
        section_path = self.section_path(section_id)
        if not section_path and resolved_block:
            section_path = self.section_path(self.block_section.get(resolved_block))
        parsed_block: UUID | None = None
        if resolved_block:
            try:
                parsed_block = UUID(resolved_block)
            except (ValueError, TypeError):
                parsed_block = None
        return SourceLocator(
            source_id=document.source_id,
            document_id=document.id,
            document_title=document.title,
            block_id=parsed_block,
            page=page,
            section_path=section_path,
            table_reference=table_reference,
            row_reference=row_reference,
            cell_reference=cell_reference,
            content_hash=(
                self.block_hash.get(resolved_block) if resolved_block else None
            )
            or document.content_hash,
        )


def _evidence(
    index: _LocatorIndex,
    *,
    excerpt: str,
    evidence_type: str = EvidenceType.STRUCTURAL.value,
    confidence: float = 0.8,
    method: str = "deterministic",
    **locator_kwargs,
) -> EvidenceRef:
    return EvidenceRef(
        locator=index.locator(**locator_kwargs),
        evidence_type=evidence_type,
        excerpt=excerpt,
        method=method,
        confidence=confidence,
    )


def _reject_label(
    collector: QualityCollector | None,
    document: StructuredDocument,
    *,
    subject: str,
    quality_status: str,
    evidence: EvidenceRef | None = None,
    detail: dict | None = None,
) -> None:
    """Registra un candidato rechazado. Sin collector no hay I/O, solo skip."""
    if collector is None:
        return
    kind = {
        TextQualityStatus.FRAGMENT_OF_EXISTING_TEXT.value: QualityKind.FRAGMENT_OF_EXISTING_TEXT.value,
        TextQualityStatus.TRUNCATED_WORD.value: QualityKind.TRUNCATED_WORD.value,
        TextQualityStatus.LAYOUT_ARTIFACT.value: QualityKind.LAYOUT_ARTIFACT.value,
        TextQualityStatus.SENTENCE_FRAGMENT.value: QualityKind.SENTENCE_FRAGMENT.value,
        TextQualityStatus.TOO_LONG_FOR_TERM.value: QualityKind.TOO_LONG_FOR_TERM.value,
    }.get(quality_status, QualityKind.LOW_QUALITY_EXTRACTION.value)
    collector.add(
        kind,
        subject,
        detail={"quality_status": quality_status, **(detail or {})},
        evidence=evidence,
        source_id=document.source_id,
        document_id=document.id,
    )


def extract_semantic_units(
    document: StructuredDocument,
    *,
    quality: QualityCollector | None = None,
) -> list[SemanticUnit]:
    """Unidades semánticas del documento: definiciones, campos, tablas, etc.

    Unidad que no supera el control de calidad (fragmento, corte, artefacto)
    no entra: se registra en la cola de calidad de ingesta.
    """
    index = _LocatorIndex(document)
    extracted = extracta_for(document)
    references = _reference_corpus(document)
    units: list[SemanticUnit] = []
    seen: set[tuple[str, str]] = set()

    def add(unit: SemanticUnit) -> None:
        if len(units) >= _MAX_UNITS_PER_DOCUMENT:
            return
        key = (unit.kind, unit.key)
        if key in seen:
            return
        seen.add(key)
        units.append(unit)

    for item in extracted["definitions"]:
        term = str(item.get("term") or "").strip()
        body = str(item.get("definition") or "").strip()
        if len(term) < _MIN_TEXT or len(body) < _MIN_TEXT:
            continue
        if _is_title_banner(term, document):
            _reject_label(
                quality,
                document,
                subject=term,
                quality_status=TextQualityStatus.LOW_QUALITY_EXTRACTION.value,
                detail={"stage": "definition", "reason": "title_banner"},
            )
            continue
        term_quality = _label_quality(term, references)
        if not term_quality.ok:
            _reject_label(
                quality,
                document,
                subject=term,
                quality_status=term_quality.status,
                evidence=_evidence(
                    index,
                    excerpt=term,
                    block_id=item.get("block_id"),
                    section_id=item.get("section_id"),
                    page=item.get("page"),
                ),
                detail={"stage": "definition"},
            )
            continue
        add(
            SemanticUnit(
                kind=SemanticUnitKind.DEFINITION.value,
                key=f"definition:{normalize_term(term)}",
                label=term,
                text=body,
                confidence=float(item.get("confidence") or 0.82),
                attributes={"scope": item.get("scope")},
                evidence=_evidence(
                    index,
                    excerpt=f"{term}: {body}",
                    block_id=item.get("block_id"),
                    section_id=item.get("section_id"),
                    page=item.get("page"),
                    confidence=float(item.get("confidence") or 0.82),
                ),
            )
        )

    for item in extracted["technical_fields"]:
        name = str(item.get("name") or "").strip()
        if len(name) < _MIN_TEXT:
            continue
        name_quality = _label_quality(name, references)
        if not name_quality.ok:
            _reject_label(
                quality,
                document,
                subject=name,
                quality_status=name_quality.status,
                evidence=_evidence(
                    index,
                    excerpt=name,
                    block_id=item.get("block_id"),
                    section_id=item.get("section_id"),
                    page=item.get("page"),
                ),
                detail={"stage": "technical_field"},
            )
            continue
        description = str(item.get("description") or "").strip()
        start, end = item.get("start_position"), item.get("end_position")
        add(
            SemanticUnit(
                kind=SemanticUnitKind.FIELD.value,
                key=f"field:{normalize_term(name)}",
                label=name,
                text=description,
                confidence=float(item.get("confidence") or 0.84),
                attributes={
                    "start_position": start,
                    "end_position": end,
                    "length": item.get("length"),
                    "literal_pattern": item.get("literal_pattern"),
                    "allowed_values": item.get("allowed_values") or [],
                },
                evidence=_evidence(
                    index,
                    excerpt=description or name,
                    block_id=item.get("block_id"),
                    section_id=item.get("section_id"),
                    page=item.get("page"),
                    confidence=float(item.get("confidence") or 0.84),
                ),
            )
        )

    for table in document.tables:
        reference = table.caption or f"table-{table.id}"
        add(
            SemanticUnit(
                kind=SemanticUnitKind.TABLE.value,
                key=f"table:{normalize_term(reference)}",
                label=reference,
                text="\n".join(
                    " | ".join(row) for row in table.rows[:20]
                ),
                confidence=0.9,
                attributes={
                    "headers": list(table.headers),
                    "row_count": table.row_count,
                    "column_count": table.column_count,
                },
                evidence=_evidence(
                    index,
                    excerpt=table.caption or reference,
                    page=table.page,
                    table_reference=reference,
                    evidence_type=EvidenceType.STRUCTURAL.value,
                    confidence=0.9,
                ),
            )
        )
        header_evidence = _evidence(
            index,
            excerpt=" | ".join(table.headers)[:400],
            page=table.page,
            table_reference=reference,
            evidence_type=EvidenceType.STRUCTURAL.value,
            confidence=0.9,
        )
        for position, header in enumerate(table.headers, start=1):
            column_name = str(header or "").strip()
            if len(column_name) < _MIN_TEXT:
                continue
            if _is_title_banner(column_name, document):
                _reject_label(
                    quality,
                    document,
                    subject=column_name,
                    quality_status=TextQualityStatus.LOW_QUALITY_EXTRACTION.value,
                    evidence=header_evidence,
                    detail={"stage": "table_header", "table": reference, "reason": "banner"},
                )
                continue
            column_quality = _label_quality(column_name, references, max_words=8)
            if not column_quality.ok:
                _reject_label(
                    quality,
                    document,
                    subject=column_name,
                    quality_status=column_quality.status,
                    evidence=header_evidence,
                    detail={"stage": "table_header", "table": reference},
                )
                continue
            add(
                SemanticUnit(
                    kind=SemanticUnitKind.COLUMN.value,
                    key=f"column:{normalize_term(reference)}:{normalize_term(column_name)}",
                    label=column_name,
                    text=f"Columna {position} de {reference}",
                    confidence=0.88,
                    attributes={
                        "position": position,
                        "table": reference,
                        "row_reference": None,
                    },
                    evidence=header_evidence,
                )
            )

    for block in document.blocks:
        role = str(block.metadata.get("role") or "")
        text = block.text.strip()
        if not text or len(text) < _MIN_TEXT:
            continue
        if block.metadata.get("chrome") or block.metadata.get("superseded"):
            continue
        if _reconstruction_blocked(block):
            continue
        kind = {
            "procedure": SemanticUnitKind.PROCEDURE_STEP.value,
            "note": SemanticUnitKind.NOTE.value,
            "footnote": SemanticUnitKind.NOTE.value,
            "warning": SemanticUnitKind.WARNING.value,
            "example": SemanticUnitKind.EXAMPLE.value,
            "reference": SemanticUnitKind.REFERENCE.value,
        }.get(role)
        if kind is None:
            # El tipo de bloque también declara semántica: un bloque DEFINITION
            # es una definición aunque la heurística de roles no lo marque.
            kind = {
                StructuredBlockKind.DEFINITION.value: SemanticUnitKind.DEFINITION.value,
                StructuredBlockKind.NOTE.value: SemanticUnitKind.NOTE.value,
                StructuredBlockKind.WARNING.value: SemanticUnitKind.WARNING.value,
                StructuredBlockKind.EXAMPLE.value: SemanticUnitKind.EXAMPLE.value,
                StructuredBlockKind.FOOTNOTE.value: SemanticUnitKind.NOTE.value,
                StructuredBlockKind.PROCEDURE.value: SemanticUnitKind.PROCEDURE_STEP.value,
                StructuredBlockKind.REFERENCE.value: SemanticUnitKind.REFERENCE.value,
            }.get(block.kind.value)
        if kind is None and block.kind is StructuredBlockKind.FIELD_DEFINITION:
            kind = SemanticUnitKind.FIELD.value
        if kind is None and block.kind in {
            StructuredBlockKind.HEADING,
            StructuredBlockKind.TITLE,
        }:
            # "ATPCO Record 4 (R4)" declara el alias en el propio encabezado.
            declared = _NAME_WITH_ALIAS.match(text.splitlines()[0].strip())
            if declared is not None:
                name = declared.group("name").strip(" .,:;|-–—")
                alias = declared.group("alias").strip()
                if len(name) >= _MIN_TEXT and len(alias) >= _MIN_TEXT:
                    add(
                        SemanticUnit(
                            kind=SemanticUnitKind.DEFINITION.value,
                            key=f"definition:{normalize_term(name)}",
                            label=name,
                            text=text,
                            confidence=0.8,
                            attributes={"declared_alias": alias},
                            evidence=_evidence(
                                index,
                                excerpt=text,
                                block_id=block.id,
                                page=block.page,
                                confidence=0.8,
                            ),
                        )
                    )
            continue
        if kind is None:
            # Bloques de texto plano: el compilador aplica su propia extracción
            # tolerante ("Término: definición", "Byte 105 | 3 | ..."), sin
            # depender de que la heurística de roles los haya clasificado.
            fallback = _unit_from_plain_block(
                block, index, references=references, quality=quality
            )
            if fallback is not None:
                add(fallback)
            continue
        label = text.splitlines()[0][:160]
        attributes: dict = {"role": role or block.kind.value}
        confidence = float(block.metadata.get("confidence") or 0.7)
        if kind == SemanticUnitKind.DEFINITION.value:
            parsed = _parse_definition_line(text)
            if parsed is None:
                continue
            label, text = parsed
            confidence = max(confidence, 0.8)
        elif kind == SemanticUnitKind.FIELD.value:
            parsed = _parse_field_line(text)
            if parsed is None:
                continue
            label = parsed["name"]
            text = parsed["description"]
            attributes.update(parsed["attributes"])
            confidence = max(confidence, 0.8)
        if kind in {
            SemanticUnitKind.DEFINITION.value,
            SemanticUnitKind.FIELD.value,
            SemanticUnitKind.PROCEDURE_STEP.value,
            SemanticUnitKind.SECTION.value,
            SemanticUnitKind.REFERENCE.value,
        }:
            if kind in {
                SemanticUnitKind.DEFINITION.value,
                SemanticUnitKind.FIELD.value,
            } and _is_title_banner(label, document):
                _reject_label(
                    quality,
                    document,
                    subject=label,
                    quality_status=TextQualityStatus.LOW_QUALITY_EXTRACTION.value,
                    detail={"stage": f"block:{kind}", "reason": "title_banner"},
                )
                continue
            label_quality = _label_quality(label, references)
            if not label_quality.ok:
                _reject_label(
                    quality,
                    document,
                    subject=label,
                    quality_status=label_quality.status,
                    evidence=_evidence(
                        index,
                        excerpt=text,
                        block_id=block.id,
                        page=block.page,
                    ),
                    detail={"stage": f"block:{kind}"},
                )
                continue
        add(
            SemanticUnit(
                kind=kind,
                key=f"{kind}:{normalize_term(label)}",
                label=label,
                text=text,
                confidence=confidence,
                attributes=attributes,
                evidence=_evidence(
                    index,
                    excerpt=text,
                    block_id=block.id,
                    page=block.page,
                    evidence_type=(
                        EvidenceType.DOCUMENT.value
                        if kind
                        in {
                            SemanticUnitKind.NOTE.value,
                            SemanticUnitKind.WARNING.value,
                            SemanticUnitKind.EXAMPLE.value,
                        }
                        else EvidenceType.STRUCTURAL.value
                    ),
                    confidence=confidence,
                ),
            )
        )

    for item in extracted["cross_references"]:
        target = str(item.get("target") or item.get("to") or "").strip()
        source_text = str(item.get("text") or item.get("statement") or target).strip()
        if len(target) < _MIN_TEXT:
            continue
        add(
            SemanticUnit(
                kind=SemanticUnitKind.REFERENCE.value,
                key=f"reference:{normalize_term(target)}:{normalize_term(source_text[:80])}",
                label=target,
                text=source_text,
                confidence=float(item.get("confidence") or 0.7),
                attributes={"target": target},
                evidence=_evidence(
                    index,
                    excerpt=source_text or target,
                    block_id=item.get("block_id"),
                    page=item.get("page"),
                    evidence_type=EvidenceType.STRUCTURAL.value,
                ),
            )
        )

    rejected = _rejected_terms(document)
    if rejected:
        units = [unit for unit in units if normalize_term(unit.label) not in rejected]
    return units


def _unit_from_plain_block(
    block,
    index: _LocatorIndex,
    *,
    references: tuple[str, ...] = (),
    quality: QualityCollector | None = None,
) -> SemanticUnit | None:
    """Unidad desde un bloque de texto sin rol: alias, definición o campo."""
    text = (block.text or "").strip()
    if len(text) < _MIN_TEXT:
        return None
    kind = StructuredBlockKind.PARAGRAPH.value
    if block.kind.value not in {kind, "code", "list_item", "quote"}:
        return None
    declared = _NAME_WITH_ALIAS.match(text.splitlines()[0].strip())
    if declared is not None:
        name = declared.group("name").strip(" .,:;|-–—")
        alias = declared.group("alias").strip()
        if len(name) >= _MIN_TEXT and len(alias) >= _MIN_TEXT:
            declared_quality = _label_quality(name, references)
            if not declared_quality.ok:
                _reject_label(
                    quality,
                    _document_for(index),
                    subject=name,
                    quality_status=declared_quality.status,
                    detail={"stage": "plain_block:declared_alias"},
                )
                return None
            return SemanticUnit(
                kind=SemanticUnitKind.DEFINITION.value,
                key=f"definition:{normalize_term(name)}",
                label=name,
                text=text,
                confidence=0.8,
                attributes={"declared_alias": alias},
                evidence=_evidence(
                    index,
                    excerpt=text,
                    block_id=block.id,
                    page=block.page,
                    confidence=0.8,
                ),
            )
    definition = _parse_definition_line(text)
    if definition is not None:
        term, body = definition
        if _is_title_banner(term, _document_for(index)):
            _reject_label(
                quality,
                _document_for(index),
                subject=term,
                quality_status=TextQualityStatus.LOW_QUALITY_EXTRACTION.value,
                detail={"stage": "plain_block:definition", "reason": "title_banner"},
            )
            return None
        term_quality = _label_quality(term, references)
        if not term_quality.ok:
            _reject_label(
                quality,
                _document_for(index),
                subject=term,
                quality_status=term_quality.status,
                detail={"stage": "plain_block:definition"},
            )
            return None
        return SemanticUnit(
            kind=SemanticUnitKind.DEFINITION.value,
            key=f"definition:{normalize_term(term)}",
            label=term,
            text=body,
            confidence=0.78,
            attributes={"role": "paragraph"},
            evidence=_evidence(
                index,
                excerpt=f"{term}: {body}",
                block_id=block.id,
                page=block.page,
                confidence=0.78,
            ),
        )
    first_line = text.splitlines()[0]
    if first_line.count("|") >= 2:
        field = _parse_field_line(text)
        if field is not None:
            if _is_title_banner(field["name"], _document_for(index)):
                _reject_label(
                    quality,
                    _document_for(index),
                    subject=field["name"],
                    quality_status=TextQualityStatus.LOW_QUALITY_EXTRACTION.value,
                    detail={"stage": "plain_block:field", "reason": "title_banner"},
                )
                return None
            field_quality = _label_quality(field["name"], references)
            if not field_quality.ok:
                _reject_label(
                    quality,
                    _document_for(index),
                    subject=field["name"],
                    quality_status=field_quality.status,
                    detail={"stage": "plain_block:field"},
                )
                return None
            attributes = {"role": "paragraph", **field["attributes"]}
            return SemanticUnit(
                kind=SemanticUnitKind.FIELD.value,
                key=f"field:{normalize_term(field['name'])}",
                label=field["name"],
                text=field.get("description") or "",
                confidence=0.75,
                attributes=attributes,
                evidence=_evidence(
                    index,
                    excerpt=first_line,
                    block_id=block.id,
                    page=block.page,
                    confidence=0.75,
                ),
            )
    return None


def _document_for(index: _LocatorIndex) -> StructuredDocument:
    return index.document


def extract_tabular_units(
    workbook: object, *, document: StructuredDocument | None = None
) -> list[SemanticUnit]:
    """Excel/CSV como DATOS: tablas, columnas y tipos, no como texto.

    Cada unidad conserva la referencia exacta (hoja, rango, columna) para que
    la provenance sobreviva hasta la celda.
    """
    if workbook is None:
        return []
    document_id = getattr(document, "id", None)
    source_id = getattr(document, "source_id", None)
    content_hash = getattr(document, "content_hash", None)
    units: list[SemanticUnit] = []

    def locator(**kwargs) -> SourceLocator:
        return SourceLocator(
            source_id=source_id,
            document_id=document_id,
            document_title=getattr(document, "title", "") or "",
            content_hash=content_hash,
            **kwargs,
        )

    for sheet in getattr(workbook, "sheets", ()) or ():
        sheet_name = str(getattr(sheet, "name", "") or "hoja")
        for table in getattr(sheet, "tables", ()) or ():
            table_name = str(getattr(table, "name", "") or "tabla")
            reference = f"{sheet_name}!{table_name}"
            cell_range = getattr(table, "range", None)
            range_label = getattr(cell_range, "label", None) or getattr(
                cell_range, "a1", None
            )
            units.append(
                SemanticUnit(
                    kind=SemanticUnitKind.TABLE.value,
                    key=f"worksheet:{normalize_term(reference)}",
                    label=reference,
                    text=f"Rango {range_label}" if range_label else "",
                    confidence=float(
                        getattr(table, "detection_confidence", 0.8) or 0.8
                    ),
                    attributes={
                        "sheet": sheet_name,
                        "range": str(range_label) if range_label else None,
                        "row_count": len(getattr(table, "rows", ()) or ()),
                        "column_count": len(getattr(table, "columns", ()) or ()),
                        "header_depth": getattr(table, "header_depth", 1),
                        "detection_method": str(
                            getattr(
                                getattr(table, "detection_method", None), "value", ""
                            )
                            or ""
                        ),
                    },
                    evidence=EvidenceRef(
                        locator=locator(table_reference=reference),
                        evidence_type=EvidenceType.STRUCTURAL.value,
                        excerpt=f"Tabla {reference}",
                        confidence=0.9,
                    ),
                )
            )
            for column in getattr(table, "columns", ()) or ():
                column_name = str(
                    getattr(column, "original_name", "")
                    or getattr(column, "normalized_name", "")
                ).strip()
                if not column_name:
                    continue
                header_path = tuple(getattr(column, "header_path", ()) or ())
                units.append(
                    SemanticUnit(
                        kind=SemanticUnitKind.COLUMN.value,
                        key=(
                            f"worksheet-column:{normalize_term(reference)}:"
                            f"{normalize_term(column_name)}"
                        ),
                        label=column_name,
                        text=str(getattr(column, "description", "") or ""),
                        confidence=float(
                            getattr(column, "semantic_confidence", 0.0) or 0.8
                        ),
                        attributes={
                            "sheet": sheet_name,
                            "table": reference,
                            "excel_letter": getattr(column, "excel_letter", None),
                            "position": getattr(column, "physical_column", None),
                            "inferred_type": str(
                                getattr(
                                    getattr(column, "inferred_type", None), "value", ""
                                )
                                or "unknown"
                            ),
                            "semantic_type": str(
                                getattr(
                                    getattr(column, "semantic_type", None), "value", ""
                                )
                                or "unknown"
                            ),
                            "aliases": list(getattr(column, "aliases", ()) or ()),
                            "header_path": list(header_path),
                            "sample_values": list(
                                getattr(column, "sample_values", ()) or ()
                            )[:5],
                            "nullable": bool(getattr(column, "nullable", True)),
                        },
                        evidence=EvidenceRef(
                            locator=locator(
                                table_reference=reference,
                                cell_reference=(
                                    f"{getattr(column, 'excel_letter', '?')}1"
                                ),
                            ),
                            evidence_type=EvidenceType.SCHEMA.value,
                            excerpt=f"{column_name} en {reference}",
                            confidence=0.9,
                        ),
                    )
                )
    if document is not None:
        rejected = _rejected_terms(document)
        if rejected:
            units = [
                unit for unit in units if normalize_term(unit.label) not in rejected
            ]
    return units
