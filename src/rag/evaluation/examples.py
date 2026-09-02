# =============================================================================
# Evaluation Examples — gestión first-class de casos (manual/CSV/synthetic)
# =============================================================================
# La tabla eval_examples es la fuente de gestión; materialize_cases() regenera
# eval_datasets.cases (JSONB v2) para que el runner existente no cambie.
# =============================================================================
from __future__ import annotations

import csv
import io
import json
from uuid import UUID, uuid4

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)


def normalize_example(raw: dict) -> dict:
    """Normaliza un ejemplo al schema v2 (compatible con EvalCase)."""
    question = str(raw.get("question") or "").strip()
    if not question:
        raise ValueError("question is required")
    expected_sources = raw.get("expected_sources") or []
    if isinstance(expected_sources, str):
        expected_sources = [
            s.strip() for s in expected_sources.replace("|", ";").split(";") if s.strip()
        ]
    return {
        "question": question,
        "expected_answer": raw.get("expected_answer") or None,
        "expected_behavior": raw.get("expected_behavior") or None,
        "expected_sources": list(expected_sources),
        "must_cite": bool(raw.get("must_cite", False)),
        "metadata": raw.get("metadata") or {},
    }


def parse_csv(csv_text: str) -> list[dict]:
    """Parsea CSV con cabecera: question,expected_answer,expected_behavior,
    expected_sources (separadas por '|' o ';'),must_cite."""
    rows = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for line in reader:
        if not (line.get("question") or "").strip():
            continue
        rows.append(
            {
                "question": line["question"].strip(),
                "expected_answer": (line.get("expected_answer") or "").strip() or None,
                "expected_behavior": (line.get("expected_behavior") or "").strip() or None,
                "expected_sources": [
                    s.strip()
                    for s in (line.get("expected_sources") or "").replace("|", ";").split(";")
                    if s.strip()
                ],
                "must_cite": (line.get("must_cite") or "").strip().lower()
                in ("true", "1", "yes", "si"),
            }
        )
    return rows


async def list_examples(
    organization_id: UUID, dataset_id: UUID, limit: int = 500
) -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, question, expected_answer, expected_behavior, "
                    "expected_sources, must_cite, metadata, created_at "
                    "FROM eval_examples WHERE organization_id = :oid "
                    "AND dataset_id = :did ORDER BY created_at ASC LIMIT :limit"
                ),
                {"oid": organization_id, "did": dataset_id, "limit": limit},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "question": r.question,
            "expected_answer": r.expected_answer,
            "expected_behavior": r.expected_behavior,
            "expected_sources": list(r.expected_sources or []),
            "must_cite": bool(r.must_cite),
            "metadata": r.metadata if isinstance(r.metadata, dict) else {},
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


async def add_examples(
    organization_id: UUID,
    dataset_id: UUID,
    examples: list[dict],
) -> list[dict]:
    """Inserta ejemplos y re-materializa eval_datasets.cases."""
    session = await get_async_session()
    inserted: list[dict] = []
    try:
        # Self-healing: migra cases JSONB legacy antes de mutar (una sola vez).
        await _backfill_legacy_cases(session, organization_id, dataset_id)
        for raw in examples:
            ex = normalize_example(raw)
            row = (
                await session.execute(
                    text(
                        "INSERT INTO eval_examples (id, organization_id, dataset_id, "
                        "question, expected_answer, expected_behavior, "
                        "expected_sources, must_cite, metadata) "
                        "VALUES (:id, :oid, :did, :q, :ea, :eb, "
                        "CAST(:src AS jsonb), :must, CAST(:meta AS jsonb)) "
                        "RETURNING id, question, expected_behavior, created_at"
                    ),
                    {
                        "id": uuid4(),
                        "oid": organization_id,
                        "did": dataset_id,
                        "q": ex["question"],
                        "ea": ex["expected_answer"],
                        "eb": ex["expected_behavior"],
                        "src": json.dumps(ex["expected_sources"]),
                        "must": ex["must_cite"],
                        "meta": json.dumps(ex["metadata"]),
                    },
                )
            ).fetchone()
            inserted.append(
                {
                    "id": str(row.id),
                    "question": row.question,
                    "expected_behavior": row.expected_behavior,
                }
            )
        await materialize_cases(session, organization_id, dataset_id)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    return inserted


async def delete_example(
    organization_id: UUID, dataset_id: UUID, example_id: UUID
) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "DELETE FROM eval_examples WHERE id = :eid "
                "AND organization_id = :oid AND dataset_id = :did"
            ),
            {"eid": example_id, "oid": organization_id, "did": dataset_id},
        )
        if result.rowcount:
            await materialize_cases(session, organization_id, dataset_id)
        await session.commit()
        return result.rowcount > 0
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def _backfill_legacy_cases(session, organization_id: UUID, dataset_id: UUID) -> None:
    """Migra cases del JSONB legacy a eval_examples si la tabla está vacía."""
    existing = (
        await session.execute(
            text(
                "SELECT COUNT(*) FROM eval_examples "
                "WHERE organization_id = :oid AND dataset_id = :did"
            ),
            {"oid": organization_id, "did": dataset_id},
        )
    ).scalar()
    if int(existing or 0) > 0:
        return
    legacy = (
        await session.execute(
            text(
                "SELECT cases FROM eval_datasets "
                "WHERE id = :did AND organization_id = :oid"
            ),
            {"did": dataset_id, "oid": organization_id},
        )
    ).fetchone()
    for case in legacy.cases if legacy and isinstance(legacy.cases, list) else []:
        if not isinstance(case, dict) or not str(case.get("question", "")).strip():
            continue
        await session.execute(
            text(
                "INSERT INTO eval_examples (id, organization_id, dataset_id, "
                "question, expected_answer, expected_behavior, "
                "expected_sources, must_cite, metadata) "
                "VALUES (gen_random_uuid(), :oid, :did, :q, :ea, :eb, "
                "CAST(:src AS jsonb), :must, CAST(:meta AS jsonb))"
            ),
            {
                "oid": organization_id,
                "did": dataset_id,
                "q": str(case["question"]),
                "ea": case.get("expected_answer"),
                "eb": case.get("expected_behavior"),
                "src": json.dumps(case.get("expected_sources") or []),
                "must": bool(case.get("must_cite", False)),
                "meta": json.dumps(case.get("metadata") or {}),
            },
        )


async def materialize_cases(session, organization_id: UUID, dataset_id: UUID) -> None:
    """Regenera eval_datasets.cases (JSONB v2) desde eval_examples."""
    rows = (
        await session.execute(
            text(
                "SELECT question, expected_answer, expected_behavior, "
                "expected_sources, must_cite, metadata "
                "FROM eval_examples WHERE organization_id = :oid "
                "AND dataset_id = :did ORDER BY created_at ASC"
            ),
            {"oid": organization_id, "did": dataset_id},
        )
    ).fetchall()
    cases = [
        {
            "id": f"example-{i + 1}",
            "question": r.question,
            "expected_answer": r.expected_answer,
            "expected_behavior": r.expected_behavior,
            "expected_sources": list(r.expected_sources or []),
            "must_cite": bool(r.must_cite),
            "metadata": r.metadata if isinstance(r.metadata, dict) else {},
        }
        for i, r in enumerate(rows)
    ]
    await session.execute(
        text(
            "UPDATE eval_datasets SET cases = CAST(:cases AS jsonb), "
            "schema_version = 2 WHERE id = :did AND organization_id = :oid"
        ),
        {"cases": json.dumps(cases), "did": dataset_id, "oid": organization_id},
    )
