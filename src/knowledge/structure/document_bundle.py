# =============================================================================
# ParsedDocumentBundle — representación dual de UNA conversión ODL
# =============================================================================
# OpenDataLoader es la Document Intelligence Layer: UNA ejecución produce
#
#   JSON      -> representación estructural CANÓNICA (StructuredDocument,
#                Semantic Units, anchors, bbox, CanonicalRule compiler,
#                Premise Closure, decisiones deterministas, citas, auditoría)
#   Markdown  -> representación LLM-ready (proyección legible para contexto,
#                resúmenes, RAG narrativo, previews y explicación del agente)
#
# El Markdown NUNCA es autoridad independiente: es una proyección del mismo
# contenido. El crosswalk JSON ↔ Markdown permite que el citation engine vuelva
# del texto legible al elemento canónico (id, página, bbox).
#
# Identidad de evidencia: JSON y Markdown comparten `canonical_evidence_id`.
# No son 2 fuentes ni 2 evidencias: son 2 representations del mismo evidence.
# =============================================================================
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

BUNDLE_SCHEMA_VERSION = "parsed-document-bundle-1"
MARKDOWN_CHUNKING_VERSION = "markdown-sections-1"

#: Kinds de representación (vocabulario estable para telemetría/UI).
REPRESENTATION_JSON = "structured_json"
REPRESENTATION_MARKDOWN = "llm_markdown"
REPRESENTATION_HTML = "html_projection"

#: Storage de un artefacto.
STORAGE_BUNDLE = "bundle"
STORAGE_ARTIFACT = "artifact"
STORAGE_INLINE = "inline"

_PAGE_MARK_RE = re.compile(r"<!--\s*page\s*[:=]?\s*(\d+)\s*-->", re.IGNORECASE)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
_INLINE_MARKUP_RE = re.compile(r"[*_`]+")
_WS_RE = re.compile(r"\s+")


def canonical_json_text(payload: Mapping[str, Any] | None) -> str:
    """Serialización estable (hash determinista) del JSON canónico."""
    if not payload:
        return "{}"
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8", "ignore")).hexdigest()


def canonical_evidence_id(document_id: Any, element_id: Any) -> str:
    """Id de evidencia COMPARTIDO por JSON y Markdown del mismo elemento.

    Dos representations del mismo bloque no son dos evidencias: comparten este
    id canónico (una sola entrada en conteos/confidence).
    """
    return f"ev:{document_id}:{element_id}"


def _normalize_heading(text: Any) -> str:
    plain = _INLINE_MARKUP_RE.sub("", str(text or ""))
    plain = _WS_RE.sub(" ", plain).strip().strip(":").lower()
    # "4.1 Fare Class" == "4.1 fare class": el número se conserva porque ancla
    # la jerarquía; solo se normaliza el espaciado alrededor del punto.
    plain = re.sub(r"\s*([.\-])\s*", r"\1", plain)
    return plain


# -----------------------------------------------------------------------------
# Artefactos y provenance
# -----------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class RepresentationArtifact:
    """Un artefacto de la conversión (JSON/Markdown/HTML) con su hash."""

    kind: str
    content: str = ""
    content_hash: str = ""
    bytes: int = 0
    ref: str = ""
    storage: str = STORAGE_BUNDLE
    metadata: Mapping[str, Any] = field(default_factory=dict)

    #: True para la representación estructural canónica.
    @property
    def canonical(self) -> bool:
        return self.kind == REPRESENTATION_JSON

    def to_public_dict(self) -> dict[str, Any]:
        """Vista para metadata/UI: SIN contenido (nunca markdown gigante)."""
        return {
            "kind": self.kind,
            "representation": self.kind,
            "canonical": bool(self.canonical),
            "content_hash": self.content_hash,
            "bytes": int(self.bytes),
            "ref": self.ref,
            "storage": self.storage,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, kw_only=True)
class BundleProvenance:
    """Quién produjo la conversión y con qué opciones (sin secretos)."""

    parser_engine: str = ""
    parser_version: str = ""
    parser_mode: str = ""
    structure_source: str = ""
    options_fingerprint: Mapping[str, Any] = field(default_factory=dict)
    formats: tuple[str, ...] = ()
    elapsed_seconds: float = 0.0
    java: str = ""
    fallback_warnings: tuple[str, ...] = ()

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "parser_engine": self.parser_engine,
            "parser_version": self.parser_version,
            "parser_mode": self.parser_mode,
            "structure_source": self.structure_source,
            "formats": list(self.formats),
            "elapsed_seconds": round(float(self.elapsed_seconds or 0.0), 3),
            "java": self.java,
            "options_fingerprint": dict(self.options_fingerprint),
            "fallback_warnings": list(self.fallback_warnings[:4]),
        }


# -----------------------------------------------------------------------------
# Crosswalk Markdown ↔ JSON
# -----------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class MarkdownSection:
    """Sección de Markdown mapeada a elementos canónicos del JSON."""

    index: int
    heading: str = ""
    level: int = 0
    text: str = ""
    char_start: int = 0
    char_end: int = 0
    page_start: int | None = None
    page_end: int | None = None
    section_path: tuple[str, ...] = ()
    canonical_section_id: str = ""
    canonical_element_ids: tuple[str, ...] = ()
    canonical_evidence_ids: tuple[str, ...] = ()
    bbox_anchors: tuple[tuple[float, float, float, float], ...] = ()
    mapped: bool = False

    def to_public_dict(self, *, include_text: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "index": self.index,
            "heading": self.heading[:200],
            "level": self.level,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "section_path": list(self.section_path[:6]),
            "canonical_section_id": self.canonical_section_id,
            "canonical_element_ids": list(self.canonical_element_ids[:24]),
            "canonical_evidence_ids": list(self.canonical_evidence_ids[:24]),
            "bbox_anchors": [list(box) for box in self.bbox_anchors[:4]],
            "mapped": bool(self.mapped),
            "char_start": self.char_start,
            "char_end": self.char_end,
        }
        if include_text:
            payload["text"] = self.text[:4000]
        return payload


