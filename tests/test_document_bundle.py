# =============================================================================
# ParsedDocumentBundle — representación dual JSON + Markdown (una conversión)
# =============================================================================
# Contrato:
#   1. JSON = autoridad estructural; Markdown = proyección LLM-ready.
#   2. Crosswalk Markdown -> element ids / páginas / bbox.
#   3. Chunking por heading/sección (nunca tamaño fijo ciego).
#   4. Identidad de evidencia compartida: JSON y Markdown NO son 2 evidencias.
#   5. Quality gates antes de promover el Markdown; el JSON sigue funcionando.
#   6. Fingerprint incluye engine/version/options/hashes/schema.
# =============================================================================
from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

from src.core.domain.knowledge_v2 import (
    BoundingBox,
    DocumentPage,
    DocumentSection,
    DocumentTable,
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.structure.document_bundle import (
    BUNDLE_SCHEMA_VERSION,
    MARKDOWN_CHUNKING_VERSION,
    REPRESENTATION_JSON,
    REPRESENTATION_MARKDOWN,
    STORAGE_ARTIFACT,
    build_markdown_crosswalk,
    build_parsed_document_bundle,
    bundle_fingerprint,
    canonical_evidence_id,
    chunk_markdown,
    citation_from_markdown_offset,
    evaluate_bundle_quality,
    markdown_chunk_qdrant_payload,
    markdown_first_recommended,
    place_bundle_artifacts,
    representation_stale,
    select_markdown_context,
)

MARKDOWN = """<!-- page:16 -->
# 4. Fare Class Restrictions

The symbol & matches one alphanumeric position.

<!-- page:17 -->
## 4.1 Matching Rules

Matching is positional, left to right. Literal characters must match exactly
at their position. The value may be longer than the pattern.
"""


def _doc_id() -> UUID:
    return UUID("11111111-2222-3333-4444-555555555555")


def _block(
    kind: StructuredBlockKind,
    text: str,
    *,
    order: int,
    page: int,
    heading: tuple[str, ...] = (),
) -> StructuredBlock:
    return StructuredBlock(
        kind=kind,
        text=text,
        order=order,
        page=page,
        heading_path=heading,
        bbox=BoundingBox(page=page, x0=10.0, y0=20.0, x1=200.0, y1=40.0),
    )


def _document(*, with_tables: bool = False) -> StructuredDocument:
    doc_id = _doc_id()
    org = uuid4()
    heading = _block(
        StructuredBlockKind.HEADING,
        "4. Fare Class Restrictions",
        order=0,
        page=16,
        heading=("4. Fare Class Restrictions",),
    )
    body = _block(
        StructuredBlockKind.PARAGRAPH,
        "The symbol & matches one alphanumeric position.",
        order=1,
        page=16,
        heading=("4. Fare Class Restrictions",),
    )
    sub_heading = _block(
        StructuredBlockKind.HEADING,
        "4.1 Matching Rules",
        order=2,
        page=17,
        heading=("4. Fare Class Restrictions", "4.1 Matching Rules"),
    )
    sub_body = _block(
        StructuredBlockKind.PARAGRAPH,
        "Matching is positional, left to right. Literal characters must match "
        "exactly at their position. The value may be longer than the pattern.",
        order=3,
        page=17,
        heading=("4. Fare Class Restrictions", "4.1 Matching Rules"),
    )
    section_one = DocumentSection(
        document_id=doc_id,
        organization_id=org,
        section_path=("4",),
        heading="4. Fare Class Restrictions",
        depth=1,
        page_start=16,
        page_end=16,
        block_ids=(heading.id, body.id),
    )
    section_two = DocumentSection(
        document_id=doc_id,
        organization_id=org,
        section_path=("4", "4.1"),
        heading="4.1 Matching Rules",
        depth=2,
        page_start=17,
        page_end=17,
        block_ids=(sub_heading.id, sub_body.id),
    )
    pages = tuple(
        DocumentPage(
            document_id=doc_id,
            organization_id=org,
            page_number=number,
            text="",
        )
        for number in (16, 17)
    )
    tables = (
        (
            DocumentTable(
                document_id=doc_id,
                organization_id=org,
                caption="Tabla 4-1",
                page=16,
            ),
        )
        if with_tables
        else ()
    )
    return StructuredDocument(
        id=doc_id,
        organization_id=org,
        external_id="record2_ampersand.pdf",
        title="Data Application For Record 2",
        content_hash="file-hash",
        blocks=(heading, body, sub_heading, sub_body),
        pages=pages,
        sections=(section_one, section_two),
        tables=tables,
    )


def _bundle(
    *,
    markdown: str = MARKDOWN,
    document: StructuredDocument | None = None,
    min_coverage: float = 0.6,
):
    class _Conversion:
        data = {"kids": [], "title": "record2"}
        markdown = ""
        html = ""
        output_json_bytes = 0
        output_markdown_bytes = 0
        output_html_bytes = 0
        elapsed_seconds = 0.25
        java = "17"

    conversion = _Conversion()
    conversion.markdown = markdown
    conversion.output_markdown_bytes = len(markdown.encode("utf-8"))
    return build_parsed_document_bundle(
        document or _document(),
        conversion=conversion,
        parser_info={
            "engine": "opendataloader",
            "version": "2.5.12",
            "mode": "local",
            "structure_source": "inferred_layout",
            "options": {"table_method": "default", "formats": ["json", "markdown"]},
        },
        min_crosswalk_coverage=min_coverage,
    )


class TestCrosswalk:
    def test_sections_map_to_canonical_elements(self) -> None:
        bundle = _bundle()
        crosswalk = bundle.crosswalk
        assert crosswalk.headings_total == 2
        assert crosswalk.headings_mapped == 2
        assert crosswalk.coverage == 1.0
        assert crosswalk.element_coverage == 1.0
        assert crosswalk.pages_seen == (16, 17)
        assert crosswalk.page_marks_found == 2

        second = crosswalk.sections[1]
        assert second.heading == "4.1 Matching Rules"
        assert second.level == 2
        assert second.section_path == ("4", "4.1")
        assert second.page_start == 17 and second.page_end == 17
        assert second.canonical_section_id
        assert len(second.canonical_element_ids) == 2
        assert second.bbox_anchors and second.bbox_anchors[0] == (10.0, 20.0, 200.0, 40.0)
        assert all(
            evidence_id.startswith(f"ev:{_doc_id()}")
            for evidence_id in second.canonical_evidence_ids
        )

    def test_unmatched_heading_is_not_mapped(self) -> None:
        markdown = MARKDOWN + "\n## Sección Inexistente\n\nContenido suelto.\n"
        crosswalk = build_markdown_crosswalk(_document(), markdown)
        unmapped = crosswalk.sections[-1]
        assert unmapped.mapped is False
        assert unmapped.canonical_element_ids == ()
        assert crosswalk.coverage < 1.0

    def test_evidence_identity_is_shared(self) -> None:
        bundle = _bundle()
        evidence_ids = bundle.crosswalk.evidence_ids()
        assert len(evidence_ids) == len(set(evidence_ids))
        # Un solo evidence id por elemento canónico, aunque lo referencien las
        # dos representaciones.
        assert all(
            evidence_id == canonical_evidence_id(_doc_id(), element_id)
            for evidence_id, element_id in zip(
                bundle.crosswalk.sections[0].canonical_evidence_ids,
                bundle.crosswalk.sections[0].canonical_element_ids,
            )
        )


class TestChunking:
    def test_chunks_follow_structure(self) -> None:
        bundle = _bundle()
        chunks = bundle.markdown_chunks()
        assert len(chunks) == 2
        first, second = chunks
        assert first.heading == "4. Fare Class Restrictions"
        assert first.page_start == 16 and first.page_end == 16
        assert first.canonical_element_ids
        assert second.heading == "4.1 Matching Rules"
        assert second.page_start == 17
        assert all(chunk.representation_kind == "llm_markdown" for chunk in chunks)
        assert all(chunk.schema_version == MARKDOWN_CHUNKING_VERSION for chunk in chunks)

    def test_long_section_splits_without_breaking_sentences(self) -> None:
        long_sentence = "El valor debe respetar la política documentada de longitud."
        paragraphs = "\n\n".join([long_sentence] * 40)
        markdown = (
            "# 4. Fare Class Restrictions\n\n"
            "<!-- page:16 -->\n\n"
            f"{paragraphs}\n"
        )
        crosswalk = build_markdown_crosswalk(_document(), markdown)
        chunks = chunk_markdown(markdown, crosswalk, document_id=str(_doc_id()), max_chars=500)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk.text) <= 500
            if len(chunk.text) < 500:
                assert chunk.text.rstrip().endswith(".")
            assert chunk.canonical_element_ids
            assert chunk.page_start == 16

    def test_chunks_never_reference_unknown_evidence(self) -> None:
        bundle = _bundle()
        known = set(bundle.crosswalk.evidence_ids())
        for chunk in bundle.markdown_chunks():
            assert set(chunk.canonical_evidence_ids) <= known


