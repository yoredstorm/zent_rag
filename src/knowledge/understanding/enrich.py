# =============================================================================
# Document Understanding — enriquecimiento determinista
# =============================================================================
# Definiciones, campos técnicos, literales, notas y referencias salen de la
# forma del texto. Ninguna regla nombra un dominio (ni ATPCO ni otro).
# Una máscara se guarda tal cual. No se le inventa significado.
# =============================================================================
from __future__ import annotations

import dataclasses
import re
from uuid import UUID, uuid5

from src.core.domain.knowledge_v2 import (
    DocumentTable,
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.structure.base import content_hash, token_count
from src.knowledge.understanding.versions import DERIVED_NS

_NS = UUID(DERIVED_NS)

_SPACED_LINE = re.compile(r"^(?:[A-Za-z]\s+){3,}[A-Za-z]$")
_DEF_LINE = re.compile(r"^(.{1,48}?)\s+(?:[—–]|-{1,2}|:)\s+(\S.{0,400})$")
_FIELD_NAME = re.compile(r"^(?:field|campo|name|nombre)\s*:\s*(.+)$", re.IGNORECASE)
_BYTES = re.compile(
    r"^(?:bytes?|posici[oó]n|position)\s*:?\s*(\d{1,4})\s*[-–]\s*(\d{1,4})\b",
    re.IGNORECASE,
)
_LENGTH = re.compile(r"^(?:length|longitud|len)\s*:\s*(\d{1,4})\b", re.IGNORECASE)
_FORMAT = re.compile(r"^(?:format|formato|type|tipo)\s*:\s*(.+)$", re.IGNORECASE)
_DESC = re.compile(r"^(?:description|descripci[oó]n)\s*:\s*(.+)$", re.IGNORECASE)
_LAYOUT_ROW = re.compile(r"^(\d{1,4})\s*[-–]\s*(\d{1,4})\s+(\S+)\s+(.+)$")
_NOTE = re.compile(r"^(?:note|nota|footnote|n\.b\.)\b", re.IGNORECASE)
_WARNING = re.compile(r"^(?:warning|advertencia|caution|importante|important)\b", re.IGNORECASE)
_EXAMPLE = re.compile(r"^(?:example|ejemplo|e\.g\.)\b", re.IGNORECASE)
_CAPTION = re.compile(r"^(?:figure|fig\.|figura|diagrama|table|tabla)\s+\d+", re.IGNORECASE)
_XREF = re.compile(
    r"\b(?:see|refer to|v[eé]ase|ver)\s+"
    r"(table|note|section|appendix|category|record|figura|tabla|nota|secci[oó]n|anexo)"
    r"\s+([A-Za-z0-9.]+)",
    re.IGNORECASE,
)
_STEP = re.compile(r"(?m)^\s*(?:\d{1,2}[.)]|paso\s+\d+)\s+\S", re.IGNORECASE)
_BULLET = re.compile(r"(?m)^\s*(?:[-•]|\*(?=\s))\s+\S")
_MASK_TOKEN = re.compile(r"\S*[&%#?*\[\]]\S*")
_HEX = re.compile(r"\b0x[0-9A-Fa-f]{2,}\b")
_BYTE_REF = re.compile(r"\bBytes?\s+\d{1,4}(?:\s*[-–]\s*\d{1,4})?\b", re.IGNORECASE)
_IDENT = re.compile(r"\b[A-Z][A-Z0-9]{3,}\b")
_SKU = re.compile(r"\b[A-Z]{1,8}-\d{2,}[A-Z0-9-]*\b")
_MIXED_CODE = re.compile(r"\b(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*\d)[A-Z0-9]{6,}\b")

_IDENT_STOP = frozenset(
    {
        "NOTE",
        "TABLE",
        "PAGE",
        "THIS",
        "THAT",
        "WITH",
        "FROM",
        "BYTE",
        "BYTES",
        "FIELD",
        "TRUE",
        "FALSE",
        "NULL",
        "NONE",
        "TEXT",
        "CODE",
        "NAME",
        "TYPE",
        "WHEN",
        "THEN",
        "ELSE",
        "ALSO",
        "ONLY",
        "EACH",
        "SUCH",
        "MUST",
        "SHALL",
    }
)


def preserve_symbols(text: str) -> str:
    """Identidad. Los códigos no se normalizan aquí."""
    return text or ""


def collapse_spaced_letters(document: StructuredDocument) -> StructuredDocument:
    """Une «F C L A S» solo cuando TODA la línea son letras sueltas.

    Guarda el texto crudo. No toca máscaras ni códigos con símbolos.
    """
    blocks: list[StructuredBlock] = []
    changed = False
    for block in document.blocks:
        if block.metadata.get("chrome"):
            blocks.append(block)
            continue
        raw_lines = block.text.splitlines() or [block.text]
        new_lines: list[str] = []
        touched = False
        for line in raw_lines:
            stripped = line.strip()
            if _SPACED_LINE.fullmatch(stripped):
                new_lines.append(stripped.replace(" ", ""))
                touched = True
            else:
                new_lines.append(line)
        if not touched:
            blocks.append(block)
            continue
        text = "\n".join(new_lines)
        meta = dict(block.metadata)
        meta["raw_extraction"] = block.text
        meta["normalized"] = True
        meta["normalization_confidence"] = 0.8
        meta["derived_by"] = "rules"
        meta["provenance_type"] = "STRUCTURED"
        blocks.append(
            dataclasses.replace(
                block,
                text=text,
                token_count=token_count(text),
                content_hash=content_hash(text),
                metadata=meta,
            )
        )
        changed = True
    if not changed:
        return document
    return dataclasses.replace(document, blocks=tuple(blocks))


def merge_multipage_tables(
    document: StructuredDocument,
    *,
    min_confidence: float = 0.65,
) -> StructuredDocument:
    """Une tablas solo si merge_confidence alcanza el umbral.

    Misma cabecera y página siguiente no bastan. Sección o caption distintos
    dejan continuation_candidate y no fusionan.
    """
    if len(document.tables) < 2:
        return document
    ordered = sorted(
        document.tables,
        key=lambda table: (table.page or 0, int(table.metadata.get("table_index") or 0)),
    )
    used: set[UUID] = set()
    survivors: list[DocumentTable] = []
    merged_into: dict[UUID, UUID] = {}
    low_conf: dict[UUID, float] = {}
    merge_scores: dict[UUID, float] = {}
    for table in ordered:
        if table.id in used:
            continue
        rows = list(table.rows)
        pages = [table.page] if table.page else []
        absorbed: list[UUID] = []
        for other in ordered:
            if other.id == table.id or other.id in used:
                continue
            if not _same_headers(table, other):
                continue
            if not pages or other.page is None or other.page != pages[-1] + 1:
                continue
            confidence = _table_merge_confidence(table, other)
            if confidence < min_confidence:
                low_conf[other.id] = confidence
                continue
            merge_scores[table.id] = max(merge_scores.get(table.id, 0.0), confidence)
            extra = [
                row
                for row in other.rows
                if not _is_header_repeat(row, table.headers)
            ]
            rows.extend(extra)
            pages.append(other.page)
            used.add(other.id)
            absorbed.append(other.id)
            merged_into[other.id] = table.id
        used.add(table.id)
        meta = dict(table.metadata)
        meta["page_start"] = pages[0] if pages else table.page
        meta["page_end"] = pages[-1] if pages else table.page
        meta["merged_pages"] = pages
        if absorbed:
            meta["merge_confidence"] = merge_scores.get(table.id, 0.0)
            meta["merge_decision"] = "merged"
            meta["provenance_type"] = "STRUCTURED"
        elif table.id in low_conf:
            meta["merge_confidence"] = low_conf[table.id]
            meta["merge_decision"] = "related_table"
            meta["continuation_candidate"] = True
            meta["provenance_type"] = meta.get("provenance_type", "EXTRACTED")
        else:
            meta["provenance_type"] = meta.get("provenance_type", "EXTRACTED")
        survivors.append(dataclasses.replace(table, rows=tuple(rows), metadata=meta))

    if not merged_into and not low_conf:
        return document
    if not merged_into:
        return dataclasses.replace(document, tables=tuple(survivors))

    rendered = {table.id: _render_rows(table) for table in survivors}
    blocks: list[StructuredBlock] = []
    for block in document.blocks:
        table_id = _as_uuid(block.metadata.get("table_id"))
        if table_id is not None and table_id in merged_into:
            meta = dict(block.metadata)
            meta["superseded"] = True
            meta["merged_into"] = str(merged_into[table_id])
            meta["index_semantic"] = False
            meta["provenance_type"] = "STRUCTURED"
            blocks.append(dataclasses.replace(block, metadata=meta))
            continue
        if table_id is not None and table_id in rendered:
            text = rendered[table_id]
            meta = dict(block.metadata)
            meta["merged_pages"] = next(
                table.metadata.get("merged_pages")
                for table in survivors
                if table.id == table_id
            )
            meta["provenance_type"] = "STRUCTURED"
            blocks.append(
                dataclasses.replace(
                    block,
                    text=text or block.text,
                    token_count=token_count(text or block.text),
                    content_hash=content_hash(text or block.text),
                    metadata=meta,
                )
            )
            continue
        blocks.append(block)
    return dataclasses.replace(document, tables=tuple(survivors), blocks=tuple(blocks))


def _same_headers(left: DocumentTable, right: DocumentTable) -> bool:
    a = tuple(cell.strip().lower() for cell in left.headers if cell.strip())
    b = tuple(cell.strip().lower() for cell in right.headers if cell.strip())
    return bool(a) and a == b


def _table_merge_confidence(left: DocumentTable, right: DocumentTable) -> float:
    """Señales estructurales. No fusiona por cabecera repetida sola."""
    if not _same_headers(left, right):
        return 0.0
    score = 0.35
    if left.page and right.page and right.page == (left.page + 1):
        score += 0.2
    if left.headers and len(left.headers) == len(right.headers):
        score += 0.15
    left_section = str(left.metadata.get("section_id") or left.metadata.get("parent_section_id") or "")
    right_section = str(right.metadata.get("section_id") or right.metadata.get("parent_section_id") or "")
    if left_section and right_section and left_section == right_section:
        score += 0.15
    elif left_section and right_section and left_section != right_section:
        score -= 0.4
    left_caption = _caption_key(left)
    right_caption = _caption_key(right)
    if left_caption and right_caption and left_caption == right_caption:
        score += 0.1
    elif left_caption and right_caption and left_caption != right_caption:
        score -= 0.45
    if left.bbox is not None and right.bbox is not None:
        overlap = min(left.bbox.x1, right.bbox.x1) - max(left.bbox.x0, right.bbox.x0)
        width = max(left.bbox.x1 - left.bbox.x0, 1.0)
        if overlap / width >= 0.6:
            score += 0.1
    return max(0.0, min(1.0, round(score, 2)))


def _caption_key(table: DocumentTable) -> str:
    raw = table.caption or str(table.metadata.get("caption") or "")
    return re.sub(r"\s+", " ", raw).strip().lower()


def _is_header_repeat(row: tuple[str, ...], headers: tuple[str, ...]) -> bool:
    if not headers:
        return False
    return [cell.strip().lower() for cell in row] == [cell.strip().lower() for cell in headers]


def _render_rows(table: DocumentTable) -> str:
    parts: list[str] = []
    if table.headers:
        parts.append(" | ".join(table.headers))
    parts.extend(" | ".join(row) for row in table.rows)
    return "\n".join(part for part in parts if part.strip())


def _as_uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if not value:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _termish(term: str) -> bool:
    cleaned = term.strip()
    if not cleaned or len(cleaned) > 48:
        return False
    if re.match(r"^(field|byte|bytes|campo)\b", cleaned, re.IGNORECASE):
        return True
    if re.search(r"[&%#?*]|[A-Z0-9]{2,}", cleaned):
        return True
    if re.search(r"[a-z]{4,}", cleaned):
        return False
    return len(cleaned.split()) <= 4


def attach_section_owners(document: StructuredDocument) -> StructuredDocument:
    """Anota parent_section_id sin duplicar block_ids (el chunker los completa)."""
    if not document.sections or not document.blocks:
        return document
    section_by_heading: dict[UUID, object] = {}
    for section in document.sections:
        for heading_id in section.block_ids:
            section_by_heading[heading_id] = section
    stack: list = []
    owners: dict[UUID, UUID] = {}
    for block in sorted(document.blocks, key=lambda item: item.order):
        section = section_by_heading.get(block.id)
        if section is not None:
            while stack and stack[-1].depth >= section.depth:
                stack.pop()
            stack.append(section)
            owners[block.id] = section.id
            continue
        if stack:
            owners[block.id] = stack[-1].id
    if not owners:
        return document
    blocks: list[StructuredBlock] = []
    for block in document.blocks:
        owner = owners.get(block.id)
        if owner is None:
            blocks.append(block)
            continue
        meta = dict(block.metadata)
        meta["parent_section_id"] = str(owner)
        blocks.append(dataclasses.replace(block, metadata=meta))
    return dataclasses.replace(document, blocks=tuple(blocks))


def classify_blocks(document: StructuredDocument) -> tuple[StructuredDocument, dict]:
    """Clasifica bloques y arma definiciones, campos, literales y relaciones."""
    blocks = list(document.blocks)
    definitions: list[dict] = []
    fields: list[dict] = []
    literals: list[dict] = []
    references: list[dict] = []
    relations: list[dict] = []
    seen_literals: set[tuple[str, str]] = set()

    for index, block in enumerate(blocks):
        if block.metadata.get("chrome") or block.metadata.get("superseded"):
            continue
        if block.metadata.get("derived_by") == "model" and block.metadata.get("role"):
            pass
        else:
            role, kind, confidence = _role_for(block)
            if role:
                meta = dict(block.metadata)
                meta["role"] = role
                meta["confidence"] = confidence
                meta["derived_by"] = "rules"
                meta.setdefault("provenance_type", "EXTRACTED")
                blocks[index] = dataclasses.replace(block, kind=kind, metadata=meta)
                block = blocks[index]
        for item in _definitions_in(block):
            definitions.append(item)
        for item in _literals_in(block):
            key = (item["value"], item["block_id"])
            if key in seen_literals:
                continue
            seen_literals.add(key)
            literals.append(item)

    fields.extend(_fields_from_blocks(blocks))
    fields.extend(_assemble_section_fields(blocks, literals, definitions))
    fields = _dedupe_fields(fields)
    _link_patterns(fields, literals, relations)
    _link_notes(blocks, relations)
    _link_parts(blocks, document, relations)
    references.extend(_cross_references(blocks, document))
    _mark_procedure_groups(blocks)

    return (
        dataclasses.replace(document, blocks=tuple(blocks)),
        {
            "definitions": definitions,
            "technical_fields": fields,
            "exact_literals": literals,
            "cross_references": references,
            "relations": relations,
        },
    )


def derive_document_semantics(document: StructuredDocument) -> tuple[StructuredDocument, dict]:
    """Idempotente. Rearma derivados desde los bloques ya clasificados.

    Un rol con derived_by=model se conserva. Definiciones, campos, literales,
    relaciones y referencias se reconstruyen siempre. Sin OCR ni visión.
    """
    return classify_blocks(document)


def _role_for(block: StructuredBlock) -> tuple[str | None, StructuredBlockKind, float]:
    if block.kind in {
        StructuredBlockKind.HEADING,
        StructuredBlockKind.TITLE,
        StructuredBlockKind.TABLE,
        StructuredBlockKind.FIGURE,
        StructuredBlockKind.HEADER,
        StructuredBlockKind.FOOTER,
        StructuredBlockKind.PAGE_NUMBER,
    }:
        role = block.metadata.get("role") or block.kind.value
        return str(role), block.kind, 0.99
    text = block.text.strip()
    if not text:
        return None, block.kind, 0.0
    if _NOTE.match(text):
        return "note", StructuredBlockKind.NOTE, 0.9
    if _WARNING.match(text):
        return "warning", StructuredBlockKind.WARNING, 0.9
    if _EXAMPLE.match(text):
        return "example", StructuredBlockKind.EXAMPLE, 0.86
    if _CAPTION.match(text) and len(text) < 160:
        return "caption", StructuredBlockKind.CAPTION, 0.8
    if len(_STEP.findall(text)) >= 2:
        return "procedure", StructuredBlockKind.PROCEDURE, 0.84
    if len(_BULLET.findall(text)) >= 2:
        return "list", StructuredBlockKind.LIST, 0.8
    if _looks_like_field_block(text):
        return "field_definition", StructuredBlockKind.FIELD_DEFINITION, 0.86
    if _definition_line(text) is not None:
        return "definition", StructuredBlockKind.DEFINITION, 0.82
    if _XREF.search(text):
        return "reference", StructuredBlockKind.REFERENCE, 0.7
    return None, block.kind, 0.0


def _definition_line(text: str) -> tuple[str, str] | None:
    first = text.strip().splitlines()[0] if text.strip() else ""
    match = _DEF_LINE.match(first)
    if not match:
        return None
    term, body = match.group(1).strip(), match.group(2).strip()
    if not _termish(term) or len(body) < 2:
        return None
    return term, body


def _looks_like_field_block(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    named = any(_FIELD_NAME.match(line) for line in lines)
    ranged = any(_BYTES.match(line) or _LAYOUT_ROW.match(line) for line in lines)
    if named and ranged:
        return True
    hits = [line for line in lines if _LAYOUT_ROW.match(line)]
    return len(hits) >= 2


def _definitions_in(block: StructuredBlock) -> list[dict]:
    found: list[dict] = []
    for line in block.text.splitlines():
        parsed = _definition_line(line)
        if parsed is None:
            continue
        term, body = parsed
        found.append(
            {
                "term": term,
                "definition": body,
                "scope": None,
                "section_id": block.metadata.get("parent_section_id"),
                "page": block.page,
                "block_id": str(block.id),
                "confidence": 0.82,
                "derived_by": "rules",
                "provenance": "EXTRACTED",
            }
        )
    return found


def _literals_in(block: StructuredBlock) -> list[dict]:
    text = preserve_symbols(block.text)
    found: list[dict] = []
    seen: set[str] = set()

    def add(value: str, pattern_type: str) -> None:
        literal = value.strip()
        if len(literal) < 2 or literal in seen:
            return
        if any(ch.isspace() for ch in literal) and pattern_type != "byte_ref":
            return
        seen.add(literal)
        section_id = block.metadata.get("parent_section_id")
        bbox = None
        if block.bbox is not None:
            bbox = {
                "page": block.bbox.page,
                "x0": block.bbox.x0,
                "y0": block.bbox.y0,
                "x1": block.bbox.x1,
                "y1": block.bbox.y1,
            }
        found.append(
            {
                "value": literal,
                "pattern_type": pattern_type,
                "block_id": str(block.id),
                "page": block.page,
                "section_id": str(section_id) if section_id else None,
                "field_name": None,
                "bbox": bbox,
                "relation_target": None,
                "canonical_source": "text_layer",
                "parent_definition": None,
                "confidence": 0.95,
                "derived_by": "rules",
                "provenance": "EXTRACTED",
            }
        )

    for match in _HEX.finditer(text):
        add(match.group(0), "hex")
    for match in _BYTE_REF.finditer(text):
        add(match.group(0), "byte_ref")
    for match in _SKU.finditer(text):
        add(match.group(0), "code")
    for match in _MIXED_CODE.finditer(text):
        add(match.group(0), "code")
    for match in _MASK_TOKEN.finditer(text):
        token = match.group(0).strip(".,;:()\"'")
        symbols = sum(token.count(ch) for ch in "&%#?*[]")
        if symbols < 1 or len(token) < 2:
            continue
        if symbols < 2 and not any(ch.isalpha() for ch in token):
            continue
        add(token, "mask")
    for match in _IDENT.finditer(text):
        token = match.group(0)
        if token in _IDENT_STOP:
            continue
        add(token, "identifier")
    return found


def _fields_from_blocks(blocks: list[StructuredBlock]) -> list[dict]:
    fields: list[dict] = []
    for block in blocks:
        if block.metadata.get("chrome") or block.metadata.get("superseded"):
            continue
        parsed = _field_from_text(block.text)
        if parsed is not None:
            parsed.update(
                {
                    "block_id": str(block.id),
                    "page": block.page,
                    "section_id": block.metadata.get("parent_section_id"),
                    "confidence": 0.86,
                    "derived_by": "rules",
                    "provenance": "STRUCTURED",
                }
            )
            fields.append(parsed)
        for line in block.text.splitlines():
            row = _LAYOUT_ROW.match(line.strip())
            if row is None:
                continue
            name = row.group(3).strip()
            if any(item["name"] == name and item["block_id"] == str(block.id) for item in fields):
                continue
            start, end = int(row.group(1)), int(row.group(2))
            fields.append(
                {
                    "name": name,
                    "description": row.group(4).strip(),
                    "start_position": start,
                    "end_position": end,
                    "length": end - start + 1 if end >= start else None,
                    "type": None,
                    "format": None,
                    "allowed_values": [],
                    "examples": [],
                    "notes": [],
                    "literal_pattern": None,
                    "block_id": str(block.id),
                    "page": block.page,
                    "section_id": block.metadata.get("parent_section_id"),
                    "confidence": 0.8,
                    "derived_by": "rules",
                    "provenance": "STRUCTURED",
                }
            )
    return fields


def _field_from_text(text: str) -> dict | None:
    name = None
    start = end = length = None
    fmt = None
    description = None
    for line in text.splitlines():
        stripped = line.strip()
        found_name = _FIELD_NAME.match(stripped)
        found_bytes = _BYTES.match(stripped)
        found_len = _LENGTH.match(stripped)
        found_fmt = _FORMAT.match(stripped)
        found_desc = _DESC.match(stripped)
        if found_name:
            name = found_name.group(1).strip()
        elif found_bytes:
            start, end = int(found_bytes.group(1)), int(found_bytes.group(2))
        elif found_len:
            length = int(found_len.group(1))
        elif found_fmt:
            fmt = found_fmt.group(1).strip()
        elif found_desc:
            description = found_desc.group(1).strip()
    if name is None and start is None:
        return None
    if name is None:
        return None
    if length is None and start is not None and end is not None and end >= start:
        length = end - start + 1
    return {
        "name": name,
        "description": description,
        "start_position": start,
        "end_position": end,
        "length": length,
        "type": None,
        "format": fmt,
        "allowed_values": [],
        "examples": [],
        "notes": [],
        "literal_pattern": None,
    }


def _dedupe_fields(fields: list[dict]) -> list[dict]:
    order: list[tuple[str, str]] = []
    by_key: dict[tuple[str, str], dict] = {}
    for field in fields:
        key = (str(field.get("name") or ""), str(field.get("page") or ""))
        if not key[0]:
            continue
        if key not in by_key:
            by_key[key] = field
            order.append(key)
            continue
        kept = by_key[key]
        for slot in (
            "literal_pattern",
            "description",
            "start_position",
            "end_position",
            "length",
            "format",
            "section_id",
        ):
            if not kept.get(slot) and field.get(slot):
                kept[slot] = field[slot]
    return [by_key[key] for key in order]


def _assemble_section_fields(
    blocks: list[StructuredBlock],
    literals: list[dict],
    definitions: list[dict],
) -> list[dict]:
    """Arma un campo técnico con piezas vecinas de la misma sección.

    El nombre, el rango y la máscara pueden vivir en bloques distintos.
    La máscara no se interpreta: solo se enlaza.
    """
    groups: dict[str, list[StructuredBlock]] = {}
    for block in blocks:
        section_id = str(block.metadata.get("parent_section_id") or "")
        if section_id:
            groups.setdefault(section_id, []).append(block)
    assembled: list[dict] = []
    for section_id, group in groups.items():
        ids = {str(block.id) for block in group}
        text = "\n".join(block.text for block in group)
        term = next((item for item in definitions if str(item.get("block_id")) in ids), None)
        name = term["term"] if term else None
        description = term["definition"] if term else None
        if name is None:
            heading = next(
                (
                    block.text.strip()
                    for block in group
                    if block.kind is StructuredBlockKind.HEADING and _termish(block.text.strip())
                ),
                None,
            )
            name = heading
        if not name:
            continue
        found_bytes = re.search(
            r"\bBytes?\s*:?\s*(\d{1,4})\s*[-–]\s*(\d{1,4})\b",
            text,
            flags=re.IGNORECASE,
        )
        masks = [
            item
            for item in literals
            if str(item.get("block_id")) in ids and item.get("pattern_type") == "mask"
        ]
        if found_bytes is None and not masks:
            continue
        start = int(found_bytes.group(1)) if found_bytes else None
        end = int(found_bytes.group(2)) if found_bytes else None
        length = end - start + 1 if start is not None and end is not None and end >= start else None
        anchor = next((block for block in group if found_bytes and found_bytes.group(0) in block.text), group[0])
        assembled.append(
            {
                "name": name,
                "description": description,
                "start_position": start,
                "end_position": end,
                "length": length,
                "type": None,
                "format": None,
                "allowed_values": [],
                "examples": [],
                "notes": [],
                "literal_pattern": masks[0]["value"] if masks else None,
                "block_id": str(anchor.id),
                "page": anchor.page,
                "section_id": section_id,
                "confidence": 0.84,
                "derived_by": "rules",
                "provenance": "STRUCTURED",
            }
        )
    return assembled


def _link_patterns(fields: list[dict], literals: list[dict], relations: list[dict]) -> None:
    by_block: dict[str, list[dict]] = {}
    for literal in literals:
        by_block.setdefault(str(literal["block_id"]), []).append(literal)
    for field in fields:
        block_id = str(field.get("block_id") or "")
        masks = [item for item in by_block.get(block_id, []) if item["pattern_type"] == "mask"]
        pattern = field.get("literal_pattern") or (masks[0]["value"] if masks else None)
        if not pattern:
            continue
        field["literal_pattern"] = pattern
        owner = next((item for item in literals if item["value"] == pattern), None)
        if owner is not None:
            owner["parent_definition"] = field["name"]
            owner["field_name"] = field["name"]
            owner["relation_target"] = field["name"]
            if not owner.get("section_id") and field.get("section_id"):
                owner["section_id"] = field["section_id"]
        relations.append(
            {
                "relation_type": "HAS_PATTERN",
                "from_block_id": block_id,
                "to_block_id": str(owner["block_id"]) if owner else block_id,
                "target_literal": pattern,
                "field_name": field["name"],
                "confidence": 0.9,
                "derived_by": "rules",
                "provenance": "INFERRED",
            }
        )


def _link_notes(blocks: list[StructuredBlock], relations: list[dict]) -> None:
    for index, block in enumerate(blocks):
        role = str(block.metadata.get("role") or "")
        if role not in {"note", "footnote", "example", "warning"}:
            continue
        owner = _previous_owner(blocks, index)
        if owner is None:
            continue
        relation = {
            "note": "HAS_NOTE",
            "footnote": "HAS_NOTE",
            "example": "HAS_EXAMPLE",
            "warning": "HAS_WARNING",
        }[role]
        relations.append(
            {
                "relation_type": relation,
                "from_block_id": str(owner.id),
                "to_block_id": str(block.id),
                "confidence": 0.88,
                "derived_by": "rules",
                "provenance": "INFERRED",
            }
        )


def _previous_owner(blocks: list[StructuredBlock], index: int) -> StructuredBlock | None:
    for cursor in range(index - 1, -1, -1):
        block = blocks[cursor]
        if block.metadata.get("chrome") or block.metadata.get("superseded"):
            continue
        role = str(block.metadata.get("role") or block.kind.value)
        if role in {"table", "field_definition", "definition", "heading"}:
            return block
        if cursor < index - 4:
            break
    return None


def _link_parts(
    blocks: list[StructuredBlock],
    document: StructuredDocument,
    relations: list[dict],
) -> None:
    section_by_block: dict[UUID, UUID] = {}
    for section in document.sections:
        for block_id in section.block_ids:
            section_by_block[block_id] = section.id
    for block in blocks:
        section_id = section_by_block.get(block.id)
        if section_id is None:
            continue
        role = str(block.metadata.get("role") or "")
        if role not in {"field_definition", "definition", "table", "note", "example"}:
            continue
        relations.append(
            {
                "relation_type": "PART_OF",
                "from_block_id": str(block.id),
                "to_block_id": str(section_id),
                "confidence": 0.93,
                "derived_by": "rules",
                "provenance": "STRUCTURED",
            }
        )


def _cross_references(blocks: list[StructuredBlock], document: StructuredDocument) -> list[dict]:
    refs: list[dict] = []
    for block in blocks:
        if block.metadata.get("chrome"):
            continue
        for match in _XREF.finditer(block.text):
            kind = match.group(1)
            target = match.group(2)
            resolved, confidence = _resolve_target(target, document)
            refs.append(
                {
                    "from_block": str(block.id),
                    "reference_text": match.group(0),
                    "target_kind": kind,
                    "target_candidate": target,
                    "resolved_target": resolved,
                    "confidence": confidence,
                    "derived_by": "rules",
                    "provenance": "INFERRED" if resolved else "EXTRACTED",
                }
            )
    return refs


def _resolve_target(target: str, document: StructuredDocument) -> tuple[str | None, float]:
    needle = target.strip().lower()
    if not needle:
        return None, 0.0
    hits: list[str] = []
    for section in document.sections:
        heading = section.heading.strip().lower()
        path = ".".join(section.section_path).lower()
        if needle == heading or needle == path or needle in heading.split():
            hits.append(str(section.id))
    if len(hits) == 1:
        return hits[0], 0.86
    return None, 0.4


def _mark_procedure_groups(blocks: list[StructuredBlock]) -> None:
    group_start: int | None = None
    for index, block in enumerate(blocks):
        text = block.text.strip()
        step = bool(re.match(r"^\d{1,2}[.)]\s+\S", text))
        if step and not block.metadata.get("chrome"):
            if group_start is None:
                group_start = index
            continue
        group_start = _close_procedure(blocks, group_start, index)
    _close_procedure(blocks, group_start, len(blocks))


def _close_procedure(
    blocks: list[StructuredBlock],
    start: int | None,
    end: int,
) -> None:
    if start is None or end - start < 2:
        return None
    group_id = str(uuid5(_NS, "|".join(str(blocks[i].id) for i in range(start, end))))
    for index in range(start, end):
        block = blocks[index]
        meta = dict(block.metadata)
        meta["role"] = "list_item"
        meta["procedure_id"] = group_id
        meta["derived_by"] = "rules"
        meta["confidence"] = 0.84
        meta["provenance_type"] = "STRUCTURED"
        blocks[index] = dataclasses.replace(
            block,
            kind=StructuredBlockKind.LIST_ITEM,
            metadata=meta,
        )
    return None


def link_neighbors(document: StructuredDocument) -> StructuredDocument:
    """prev/next de bloques y de secciones. Sirve para expandir contexto."""
    blocks = list(document.blocks)
    ordered = sorted(range(len(blocks)), key=lambda index: blocks[index].order)
    for position, index in enumerate(ordered):
        meta = dict(blocks[index].metadata)
        meta["prev_block_id"] = str(blocks[ordered[position - 1]].id) if position else None
        meta["next_block_id"] = (
            str(blocks[ordered[position + 1]].id) if position + 1 < len(ordered) else None
        )
        blocks[index] = dataclasses.replace(blocks[index], metadata=meta)

    sections = list(document.sections)
    order = sorted(range(len(sections)), key=lambda index: (sections[index].order, sections[index].page_start or 0))
    for position, index in enumerate(order):
        meta = dict(sections[index].metadata)
        meta["prev_section_id"] = str(sections[order[position - 1]].id) if position else None
        meta["next_section_id"] = (
            str(sections[order[position + 1]].id) if position + 1 < len(order) else None
        )
        sections[index] = dataclasses.replace(sections[index], metadata=meta)
    return dataclasses.replace(document, blocks=tuple(blocks), sections=tuple(sections))
