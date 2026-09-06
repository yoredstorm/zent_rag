# =============================================================================
# FASE 03 (S3) — AI Quality Root Cause: clasificación honesta sobre señales reales
# =============================================================================
"""Probable cause / Possible contributing factor — nunca certeza probabilística."""
from uuid import uuid4

import pytest

from src.agents.runtime.trace_store import save_run
from src.platform.quality.analysis import analyze_run


class _Run:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _result(**overrides) -> _Run:
    base = dict(
        run_id=uuid4(),
        agent_id=uuid4(),
        organization_id=None,  # se sobreescribe por test
        status="completed",
        answer="Respuesta de prueba",
        message="pregunta",
        user_id=None,
        role="admin",
        deployment_id=None,
        version_id=None,
        environment="development",
        steps=[],
        spans=[],
        total_latency_ms=1200.0,
        total_tokens=120,
        prompt_tokens=40,
        completion_tokens=80,
        cost=0.01,
        injection_detected=False,
        trace_id=str(uuid4()),
        model="gpt-4o",
        provider="openai",
    )
    base.update(overrides)
    return _Run(**base)


@pytest.mark.asyncio
async def test_analysis_flags_sql_failure_as_probable(dev_api_token, async_client):
    from uuid import UUID


    # Creamos un run con fallo de query_database en la org demo.
    org = UUID("00000000-0000-0000-0000-000000000001")
    r = _result(
        organization_id=org,
        steps=[
            {"type": "llm", "step": 0, "action": {"tool": "query_database"}},
            {
                "type": "tool_call",
                "tool": "query_database",
                "latency_ms": 500,
                "error": "syntax error at or near SELECT",
            },
            {"type": "final", "answer": "No pude consultar la base."},
        ],
        status="completed",
    )
    await save_run(r)

    analysis = await analyze_run(org, r.run_id)
    factors = [f["factor"] for f in analysis["probable_causes"]]
    assert "sql_failure" in factors
    # Lenguaje honesto: evidencia concreta, sin "0.9 certeza".
    labels = " ".join(f["label"] for f in analysis["probable_causes"])
    assert "SQL" in labels
    assert analysis["signals"]["status"] == "completed"


@pytest.mark.asyncio
async def test_analysis_negative_feedback_uses_possible_language(dev_api_token, async_client):
    from uuid import UUID

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    org = UUID("00000000-0000-0000-0000-000000000001")
    r = _result(
        organization_id=org,
        steps=[{"type": "final", "answer": "Respuesta sin verificación"}],
        status="completed",
        total_latency_ms=400,
    )
    await save_run(r)

    # Feedback negativo con razón wrong_answer vinculado al run.
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO feedback (id, organization_id, agent_id, run_id, rating, reason) "
                "VALUES (gen_random_uuid(), :oid, :aid, :rid, 'down', 'wrong_answer') "
                "ON CONFLICT DO NOTHING"
            ),
            {"oid": org, "aid": r.agent_id, "rid": r.run_id},
        )
        await session.commit()
    finally:
        await session.close()

    analysis = await analyze_run(org, r.run_id)
    possible = [f["factor"] for f in analysis["possible_contributing_factors"]]
    # No hay tool de retrieval → contexto insuficiente como POSSIBLE, nunca "certain".
    assert "possible_hallucination" in possible
    for f in analysis["possible_contributing_factors"]:
        assert f["factor"] in ("possible_hallucination", "insufficient_context", "answer_quality")
