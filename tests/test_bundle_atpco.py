# =============================================================================
# Caso ATPCO obligatorio — bundle dual con POSITIONAL_MATCH / MATCH
# =============================================================================
# Con UNA conversión ODL:
#   - JSON permite matching.symbol.&, semántica posicional y length policy
#     (Rule Lane / Premise Closure / decisión).
#   - Markdown contiene una representación legible de la MISMA sección.
#   - Query `&&&F` vs `ABCFGEGE` => POSITIONAL_MATCH / MATCH.
#   - El Personality Composer puede recibir contexto Markdown, sin autoridad.
#   - El Rule Compiler NO crea propiedades desde el Markdown.
#
# ATPCO se usa SOLO como fixture de regresión, nunca como lógica productiva.
# =============================================================================
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from src.intelligence.reasoning.grounded_engine import reason_over_evidence
from src.knowledge.structure.bundle_benchmark import (
    BundleCase,
    measure_bundle,
    run_bundle_benchmark,
)
from src.knowledge.structure.document_bundle import (
    markdown_first_recommended,
    select_markdown_context,
)
from src.knowledge.structure.opendataloader_client import (
    OpenDataLoaderConversion,
    OpenDataLoaderOptions,
)
from src.knowledge.structure.opendataloader_parser import (
    OpenDataLoaderPdfParser,
    PdfProbe,
)
from src.runtime.decision_envelope import build_decision_envelope
from src.runtime.query_local_rules import compile_query_local_rules
from src.runtime.response_composer import RENDER_MODE_POLISH, compose_fast_path_answer

FIXTURES = Path(__file__).parent / "fixtures" / "parser_lab"
ODL_PAYLOAD = json.loads(
    (FIXTURES / "atpco_ampersand_record2.json").read_text(encoding="utf-8")
)
QUESTION = "¿ABCFGEGE cumple el patrón &&&F?"
SECTION_HEADING = "DATA APPLICATION FOR RECORD 2 – CATEGORY CONTROL"
MARKDOWN = f"""# {SECTION_HEADING}

<!-- page:1 -->
The Exclamation Point (!) or Ampersand (&) is used in conjunction with alphanumeric characters in the fare family match process to positionally match fare class characters.

The “!” or “&” indicate a match to any alphanumeric character in that position of the fare class (following the business rules outlined below).

Matching is positional, left to right.

When using special characters “!” or “&”, a fare class must contain at least the number of characters referenced in the fare class field (additional characters may follow).
"""


class _Item:
    """Chunk mínimo desde un bloque del bundle (contrato RetrievalChunk)."""

    def __init__(self, content: str, *, evidence_id: str, document_id: str) -> None:
        self.content = content
        self.evidence_id = evidence_id
        self.source_id = "source-atpco"
        self.document_id = document_id
        self.page = 1
        self.section_path = (SECTION_HEADING,)
        self.metadata = {
            "document_id": document_id,
            "source_id": "source-atpco",
            "page": 1,
            "section_path": [SECTION_HEADING],
        }


def _bundle(tmp_path: Path, *, markdown: str = MARKDOWN):
    def runner(data, *, options, use_struct_tree, workdir):
        return OpenDataLoaderConversion(
            data=ODL_PAYLOAD,
            markdown=markdown,
            output_json_bytes=len(json.dumps(ODL_PAYLOAD)),
            output_markdown_bytes=len(markdown.encode("utf-8")),
            java="17",
        )

    parser = OpenDataLoaderPdfParser(
        options=OpenDataLoaderOptions(formats=("json", "markdown")),
        runner=runner,
        page_probe=lambda path: PdfProbe(page_heights=(792.0,)),
        artifact_root=tmp_path,
    )
    return parser.parse_document(
        b"%PDF-1.4",
        organization_id=uuid4(),
        external_id="record2.pdf",
        source_name="record2.pdf",
    )


