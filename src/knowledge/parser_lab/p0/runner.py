# =============================================================================
# P0 — Runner del benchmark de conocimiento PDF
# =============================================================================
# Por documento: parse A (pdfplumber) / B (ODL local) / C opcional (ODL hybrid),
# misma cadena Knowledge OS offline, métricas golden, retrieval, decisión,
# consistencia, KnowledgeDiff y visual debug. Nada persiste.
# =============================================================================
from __future__ import annotations

import dataclasses
import json
import time
import tracemalloc
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID

from src.knowledge.parser_lab.p0 import report as report_mod
from src.knowledge.parser_lab.p0.corpus import (
    CORPUS,
    CorpusDoc,
    build_corpus_pdf,
    golden_for,
)
from src.knowledge.parser_lab.p0.diff import knowledge_diff
from src.knowledge.parser_lab.p0.evaluate import all_static_metrics
from src.knowledge.parser_lab.p0.runtime_eval import runtime_metrics
from src.knowledge.parser_lab.p0.scoring import knowledge_completeness_score
from src.knowledge.parser_lab.p0.state import KnowledgeState
from src.knowledge.parser_lab.p0.visual import write_visual_debug
from src.knowledge.structure.opendataloader_client import OpenDataLoaderOptions
from src.knowledge.structure.opendataloader_parser import OpenDataLoaderPdfParser
from src.knowledge.structure.pdf_engine import options_from_settings
from src.knowledge.structure.pdf_parser import PdfParseOptions, PdfParser

_ORG_ID = UUID("00000000-0000-0000-0000-00000000ab01")


@dataclass
class BenchConfig:
    out_dir: Path = Path("artifacts/pdf-parser-benchmark")
    java: str = ""
    hybrid: bool = False
    hybrid_url: str = ""
    consistency_runs: int = 100
    docs: tuple[str, ...] = ()
    large_pages: int = 0
    visual: bool = True


def _odl_options(config: BenchConfig, *, hybrid: bool) -> OpenDataLoaderOptions:
    try:
        from src.core.config import get_settings

        settings = get_settings()
    except Exception:  # noqa: BLE001 — benchmark sin entorno completo
        settings = object()
    options = options_from_settings(settings)
    if config.java:
        options = dataclasses.replace(options, java=config.java)
    if hybrid:
        options = dataclasses.replace(
            options,
            mode="hybrid",
            hybrid_url=config.hybrid_url or options.hybrid_url,
        )
    return options


def _raw_reference(data: bytes) -> str:
    try:
        import pdfplumber

        with pdfplumber.open(BytesIO(data)) as pdf:
            return "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception:  # noqa: BLE001 — referencia best-effort
        return ""


def _timed_parse(parse_callable) -> tuple[Any, float, int]:
    tracemalloc.start()
    started = time.perf_counter()
    document = parse_callable()
    elapsed = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return document, elapsed, peak


def _parse_pdfplumber(data: bytes, name: str) -> Any:
    return PdfParser().parse(
        data,
        organization_id=_ORG_ID,
        external_id=name,
        source_name=name,
        options=PdfParseOptions(column_detection=True),
    )


def _parse_odl(data: bytes, name: str, options: OpenDataLoaderOptions) -> Any:
    return OpenDataLoaderPdfParser(options=options).parse(
        data,
        organization_id=_ORG_ID,
        external_id=name,
        source_name=name,
    )


def _performance(document: Any, elapsed: float, peak: int) -> dict[str, Any]:
    parser_meta = document.metadata.get("parser") or {}
    conversion = parser_meta.get("conversion") or {}
    pages = max(document.page_count, 1)
    return {
        "seconds": round(elapsed, 4),
        "seconds_per_page": round(elapsed / pages, 5),
        "peak_python_bytes": peak,
        "pages": document.page_count,
        "json_bytes": conversion.get("output_json_bytes"),
        "java": conversion.get("java"),
    }


