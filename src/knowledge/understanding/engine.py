# =============================================================================
# Document Understanding Engine
# =============================================================================
# SOURCE FILE se conserva. Esta capa produce CanonicalDocument encima del
# StructuredDocument que ZENT ya persiste. No trocea. No llama a un LLM.
# Markdown es una vista. La inferencia va marcada como INFERRED.
# =============================================================================
from __future__ import annotations

import dataclasses
import hashlib
import time

from src.core.domain.catalog import CatalogProvenance
from src.core.domain.knowledge_v2 import (
    KnowledgeObjectStatus,
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.structure.base import content_hash, token_count
from src.knowledge.understanding.artifacts import CanonicalArtifactStore
from src.knowledge.understanding.enrich import (
    attach_section_owners,
    collapse_spaced_letters,
    derive_document_semantics,
    link_neighbors,
    merge_multipage_tables,
)
from src.knowledge.understanding.layout import mark_repeated_chrome
from src.knowledge.understanding.providers import DocumentUnderstandingProvider, PageOcrProvider
from src.knowledge.understanding.units import build_retrieval_units
from src.knowledge.understanding.versions import (
    CHUNKING_VERSION,
    PARSER_VERSION,
    SCHEMA_VERSION,
    SEMANTIC_UNIT_VERSION,
    SOURCE_PROFILE_VERSION,
    UNDERSTANDING_SCHEMA_VERSION,
)
from src.knowledge.understanding.views import (
    build_report,
    canonical_digest,
    parsed_digest,
    pipeline_state,
    quality_report,
    retrieval_digest,
    source_profile,
    to_ast,
    to_markdown,
    to_tree,
)

_OCR_MIN_CHARS = 12


def apply_understanding(
    document: StructuredDocument,
    *,
    file_hash: str | None = None,
    filename: str | None = None,
    merge_tables: bool = True,
    ocr_provider: PageOcrProvider | None = None,
    model_provider: DocumentUnderstandingProvider | None = None,
) -> StructuredDocument:
    """Entiende el documento: layout, tablas, literales, árbol y semánticas."""
    return understand_document(
        document,
        file_hash=file_hash,
        filename=filename,
        merge_tables=merge_tables,
        ocr_provider=ocr_provider,
        model_provider=model_provider,
    )


def understand_document(
    document: StructuredDocument,
    *,
    file_hash: str | None = None,
    filename: str | None = None,
    merge_tables: bool = True,
    ocr_provider: PageOcrProvider | None = None,
    model_provider: DocumentUnderstandingProvider | None = None,
) -> StructuredDocument:
    started = time.perf_counter()
    warnings: list[str] = []
    current = mark_repeated_chrome(document)
    ocr_required = [
        page.page_number
        for page in current.pages
        if len((page.text or "").strip()) < _OCR_MIN_CHARS
    ]
    current, ocr_used_pages = _apply_ocr(current, ocr_provider, warnings)
    if ocr_required and ocr_provider is None:
        warnings.append("text layer missing on some pages; OCR provider not configured")
    current = attach_section_owners(current)
    current = collapse_spaced_letters(current)
    if merge_tables:
        current = merge_multipage_tables(
            current,
            min_confidence=float(_setting("TABLE_MERGE_MIN_CONFIDENCE", 0.65)),
        )
        current = attach_section_owners(current)
    current, extracted = derive_document_semantics(current)
    if model_provider is not None:
        current, _ignored = _apply_model(current, extracted, model_provider, warnings)
        current, extracted = derive_document_semantics(current)
    current = link_neighbors(current)
    current = _stamp_pages(current, ocr_used_pages)

    quality = quality_report(
        current,
        ocr_pages=ocr_used_pages,
        warnings=warnings,
        extracted=extracted,
    )
    pending = [page for page in ocr_required if page not in ocr_used_pages]
    quality["ocr_required_pages"] = pending
    quality["ocr_pages"] = sorted(set(pending + ocr_used_pages))
    quality["warnings"] = list(warnings)
    state = pipeline_state(quality)
    filename = filename or str(current.metadata.get("filename") or current.title)
    profile = source_profile(current, extracted, quality, filename=filename)
    markdown = to_markdown(current)
    ast = to_ast(current, extracted)
    tree = to_tree(current)
    elapsed = time.perf_counter() - started
    report = build_report(
        current,
        extracted,
        quality,
        filename=filename,
        state=state,
        elapsed_s=elapsed,
    )
    unit_source = dataclasses.replace(
        current,
        metadata={
            **current.metadata,
            "understanding": {
                "exact_literals": extracted["exact_literals"],
                "technical_fields": extracted["technical_fields"],
                "relations": extracted["relations"],
            },
        },
    )
    units = build_retrieval_units(
        unit_source,
        budget=int(_setting("SEMANTIC_UNIT_MAX_CHARS", 1200)),
    )
    retrieval_hash = retrieval_digest(units)
    canonical_hash = canonical_digest(ast, current)
    parsed_hash = parsed_digest(current)
    placed = CanonicalArtifactStore(root=_artifact_root()).place(
        organization_id=str(current.organization_id),
        document_id=str(current.id),
        markdown=markdown,
        ast=ast,
        max_inline_bytes=int(_setting("CANONICAL_INLINE_MAX_BYTES", 48_000)),
    )
    table_score = quality.get("table_confidence")
    visual = bool(current.figures) or bool(quality.get("ocr_pages")) or (
        isinstance(table_score, (int, float)) and table_score < 0.5
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "understanding_schema_version": UNDERSTANDING_SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "chunking_version": CHUNKING_VERSION,
        "semantic_unit_version": SEMANTIC_UNIT_VERSION,
        "source_profile_version": SOURCE_PROFILE_VERSION,
        "canonical_version": SCHEMA_VERSION,
        "pipeline_state": state,
        "file_hash": file_hash,
        "parsed_hash": parsed_hash,
        "canonical_hash": canonical_hash,
        "retrieval_hash": retrieval_hash,
        "profile": profile,
        "quality": quality,
        "report": report,
        "definitions": extracted["definitions"],
        "technical_fields": extracted["technical_fields"],
        "exact_literals": extracted["exact_literals"],
        "cross_references": extracted["cross_references"],
        "relations": extracted["relations"],
        "retrieval_units": [unit.compact() for unit in units],
        "semantic_unit_count": sum(1 for unit in units if unit.unit_type != "SECTION"),
        "semantic_units": True,
        "tree": tree,
        "visual_processing_required": visual,
        "artifact": {
            "storage": placed["storage"],
            "markdown_ref": placed.get("markdown_ref"),
            "ast_ref": placed.get("ast_ref"),
            "markdown_bytes": placed.get("markdown_bytes"),
            "ast_bytes": placed.get("ast_bytes"),
            "overflow": placed.get("overflow", False),
        },
    }
    if placed["storage"] == "inline":
        payload["views"] = {"markdown": placed["markdown"], "ast": placed["ast"]}
    metadata = {**current.metadata, "filename": filename, "understanding": payload}
    hashed = retrieval_hash
    return dataclasses.replace(
        current,
        content_hash=hashed,
        metadata=metadata,
        document_type=profile["document_type"],
    )


def _setting(name: str, default):
    try:
        from src.core.config import get_settings

        return getattr(get_settings(), name, default)
    except Exception:  # noqa: BLE001
        return default


def _artifact_root():
    try:
        from pathlib import Path

        from src.core.config import get_settings

        raw = getattr(get_settings(), "UPLOAD_DIR", None)
        if not raw:
            return None
        return Path(str(raw))
    except Exception:  # noqa: BLE001
        return None


def _apply_ocr(
    document: StructuredDocument,
    provider: PageOcrProvider | None,
    warnings: list[str],
) -> tuple[StructuredDocument, list[int]]:
    needed = [
        page.page_number
        for page in document.pages
        if len((page.text or "").strip()) < _OCR_MIN_CHARS
    ]
    if not needed or provider is None:
        return document, []
    used: list[int] = []
    blocks = list(document.blocks)
    pages = list(document.pages)
    order = max((block.order for block in blocks), default=-1)
    for index, page in enumerate(pages):
        if page.page_number not in needed:
            continue
        try:
            recognized = provider.recognize_page(
                page_number=page.page_number,
                page_text=page.text,
                image=None,
            )
        except Exception as exc:  # noqa: BLE001 — una página no tumba el documento
            warnings.append(f"ocr failed on page {page.page_number}: {exc}")
            continue
        text = (recognized or "").strip()
        if not text:
            continue
        order += 1
        block = StructuredBlock(
            kind=StructuredBlockKind.PARAGRAPH,
            text=text,
            order=order,
            page=page.page_number,
            token_count=token_count(text),
            content_hash=content_hash(text),
            metadata={
                "ocr": True,
                "provenance_type": "EXTRACTED",
                "derived_by": "ocr",
                "confidence": 0.7,
            },
        )
        blocks.append(block)
        meta = dict(page.metadata)
        meta["ocr_used"] = True
        meta["text_confidence"] = 0.7
        pages[index] = dataclasses.replace(
            page,
            text=(page.text + "\n" + text).strip(),
            block_ids=page.block_ids + (block.id,),
            token_count=token_count(text),
            content_hash=content_hash(text),
            metadata=meta,
            provenance=CatalogProvenance.OBSERVED,
            status=KnowledgeObjectStatus.OBSERVED,
        )
        used.append(page.page_number)
    if not used:
        return document, []
    return dataclasses.replace(document, blocks=tuple(blocks), pages=tuple(pages)), used


def _stamp_pages(document: StructuredDocument, ocr_pages: list[int]) -> StructuredDocument:
    if not document.pages:
        return document
    pages = []
    for page in document.pages:
        meta = dict(page.metadata)
        size = len((page.text or "").strip())
        meta.setdefault("text_confidence", 1.0 if size >= 40 else 0.0 if size == 0 else 0.45)
        meta.setdefault("ocr_used", page.page_number in ocr_pages)
        meta["ocr_required"] = size < _OCR_MIN_CHARS and page.page_number not in ocr_pages
        pages.append(dataclasses.replace(page, metadata=meta))
    return dataclasses.replace(document, pages=tuple(pages))


def _apply_model(
    document: StructuredDocument,
    extracted: dict,
    provider: DocumentUnderstandingProvider,
    warnings: list[str],
) -> tuple[StructuredDocument, dict]:
    try:
        correction = provider.correct(
            raw_text="\n".join(block.text for block in document.blocks),
            layout_blocks=[
                {"id": str(block.id), "text": block.text, "role": block.metadata.get("role")}
                for block in document.blocks
            ],
            page_image=None,
        )
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"understanding provider failed: {exc}")
        return document, extracted
    roles = correction.get("block_roles") if isinstance(correction, dict) else None
    if not isinstance(roles, dict):
        return document, extracted
    blocks = []
    for block in document.blocks:
        role = roles.get(str(block.id))
        if not role:
            blocks.append(block)
            continue
        meta = dict(block.metadata)
        meta["role"] = str(role)
        meta["derived_by"] = "model"
        meta["provenance_type"] = "INFERRED"
        meta["confidence"] = float(correction.get("confidence") or 0.6)
        blocks.append(dataclasses.replace(block, metadata=meta))
    return dataclasses.replace(document, blocks=tuple(blocks)), extracted


