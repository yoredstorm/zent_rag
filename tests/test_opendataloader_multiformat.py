# =============================================================================
# OpenDataLoader multi-format — UNA conversión: JSON canónico + Markdown LLM
# =============================================================================
# Contrato:
#   1. `--format json,markdown` viaja en UN solo comando (una sola JVM).
#   2. El reader acepta JSON obligatorio + markdown/html opcionales.
#   3. `convert_pdf_to_json` conserva el comportamiento JSON-only.
#   4. El parser devuelve StructuredDocument (contrato) con metadata liviana
#      de representaciones; `parse_document` devuelve el bundle completo.
#   5. El probe usa pdfminer (sin pdfplumber).
# =============================================================================
from __future__ import annotations

import inspect
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.knowledge.structure import opendataloader_client as client_module
from src.knowledge.structure.base import StructuredParserError
from src.knowledge.structure.document_bundle import (
    STORAGE_ARTIFACT,
)
from src.knowledge.structure.opendataloader_client import (
    OpenDataLoaderConversion,
    OpenDataLoaderOptions,
    _build_command,
    _read_output_artifacts,
    convert_pdf_to_json,
)
from src.knowledge.structure.opendataloader_parser import (
    OpenDataLoaderPdfParser,
    PdfProbe,
    probe_pdf,
)

FIXTURES = Path(__file__).parent / "fixtures" / "parser_lab"
ODL_PAYLOAD = json.loads(
    (FIXTURES / "atpco_ampersand_record2.json").read_text(encoding="utf-8")
)
SECTION_HEADING = "DATA APPLICATION FOR RECORD 2 – CATEGORY CONTROL"
ODL_MARKDOWN = f"""# {SECTION_HEADING}

<!-- page:1 -->
The Exclamation Point (!) or Ampersand (&) is used in conjunction with alphanumeric characters in the fare family match process to positionally match fare class characters.

The “!” or “&” indicate a match to any alphanumeric character in that position of the fare class (following the business rules outlined below).

Matching is positional, left to right.

When using special characters “!” or “&”, a fare class must contain at least the number of characters referenced in the fare class field (additional characters may follow).
"""


def _command(**overrides) -> list[str]:
    defaults = dict(
        java="java",
        jar="odl.jar",
        pdf_path=Path("input.pdf"),
        output_dir=Path("out"),
        options=overrides.pop("options", OpenDataLoaderOptions(formats=("json", "markdown"))),
        use_struct_tree=False,
    )
    defaults.update(overrides)
    return _build_command(**defaults)


class TestSingleConversionCommand:
    def test_json_and_markdown_in_one_command(self) -> None:
        command = _command()
        assert command[command.index("--format") + 1] == "json,markdown"
        assert command[command.index("--markdown-page-separator") + 1] == (
            "<!-- page:%%page-number%% -->"
        )
        assert "--markdown-with-html" not in command

    def test_markdown_with_html_is_opt_in(self) -> None:
        command = _command(
            options=OpenDataLoaderOptions(
                formats=("json", "markdown"), markdown_with_html=True
            )
        )
        assert "--markdown-with-html" in command

    def test_json_only_has_no_markdown_flags(self) -> None:
        command = _command(options=OpenDataLoaderOptions())
        assert command[command.index("--format") + 1] == "json"
        assert "--markdown-page-separator" not in command
        assert "--markdown-with-html" not in command

    def test_resolved_formats_keeps_json_first_and_drops_invalid(self) -> None:
        options = OpenDataLoaderOptions(formats=("markdown", "json", "invented", "markdown"))
        assert options.resolved_formats() == ("json", "markdown")
        assert OpenDataLoaderOptions(formats=()).resolved_formats() == ("json",)
        assert OpenDataLoaderOptions(formats=("markdown",)).resolved_formats() == (
            "json",
            "markdown",
        )

    def test_options_fingerprint_includes_representation_flags(self) -> None:
        fingerprint = OpenDataLoaderOptions(
            formats=("json", "markdown"), markdown_with_html=True
        ).fingerprint()
        assert fingerprint["formats"] == ["json", "markdown"]
        assert fingerprint["markdown_with_html"] is True
        assert fingerprint["markdown_page_separator"]


