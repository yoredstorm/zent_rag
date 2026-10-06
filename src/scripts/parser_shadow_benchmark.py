# =============================================================================
# Parser Lab — benchmark shadow pdfplumber vs OpenDataLoader
# =============================================================================
# Uso:
#   python -m src.scripts.parser_shadow_benchmark PDF... [--out DIR]
#       [--engines both|pdfplumber|opendataloader] [--no-knowledge]
#       [--expectations FILE.json] [--java PATH]
#
# Corre, por documento:
#   1. ambos parsers -> StructuredDocument
#   2. comparación estructural (DocumentParserComparison)
#   3. Knowledge A/B offline (misma cadena, sin persistencia)
#   4. reporte de cobertura por parser
#   5. performance (segundos, s/página, JSON bytes, memoria Python)
# Nada escribe en Postgres ni Qdrant. Termina sin declarar ganador: Fase 2.
# =============================================================================
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
import tracemalloc
from io import BytesIO
from pathlib import Path
from typing import Any, Callable
from uuid import UUID, uuid4

from src.knowledge.parser_lab.comparison import compare_documents, side_metrics
from src.knowledge.parser_lab.knowledge_ab import (
    compare_knowledge_sides,
    run_offline_knowledge,
)
from src.knowledge.parser_lab.report import (
    build_coverage_report,
    render_report_text,
    write_report,
)
from src.knowledge.structure.opendataloader_client import availability
from src.knowledge.structure.opendataloader_parser import OpenDataLoaderPdfParser
from src.knowledge.structure.pdf_engine import options_from_settings
from src.knowledge.structure.pdf_parser import PdfParseOptions, PdfParser


def _timed(call: Callable[[], Any]) -> tuple[Any, float, int]:
    tracemalloc.start()
    started = time.perf_counter()
    result = call()
    elapsed = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return result, elapsed, peak


def _reference_text(data: bytes) -> str:
    """Texto crudo pdfplumber de referencia para lost-text."""
    try:
        import pdfplumber

        with pdfplumber.open(BytesIO(data)) as pdf:
            return "\n".join(
                (page.extract_text() or "") for page in pdf.pages
            )
    except Exception:  # noqa: BLE001 — referencia best-effort
        return ""


def _doc_summary(document) -> dict[str, Any]:
    parser_info = document.metadata.get("parser") or {}
    return {
        "pages": document.page_count,
        "blocks": document.block_count,
        "sections": document.section_count,
        "tables": document.table_count,
        "figures": document.figure_count,
        "content_hash": document.content_hash,
        "parser": parser_info,
        "structure_source": document.metadata.get("structure_source"),
        "parser_warnings": list(document.metadata.get("parser_warnings") or []),
    }


def _parse_pdfplumber(
    data: bytes,
    external_id: str,
    *,
    organization_id: UUID,
    source_id: UUID,
):
    parser = PdfParser()
    return parser.parse(
        data,
        organization_id=organization_id,
        external_id=external_id,
        source_id=source_id,
        source_name=external_id,
        options=PdfParseOptions(column_detection=True),
    )


def _parse_opendataloader(
    data: bytes,
    external_id: str,
    *,
    organization_id: UUID,
    source_id: UUID,
    odl_options,
):
    parser = OpenDataLoaderPdfParser(options=odl_options)
    return parser.parse(
        data,
        organization_id=organization_id,
        external_id=external_id,
        source_id=source_id,
        source_name=external_id,
    )


