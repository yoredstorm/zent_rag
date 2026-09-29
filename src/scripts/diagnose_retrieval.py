# =============================================================================
# diagnose_retrieval — diagnóstico genérico de una búsqueda real
# =============================================================================
# Responde, sin needles de dominio, tres preguntas:
#   1. ¿qué fuentes declaradas tiene la organización? (--list-sources)
#   2. ¿qué trajo la búsqueda para ESTA pregunta? (top-k con score, sección,
#      página y método de recuperación)
#   3. ¿la evidencia cubre lo que la pregunta nombra? (entidades + anchors)
#
# Uso:
#   python -m src.scripts.diagnose_retrieval --org <uuid> --list-sources
#   python -m src.scripts.diagnose_retrieval --org <uuid> --question "..." \
#       [--kb <uuid>] [--source <uuid>] [--strategy hybrid] [--top-k 8] [--json]
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from uuid import UUID


def summarize_coverage(chunks, question: str) -> dict[str, list[str]]:
    """Qué entidades y anchors de la pregunta cubre la evidencia recuperada.

    Es un DATO (contención de texto), no una opinión: sirve para saber si el
    problema fue el retrieval (no trajo la sección) o el generador.
    """
    from src.intelligence.response.anchors import anchor_covered, extract_anchors
    from src.intelligence.response.entities import asked_entities, entity_covered

    entidades = asked_entities(question)
    anchors = extract_anchors(question)
    texto = "\n".join(str(getattr(chunk, "content", "") or "") for chunk in chunks)
    return {
        "entities_covered": [e.label for e in entidades if entity_covered(e, texto)],
        "entities_missing": [e.label for e in entidades if not entity_covered(e, texto)],
        "anchors_covered": [a.label for a in anchors if anchor_covered(a, texto)],
        "anchors_missing": [a.label for a in anchors if not anchor_covered(a, texto)],
    }


def _chunk_row(index: int, chunk) -> dict:
    metadata = getattr(chunk, "metadata", None) or {}
    section_path = metadata.get("section_path")
    if isinstance(section_path, str):
        section_path = [section_path]
    return {
        "doc": index,
        "score": round(float(getattr(chunk, "score", 0.0) or 0.0), 4),
        "source_id": str(metadata.get("source_id") or ""),
        "title": str(metadata.get("filename") or metadata.get("title") or "")[:80],
        "retrieval": str(metadata.get("retrieval") or ""),
        "page": metadata.get("page_start") if isinstance(metadata.get("page_start"), int) else None,
        "section_path": [str(part) for part in (section_path or []) if part],
        "preview": " ".join(str(getattr(chunk, "content", "") or "").split())[:220],
    }


async def list_sources(organization_id: UUID) -> list[dict]:
    """Fuentes declaradas de la organización (id, nombre, tipo, estado)."""
    from sqlalchemy import text as sql_text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                sql_text(
                    "SELECT id::text, name, source_type, status "
                    "FROM kb_sources WHERE organization_id = :oid "
                    "ORDER BY name"
                ),
                {"oid": str(organization_id)},
            )
        ).fetchall()
        return [
            {
                "id": str(row[0]),
                "name": str(row[1] or ""),
                "source_type": str(row[2] or ""),
                "status": str(row[3] or ""),
            }
            for row in rows
        ]
    finally:
        await session.close()


async def diagnose(
    organization_id: UUID,
    question: str,
    *,
    kb_ids: list[UUID],
    source_ids: list[UUID],
    strategy: str,
    top_k: int,
) -> dict:
    from src.api.deps import get_embedding_provider, get_retriever
    from src.intelligence.response.anchors import dense_query_rewrite, extract_anchors
    from src.rag.retrieval.models import RetrievalQuery

    anchors = extract_anchors(question)
    expansion_terms = [
        term for anchor in anchors for term in anchor.expansion_terms if term
    ]
    dense_text = dense_query_rewrite(question, anchors)
    if expansion_terms:
        dense_text = f"{dense_text} {' '.join(dict.fromkeys(expansion_terms))}".strip()

    vector = None
    if strategy != "lexical":
        embedder = get_embedding_provider()
        embedding = await embedder.embed(dense_text)
        if embedding and isinstance(embedding[0], list):
            embedding = embedding[0]
        vector = list(embedding) if embedding else None

    retriever = get_retriever()
    result = await retriever.retrieve(
        RetrievalQuery(
            query=question,
            organization_id=organization_id,
            role="admin",
            source_ids=source_ids or None,
            knowledge_base_id=kb_ids[0] if kb_ids else None,
            top_k=top_k,
            effective_top_k=top_k,
            score_threshold=0.0,
            strategy=strategy,
            query_embedding=vector,
        )
    )
    chunks = list(result.chunks)
    return {
        "question": question,
        "strategy": strategy,
        "dense_text": dense_text,
        "anchors": [anchor.to_public_dict() for anchor in anchors],
        "hits": [_chunk_row(index + 1, chunk) for index, chunk in enumerate(chunks)],
        "coverage": summarize_coverage(chunks, question),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnóstico genérico de retrieval")
    parser.add_argument("--org", required=True)
    parser.add_argument("--question")
    parser.add_argument("--kb", action="append", default=[])
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--strategy", default="")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--list-sources", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    organization_id = UUID(args.org)

    payload: dict = {"organization_id": str(organization_id)}
    if args.list_sources:
        payload["sources"] = await list_sources(organization_id)
    if args.question:
        strategy = args.strategy
        if not strategy:
            from src.core.config import get_settings

            strategy = str(getattr(get_settings(), "RAG_RETRIEVAL_STRATEGY", "") or "vector")
        payload["diagnosis"] = await diagnose(
            organization_id,
            args.question,
            kb_ids=[UUID(item) for item in args.kb],
            source_ids=[UUID(item) for item in args.source],
            strategy=strategy,
            top_k=max(1, min(args.top_k, 50)),
        )

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for source in payload.get("sources", []):
            print(f"[source] {source['name']} | {source['source_type']} | {source['status']} | {source['id']}")
        diagnosis = payload.get("diagnosis")
        if diagnosis:
            print(f"strategy: {diagnosis['strategy']}")
            print(f"dense_text: {diagnosis['dense_text']}")
            for anchor in diagnosis["anchors"]:
                print(f"[anchor] {anchor['label']}")
            for hit in diagnosis["hits"]:
                seccion = "/".join(hit["section_path"]) or "-"
                print(
                    f"[Doc {hit['doc']}] score={hit['score']} page={hit['page']} "
                    f"section={seccion} retrieval={hit['retrieval'] or '-'} "
                    f"source={hit['source_id']}"
                )
                print(f"    {hit['preview']}")
            coverage = diagnosis["coverage"]
            print(
                "coverage: "
                f"entidades ok={coverage['entities_covered']} faltan={coverage['entities_missing']} | "
                f"anchors ok={coverage['anchors_covered']} faltan={coverage['anchors_missing']}"
            )
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