class TestArtifactReader:
    def _prepare(self, tmp_path: Path, *, markdown: bool = True, html: bool = False):
        (tmp_path / "input.json").write_text('{"kids": []}', encoding="utf-8")
        if markdown:
            (tmp_path / "input.md").write_text("# Sección\n", encoding="utf-8")
        if html:
            (tmp_path / "input.html").write_text("<h1>Sección</h1>", encoding="utf-8")

    def test_reads_all_artifacts_of_one_run(self, tmp_path: Path) -> None:
        self._prepare(tmp_path, html=True)
        (
            payload,
            json_bytes,
            json_path,
            markdown,
            markdown_bytes,
            markdown_path,
            html,
            html_bytes,
            html_path,
        ) = _read_output_artifacts(tmp_path, Path("input.pdf"))
        assert payload == {"kids": []}
        assert json_bytes > 0 and json_path.endswith("input.json")
        assert markdown.startswith("# Sección") and markdown_bytes > 0
        assert markdown_path.endswith("input.md")
        assert html.startswith("<h1>") and html_bytes > 0
        assert html_path.endswith("input.html")

    def test_markdown_missing_is_not_fatal(self, tmp_path: Path) -> None:
        self._prepare(tmp_path, markdown=False)
        result = _read_output_artifacts(tmp_path, Path("input.pdf"))
        payload, _json_bytes, _json_path, markdown, markdown_bytes, markdown_path = result[:6]
        assert payload == {"kids": []}
        assert markdown == "" and markdown_bytes == 0 and markdown_path is None

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        (tmp_path / "input.json").write_text("{not-json", encoding="utf-8")
        with pytest.raises(StructuredParserError):
            _read_output_artifacts(tmp_path, Path("input.pdf"))