@dataclass(frozen=True, kw_only=True)
class MarkdownSectionMap:
    """Crosswalk completo + métricas de cobertura."""

    sections: tuple[MarkdownSection, ...] = ()
    pages_seen: tuple[int, ...] = ()
    page_marks_found: int = 0
    headings_total: int = 0
    headings_mapped: int = 0
    coverage: float = 0.0
    element_coverage: float = 0.0
    document_id: str = ""
    schema_version: str = BUNDLE_SCHEMA_VERSION

    def section_for_offset(self, offset: int) -> MarkdownSection | None:
        for section in self.sections:
            if section.char_start <= offset < section.char_end:
                return section
        return None

    def evidence_ids(self) -> tuple[str, ...]:
        found: list[str] = []
        for section in self.sections:
            for evidence_id in section.canonical_evidence_ids:
                if evidence_id not in found:
                    found.append(evidence_id)
        return tuple(found)

    def to_public_dict(self, *, include_sections: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "document_id": self.document_id,
            "pages_seen": list(self.pages_seen[:64]),
            "page_marks_found": int(self.page_marks_found),
            "headings_total": int(self.headings_total),
            "headings_mapped": int(self.headings_mapped),
            "coverage": round(float(self.coverage), 4),
            "element_coverage": round(float(self.element_coverage), 4),
        }
        if include_sections:
            payload["sections"] = [
                section.to_public_dict() for section in self.sections[:64]
            ]
        return payload


def _substantive_text(text: str) -> str:
    """Texto sin comentarios HTML ni whitespace (marca si hay contenido real)."""
    without_comments = re.sub(r"<!--.*?-->", " ", str(text or ""), flags=re.DOTALL)
    return _WS_RE.sub(" ", without_comments).strip()


def _markdown_sections(markdown: str) -> list[dict[str, Any]]:
    """Corta el markdown por jerarquía de headings, conservando offsets.

    Nunca corta por tamaño fijo: la unidad es heading → subsección. Un
    preámbulo sin contenido real (solo `<!-- page:N -->`/blancos) se fusiona
    con la primera sección para no diluir la cobertura del crosswalk.

    Los marcadores de página anuncian el INICIO de página: el que precede a un
    heading pertenece a esa sección, no a la anterior (evita doble conteo).
    """
    text = str(markdown or "")
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_page = 0
    pending_page = 0
    pending_start: int | None = None
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        marker = _PAGE_MARK_RE.search(stripped)
        if marker is not None:
            current_page = int(marker.group(1))
            pending_page = current_page
            if current is None and pending_start is None:
                # El marcador que precede al primer heading pertenece al span
                # de la primera sección (cobertura del crosswalk).
                pending_start = offset
            offset += len(line)
            continue
        heading = _HEADING_RE.match(stripped)
        if heading is not None:
            heading_start = (
                pending_start if pending_start is not None else offset
            )
            if current is not None:
                if current["heading"] == "" and not _substantive_text(
                    "".join(current["text_parts"])
                ):
                    heading_start = int(current["char_start"])
                else:
                    current["char_end"] = offset
                    sections.append(current)
            start_page = pending_page or current_page
            current = {
                "heading": heading.group(2).strip(),
                "level": len(heading.group(1)),
                "char_start": heading_start,
                "char_end": len(text),
                "pages": set([start_page] if start_page else []),
                "text_parts": [line],
            }
            pending_page = 0
            pending_start = None
        elif current is not None:
            current["text_parts"].append(line)
            if current_page:
                current["pages"].add(current_page)
        else:
            # Preámbulo (contenido antes del primer heading).
            if stripped:
                start_page = pending_page or current_page
                current = {
                    "heading": "",
                    "level": 0,
                    "char_start": (
                        pending_start if pending_start is not None else (offset if offset else 0)
                    ),
                    "char_end": len(text),
                    "pages": set([start_page] if start_page else []),
                    "text_parts": [line],
                }
                pending_page = 0
                pending_start = None
        offset += len(line)
    if current is not None:
        current["char_end"] = len(text)
        sections.append(current)
    for section in sections:
        section["text"] = "".join(section.pop("text_parts"))
        section["pages"] = tuple(sorted(section["pages"]))
    return sections


def _block_bbox_anchor(block: Any) -> tuple[float, float, float, float] | None:
    bbox = getattr(block, "bbox", None)
    if bbox is None:
        return None
    try:
        return (
            float(bbox.x0),
            float(bbox.y0),
            float(bbox.x1),
            float(bbox.y1),
        )
    except (AttributeError, TypeError, ValueError):
        return None


