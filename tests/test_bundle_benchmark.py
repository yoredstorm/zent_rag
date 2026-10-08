# =============================================================================
# Bundle Benchmark offline — fixtures JSON+Markdown sin JVM
# =============================================================================
# Mide crosswalk, quality gates, chunking, identidad de evidencia y latencia
# sobre el fixture ATPCO (JSON de OpenDataLoader + proyección Markdown).
# =============================================================================
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from src.knowledge.structure.bundle_benchmark import (
    BundleCase,
    measure_bundle,
    run_bundle_benchmark,
)
from src.knowledge.structure.document_bundle import build_parsed_document_bundle
from src.knowledge.structure.opendataloader_client import OpenDataLoaderConversion
from src.knowledge.structure.opendataloader_mapping import (
    OpenDataLoaderMappingContext,
    map_opendataloader_document,
)

FIXTURES = Path(__file__).parent / "fixtures" / "parser_lab"


def _fixture_bundle():
    payload = json.loads(
        (FIXTURES / "atpco_fare_class.json").read_text(encoding="utf-8")
    )
    markdown = (FIXTURES / "atpco_fare_class.llm.md").read_text(encoding="utf-8")
    document = map_opendataloader_document(
        payload,
        context=OpenDataLoaderMappingContext(
            organization_id=uuid4(),
            external_id="atpco_fare_class.json",
            source_name="atpco_fare_class.json",
            page_heights=(792.0, 792.0),
            parser_info={"engine": "opendataloader", "version": "2.5.12"},
            structure_source="inferred_layout",
            conversion=OpenDataLoaderConversion(data=payload),
        ),
    )
    return build_parsed_document_bundle(
        document,
        conversion=OpenDataLoaderConversion(data=payload, markdown=markdown),
        parser_info={
            "engine": "opendataloader",
            "version": "2.5.12",
            "options": {"table_method": "default", "formats": ["json", "markdown"]},
        },
    )


class TestBundleBenchmarkFixture:
    def test_measure_bundle_reports_representation_metrics(self) -> None:
        bundle = _fixture_bundle()
        metrics = measure_bundle(bundle)
        assert metrics["representation"]["canonical"] == "structured_json"
        assert metrics["representation"]["llm"] == "llm_markdown"
        assert metrics["crosswalk"]["sections"] >= 1
        assert metrics["crosswalk"]["coverage"] >= 0.6
        assert metrics["crosswalk"]["headings_mapped"] >= 1
        assert metrics["quality"]["promoted"] is True
        assert metrics["chunks"]["count"] >= 1
        assert metrics["chunks"]["evidence_identity_ok"] is True
        assert metrics["chunks"]["double_counting_free"] is True
        assert metrics["document"]["pages"] == 2
        assert metrics["latency_ms"] >= 0

    def test_run_bundle_benchmark_aggregates(self) -> None:
        bundle = _fixture_bundle()
        report = run_bundle_benchmark(
            [
                BundleCase(label="atpco_fare_class", bundle=bundle, kind="atpco"),
            ]
        )
        assert report["cases"] == 1
        aggregate = report["aggregate"]
        assert aggregate["crosswalk_coverage_avg"] >= 0.6
        assert aggregate["quality_promoted_rate"] == 1.0
        assert aggregate["citation_mapping_ok_rate"] == 1.0
        assert aggregate["double_counting_free_rate"] == 1.0

    def test_citation_resolves_markdown_section_to_json(self) -> None:
        from src.knowledge.structure.document_bundle import (
            citation_from_markdown_offset,
        )

        bundle = _fixture_bundle()
        offset = bundle.markdown.index("Fare class &F1 must be issued")
        citation = citation_from_markdown_offset(bundle.crosswalk, offset)
        assert citation
        assert citation["canonical_representation"] == "structured_json"
        assert citation["page"] == 1
        assert citation["page_range"] == [1, 1]
        assert citation["canonical_element_ids"]
        assert citation["canonical_evidence_ids"]