def test_atpco_bundle_json_allows_positional_grammar(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    document = bundle.structured_document
    items = [
        _Item(block.text, evidence_id=f"ev:{block.id}", document_id=str(document.id))
        for block in document.blocks
        if str(block.text or "").strip()
    ]
    compilation = compile_query_local_rules(items, document_id=str(document.id))
    executable = [rule for rule in compilation.rules if rule.executable]
    assert executable, "el JSON del bundle debe permitir compilar la gramática"
    assert any(
        "matching.symbol.&" in rule.properties for rule in compilation.rules
    )
    assert any("matching.operator" in rule.properties for rule in compilation.rules)
    assert any("length.policy" in rule.properties for rule in compilation.rules)

    grounded = reason_over_evidence(
        question=QUESTION,
        evidence_items=items,
        canonical_rules=compilation.rules,
    )
    envelope = build_decision_envelope(grounded)
    assert envelope is not None
    assert envelope.operation == "POSITIONAL_MATCH"
    assert envelope.normalized_result == "MATCH"


def test_atpco_markdown_is_legible_and_crosswalked(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    assert bundle.markdown.strip()
    assert "positionally match fare class characters" in bundle.markdown
    crosswalk = bundle.crosswalk
    assert crosswalk.headings_mapped == 1
    assert crosswalk.coverage == 1.0
    assert crosswalk.pages_seen == (1,)
    section = crosswalk.sections[0]
    assert section.heading == SECTION_HEADING
    assert section.canonical_element_ids
    chunks = bundle.markdown_chunks()
    assert chunks
    assert select_markdown_context("¿cómo funciona el matching?", chunks)


def test_atpco_rule_compiler_ignores_markdown_only_text(tmp_path: Path) -> None:
    """Item 14: una frase SOLO presente en Markdown no crea propiedades."""
    injected = (
        "\n## Sección Inventada\n\n"
        "The value must be at least 999 characters for the fare class.\n"
    )
    bundle = _bundle(tmp_path, markdown=MARKDOWN + injected)
    assert "at least 999" in bundle.markdown
    document = bundle.structured_document
    items = [
        _Item(block.text, evidence_id=f"ev:{block.id}", document_id=str(document.id))
        for block in document.blocks
        if str(block.text or "").strip()
    ]
    compilation = compile_query_local_rules(items, document_id=str(document.id))
    serialized = json.dumps(
        [
            {
                "statement": rule.statement,
                "properties": {
                    name: str(getattr(prop, "value", ""))
                    for name, prop in rule.properties.items()
                },
            }
            for rule in compilation.rules
        ],
        ensure_ascii=False,
    )
    assert "999" not in serialized
    assert "Sección Inventada" not in serialized


@dataclass
class _Resp:
    content: str = ""
    model: str = "composer-test"
    prompt_tokens: int = 10
    completion_tokens: int = 5


class _FakeLLM:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0
        self.last_prompt = ""

    async def __call__(self, prompt: str, **kwargs) -> _Resp:
        self.calls += 1
        self.last_prompt = prompt
        return _Resp(content=self.content)


async def test_atpco_composer_uses_markdown_context_without_authority(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    document = bundle.structured_document
    items = [
        _Item(block.text, evidence_id=f"ev:{block.id}", document_id=str(document.id))
        for block in document.blocks
        if str(block.text or "").strip()
    ]
    compilation = compile_query_local_rules(items, document_id=str(document.id))
    grounded = reason_over_evidence(
        question=QUESTION,
        evidence_items=items,
        canonical_rules=compilation.rules,
    )
    envelope = build_decision_envelope(grounded)
    assert envelope is not None

    chunks = select_markdown_context(
        "explícame el matching posicional de la fare class",
        bundle.markdown_chunks(),
    )
    context = "\n\n".join(chunk.text for chunk in chunks)
    assert context

    llm = _FakeLLM("Sí, cumple. El patrón posicional calza con el valor. quedo a disposición.")
    composed = await compose_fast_path_answer(
        envelope=envelope,
        deterministic_answer="Sí, cumple.",
        agent_config={"custom_instructions": "responde amable y simple"},
        message=QUESTION,
        mode=RENDER_MODE_POLISH,
        generate=llm,
        model="composer-test",
        markdown_context=context,
    )
    assert llm.calls == 1
    assert "CONTEXTO DOCUMENTAL" in llm.last_prompt
    assert "fare class characters" in llm.last_prompt
    assert composed.llm_polish is True
    assert composed.answer.startswith("Sí, cumple.")
    # La autoridad sigue siendo el envelope: el Markdown no decide.
    assert envelope.operation == "POSITIONAL_MATCH"
    assert envelope.normalized_result == "MATCH"
    assert markdown_first_recommended("¿qué es el matching posicional?") is True


def test_atpco_bundle_benchmark(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    metrics = measure_bundle(bundle)
    assert metrics["crosswalk"]["coverage"] == 1.0
    assert metrics["crosswalk"]["headings_mapped"] == 1
    assert metrics["quality"]["promoted"] is True
    assert metrics["chunks"]["count"] >= 1
    assert metrics["chunks"]["evidence_identity_ok"] is True
    assert metrics["chunks"]["double_counting_free"] is True
    assert metrics["representation"]["canonical"] == "structured_json"
    assert metrics["representation"]["llm"] == "llm_markdown"

    report = run_bundle_benchmark(
        [BundleCase(label="atpco_record2", bundle=bundle, kind="atpco")]
    )
    assert report["cases"] == 1
    aggregate = report["aggregate"]
    assert aggregate["crosswalk_coverage_avg"] == 1.0
    assert aggregate["quality_promoted_rate"] == 1.0
    assert aggregate["citation_mapping_ok_rate"] == 1.0
    assert aggregate["double_counting_free_rate"] == 1.0
    assert aggregate["latency_ms_avg"] >= 0