class TestConvertPdf:
    def test_single_subprocess_produces_json_and_markdown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[list[str]] = []

        def fake_run(command, **kwargs):
            calls.append(list(command))
            output_dir = Path(command[command.index("--output-dir") + 1])
            (output_dir / "input.json").write_text('{"kids": [1]}', encoding="utf-8")
            (output_dir / "input.md").write_text("# Título\n\nCuerpo.", encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        # El test es unitario: el jar empaquetado (extra pdf-odl) no es necesario.
        fake_resources = SimpleNamespace(
            files=lambda package: SimpleNamespace(
                joinpath=lambda *parts: Path("odl.jar")
            ),
            as_file=lambda ref: nullcontext(Path("odl.jar")),
        )
        monkeypatch.setattr(client_module, "resources", fake_resources)
        monkeypatch.setattr(client_module, "resolve_java", lambda options: ("java", 17))
        monkeypatch.setattr(client_module.subprocess, "run", fake_run)

        conversion = client_module.convert_pdf(
            b"%PDF-1.4",
            options=OpenDataLoaderOptions(formats=("json", "markdown")),
            workdir=tmp_path,
        )
        assert len(calls) == 1
        assert "--format" in calls[0] and "json,markdown" in calls[0]
        assert conversion.data == {"kids": [1]}
        assert conversion.markdown.startswith("# Título")
        assert conversion.has_markdown is True
        assert conversion.output_markdown_bytes > 0
        assert conversion.output_json_bytes > 0

    def test_convert_pdf_to_json_forces_json_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict = {}

        def fake_convert(data, *, options, use_struct_tree=False, workdir=None):
            captured["formats"] = options.formats
            return OpenDataLoaderConversion(data={"kids": []})

        monkeypatch.setattr(client_module, "convert_pdf", fake_convert)
        conversion = convert_pdf_to_json(
            b"%PDF", options=OpenDataLoaderOptions(formats=("json", "markdown"))
        )
        assert captured["formats"] == ("json",)
        assert conversion.data == {"kids": []}


class TestParserBundle:
    def _parser(self, tmp_path: Path, *, calls: list) -> OpenDataLoaderPdfParser:
        def runner(data, *, options, use_struct_tree, workdir):
            calls.append(options)
            return OpenDataLoaderConversion(
                data=ODL_PAYLOAD,
                markdown=ODL_MARKDOWN,
                output_json_bytes=len(json.dumps(ODL_PAYLOAD)),
                output_markdown_bytes=len(ODL_MARKDOWN.encode("utf-8")),
                java="17",
            )

        return OpenDataLoaderPdfParser(
            options=OpenDataLoaderOptions(formats=("json", "markdown")),
            runner=runner,
            page_probe=lambda path: PdfProbe(page_heights=(792.0,)),
            artifact_root=tmp_path,
        )

    def test_one_conversion_builds_bundle_and_places_artifacts(
        self, tmp_path: Path
    ) -> None:
        calls: list = []
        parser = self._parser(tmp_path, calls=calls)
        org = uuid4()
        bundle = parser.parse_document(
            b"%PDF-1.4",
            organization_id=org,
            external_id="atpco.pdf",
            source_name="atpco.pdf",
        )
        assert len(calls) == 1  # UNA sola conversión
        assert bundle.canonical is not None
        assert bundle.markdown.strip()
        assert bundle.quality.promoted is True
        assert bundle.crosswalk.coverage > 0.6
        # Crosswalk: el heading del fixture mapea a la sección canónica.
        assert bundle.crosswalk.headings_mapped == 1

        document = bundle.structured_document
        folder = tmp_path / str(org) / "representations" / str(document.id)
        assert (folder / "llm.markdown").is_file()
        assert (folder / "canonical.json").is_file()
        assert (folder / "crosswalk.json").is_file()

        representations = document.metadata["representations"]
        markdown_artifact = representations["llm_markdown"]
        assert markdown_artifact["storage"] == STORAGE_ARTIFACT
        assert markdown_artifact["ref"].endswith("llm.markdown")
        assert markdown_artifact["content_hash"] == bundle.markdown_hash
        # Metadata liviana: el markdown NO viaja en el StructuredDocument.
        serialized = json.dumps(document.metadata, ensure_ascii=False)
        assert "positionally match fare class characters" not in serialized
        assert representations["quality"]["promoted"] is True

    def test_parse_returns_structured_document_contract(self, tmp_path: Path) -> None:
        calls: list = []
        parser = self._parser(tmp_path, calls=calls)
        document = parser.parse(
            b"%PDF-1.4",
            organization_id=uuid4(),
            external_id="atpco.pdf",
            source_name="atpco.pdf",
        )
        assert document.external_id == "atpco.pdf"
        assert document.blocks
        assert "representations" in document.metadata
        assert len(calls) == 1

    def test_bundle_chunks_carry_canonical_evidence(self, tmp_path: Path) -> None:
        parser = self._parser(tmp_path, calls=[])
        bundle = parser.parse_document(
            b"%PDF-1.4",
            organization_id=uuid4(),
            external_id="atpco.pdf",
            source_name="atpco.pdf",
        )
        chunks = bundle.markdown_chunks()
        assert chunks
        known = set(bundle.crosswalk.evidence_ids())
        for chunk in chunks:
            assert set(chunk.canonical_evidence_ids) <= known
            assert chunk.page_start == 1


class TestSettingsAndProvenance:
    def test_options_from_settings_enables_markdown_by_default(self) -> None:
        from src.knowledge.structure.pdf_engine import options_from_settings

        settings = SimpleNamespace(
            ODL_USE_STRUCT_TREE="auto",
            ODL_LLM_MARKDOWN=True,
            ODL_MARKDOWN_PAGE_SEPARATOR="<!-- page:%%page-number%% -->",
            ODL_MARKDOWN_WITH_HTML=False,
        )
        options = options_from_settings(settings)
        assert options.resolved_formats() == ("json", "markdown")
        assert options.wants_markdown is True

        settings_off = SimpleNamespace(
            ODL_USE_STRUCT_TREE="never", ODL_LLM_MARKDOWN=False
        )
        assert options_from_settings(settings_off).resolved_formats() == ("json",)

    def test_stamp_provenance_includes_representation_summary(
        self, tmp_path: Path
    ) -> None:
        from src.knowledge.structure.pdf_engine import stamp_parser_provenance

        parser = TestParserBundle()._parser(tmp_path, calls=[])
        bundle = parser.parse_document(
            b"%PDF-1.4",
            organization_id=uuid4(),
            external_id="atpco.pdf",
            source_name="atpco.pdf",
        )
        stamped = stamp_parser_provenance(bundle.structured_document, parser=parser)
        summary = stamped.metadata["document_parser"]["representations"]
        assert summary["canonical"] == "structured_json"
        assert summary["llm_markdown"] is True
        assert summary["quality_promoted"] is True
        assert summary["crosswalk_coverage"] > 0

    def test_api_parser_payload_exposes_representations(self, tmp_path: Path) -> None:
        from src.api.routes.sources import _parser_payload
        from src.knowledge.structure.pdf_engine import stamp_parser_provenance

        parser = TestParserBundle()._parser(tmp_path, calls=[])
        bundle = parser.parse_document(
            b"%PDF-1.4",
            organization_id=uuid4(),
            external_id="atpco.pdf",
            source_name="atpco.pdf",
        )
        stamped = stamp_parser_provenance(bundle.structured_document, parser=parser)
        payload = _parser_payload(stamped.metadata)
        assert payload is not None
        assert payload["engine"] == "opendataloader"
        representations = payload["representations"]
        assert representations["canonical"] == "structured_json"
        assert representations["structured_json"] is True
        assert representations["llm_markdown"] is True
        assert representations["original_pdf"] is True
        assert representations["markdown_ref"].endswith("llm.markdown")


class TestPdfminerProbe:
    def test_probe_does_not_import_pdfplumber(self) -> None:
        source = inspect.getsource(probe_pdf)
        assert "import pdfplumber" not in source
        assert "pdfminer" in source

    def test_junk_bytes_return_empty_probe(self, tmp_path: Path) -> None:
        path = tmp_path / "junk.pdf"
        path.write_bytes(b"not a pdf at all")
        probe = probe_pdf(path)
        assert probe.page_heights == ()
        assert probe.has_structure_tree is False

    def test_minimal_pdf_heights_and_struct_tree(self, tmp_path: Path) -> None:
        untagged = tmp_path / "untagged.pdf"
        untagged.write_bytes(_minimal_pdf(tagged=False))
        probe = probe_pdf(untagged)
        assert probe.page_heights == (792.0,)
        assert probe.has_structure_tree is False

        tagged = tmp_path / "tagged.pdf"
        tagged.write_bytes(_minimal_pdf(tagged=True))
        probe = probe_pdf(tagged)
        assert probe.page_heights == (792.0,)
        assert probe.has_structure_tree is True


def _minimal_pdf(*, tagged: bool) -> bytes:
    """PDF mínimo válido (1 página, MediaBox 612x792, StructTreeRoot opcional)."""
    catalog = b"<< /Type /Catalog /Pages 2 0 R"
    if tagged:
        catalog += b" /StructTreeRoot 5 0 R"
    catalog += b" >>"
    page = (
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 6 0 R >> >> >>"
    )
    stream = b"BT /F1 12 Tf 72 720 Td (Hello) Tj ET"
    objects = [
        catalog,
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        page,
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    if tagged:
        objects.append(b"<< /Type /StructTreeRoot /K [] >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_offset = len(out)
    count = len(objects) + 1
    out += f"xref\n0 {count}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n"
        f"{xref_offset}\n%%EOF\n"
    ).encode()
    return bytes(out)