def build_markdown_crosswalk(
    document: Any, markdown: str
) -> MarkdownSectionMap:
    """Mapea cada sección Markdown a elementos canónicos del StructuredDocument.

    Estrategia determinista:
      1. match por heading normalizado contra `document.sections`;
      2. fallback por heading contra bloques HEADING/TITLE;
      3. sin match → section no mapeada (coverage lo refleja).
    """
    document_id = str(getattr(document, "id", "") or "")
    md_sections = _markdown_sections(markdown)
    blocks = tuple(getattr(document, "blocks", ()) or ())
    doc_sections = tuple(getattr(document, "sections", ()) or ())
    blocks_by_id = {str(getattr(block, "id", "")): block for block in blocks}
    total_blocks = sum(
        1
        for block in blocks
        if str(getattr(block, "text", "") or "").strip()
    )

    sections_by_norm: dict[str, list[Any]] = {}
    for section in doc_sections:
        key = _normalize_heading(getattr(section, "heading", ""))
        if key:
            sections_by_norm.setdefault(key, []).append(section)
    heading_blocks_by_norm: dict[str, list[Any]] = {}
    for block in blocks:
        kind = str(getattr(getattr(block, "kind", None), "value", getattr(block, "kind", ""))).lower()
        if kind not in ("heading", "title"):
            continue
        key = _normalize_heading(getattr(block, "text", ""))
        if key:
            heading_blocks_by_norm.setdefault(key, []).append(block)

    mapped_sections: list[MarkdownSection] = []
    mapped_elements: set[str] = set()
    used_section_keys: set[str] = set()
    covered_chars = 0
    pages_seen: set[int] = set()
    page_marks = 0
    for index, raw in enumerate(md_sections):
        pages = tuple(int(page) for page in raw.get("pages") or ())
        pages_seen.update(pages)
        page_marks += len(pages)
        key = _normalize_heading(raw.get("heading"))
        canonical_section = None
        if key:
            candidates = sections_by_norm.get(key) or []
            for candidate in candidates:
                candidate_id = str(getattr(candidate, "id", "") or "")
                if candidate_id not in used_section_keys:
                    canonical_section = candidate
                    used_section_keys.add(candidate_id)
                    break
        element_ids: list[str] = []
        evidence_ids: list[str] = []
        section_path: tuple[str, ...] = ()
        page_start: int | None = pages[0] if pages else None
        page_end: int | None = pages[-1] if pages else None
        canonical_section_id = ""
        bbox_anchors: list[tuple[float, float, float, float]] = []
        if canonical_section is not None:
            canonical_section_id = str(getattr(canonical_section, "id", "") or "")
            section_path = tuple(
                str(part)
                for part in (getattr(canonical_section, "section_path", ()) or ())
            )
            element_ids = [
                str(block_id)
                for block_id in (getattr(canonical_section, "block_ids", ()) or ())
            ]
            if getattr(canonical_section, "page_start", None):
                page_start = int(canonical_section.page_start)
            if getattr(canonical_section, "page_end", None):
                page_end = int(canonical_section.page_end)
            for block_id in element_ids:
                block = blocks_by_id.get(block_id)
                anchor = _block_bbox_anchor(block) if block is not None else None
                if anchor is not None:
                    bbox_anchors.append(anchor)
        elif key:
            # Fallback: bloques HEADING con ese texto (documento sin sections).
            for block in heading_blocks_by_norm.get(key, []):
                block_id = str(getattr(block, "id", "") or "")
                if block_id in mapped_elements:
                    continue
                element_ids.append(block_id)
                page = getattr(block, "page", None)
                if isinstance(page, int):
                    page_start = page if page_start is None else min(page_start, page)
                    page_end = page if page_end is None else max(page_end, page)
                anchor = _block_bbox_anchor(block)
                if anchor is not None:
                    bbox_anchors.append(anchor)
                break
        for block_id in element_ids:
            mapped_elements.add(block_id)
            evidence_ids.append(canonical_evidence_id(document_id, block_id))
        mapped = bool(element_ids)
        if mapped:
            covered_chars += max(0, int(raw["char_end"]) - int(raw["char_start"]))
        mapped_sections.append(
            MarkdownSection(
                index=index,
                heading=str(raw.get("heading") or ""),
                level=int(raw.get("level") or 0),
                text=str(raw.get("text") or ""),
                char_start=int(raw.get("char_start") or 0),
                char_end=int(raw.get("char_end") or 0),
                page_start=page_start,
                page_end=page_end,
                section_path=section_path,
                canonical_section_id=canonical_section_id,
                canonical_element_ids=tuple(element_ids),
                canonical_evidence_ids=tuple(evidence_ids),
                bbox_anchors=tuple(bbox_anchors[:8]),
                mapped=mapped,
            )
        )
    total_chars = len(str(markdown or ""))
    headings_total = sum(1 for section in mapped_sections if section.heading)
    headings_mapped = sum(1 for section in mapped_sections if section.heading and section.mapped)
    return MarkdownSectionMap(
        sections=tuple(mapped_sections),
        pages_seen=tuple(sorted(pages_seen)),
        page_marks_found=page_marks,
        headings_total=headings_total,
        headings_mapped=headings_mapped,
        coverage=(covered_chars / total_chars) if total_chars else 0.0,
        element_coverage=(len(mapped_elements) / total_blocks) if total_blocks else 0.0,
        document_id=document_id,
    )


