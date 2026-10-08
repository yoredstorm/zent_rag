# =============================================================================
# Bundle Benchmark — representación dual ODL (offline, sin JVM)
# =============================================================================
# Mide la capa de representación (crosswalk JSON↔Markdown, chunking por
# estructura, quality gates, identidad de evidencia y costo de CPU) sobre
# bundles ya construidos. El parseo real (JVM) queda fuera: si hay Java 11+ el
# caller puede generar bundles con OpenDataLoaderPdfParser y pasarlos acá.
#
# Métricas exigidas por el plan:
#   reading order / heading accuracy / table accuracy  -> checks del bundle y
#     del parser lab existente (comparison); acá se agregan coverage, page
#     mapping, tabla markdown, secciones y chunks.
#   semantic unit quality / premise recall / CanonicalRule precision /
#     false rule rate / citation mapping / answer quality -> se miden con el
#     pipeline canónico en los tests de ingesta (ATPCO obligatorio).
# =============================================================================
from __future__ import annotations

import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from src.knowledge.structure.document_bundle import (
    ParsedDocumentBundle,
    canonical_evidence_id,
)

BUNDLE_BENCHMARK_VERSION = "bundle-benchmark-1"


@dataclass(frozen=True, kw_only=True)
class BundleCase:
    """Caso del benchmark: label + bundle ya construido (JSON + Markdown)."""

    label: str
    bundle: ParsedDocumentBundle
    kind: str = "generic"
    query: str = ""


def measure_bundle(bundle: ParsedDocumentBundle) -> dict[str, Any]:
    """Métricas deterministas de UN bundle (CPU real medida)."""
    started = time.perf_counter()
    chunks = bundle.markdown_chunks()
    latency_ms = (time.perf_counter() - started) * 1000

    crosswalk = bundle.crosswalk
    quality = bundle.quality
    document = bundle.structured_document
    evidence_ids = set(crosswalk.evidence_ids())
    chunk_evidence: set[str] = set()
    for chunk in chunks:
        chunk_evidence.update(chunk.canonical_evidence_ids)
    identity_ok = bool(chunk_evidence) and chunk_evidence.issubset(evidence_ids)
    # No double counting: cada element_id canónico tiene UN evidence id en la
    # metadata (aunque lo referencien JSON y Markdown).
    element_ids = {
        element_id
        for section in crosswalk.sections
        for element_id in section.canonical_element_ids
    }
    expected_evidence = {
        canonical_evidence_id(crosswalk.document_id, element_id)
        for element_id in element_ids
    }
    double_counting_free = len(evidence_ids) == len(expected_evidence)

    chunk_sizes = [len(chunk.text) for chunk in chunks if chunk.text]
    return {
        "representation": {
            "canonical": "structured_json",
            "llm": "llm_markdown",
            "json_bytes": int(
                (bundle.artifacts.get("structured_json").bytes if bundle.artifacts.get("structured_json") else 0)
            ),
            "markdown_bytes": int(
                (bundle.artifacts.get("llm_markdown").bytes if bundle.artifacts.get("llm_markdown") else 0)
            ),
            "fingerprint": bundle.fingerprint,
        },
        "crosswalk": {
            "sections": len(crosswalk.sections),
            "headings_total": crosswalk.headings_total,
            "headings_mapped": crosswalk.headings_mapped,
            "coverage": round(float(crosswalk.coverage), 4),
            "element_coverage": round(float(crosswalk.element_coverage), 4),
            "pages_seen": list(crosswalk.pages_seen[:16]),
            "page_marks_found": int(crosswalk.page_marks_found),
        },
        "quality": quality.to_public_dict(),
        "chunks": {
            "count": len(chunks),
            "avg_chars": round(statistics.fmean(chunk_sizes), 1) if chunk_sizes else 0.0,
            "max_chars": max(chunk_sizes) if chunk_sizes else 0,
            "evidence_identity_ok": bool(identity_ok),
            "double_counting_free": bool(double_counting_free),
        },
        "document": {
            "blocks": len(getattr(document, "blocks", ()) or ()),
            "pages": len(getattr(document, "pages", ()) or ()),
            "sections": len(getattr(document, "sections", ()) or ()),
            "tables": len(getattr(document, "tables", ()) or ()),
        },
        "latency_ms": round(latency_ms, 3),
    }


