# =============================================================================
# Offline RAG evaluation against a golden set
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from uuid import UUID

from src.api.deps import get_rag_orchestrator
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_GOLDEN = Path(__file__).resolve().parents[1] / "verticals" / "demo_farmacia" / "golden" / "rag_farmacia.json"
DEFAULT_ORGANIZATION = UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_USER = UUID("00000000-0000-0000-0000-000000000002")


def _keyword_hit(answer: str, keywords: list[str]) -> bool:
    lower = (answer or "").lower()
    return any(kw.lower() in lower for kw in keywords)


async def run_eval(
    golden_path: Path,
    organization_id: UUID,
    user_id: UUID,
    top_k_override: int | None = None,
) -> dict:
    cases = json.loads(golden_path.read_text(encoding="utf-8"))
    orchestrator = get_rag_orchestrator()

    results = []
    hits = 0
    for case in cases:
        start = time.perf_counter()
        result = await orchestrator.execute(
            organization_id=organization_id,
            user_id=user_id,
            query=case["query"],
            top_k=top_k_override or case.get("top_k", 20),
            use_cache=False,
            role=case.get("role", "admin"),
        )
        latency_ms = (time.perf_counter() - start) * 1000
        answer = result.llm_response.content if result.llm_response else ""
        keywords = case.get("expected_keywords") or []
        hit = _keyword_hit(answer, keywords) if keywords else bool(answer)
        if hit:
            hits += 1

        chunk_count = len(result.retrieval_context.chunks) if result.retrieval_context else 0
        results.append({
            "id": case.get("id"),
            "query": case["query"],
            "hit": hit,
            "latency_ms": round(latency_ms, 2),
            "chunks": chunk_count,
            "status": str(result.status),
            "answer_preview": answer[:200],
        })

    summary = {
        "total": len(cases),
        "hits": hits,
        "hit_rate": round(hits / len(cases), 4) if cases else 0.0,
        "avg_latency_ms": round(
            sum(r["latency_ms"] for r in results) / len(results), 2
        ) if results else 0.0,
        "results": results,
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RAG golden-set evaluation")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--organization-id", type=UUID, default=DEFAULT_ORGANIZATION)
    parser.add_argument("--user-id", type=UUID, default=DEFAULT_USER)
    args = parser.parse_args()

    summary = asyncio.run(run_eval(args.golden, args.organization_id, args.user_id))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if summary["hit_rate"] < 0.4:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
