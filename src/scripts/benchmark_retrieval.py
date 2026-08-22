# =============================================================================
# Benchmark de Retrieval — vector vs lexical vs hybrid
# =============================================================================
# Mide a nivel retrieval (sin LLM) contra un golden set con `relevant_chunks`
# (substrings que hacen relevante un chunk recuperado):
#   - precision@k: chunks relevantes / chunks recuperados
#   - coverage (proxy de recall@k): keywords relevantes cubiertos / total
#   - latencia: avg, p50, p95
#
# Uso (stack docker arriba, embeddings disponibles):
#   python src/scripts/benchmark_retrieval.py \
#     [--golden src/verticals/demo_farmacia/golden/rag_farmacia.json] \
#     [--organization 00000000-0000-0000-0000-000000000001] \
#     [--strategies vector,lexical,hybrid] [--top-k 20] [--runs 3]
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path
from typing import cast
from uuid import UUID

from src.rag.reranking.base import NoopReranker
from src.rag.retrieval import HybridRetriever
from src.rag.retrieval.models import RetrievalQuery

DEFAULT_GOLDEN = Path(__file__).resolve().parents[1] / "verticals" / "demo_farmacia" / "golden" / "rag_farmacia.json"
DEFAULT_ORGANIZATION = UUID("00000000-0000-0000-0000-000000000001")


def _relevant_chunk(content: str, keywords: list[str]) -> bool:
    lowered = content.lower()
    return any(kw.lower() in lowered for kw in keywords)


def _precision_at_k(chunks, keywords: list[str]) -> float:
    if not chunks:
        return 0.0
    return sum(1 for c in chunks if _relevant_chunk(c.content, keywords)) / len(chunks)


def _coverage_at_k(chunks, keywords: list[str]) -> float:
    """Proxy de recall: fracción de keywords relevantes presente en los chunks."""
    if not keywords:
        return 0.0
    pool = "\n".join(c.content.lower() for c in chunks)
    return sum(1 for kw in keywords if kw.lower() in pool) / len(keywords)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(p / 100 * len(ordered)))
    return ordered[idx]


async def _embed_query(text: str) -> list[float]:
    from src.api.deps import get_embedding_provider

    embedding = await get_embedding_provider().embed(text)
    if isinstance(embedding[0], list):
        embedding = embedding[0]  # type: ignore[assignment]
    return list(embedding)  # type: ignore[arg-type]


async def run_benchmark(
    golden_path: Path,
    organization_id: UUID,
    strategies: list[str],
    top_k: int,
    runs: int,
) -> dict:
    from src.api.deps import get_vector_store
    from src.infrastructure.qdrant.vector_store import QdrantVectorStore

    vector_store = cast(QdrantVectorStore, get_vector_store())
    retriever = HybridRetriever(
        vector_store=vector_store,
        lexical_store=vector_store,
        hybrid_store=vector_store,
        reranker=NoopReranker(),
    )

    cases = json.loads(golden_path.read_text(encoding="utf-8"))
    results: dict[str, dict] = {
        strategy: {"precisions": [], "coverages": [], "latencies": []}
        for strategy in strategies
    }

    for case in cases:
        keywords = case.get("relevant_chunks") or case.get("expected_keywords") or []
        query_embedding = await _embed_query(case["query"])
        for strategy in strategies:
            rquery = RetrievalQuery(
                query=case["query"],
                organization_id=organization_id,
                role=case.get("role", "admin"),
                top_k=top_k,
                effective_top_k=top_k,
                score_threshold=0.0,
                strategy=strategy,
                query_embedding=query_embedding,
            )
            for _ in range(runs):
                start = time.perf_counter()
                try:
                    ctx = await retriever.retrieve(rquery)
                    elapsed = (time.perf_counter() - start) * 1000
                except RuntimeError as exc:
                    if "lacks sparse vectors" in str(exc):
                        print(f"SKIP {strategy}: colección legacy sin sparse (migrar).")
                        results[strategy]["skipped"] = True
                        break
                    raise
                results[strategy]["precisions"].append(_precision_at_k(ctx.chunks, keywords))
                results[strategy]["coverages"].append(_coverage_at_k(ctx.chunks, keywords))
                results[strategy]["latencies"].append(elapsed)

    summary = {}
    for strategy, metrics in results.items():
        summary[strategy] = {
            "precision_at_k": round(
                statistics.mean(metrics["precisions"]), 4
            ) if metrics["precisions"] else 0.0,
            "coverage_at_k": round(
                statistics.mean(metrics["coverages"]), 4
            ) if metrics["coverages"] else 0.0,
            "avg_latency_ms": round(
                statistics.mean(metrics["latencies"]), 2
            ) if metrics["latencies"] else 0.0,
            "p50_latency_ms": round(_percentile(metrics["latencies"], 50), 2),
            "p95_latency_ms": round(_percentile(metrics["latencies"], 95), 2),
        }
        if metrics.get("skipped"):
            summary[strategy]["skipped"] = True
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark vector vs lexical vs hybrid retrieval")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--organization", type=UUID, default=DEFAULT_ORGANIZATION)
    parser.add_argument("--strategies", type=str, default="vector,lexical,hybrid")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    summary = asyncio.run(
        run_benchmark(args.golden, args.organization, strategies, args.top_k, args.runs)
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