# -----------------------------------------------------------------------------
# Chunking por estructura (nunca tamaño fijo ciego)
# -----------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class MarkdownChunk:
    """Chunk de retrieval narrativo con anclas canónicas."""

    chunk_id: str
    document_id: str
    representation_kind: str = REPRESENTATION_MARKDOWN
    heading: str = ""
    section_path: tuple[str, ...] = ()
    text: str = ""
    page_start: int | None = None
    page_end: int | None = None
    canonical_element_ids: tuple[str, ...] = ()
    canonical_evidence_ids: tuple[str, ...] = ()
    char_start: int = 0
    char_end: int = 0
    token_estimate: int = 0
    part: int = 0
    schema_version: str = MARKDOWN_CHUNKING_VERSION

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "representation_kind": self.representation_kind,
            "heading": self.heading[:200],
            "section_path": list(self.section_path[:6]),
            "text": self.text[:1500],
            "page_start": self.page_start,
            "page_end": self.page_end,
            "canonical_element_ids": list(self.canonical_element_ids[:24]),
            "canonical_evidence_ids": list(self.canonical_evidence_ids[:24]),
            "token_estimate": int(self.token_estimate),
            "part": int(self.part),
        }


def _split_section_text(text: str, *, max_chars: int) -> list[str]:
    """Divide respetando párrafos/items; nunca parte una oración si puede."""
    body = _PAGE_MARK_RE.sub("", str(text or "")).strip()
    if not body:
        return []
    if len(body) <= max_chars:
        return [body]
    pieces: list[str] = []
    pending = ""
    for paragraph in re.split(r"\n{2,}", body):
        candidate = f"{pending}\n\n{paragraph}".strip() if pending else paragraph
        if len(candidate) <= max_chars:
            pending = candidate
            continue
        if pending:
            pieces.append(pending)
        if len(paragraph) <= max_chars:
            pending = paragraph
            continue
        # Párrafo gigante: cortar por oración (o item de lista) sin partirla.
        sentences = re.split(r"(?<=[.;:!?])\s+|\n(?=[-*•]|\d+[.)]\s)", paragraph)
        buffer = ""
        for sentence in sentences:
            candidate = f"{buffer} {sentence}".strip() if buffer else sentence
            if len(candidate) <= max_chars:
                buffer = candidate
            else:
                if buffer:
                    pieces.append(buffer)
                buffer = sentence
        pending = buffer
    if pending:
        pieces.append(pending)
    final: list[str] = []
    for piece in pieces:
        while len(piece) > max_chars:
            final.append(piece[:max_chars])
            piece = piece[max_chars:]
        if piece:
            final.append(piece)
    return final


def chunk_markdown(
    markdown: str,
    crosswalk: MarkdownSectionMap,
    *,
    document_id: str = "",
    max_chars: int = 1800,
) -> tuple[MarkdownChunk, ...]:
    """Chunks de la proyección Markdown por sección/subsección.

    Cada chunk conserva document_id, section_path, page range y los ids
    canónicos del JSON: el LLM lee Markdown, las citas vuelven al JSON.
    """
    chunks: list[MarkdownChunk] = []
    for section in crosswalk.sections:
        for part, piece in enumerate(_split_section_text(section.text, max_chars=max_chars)):
            if not piece:
                continue
            chunk_id = f"md:{document_id}:{section.index}:{part}"
            chunks.append(
                MarkdownChunk(
                    chunk_id=chunk_id,
                    document_id=document_id or crosswalk.document_id,
                    heading=section.heading,
                    section_path=section.section_path,
                    text=piece,
                    page_start=section.page_start,
                    page_end=section.page_end,
                    canonical_element_ids=section.canonical_element_ids,
                    canonical_evidence_ids=section.canonical_evidence_ids,
                    char_start=section.char_start,
                    char_end=section.char_end,
                    token_estimate=max(1, len(piece) // 4),
                    part=part,
                )
            )
    return tuple(chunks)


# -----------------------------------------------------------------------------
# Quality gates
# -----------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class BundleQuality:
    """Gates previos a promover la representación LLM-ready."""

    promoted: bool = False
    checks: tuple[dict[str, Any], ...] = ()
    reasons: tuple[str, ...] = ()
    coverage: float = 0.0
    page_mapping_valid: bool = False
    non_empty: bool = False
    heading_hierarchy_sane: bool = False
    table_representation_sane: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "promoted": bool(self.promoted),
            "checks": [dict(check) for check in self.checks],
            "reasons": list(self.reasons[:6]),
            "coverage": round(float(self.coverage), 4),
            "page_mapping_valid": bool(self.page_mapping_valid),
            "non_empty": bool(self.non_empty),
            "heading_hierarchy_sane": bool(self.heading_hierarchy_sane),
            "table_representation_sane": bool(self.table_representation_sane),
        }


def _markdown_table_count(markdown: str) -> int:
    count = 0
    for line in str(markdown or "").splitlines():
        if _TABLE_SEPARATOR_RE.match(line):
            count += 1
    return count