def run_bundle_benchmark(cases: Sequence[BundleCase]) -> dict[str, Any]:
    """Corre la medición sobre N bundles y agrega resultados."""
    per_case: dict[str, Any] = {}
    for case in cases:
        per_case[case.label] = measure_bundle(case.bundle)
    if not per_case:
        return {
            "version": BUNDLE_BENCHMARK_VERSION,
            "cases": 0,
            "per_case": {},
            "aggregate": {},
        }
    coverages = [item["crosswalk"]["coverage"] for item in per_case.values()]
    promoted = [
        1.0 if item["quality"]["promoted"] else 0.0 for item in per_case.values()
    ]
    citation_ok = [
        1.0 if item["chunks"]["evidence_identity_ok"] else 0.0
        for item in per_case.values()
    ]
    latencies = [item["latency_ms"] for item in per_case.values()]
    return {
        "version": BUNDLE_BENCHMARK_VERSION,
        "cases": len(per_case),
        "per_case": per_case,
        "aggregate": {
            "crosswalk_coverage_avg": round(statistics.fmean(coverages), 4),
            "quality_promoted_rate": round(statistics.fmean(promoted), 4),
            "citation_mapping_ok_rate": round(statistics.fmean(citation_ok), 4),
            "latency_ms_avg": round(statistics.fmean(latencies), 3),
            "double_counting_free_rate": round(
                statistics.fmean(
                    [
                        1.0 if item["chunks"]["double_counting_free"] else 0.0
                        for item in per_case.values()
                    ]
                ),
                4,
            ),
        },
    }


# -----------------------------------------------------------------------------
# Entrada por línea de comandos (fixtures offline del repo)
# -----------------------------------------------------------------------------


def main() -> None:  # pragma: no cover — entrypoint de benchmark
    """Benchmark offline: mide crosswalk sobre fixtures JSON+Markdown si existen."""
    root = Path(__file__).resolve().parents[3]
    fixtures = root / "tests" / "fixtures" / "parser_lab"
    cases: list[BundleCase] = []
    payload = fixtures / "atpco_fare_class.json"
    markdown = fixtures / "atpco_fare_class.llm.md"
    if payload.is_file() and markdown.is_file():
        from uuid import uuid4

        from src.knowledge.structure.document_bundle import (
            build_parsed_document_bundle,
        )
        from src.knowledge.structure.opendataloader_client import (
            OpenDataLoaderConversion,
        )
        from src.knowledge.structure.opendataloader_mapping import (
            OpenDataLoaderMappingContext,
            map_opendataloader_document,
        )

        raw = json.loads(payload.read_text(encoding="utf-8"))
        document = map_opendataloader_document(
            raw,
            context=OpenDataLoaderMappingContext(
                organization_id=uuid4(),
                external_id=payload.name,
                source_name=payload.name,
                page_heights=(792.0, 792.0),
                parser_info={"engine": "opendataloader", "version": "unknown"},
                structure_source="inferred_layout",
                conversion=OpenDataLoaderConversion(data=raw),
            ),
        )
        bundle = build_parsed_document_bundle(
            document,
            conversion=OpenDataLoaderConversion(
                data=raw, markdown=markdown.read_text(encoding="utf-8")
            ),
            parser_info={"engine": "opendataloader", "version": "unknown"},
        )
        cases.append(BundleCase(label="atpco_fare_class", bundle=bundle, kind="atpco"))
    report = run_bundle_benchmark(cases)
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = [
    "BUNDLE_BENCHMARK_VERSION",
    "BundleCase",
    "measure_bundle",
    "run_bundle_benchmark",
]