class TestQualityGates:
    def test_promoted_on_sane_bundle(self) -> None:
        bundle = _bundle()
        assert bundle.quality.promoted is True
        assert bundle.llm_representation_promoted is True
        checks = {check["name"]: check["ok"] for check in bundle.quality.checks}
        assert checks == {
            "non_empty_projection": True,
            "crosswalk_coverage": True,
            "page_mapping": True,
            "heading_hierarchy": True,
            "table_representation": True,
        }

    def test_empty_projection_not_promoted(self) -> None:
        bundle = _bundle(markdown="")
        assert bundle.quality.promoted is False
        assert "empty_or_unmapped_projection" in bundle.quality.reasons

    def test_low_coverage_not_promoted(self) -> None:
        markdown = MARKDOWN + "\n## Otra Sección\n\nSin ancla canónica.\n" * 3
        quality = evaluate_bundle_quality(
            _document(),
            build_markdown_crosswalk(_document(), markdown),
            markdown,
            min_coverage=0.95,
        )
        assert quality.promoted is False
        assert any(reason.startswith("crosswalk_coverage") for reason in quality.reasons)

    def test_table_gate_fails_when_canonical_tables_missing_in_markdown(self) -> None:
        document = _document(with_tables=True)
        quality = evaluate_bundle_quality(
            document,
            build_markdown_crosswalk(document, MARKDOWN),
            MARKDOWN,
            min_coverage=0.6,
        )
        assert quality.table_representation_sane is False
        assert quality.promoted is False
        assert "table_representation_missing" in quality.reasons

    def test_page_mapping_invalid_outside_document(self) -> None:
        markdown = MARKDOWN.replace("<!-- page:17 -->", "<!-- page:99 -->")
        quality = evaluate_bundle_quality(
            _document(),
            build_markdown_crosswalk(_document(), markdown),
            markdown,
        )
        assert quality.page_mapping_valid is False
        assert quality.promoted is False