def evaluate_bundle_quality(
    document: Any,
    crosswalk: MarkdownSectionMap,
    markdown: str,
    *,
    min_coverage: float = 0.6,
    max_page: int = 0,
) -> BundleQuality:
    """Quality gates de la proyección Markdown (JSON sigue funcionando igual).

    Un Markdown que no pasa NO bloquea la ingesta: se marca no promovido y la
    autoridad estructural sigue siendo el JSON.
    """
    checks: list[dict[str, Any]] = []
    reasons: list[str] = []

    non_empty = bool(str(markdown or "").strip()) and (
        crosswalk.headings_mapped >= 1
        or any(section.mapped for section in crosswalk.sections)
    )
    checks.append({"name": "non_empty_projection", "ok": non_empty})
    if not non_empty:
        reasons.append("empty_or_unmapped_projection")

    coverage = float(crosswalk.coverage)
    coverage_ok = coverage >= float(min_coverage)
    checks.append(
        {
            "name": "crosswalk_coverage",
            "ok": coverage_ok,
            "coverage": round(coverage, 4),
            "threshold": float(min_coverage),
        }
    )
    if not coverage_ok:
        reasons.append(f"crosswalk_coverage_below_threshold:{coverage:.2f}")

    pages_found = [page for page in crosswalk.pages_seen if page > 0]
    document_pages = tuple(getattr(document, "pages", ()) or ())
    if max_page:
        page_limit = int(max_page)
    elif document_pages:
        page_limit = max(
            int(getattr(page, "page_number", 0) or 0) for page in document_pages
        )
    else:
        page_limit = 0
    if pages_found and page_limit:
        page_mapping_valid = all(page <= page_limit for page in pages_found)
    elif not pages_found:
        # Sin marcadores: la validez viene de las secciones canónicas mapeadas.
        mapped_pages = [
            section.page_start
            for section in crosswalk.sections
            if section.mapped and section.page_start
        ]
        page_mapping_valid = bool(mapped_pages) and (
            not page_limit or all(page <= page_limit for page in mapped_pages)
        )
    else:
        page_mapping_valid = True
    checks.append(
        {
            "name": "page_mapping",
            "ok": page_mapping_valid,
            "pages_seen": len(pages_found),
            "page_limit": page_limit,
        }
    )
    if not page_mapping_valid:
        reasons.append("page_mapping_invalid")

    heading_levels = [section.level for section in crosswalk.sections if section.heading]
    hierarchy_ok = all(1 <= level <= 6 for level in heading_levels) and not any(
        section.heading and not section.heading.strip()
        for section in crosswalk.sections
    )
    checks.append(
        {
            "name": "heading_hierarchy",
            "ok": hierarchy_ok,
            "headings": len(heading_levels),
        }
    )
    if not hierarchy_ok:
        reasons.append("heading_hierarchy_insane")

    doc_tables = len(getattr(document, "tables", ()) or ())
    md_tables = _markdown_table_count(markdown)
    tables_ok = doc_tables == 0 or md_tables > 0
    checks.append(
        {
            "name": "table_representation",
            "ok": tables_ok,
            "canonical_tables": doc_tables,
            "markdown_tables": md_tables,
        }
    )
    if not tables_ok:
        reasons.append("table_representation_missing")

    promoted = non_empty and coverage_ok and page_mapping_valid and hierarchy_ok and tables_ok
    return BundleQuality(
        promoted=promoted,
        checks=tuple(checks),
        reasons=tuple(reasons),
        coverage=coverage,
        page_mapping_valid=page_mapping_valid,
        non_empty=non_empty,
        heading_hierarchy_sane=hierarchy_ok,
        table_representation_sane=tables_ok,
    )


# -----------------------------------------------------------------------------
# Fingerprint de representación
# -----------------------------------------------------------------------------