async def run_document(
    doc: CorpusDoc,
    *,
    config: BenchConfig,
    pages: int | None = None,
    suffix: str = "",
) -> dict[str, Any]:
    page_count = int(pages or doc.default_pages)
    pdf_bytes = build_corpus_pdf(doc, pages=page_count)
    golden = golden_for(doc, pages=page_count)
    reference = _raw_reference(pdf_bytes)
    record: dict[str, Any] = {
        "document": f"{doc.name}{suffix}",
        "letter": doc.letter,
        "kind": doc.kind,
        "pages": page_count,
        "golden_objects": len(golden.get("objects") or []),
        "golden_queries": len(golden.get("queries") or []),
        "performance": {},
        "sides": {},
        "errors": {},
        "status": "ok",
    }
    documents: dict[str, Any] = {}
    performances: dict[str, dict[str, Any]] = {}
    parsers = {
        "pdfplumber": lambda: _parse_pdfplumber(pdf_bytes, f"{doc.name}.pdf"),
        "opendataloader": lambda: _parse_odl(
            pdf_bytes, f"{doc.name}.pdf", _odl_options(config, hybrid=False)
        ),
    }
    if config.hybrid:
        parsers["opendataloader-hybrid"] = lambda: _parse_odl(
            pdf_bytes, f"{doc.name}.pdf", _odl_options(config, hybrid=True)
        )
    for label, parse in parsers.items():
        try:
            document, elapsed, peak = _timed_parse(parse)
            documents[label] = document
            performances[label] = _performance(document, elapsed, peak)
        except Exception as exc:  # noqa: BLE001 — un motor roto no tumba el reporte
            record["errors"][label] = str(exc)[:400]
    record["performance"] = performances
    states: dict[str, KnowledgeState] = {}
    raw_matches: dict[str, dict[str, Any]] = {}
    for label, document in documents.items():
        try:
            states[label] = KnowledgeState.build(document, label=label)
        except Exception as exc:  # noqa: BLE001
            record["errors"][label] = f"knowledge chain: {str(exc)[:400]}"
    for label, state in states.items():
        from src.knowledge.parser_lab.p0.evaluate import golden_matches

        raw_matches[label] = golden_matches(state, golden)
        static = all_static_metrics(state, golden, reference_text=reference)
        runtime = await runtime_metrics(
            state, golden, consistency_runs=config.consistency_runs
        )
        metrics = {
            "structural": static["structural"],
            "semantic": static["semantic"],
            "knowledge": static["knowledge"],
            "canonical": static["canonical"],
            "premise": static["premise"],
            "runtime": runtime,
            "matches": static["matches"],
            "performance": performances[label],
        }
        record["sides"][label] = metrics
        record.setdefault("kcs", {})[label] = knowledge_completeness_score(metrics)["value"]
    if "pdfplumber" in states and "opendataloader" in states:
        diff = knowledge_diff(
            golden,
            states["pdfplumber"],
            states["opendataloader"],
            raw_matches["pdfplumber"],
            raw_matches["opendataloader"],
        )
        record["diff"] = diff
        if config.visual:
            try:
                path = config.out_dir / "visual_debug" / f"{record['document']}.html"
                record["visual_debug"] = write_visual_debug(
                    path,
                    golden=golden,
                    state_a=states["pdfplumber"],
                    state_b=states["opendataloader"],
                    diff=diff,
                )
            except Exception as exc:  # noqa: BLE001
                record["errors"]["visual"] = str(exc)[:300]
    if not states:
        record["status"] = "error"
    return record


def _flatten(node: Any, prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], float]:
    flat: dict[tuple[str, ...], float] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {"matches", "answer_counts", "kind_counts", "premise_per_kind"}:
                continue
            flat.update(_flatten(value, prefix + (str(key),)))
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        flat[prefix] = float(node)
    return flat


def _nest(flat: dict[tuple[str, ...], float]) -> dict[str, Any]:
    root: dict[str, Any] = {}
    for path, value in flat.items():
        node = root
        for key in path[:-1]:
            node = node.setdefault(key, {})
        node[path[-1]] = round(value, 6)
    return root


def aggregate_records(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    labels: set[str] = set()
    for record in records:
        labels.update((record.get("sides") or {}).keys())
    aggregate: dict[str, dict[str, Any]] = {}
    for label in sorted(labels):
        accumulator: dict[tuple[str, ...], list[float]] = {}
        for record in records:
            metrics = (record.get("sides") or {}).get(label)
            if metrics is None:
                continue
            for path, value in _flatten(metrics).items():
                accumulator.setdefault(path, []).append(value)
        flat = {
            path: sum(values) / len(values)
            for path, values in accumulator.items()
            if values
        }
        aggregate[label] = _nest(flat)
    return aggregate


def _write_golden(out_dir: Path) -> str:
    golden_dir = out_dir / "golden"
    golden_dir.mkdir(parents=True, exist_ok=True)
    for doc in CORPUS:
        payload = golden_for(doc)
        (golden_dir / f"{doc.name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return str(golden_dir)


def _write_corpus(out_dir: Path) -> str:
    corpus_dir = out_dir / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    for doc in CORPUS:
        if doc.status != "ready":
            continue
        (corpus_dir / f"{doc.name}.pdf").write_bytes(
            build_corpus_pdf(doc)
        )
    return str(corpus_dir)


async def run_benchmark(config: BenchConfig) -> dict[str, Any]:
    config.out_dir.mkdir(parents=True, exist_ok=True)
    golden_dir = _write_golden(config.out_dir)
    corpus_dir = _write_corpus(config.out_dir)
    selected = [
        doc
        for doc in CORPUS
        if (not config.docs or doc.name in config.docs)
    ]
    records: list[dict[str, Any]] = []
    pending: list[dict[str, str]] = []
    for doc in selected:
        if doc.status != "ready":
            pending.append(
                {"name": doc.name, "letter": doc.letter, "reason": doc.notes}
            )
            continue
        record = await run_document(doc, config=config)
        records.append(record)
    if config.large_pages:
        large = next((doc for doc in CORPUS if doc.name == "manual_tecnico_grande"), None)
        if large is not None and (not config.docs or large.name in config.docs):
            records.append(
                await run_document(
                    large,
                    config=config,
                    pages=config.large_pages,
                    suffix="#large",
                )
            )
    aggregate = aggregate_records(records)
    summary = report_mod.build_summary(
        records=records,
        aggregate=aggregate,
        corpus_dir=corpus_dir,
        golden_dir=golden_dir,
        config=dataclasses.asdict(config) | {"out_dir": str(config.out_dir)},
        pending_docs=pending,
    )
    summary_path, report_path = report_mod.write_outputs(config.out_dir, summary)
    summary["summary_path"] = summary_path
    summary["report_path"] = report_path
    return summary


__all__ = [
    "BenchConfig",
    "aggregate_records",
    "run_benchmark",
    "run_document",
]