class TestFingerprint:
    def test_fingerprint_is_stable_and_selective(self) -> None:
        bundle = _bundle()
        same = bundle_fingerprint(
            parser_engine="opendataloader",
            parser_version="2.5.12",
            options_fingerprint=bundle.provenance.options_fingerprint,
            json_hash=bundle.json_hash,
            markdown_hash=bundle.markdown_hash,
        )
        assert same == bundle.fingerprint
        changed_engine = bundle_fingerprint(
            parser_engine="opendataloader",
            parser_version="2.6.0",
            options_fingerprint=bundle.provenance.options_fingerprint,
            json_hash=bundle.json_hash,
            markdown_hash=bundle.markdown_hash,
        )
        assert changed_engine != bundle.fingerprint
        assert representation_stale(
            bundle.fingerprint,
            parser_engine="opendataloader",
            parser_version="2.6.0",
            options_fingerprint=bundle.provenance.options_fingerprint,
            json_hash=bundle.json_hash,
            markdown_hash=bundle.markdown_hash,
        )
        assert not representation_stale(
            bundle.fingerprint,
            parser_engine="opendataloader",
            parser_version="2.5.12",
            options_fingerprint=bundle.provenance.options_fingerprint,
            json_hash=bundle.json_hash,
            markdown_hash=bundle.markdown_hash,
        )

    def test_options_change_invalidates(self) -> None:
        changed = bundle_fingerprint(
            parser_engine="opendataloader",
            parser_version="2.5.12",
            options_fingerprint={"table_method": "cluster"},
            json_hash="j",
            markdown_hash="m",
        )
        base = bundle_fingerprint(
            parser_engine="opendataloader",
            parser_version="2.5.12",
            options_fingerprint={"table_method": "default"},
            json_hash="j",
            markdown_hash="m",
        )
        assert changed != base