def bundle_fingerprint(
    *,
    parser_engine: str,
    parser_version: str,
    options_fingerprint: Mapping[str, Any] | None,
    json_hash: str,
    markdown_hash: str = "",
    html_hash: str = "",
    schema_version: str = BUNDLE_SCHEMA_VERSION,
) -> str:
    """Huella de la representación dual: ODL version/options + hashes.

    Si cambia el engine/versión/opciones o alguno de los dos artefactos, la
    representación queda STALE y pide reingesta/reindex selectivo.
    """
    material = "|".join(
        [
            f"schema={schema_version}",
            f"engine={parser_engine}",
            f"version={parser_version}",
            f"options={json.dumps(dict(options_fingerprint or {}), sort_keys=True, default=str)}",
            f"json={json_hash}",
            f"markdown={markdown_hash}",
            f"html={html_hash}",
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def representation_stale(
    bundle_fingerprint_value: str,
    *,
    parser_engine: str,
    parser_version: str,
    options_fingerprint: Mapping[str, Any] | None,
    json_hash: str,
    markdown_hash: str = "",
    schema_version: str = BUNDLE_SCHEMA_VERSION,
) -> bool:
    """¿La representación persistida difiere del parser/opciones actuales?"""
    current = bundle_fingerprint(
        parser_engine=parser_engine,
        parser_version=parser_version,
        options_fingerprint=options_fingerprint,
        json_hash=json_hash,
        markdown_hash=markdown_hash,
        schema_version=schema_version,
    )
    return str(bundle_fingerprint_value or "") != current


# -----------------------------------------------------------------------------
# ParsedDocumentBundle
# -----------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class ParsedDocumentBundle:
    """UNA conversión ODL: StructuredDocument + artefactos + crosswalk."""

    structured_document: Any
    artifacts: Mapping[str, RepresentationArtifact] = field(default_factory=dict)
    provenance: BundleProvenance = field(default_factory=BundleProvenance)
    crosswalk: MarkdownSectionMap = field(default_factory=MarkdownSectionMap)
    quality: BundleQuality = field(default_factory=BundleQuality)
    json_hash: str = ""
    markdown_hash: str = ""
    fingerprint: str = ""
    schema_version: str = BUNDLE_SCHEMA_VERSION

    #: La representación canónica SIEMPRE es el JSON estructurado.
    @property
    def canonical(self) -> RepresentationArtifact | None:
        return self.artifacts.get(REPRESENTATION_JSON)

    @property
    def markdown(self) -> str:
        artifact = self.artifacts.get(REPRESENTATION_MARKDOWN)
        return artifact.content if artifact is not None else ""

    @property
    def llm_representation_promoted(self) -> bool:
        return bool(self.quality.promoted and self.markdown.strip())

    def markdown_chunks(self, *, max_chars: int = 1800) -> tuple[MarkdownChunk, ...]:
        if not self.markdown.strip():
            return ()
        return chunk_markdown(
            self.markdown,
            self.crosswalk,
            document_id=str(getattr(self.structured_document, "id", "") or ""),
            max_chars=max_chars,
        )

    def metadata_block(self) -> dict[str, Any]:
        """Bloque LIVIANO para `StructuredDocument.metadata["representations"]`.

        Nunca incluye el markdown ni el JSON completos: refs, hashes y métricas.
        """
        blocks = len(getattr(self.structured_document, "blocks", ()) or ())
        pages = len(getattr(self.structured_document, "pages", ()) or ())
        return {
            "schema_version": self.schema_version,
            "parser_engine": self.provenance.parser_engine,
            "parser_version": self.provenance.parser_version,
            "canonical_representation": REPRESENTATION_JSON,
            "llm_representation": REPRESENTATION_MARKDOWN,
            "canonical": (
                self.canonical.to_public_dict() if self.canonical is not None else None
            ),
            "llm_markdown": (
                self.artifacts[REPRESENTATION_MARKDOWN].to_public_dict()
                if REPRESENTATION_MARKDOWN in self.artifacts
                else None
            ),
            "html": (
                self.artifacts[REPRESENTATION_HTML].to_public_dict()
                if REPRESENTATION_HTML in self.artifacts
                else None
            ),
            "elements": blocks,
            "pages": pages,
            "crosswalk": {
                "sections": len(self.crosswalk.sections),
                "headings_mapped": self.crosswalk.headings_mapped,
                "coverage": round(float(self.crosswalk.coverage), 4),
                "element_coverage": round(float(self.crosswalk.element_coverage), 4),
                "pages_seen": list(self.crosswalk.pages_seen[:16]),
            },
            "quality": self.quality.to_public_dict(),
            "json_hash": self.json_hash,
            "markdown_hash": self.markdown_hash,
            "fingerprint": self.fingerprint,
        }

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "document_id": str(getattr(self.structured_document, "id", "") or ""),
            "external_id": str(
                getattr(self.structured_document, "external_id", "") or ""
            ),
            "provenance": self.provenance.to_public_dict(),
            "artifacts": {
                kind: artifact.to_public_dict()
                for kind, artifact in sorted(self.artifacts.items())
            },
            "crosswalk": self.crosswalk.to_public_dict(include_sections=False),
            "quality": self.quality.to_public_dict(),
            "json_hash": self.json_hash,
            "markdown_hash": self.markdown_hash,
            "fingerprint": self.fingerprint,
        }


def build_parsed_document_bundle(
    structured_document: Any,
    *,
    conversion: Any = None,
    parser_info: Mapping[str, Any] | None = None,
    fallback_warnings: Sequence[str] = (),
    min_crosswalk_coverage: float = 0.6,
    markdown_schema_note: str = "",
) -> ParsedDocumentBundle:
    """Construye el bundle dual desde la MISMA conversión ODL."""
    info = dict(parser_info or {})
    payload = getattr(conversion, "data", None) if conversion is not None else None
    markdown = str(getattr(conversion, "markdown", "") or "") if conversion is not None else ""
    html = str(getattr(conversion, "html", "") or "") if conversion is not None else ""
    json_text = canonical_json_text(payload) if payload else ""
    json_hash = _sha256_text(json_text) if json_text else str(
        getattr(structured_document, "content_hash", "") or ""
    )
    markdown_hash = _sha256_text(markdown) if markdown else ""
    html_hash = _sha256_text(html) if html else ""

    options_fingerprint = dict(info.get("options") or {})
    provenance = BundleProvenance(
        parser_engine=str(info.get("engine") or ""),
        parser_version=str(info.get("version") or ""),
        parser_mode=str(info.get("mode") or ""),
        structure_source=str(info.get("structure_source") or ""),
        options_fingerprint=options_fingerprint,
        formats=tuple(str(item) for item in (info.get("formats") or ())),
        elapsed_seconds=float(getattr(conversion, "elapsed_seconds", 0.0) or 0.0),
        java=str(getattr(conversion, "java", "") or info.get("java") or ""),
        fallback_warnings=tuple(str(item) for item in fallback_warnings if item),
    )

    artifacts: dict[str, RepresentationArtifact] = {}
    if json_text:
        artifacts[REPRESENTATION_JSON] = RepresentationArtifact(
            kind=REPRESENTATION_JSON,
            content="",
            content_hash=json_hash,
            bytes=int(getattr(conversion, "output_json_bytes", 0) or 0) or len(json_text),
            storage=STORAGE_BUNDLE,
            metadata={"authority": "canonical", "format": "opendataloader-json"},
        )
    if markdown.strip():
        artifacts[REPRESENTATION_MARKDOWN] = RepresentationArtifact(
            kind=REPRESENTATION_MARKDOWN,
            content=markdown,
            content_hash=markdown_hash,
            bytes=int(getattr(conversion, "output_markdown_bytes", 0) or 0)
            or len(markdown.encode("utf-8")),
            storage=STORAGE_BUNDLE,
            metadata={
                "representation_kind": REPRESENTATION_MARKDOWN,
                "derived_from": str(getattr(structured_document, "id", "") or ""),
                "parser_engine": provenance.parser_engine,
                "parser_version": provenance.parser_version,
                "canonical_json_hash": json_hash,
                "schema_note": markdown_schema_note,
            },
        )
    if html.strip():
        artifacts[REPRESENTATION_HTML] = RepresentationArtifact(
            kind=REPRESENTATION_HTML,
            content=html,
            content_hash=html_hash,
            bytes=int(getattr(conversion, "output_html_bytes", 0) or 0)
            or len(html.encode("utf-8")),
            storage=STORAGE_BUNDLE,
            metadata={"optional": True},
        )

    crosswalk = build_markdown_crosswalk(structured_document, markdown)
    quality = evaluate_bundle_quality(
        structured_document,
        crosswalk,
        markdown,
        min_coverage=min_crosswalk_coverage,
    )
    fingerprint = bundle_fingerprint(
        parser_engine=provenance.parser_engine,
        parser_version=provenance.parser_version,
        options_fingerprint=options_fingerprint,
        json_hash=json_hash,
        markdown_hash=markdown_hash,
        html_hash=html_hash,
    )
    return ParsedDocumentBundle(
        structured_document=structured_document,
        artifacts=artifacts,
        provenance=provenance,
        crosswalk=crosswalk,
        quality=quality,
        json_hash=json_hash,
        markdown_hash=markdown_hash,
        fingerprint=fingerprint,
    )


# -----------------------------------------------------------------------------
# Storage: artefacto una vez; en metadata solo refs/hashes
# -----------------------------------------------------------------------------


def place_bundle_artifacts(
    bundle: ParsedDocumentBundle,
    *,
    root: str | Path,
    organization_id: str,
    canonical_json_text_value: str = "",
    include_html: bool = False,
) -> ParsedDocumentBundle:
    """Persiste los artefactos UNA vez y devuelve el bundle con refs.

    Directorio: {root}/{org}/representations/{document_id}/
      - canonical.json  (ODL JSON, si se pasa el texto)
      - llm.markdown    (proyección LLM-ready)
      - crosswalk.json  (mapa secciones → element ids; sin markdown completo)

    Nunca se guarda el Markdown gigante en payloads de Qdrant: la metadata
    liviana viaja con refs (`metadata["representations"]`).
    """
    document = bundle.structured_document
    document_id = str(getattr(document, "id", "") or "document")
    folder = Path(root) / str(organization_id) / "representations" / document_id
    folder.mkdir(parents=True, exist_ok=True)

    artifacts = dict(bundle.artifacts)
    if canonical_json_text_value:
        json_path = folder / "canonical.json"
        json_path.write_text(canonical_json_text_value, encoding="utf-8")
        existing = artifacts.get(REPRESENTATION_JSON)
        artifacts[REPRESENTATION_JSON] = replace(
            existing
            if existing is not None
            else RepresentationArtifact(kind=REPRESENTATION_JSON),
            ref=str(json_path),
            storage=STORAGE_ARTIFACT,
        )
    markdown_artifact = artifacts.get(REPRESENTATION_MARKDOWN)
    if markdown_artifact is not None and markdown_artifact.content:
        markdown_path = folder / "llm.markdown"
        markdown_path.write_text(markdown_artifact.content, encoding="utf-8")
        artifacts[REPRESENTATION_MARKDOWN] = replace(
            markdown_artifact,
            ref=str(markdown_path),
            storage=STORAGE_ARTIFACT,
        )
    if include_html:
        html_artifact = artifacts.get(REPRESENTATION_HTML)
        if html_artifact is not None and html_artifact.content:
            html_path = folder / "document.html"
            html_path.write_text(html_artifact.content, encoding="utf-8")
            artifacts[REPRESENTATION_HTML] = replace(
                html_artifact, ref=str(html_path), storage=STORAGE_ARTIFACT
            )
    crosswalk_path = folder / "crosswalk.json"
    crosswalk_path.write_text(
        json.dumps(
            bundle.crosswalk.to_public_dict(),
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return replace(bundle, artifacts=artifacts)


# -----------------------------------------------------------------------------
# Query-time strategy helpers
# -----------------------------------------------------------------------------

_EXPLANATORY_QUERY_RE = re.compile(
    r"\b(?:qu[eé]\s+(?:es|significa)|significado|expl[ií]c\w*|resum\w*|"
    r"c[oó]mo\s+funciona|para\s+qu[eé]|what\s+is|explain\w*|summarize|overview)\b",
    re.IGNORECASE,
)


def markdown_first_recommended(question: str) -> bool:
    """¿Conviene retrieval narrativo (Markdown) para esta pregunta?

    Preguntas explicativas → Markdown-first. Preguntas ejecutables (aplicar/
    validar/comparar/calcular con valores) → CanonicalRule-first + JSON.
    El Markdown NUNCA decide sola una operación determinista.
    """
    text = str(question or "")
    if not text.strip():
        return False
    if _EXPLANATORY_QUERY_RE.search(text):
        return True
    try:
        from src.intelligence.reasoning.classifier import (
            has_concrete_scenario_payload,
            is_informational_request,
        )
    except Exception:  # noqa: BLE001 — sin clasificador, queda el regex de arriba
        return False
    return is_informational_request(text) and not has_concrete_scenario_payload(text)


def _markdown_from_metadata(metadata: Mapping[str, Any] | None) -> str:
    """Texto Markdown ya proyectado. Vacío si el chunk no lo trae."""
    meta = metadata if isinstance(metadata, Mapping) else {}
    for key in ("llm_markdown_text", "markdown_text"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raw = meta.get("llm_markdown")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(raw, Mapping):
        nested = str(raw.get("text") or raw.get("content") or "")
        if nested.strip():
            return nested.strip()
    representations = meta.get("representations")
    if isinstance(representations, Mapping):
        markdown = representations.get(REPRESENTATION_MARKDOWN)
        if isinstance(markdown, str) and markdown.strip():
            return markdown.strip()
        if isinstance(markdown, Mapping):
            nested = str(markdown.get("text") or markdown.get("content") or "")
            if nested.strip():
                return nested.strip()
    return ""


def narrative_context_text(
    *,
    question: str,
    canonical: str,
    metadata: Mapping[str, Any] | None = None,
) -> str:
    """Contexto que lee el LLM. Las citas siguen en el texto canónico.

    En una consulta informativa, si existe la proyección ``llm_markdown``,
    el modelo lee esa sección. El Markdown no es una fuente nueva.
    """
    canonical_text = str(canonical or "")
    if not markdown_first_recommended(question):
        return canonical_text
    markdown = _markdown_from_metadata(metadata)
    return markdown or canonical_text


def select_markdown_context(
    question: str,
    chunks: Iterable[MarkdownChunk],
    *,
    limit: int = 2,
    max_chars: int = 1200,
) -> tuple[MarkdownChunk, ...]:
    """Snippets Markdown relevantes para la PREGUNTA (contexto, no decisión)."""
    tokens = {
        token
        for token in re.findall(r"[a-z0-9_áéíóúñü]{3,}", str(question or "").lower())
    }
    if not tokens:
        return ()
    scored: list[tuple[int, MarkdownChunk]] = []
    for chunk in chunks or ():
        haystack = f"{chunk.heading} {chunk.text}".lower()
        score = sum(1 for token in tokens if token in haystack)
        if score:
            scored.append((score, chunk))
    scored.sort(key=lambda item: (-item[0], item[1].chunk_id))
    selected: list[MarkdownChunk] = []
    total = 0
    for _score, chunk in scored:
        if total + len(chunk.text) > max_chars and selected:
            break
        selected.append(chunk)
        total += len(chunk.text)
        if len(selected) >= max(1, int(limit)):
            break
    return tuple(selected)


def markdown_chunk_qdrant_payload(
    chunk: MarkdownChunk,
    *,
    artifact_ref: str = "",
    document_title: str = "",
    source_id: str = "",
) -> dict[str, Any]:
    """Payload section-level para Qdrant (nunca el Markdown completo).

    Qdrant guarda: representation kind, texto de embedding, ref al artefacto,
    documento canónico y rango de páginas + ids canónicos para citas.
    """
    return {
        "representation_kind": chunk.representation_kind,
        "canonical_representation": REPRESENTATION_JSON,
        "document_id": chunk.document_id,
        "document_title": str(document_title or "")[:200],
        "source_id": str(source_id or ""),
        "chunk_id": chunk.chunk_id,
        "heading": chunk.heading[:200],
        "section_path": list(chunk.section_path[:6]),
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "page_range": [chunk.page_start, chunk.page_end],
        "canonical_element_ids": list(chunk.canonical_element_ids[:24]),
        "canonical_evidence_ids": list(chunk.canonical_evidence_ids[:24]),
        "artifact_ref": str(artifact_ref or ""),
        "embedding_text": chunk.text,
        "token_estimate": int(chunk.token_estimate),
    }


def citation_from_markdown_offset(
    crosswalk: MarkdownSectionMap,
    offset: int,
    *,
    artifact_ref: str = "",
) -> dict[str, Any]:
    """Cita desde un offset del Markdown: vuelve al JSON (id/página/bbox).

    El LLM lee Markdown; la cita NO se sostiene en el texto: se resuelve al
    elemento canónico con página y bbox del StructuredDocument.
    """
    section = crosswalk.section_for_offset(int(offset))
    if section is None or not section.mapped:
        return {}
    return {
        "representation_kind": REPRESENTATION_MARKDOWN,
        "canonical_representation": REPRESENTATION_JSON,
        "section_path": list(section.section_path[:6]),
        "page": section.page_start,
        "page_range": [section.page_start, section.page_end],
        "bbox_anchors": [list(box) for box in section.bbox_anchors[:4]],
        "canonical_element_ids": list(section.canonical_element_ids[:12]),
        "canonical_evidence_ids": list(section.canonical_evidence_ids[:12]),
        "canonical_section_id": section.canonical_section_id,
        "artifact_ref": str(artifact_ref or ""),
    }


__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "MARKDOWN_CHUNKING_VERSION",
    "REPRESENTATION_HTML",
    "REPRESENTATION_JSON",
    "REPRESENTATION_MARKDOWN",
    "STORAGE_ARTIFACT",
    "STORAGE_BUNDLE",
    "STORAGE_INLINE",
    "BundleProvenance",
    "BundleQuality",
    "MarkdownChunk",
    "MarkdownSection",
    "MarkdownSectionMap",
    "ParsedDocumentBundle",
    "RepresentationArtifact",
    "build_markdown_crosswalk",
    "build_parsed_document_bundle",
    "bundle_fingerprint",
    "canonical_evidence_id",
    "canonical_json_text",
    "chunk_markdown",
    "citation_from_markdown_offset",
    "evaluate_bundle_quality",
    "markdown_first_recommended",
    "narrative_context_text",
    "markdown_chunk_qdrant_payload",
    "place_bundle_artifacts",
    "representation_stale",
    "select_markdown_context",
]