def benchmark_document(
    path: Path,
    *,
    engines: list[str],
    run_knowledge: bool,
    expectations: dict[str, Any] | None,
    odl_options,
    organization_id: UUID,
) -> dict[str, Any]:
    data = path.read_bytes()
    source_id = uuid4()
    reference = _reference_text(data)
    report: dict[str, Any] = {
        "file": str(path),
        "bytes": len(data),
        "engines": {},
        "errors": {},
    }

    documents: dict[str, Any] = {}
    for engine in engines:
        try:
            if engine == "pdfplumber":
                document, elapsed, peak = _timed(
                    lambda: _parse_pdfplumber(
                        data,
                        path.name,
                        organization_id=organization_id,
                        source_id=source_id,
                    )
                )
            else:
                document, elapsed, peak = _timed(
                    lambda: _parse_opendataloader(
                        data,
                        path.name,
                        organization_id=organization_id,
                        source_id=source_id,
                        odl_options=odl_options,
                    )
                )
            documents[engine] = document
            report["engines"][engine] = {
                "seconds": round(elapsed, 4),
                "seconds_per_page": (
                    round(elapsed / document.page_count, 5) if document.page_count else None
                ),
                "peak_python_bytes": peak,
                "document": _doc_summary(document),
            }
        except Exception as exc:  # noqa: BLE001 — un motor roto no tumba el reporte
            report["errors"][engine] = str(exc)[:500]

    if len(documents) == 2:
        labels = tuple(report["engines"].keys())
        docs = list(documents.values())
        comparison = compare_documents(
            docs[0], docs[1], labels=labels, reference_text=reference
        )
        report["comparison"] = comparison
    report["structural_sides"] = {
        label: side_metrics(document, label=label, reference_text=reference)
        for label, document in documents.items()
    }
    if run_knowledge:
        sides: dict[str, Any] = {}
        report["coverage_reports"] = {}
        for label, document in documents.items():
            side = run_offline_knowledge(
                document, label=label, expectations=expectations
            )
            sides[label] = side
            coverage = build_coverage_report(
                label=label,
                document=document,
                knowledge=side,
                structural=report["structural_sides"].get(label),
            )
            report["coverage_reports"][label] = coverage
            if engine_report := report["engines"].get(label):
                engine_report["coverage"] = {
                    key: coverage[key]
                    for key in (
                        "semantic_units",
                        "definitions",
                        "facts",
                        "rules",
                        "supported_rules",
                        "executable_rules",
                        "relationships",
                    )
                }
        report["knowledge_sides"] = {
            label: {
                "counts": side.counts,
                "quality": side.quality,
                "threads": side.threads,
                "premise_dimensions": side.premise_dimensions,
            }
            for label, side in sides.items()
        }
        if len(sides) == 2:
            labels = tuple(sides.keys())
            report["knowledge"] = compare_knowledge_sides(
                sides[labels[0]], sides[labels[1]]
            )
    return report


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Parser Shadow Benchmark",
        "",
        "> Fase 1: comparación, no veredicto. OpenDataLoader no reemplaza a pdfplumber todavía.",
        "",
    ]
    for document in report.get("documents") or []:
        lines.append(f"## {document['file']}")
        lines.append("")
        lines.append("| motor | s | s/pág | bloques | tablas | secciones | warnings |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
        for engine, data in (document.get("engines") or {}).items():
            summary = data.get("document") or {}
            lines.append(
                f"| {engine} | {data['seconds']} | {data['seconds_per_page']} | "
                f"{summary.get('blocks')} | {summary.get('tables')} | "
                f"{summary.get('sections')} | "
                f"{len(summary.get('parser_warnings') or [])} |"
            )
        for engine, error in (document.get("errors") or {}).items():
            lines.append(f"| {engine} | error: {error} |" )
        if document.get("comparison"):
            summary = document["comparison"]["summary"]
            lines.append("")
            lines.append(
                "Comparación: blocks "
                f"{summary['blocks_ratio']['a']} vs {summary['blocks_ratio']['b']}, "
                f"tables {summary['tables_ratio']['a']} vs {summary['tables_ratio']['b']}, "
                f"bbox {summary['bbox_coverage']['a']} vs {summary['bbox_coverage']['b']}, "
                f"missing_chars {summary['missing_reference_chars']['a']} vs "
                f"{summary['missing_reference_chars']['b']}"
            )
        if document.get("knowledge"):
            counts = document["knowledge"]["counts"]
            lines.append("")
            lines.append("| métrica | pdfplumber | opendataloader |")
            lines.append("| --- | ---: | ---: |")
            for key in (
                "semantic_units_count",
                "definitions_count",
                "facts_count",
                "rules_count",
                "canonical_rules_count",
                "supported_rules_count",
                "executable_rules_count",
                "relationships_count",
                "semantic_threads_count",
            ):
                delta = counts.get(key) or {}
                lines.append(f"| {key} | {delta.get('a')} | {delta.get('b')} |")
        elif document.get("knowledge_sides"):
            lines.append("")
            lines.append("| métrica | " + " | ".join(document["knowledge_sides"]) + " |")
            lines.append("| --- |" + " ---: |" * len(document["knowledge_sides"]))
            for key in (
                "semantic_units_count",
                "definitions_count",
                "facts_count",
                "rules_count",
                "canonical_rules_count",
                "supported_rules_count",
                "executable_rules_count",
                "semantic_threads_count",
            ):
                values = [
                    str(side["counts"].get(key))
                    for side in document["knowledge_sides"].values()
                ]
                lines.append(f"| {key} | " + " | ".join(values) + " |")
        lines.append("")
    if report.get("performance"):
        lines.append("## Performance")
        lines.append("")
        lines.append(json.dumps(report["performance"], ensure_ascii=False, indent=2))
    return "\n".join(lines)


def _collect_pdfs(inputs: list[str], limit: int | None) -> list[Path]:
    paths: list[Path] = []
    for raw in inputs:
        path = Path(raw)
        if path.is_dir():
            paths.extend(sorted(path.rglob("*.pdf")))
        elif path.is_file() and path.suffix.lower() == ".pdf":
            paths.append(path)
        else:
            print(f"ignorado (no es PDF ni directorio): {path}", file=sys.stderr)
    if limit is not None:
        paths = paths[:limit]
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark shadow pdfplumber vs OpenDataLoader (sin persistencia)."
    )
    parser.add_argument("pdfs", nargs="+")
    parser.add_argument("--out", type=Path, default=Path("data/reports/parser_shadow"))
    parser.add_argument(
        "--engines",
        choices=("both", "pdfplumber", "opendataloader"),
        default="both",
    )
    parser.add_argument("--no-knowledge", action="store_true")
    parser.add_argument("--expectations", type=Path, default=None)
    parser.add_argument("--java", default=None, help="binario java 11+ para OpenDataLoader")
    parser.add_argument("--limit", type=int, default=None)
    # Variantes Fase 2: permiten correr cluster/hybrid/struct-tree sin editar .env.
    parser.add_argument(
        "--odl-table-method",
        choices=("default", "cluster"),
        default=None,
        help="Detección de tablas de OpenDataLoader (default | cluster).",
    )
    parser.add_argument(
        "--odl-mode",
        choices=("local", "hybrid"),
        default=None,
        help="Modo OpenDataLoader. hybrid requiere servidor hybrid aparte.",
    )
    parser.add_argument("--odl-hybrid-url", default=None)
    parser.add_argument(
        "--odl-use-struct-tree",
        choices=("auto", "always", "never"),
        default=None,
    )
    args = parser.parse_args(argv)

    pdfs = _collect_pdfs(list(args.pdfs), args.limit)
    if not pdfs:
        print("no hay PDFs de entrada", file=sys.stderr)
        return 2

    engines = (
        ["pdfplumber", "opendataloader"] if args.engines == "both" else [args.engines]
    )
    odl_options = None
    if "opendataloader" in engines:
        try:
            from src.core.config import get_settings

            settings = get_settings()
        except Exception:  # noqa: BLE001 — benchmark sin entorno completo
            settings = None
        odl_options = options_from_settings(settings if settings is not None else object())
        if args.java:
            odl_options = dataclasses.replace(odl_options, java=args.java)
        if args.odl_table_method:
            odl_options = dataclasses.replace(
                odl_options, table_method=args.odl_table_method
            )
        if args.odl_mode:
            odl_options = dataclasses.replace(odl_options, mode=args.odl_mode)
        if args.odl_hybrid_url:
            odl_options = dataclasses.replace(odl_options, hybrid_url=args.odl_hybrid_url)
        if args.odl_use_struct_tree:
            policy = args.odl_use_struct_tree
            odl_options = dataclasses.replace(
                odl_options,
                use_struct_tree=None if policy == "auto" else policy == "always",
            )
        status = availability(odl_options)
        if not status["ready"]:
            if args.engines == "both":
                print(
                    f"OpenDataLoader no disponible ({status['reason']}); "
                    "se corre solo pdfplumber",
                    file=sys.stderr,
                )
                engines = ["pdfplumber"]
                odl_options = None
            else:
                print(f"OpenDataLoader no disponible: {status['reason']}", file=sys.stderr)
                return 2

    expectations = None
    if args.expectations and args.expectations.is_file():
        expectations = json.loads(args.expectations.read_text(encoding="utf-8"))

    organization_id = uuid4()
    documents: list[dict[str, Any]] = []
    started = time.perf_counter()
    for path in pdfs:
        print(f"[benchmark] {path}")
        documents.append(
            benchmark_document(
                path,
                engines=engines,
                run_knowledge=not args.no_knowledge,
                expectations=expectations,
                odl_options=odl_options,
                organization_id=organization_id,
            )
        )
    total_seconds = time.perf_counter() - started

    report = {
        "schema": "zent.parser_shadow_benchmark.1",
        "engines": engines,
        "knowledge": not args.no_knowledge,
        "odl_options": odl_options.fingerprint() if odl_options is not None else None,
        "documents": documents,
        "performance": {
            "documents": len(pdfs),
            "total_seconds": round(total_seconds, 3),
            "documents_per_minute": (
                round(len(pdfs) * 60 / total_seconds, 2) if total_seconds else None
            ),
        },
    }
    args.out.mkdir(parents=True, exist_ok=True)
    write_report(args.out / "report.json", report)
    (args.out / "report.md").write_text(_render_markdown(report), encoding="utf-8")
    for document in documents:
        for coverage in (document.get("coverage_reports") or {}).values():
            print(render_report_text(coverage))
    print(f"reporte en {args.out / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
