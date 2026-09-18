# =============================================================================
# Eval ATPCO — confiabilidad de una fuente Excel (data dictionary)
# =============================================================================
# Corre el eval set determinista contra una fuente real (SQL-first) y, con
# --retrieval, verifica que la búsqueda híbrida (BM25 + dense) encuentre los
# chunks tabulares con el término exacto.
#
# Uso:
#   python -m src.scripts.eval_atpco_questions --org <uuid> --source <uuid>
#   python -m src.scripts.eval_atpco_questions --org <uuid> --source <uuid> --retrieval
#
# El set está calibrado sobre ATPCO_Attributes (6 750 filas x 24 columnas).
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class Case:
    id: str
    question: str
    kind: str = "lookup"  # lookup | label | list | count | none
    expect_value: str | None = None
    expect_total: int | None = None
    expect_strategy: str | None = None
    expect_row_matches_min: int = 0
    metadata: dict = field(default_factory=dict)


CASES: list[Case] = [
    Case("pos-1", "What is the start position of Tariff Type?", expect_value="6"),
    Case("len-1", "How long is Tariff Type?", expect_value="1"),
    Case(
        "pos-2",
        "What is the start position of Published Fare Information?",
        expect_value="198",
    ),
    Case(
        "len-2",
        "How long is Published Fare Information?",
        expect_value="18",
    ),
    Case("pos-3", "What is the start position of Change Tag 11?", expect_value="268"),
    Case(
        "len-3",
        "How long is Effective and Discontinue Dates?",
        expect_value="12",
        expect_row_matches_min=2,
    ),
    Case(
        "ambig-1",
        "What is the start position of Carrier Code?",
        expect_value="17",
        expect_row_matches_min=2,
    ),
    Case("end-1", "What is the end position of Tariff Type?", expect_value="6"),
    Case(
        "list-1",
        "Which fields have length 2?",
        kind="list",
        expect_total=645,
        expect_strategy="tabular_lookup:value+label:list",
    ),
    Case(
        "count-1",
        "How many fields have length 2?",
        kind="count",
        expect_value="645",
        expect_strategy="tabular_aggregation",
    ),
    Case(
        "inv-1",
        "Which field starts at position 30?",
        kind="label",
        expect_value="Filler",
        expect_strategy="tabular_lookup:value+label:list",
    ),
    Case(
        "dict-1",
        "¿Qué significa Carrier Code?",
        kind="dictionary",
        expect_strategy="tabular_dictionary",
    ),
    Case(
        "dict-2",
        "What does Tariff Type mean?",
        kind="dictionary",
        expect_strategy="tabular_dictionary",
    ),
    Case("sem-1", "What does Standard Name mean?", kind="none"),
    Case("off-1", "Who is the CEO of Zent?", kind="none"),
]


def _answer_of(result) -> str:
    strategy = str((result.metadata or {}).get("strategy") or "")
    if "value+label" in strategy:
        return str(result.rows[0][0]) if result.rows else ""
    return str(result.rows[0][-1]) if result.rows else ""