def file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def observe_understanding(_organization_id: object, document: StructuredDocument) -> None:
    """Métricas de ingesta. Un fallo de Prometheus no rompe el documento."""
    payload = document.metadata.get("understanding") or {}
    report = payload.get("report") or {}
    quality = payload.get("quality") or {}
    try:
        from src.infrastructure.observability.metrics import (
            document_understanding_blocks,
            document_understanding_literals,
            document_understanding_ocr_pages,
            document_understanding_quality,
            document_understanding_seconds,
            document_understanding_sections,
            document_understanding_tables,
            document_understanding_warnings,
        )
    except Exception:  # noqa: BLE001
        return
    outcome = str(payload.get("pipeline_state") or payload.get("mode") or "unknown")
    document_understanding_seconds.labels(outcome=outcome).observe(float(report.get("elapsed_s") or 0.0))
    document_understanding_quality.labels(outcome=outcome).observe(float(quality.get("score") or 0.0))
    document_understanding_tables.labels(outcome=outcome).observe(float(report.get("tables") or 0))
    document_understanding_sections.labels(outcome=outcome).observe(float(report.get("sections") or 0))
    document_understanding_blocks.labels(outcome=outcome).observe(float(document.block_count))
    document_understanding_literals.labels(outcome=outcome).observe(float(report.get("exact_literals") or 0))
    document_understanding_ocr_pages.labels(outcome=outcome).observe(float(len(report.get("ocr_pages") or [])))
    document_understanding_warnings.labels(outcome=outcome).observe(float(len(report.get("warnings") or [])))
