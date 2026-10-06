# =============================================================================
# P0 — CLI: PDF Parser Knowledge Benchmark
# =============================================================================
# Uso:
#   python -m src.scripts.pdf_knowledge_benchmark --out artifacts/pdf-parser-benchmark \
#       --java "C:\ruta\java.exe" [--hybrid] [--large-pages 120]
#
# Genera summary.json + report.md + corpus/ + golden/ + visual_debug/.
# Nada persiste en Postgres/Qdrant. No declara ganador por parsing: la decisión
# sale del conocimiento (KCS + ZentPdfKnowledgeScore + umbral de migración).
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from src.knowledge.parser_lab.p0.corpus import write_golden_sets
from src.knowledge.parser_lab.p0.runner import BenchConfig, run_benchmark


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark P0: conocimiento adquirido por parser PDF."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("artifacts/pdf-parser-benchmark"),
    )
    parser.add_argument("--java", default=None, help="binario java 11+ para OpenDataLoader")
    parser.add_argument("--hybrid", action="store_true", help="tercera columna ODL hybrid")
    parser.add_argument("--hybrid-url", default="")
    parser.add_argument(
        "--docs",
        default="",
        help="nombres de corpus separados por coma (vacío = todos los ready)",
    )
    parser.add_argument("--large-pages", type=int, default=0, help="§23: manual grande")
    parser.add_argument("--consistency-runs", type=int, default=100)
    parser.add_argument("--no-visual", action="store_true")
    parser.add_argument(
        "--write-golden",
        type=Path,
        default=None,
        help="escribe los Golden Sets como fixtures y sale",
    )
    args = parser.parse_args(argv)

    if args.write_golden is not None:
        written = write_golden_sets(args.write_golden)
        print(json.dumps({"written": written}, ensure_ascii=False, indent=2))
        return 0

    config = BenchConfig(
        out_dir=args.out,
        java=args.java or "",
        hybrid=args.hybrid,
        hybrid_url=args.hybrid_url,
        consistency_runs=args.consistency_runs,
        docs=tuple(name.strip() for name in args.docs.split(",") if name.strip()),
        large_pages=args.large_pages,
        visual=not args.no_visual,
    )
    summary = asyncio.run(run_benchmark(config))
    recommendation = summary["recommendation"]
    print("== PDF Parser Knowledge Benchmark (P0) ==")
    for label, kcs in summary["kcs"].items():
        score = summary["zent_score"][label]
        print(
            f"{label:22} KCS={kcs['value']:.4f} "
            f"ZPKS={score['value']:.4f} perf_viable={score['performance_viable']}"
        )
    print(f"verdict: {recommendation['verdict']}")
    print(f"summary: {summary.get('summary_path')}")
    print(f"report:  {summary.get('report_path')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