class TestMetadataAndStorage:
    def test_metadata_block_is_light(self) -> None:
        bundle = _bundle()
        block = bundle.metadata_block()
        serialized = json.dumps(block, ensure_ascii=False)
        assert "The symbol & matches" not in serialized
        assert block["canonical_representation"] == REPRESENTATION_JSON
        assert block["llm_representation"] == REPRESENTATION_MARKDOWN
        assert block["canonical"]["canonical"] is True
        assert block["crosswalk"]["coverage"] == 1.0
        assert block["fingerprint"] == bundle.fingerprint
        assert block["schema_version"] == BUNDLE_SCHEMA_VERSION

    def test_place_artifacts_writes_once_and_keeps_metadata_light(self, tmp_path: Path) -> None:
        bundle = _bundle()
        org = uuid4()
        placed = place_bundle_artifacts(
            bundle,
            root=tmp_path,
            organization_id=str(org),
            canonical_json_text_value='{"kids": []}',
        )
        folder = tmp_path / str(org) / "representations" / str(_doc_id())
        assert (folder / "llm.markdown").is_file()
        assert (folder / "canonical.json").is_file()
        assert (folder / "crosswalk.json").is_file()
        markdown_artifact = placed.artifacts[REPRESENTATION_MARKDOWN]
        assert markdown_artifact.storage == STORAGE_ARTIFACT
        assert markdown_artifact.ref.endswith("llm.markdown")
        assert markdown_artifact.content == bundle.markdown
        # La metadata liviana viaja con refs/hashes; el markdown NO se
        # serializa en el StructuredDocument.
        block = placed.metadata_block()
        assert block["llm_markdown"]["ref"].endswith("llm.markdown")
        assert block["llm_markdown"]["content_hash"] == bundle.markdown_hash

    def test_crosswalk_file_has_no_full_markdown(self, tmp_path: Path) -> None:
        bundle = _bundle()
        placed = place_bundle_artifacts(
            bundle, root=tmp_path, organization_id="org", canonical_json_text_value="{}"
        )
        crosswalk_file = (
            tmp_path / "org" / "representations" / str(_doc_id()) / "crosswalk.json"
        )
        payload = crosswalk_file.read_text(encoding="utf-8")
        assert "The symbol & matches" not in payload
        assert "canonical_element_ids" in payload
        assert placed.json_hash


class TestQueryStrategy:
    def test_explanatory_question_prefers_markdown(self) -> None:
        assert markdown_first_recommended("¿Qué significa el símbolo &?") is True
        assert markdown_first_recommended("explícame la regla de matching") is True
        assert markdown_first_recommended("¿ABCFGEGE cumple el patrón &&&F?") is False
        assert markdown_first_recommended("¿120 es mayor o igual que el mínimo 100?") is False

    def test_select_markdown_context_scores_by_question(self) -> None:
        chunks = _bundle().markdown_chunks()
        selected = select_markdown_context("¿Cómo funciona el matching posicional?", chunks)
        assert selected
        assert any("Matching Rules" in chunk.heading for chunk in selected)

    def test_qdrant_payload_is_section_level(self) -> None:
        chunk = _bundle().markdown_chunks()[0]
        payload = markdown_chunk_qdrant_payload(
            chunk,
            artifact_ref="/artifacts/llm.markdown",
            document_title="Manual",
            source_id="src-1",
        )
        assert payload["representation_kind"] == "llm_markdown"
        assert payload["canonical_representation"] == "structured_json"
        assert payload["embedding_text"] == chunk.text
        assert payload["artifact_ref"].endswith("llm.markdown")
        assert payload["page_range"] == [16, 16]
        assert payload["canonical_evidence_ids"]
        assert "embedding_text" in payload and payload["embedding_text"]

    def test_citation_from_markdown_offset_returns_json_anchors(self) -> None:
        bundle = _bundle()
        offset = MARKDOWN.index("Matching is positional")
        citation = citation_from_markdown_offset(
            bundle.crosswalk, offset, artifact_ref="/artifacts/llm.markdown"
        )
        assert citation["representation_kind"] == "llm_markdown"
        assert citation["canonical_representation"] == "structured_json"
        assert citation["page"] == 17
        assert citation["page_range"] == [17, 17]
        assert citation["bbox_anchors"]
        assert all(
            box == [10.0, 20.0, 200.0, 40.0] for box in citation["bbox_anchors"]
        )
        assert citation["canonical_element_ids"]
        assert citation["canonical_evidence_ids"]
        assert all(
            evidence_id.startswith(f"ev:{_doc_id()}")
            for evidence_id in citation["canonical_evidence_ids"]
        )
        # Un offset fuera de toda sección mapeada no produce cita.
        assert citation_from_markdown_offset(bundle.crosswalk, 10_000) == {}