async def run_lookup_cases(organization_id: UUID, source_id: UUID) -> list[dict]:
    from src.api.deps import get_tabular_query_service

    service = get_tabular_query_service()
    outcomes: list[dict] = []
    for case in CASES:
        result = await service.try_answer(
            organization_id,
            case.question,
            source_ids=[source_id],
            role="admin",
            user_id=None,
        )
        metadata = (result.metadata or {}) if result is not None else {}
        strategy = str(metadata.get("strategy") or "")
        passed = False
        detail = ""
        if case.kind == "none":
            passed = result is None
            detail = "sin match (correcto)" if passed else f"match inesperado: {strategy}"
        elif result is None:
            detail = "None (se esperaba respuesta)"
        elif case.kind == "list":
            total = metadata.get("total")
            labels = [row[0] for row in result.rows]
            passed = (
                (case.expect_total is None or total == case.expect_total)
                and (case.expect_strategy is None or strategy == case.expect_strategy)
                and bool(labels)
            )
            detail = f"total={total} rows={len(result.rows)} strategy={strategy}"
        elif case.kind == "label":
            answer = _answer_of(result)
            passed = answer == case.expect_value and (
                case.expect_strategy is None or strategy == case.expect_strategy
            )
            detail = f"answer={answer!r} strategy={strategy} total={metadata.get('total')}"
        elif case.kind == "dictionary":
            passed = (
                case.expect_strategy is None or strategy == case.expect_strategy
            ) and bool(result.rows) and bool(str(result.rows[0][-1]).strip())
            detail = (
                f"strategy={strategy} definition={str(result.rows[0][-1])[:60]!r}"
                if result.rows
                else f"strategy={strategy} sin filas"
            )
        else:
            answer = _answer_of(result)
            row_matches = int(metadata.get("row_matches") or 0)
            passed = (
                (case.expect_value is None or answer == case.expect_value)
                and (case.expect_strategy is None or strategy == case.expect_strategy)
                and row_matches >= case.expect_row_matches_min
            )
            detail = (
                f"answer={answer!r} strategy={strategy} row_matches={row_matches}"
            )
        provenance = (metadata.get("provenance") or [{}])[0]
        if passed and case.kind in ("lookup", "label", "list", "dictionary"):
            passed = bool(provenance.get("table"))
            detail += " | provenance=ok" if passed else " | provenance=falta"
        outcomes.append(
            {
                "id": case.id,
                "question": case.question,
                "kind": case.kind,
                "passed": passed,
                "detail": detail,
                "provenance": provenance,
            }
        )
    return outcomes


async def run_retrieval_case(organization_id: UUID, source_id: UUID) -> dict:
    """La búsqueda híbrida debe encontrar chunks tabulares con el término exacto."""
    from src.api.deps import get_embedding_provider, get_retriever
    from src.rag.retrieval.models import RetrievalQuery

    query = "Carrier Code field position"
    embedder = get_embedding_provider()
    embedding = await embedder.embed(query)
    vector = embedding[0] if embedding and isinstance(embedding[0], list) else embedding
    retriever = get_retriever()
    hits = []
    for strategy in ("lexical", "hybrid"):
        result = await retriever.retrieve(
            RetrievalQuery(
                query=query,
                organization_id=organization_id,
                role="admin",
                source_ids=[source_id],
                top_k=8,
                effective_top_k=8,
                score_threshold=0.0,
                strategy=strategy,
                query_embedding=list(vector) if vector else None,
            )
        )
        found = any("Carrier Code" in chunk.content for chunk in result.chunks)
        hits.append({"strategy": strategy, "chunks": len(result.chunks), "found": found})
    return {
        "id": "retrieval-1",
        "question": query,
        "passed": any(hit["found"] for hit in hits),
        "detail": json.dumps(hits),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Eval de fuente Excel/CSV (ATPCO)")
    parser.add_argument("--org", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--retrieval", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    organization_id = UUID(args.org)
    source_id = UUID(args.source)

    outcomes = await run_lookup_cases(organization_id, source_id)
    if args.retrieval:
        try:
            outcomes.append(await run_retrieval_case(organization_id, source_id))
        except Exception as exc:  # noqa: BLE001
            outcomes.append(
                {
                    "id": "retrieval-1",
                    "question": "Carrier Code field position",
                    "passed": False,
                    "detail": f"error: {str(exc)[:200]}",
                }
            )

    passed = sum(1 for outcome in outcomes if outcome["passed"])
    total = len(outcomes)
    if args.json:
        print(json.dumps({"passed": passed, "total": total, "cases": outcomes}, indent=2))
    else:
        for outcome in outcomes:
            mark = "PASS" if outcome["passed"] else "FAIL"
            print(f"[{mark}] {outcome['id']}: {outcome['detail']}")
        print(f"eval: {passed}/{total}")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    asyncio.run(main())
