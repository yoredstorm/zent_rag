# =============================================================================
# Finalizer — presupuesto del cierre (un ledger, un plan).
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace

from src.runtime.finalizer import (
    FinalizeBudget,
    build_finalize_prompt,
    citations_from_evidence,
    finalize_answer_delivery,
    limits_note,
    plan_finalize_budget,
)


def _result():
    return SimpleNamespace(
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        cost=0.0,
        llm_calls=0,
        logical_steps=0,
        tool_calls=0,
    )


class TestPlanFinalizeBudget:
    async def test_con_presupuesto_devuelve_plan(self) -> None:
        budget = await plan_finalize_budget(
            _result(),
            {"model": "m", "max_total_tokens": 8000, "max_steps": 10},
            prompt="p" * 100,
            question="q",
            configured_max_tokens=0,
            answer_max_tokens=1024,
        )
        assert isinstance(budget, FinalizeBudget)
        assert budget.max_tokens > 0
        assert budget.ledger.max_tokens == 8000

    async def test_sin_presupuesto_devuelve_none(self) -> None:
        budget = await plan_finalize_budget(
            _result(),
            {"model": "m", "max_total_tokens": 0, "max_steps": 10},
            prompt="p",
            question="q",
            configured_max_tokens=0,
            answer_max_tokens=1024,
        )
        assert budget is None

    async def test_configured_cap_limita_el_desired(self) -> None:
        budget = await plan_finalize_budget(
            _result(),
            {"model": "m", "max_total_tokens": 8000, "max_steps": 10},
            prompt="p" * 100,
            question="q",
            configured_max_tokens=256,
            answer_max_tokens=1024,
        )
        assert budget is not None
        assert budget.call_plan.desired_completion_tokens == 256

    async def test_consumo_previo_reduce_el_margen(self) -> None:
        result = _result()
        result.total_tokens = 7900
        budget = await plan_finalize_budget(
            result,
            {"model": "m", "max_total_tokens": 8000, "max_steps": 10},
            prompt="p" * 400,
            question="q",
            configured_max_tokens=0,
            answer_max_tokens=1024,
        )
        assert budget is None


def _selection():
    from src.core.domain.adaptive import EvidenceItem
    from src.runtime.evidence import EvidenceMatch, EvidenceSelection

    item = EvidenceItem(
        source_type="document",
        content="contenido",
        score=1.0,
        evidence_id="e1",
        document_id="d1",
        chunk_id="c1",
        title="Manual",
        page=3,
    )
    match = EvidenceMatch(
        evidence_id="e1",
        match="narrative",
        priority=1,
        score=1.0,
        chars=1,
        content="contenido",
    )
    return EvidenceSelection(items=[item], matches=[match])


class TestPromptDelCierre:
    def test_incluye_pregunta_y_historial_reciente(self) -> None:
        prompt = build_finalize_prompt(
            question="¿qué dice el record 2?",
            history=[f"turno {i}" for i in range(15)],
            analytical_workspace="WORKSPACE\n",
            response_shape="SHAPE",
        )
        assert "¿qué dice el record 2?" in prompt
        assert "turno 14" in prompt
        assert "turno 4" not in prompt  # solo los últimos 10
        assert "WORKSPACE" in prompt
        assert "SHAPE" in prompt
        assert "Final answer (text only, no JSON):" in prompt

    def test_sin_historial_ni_bloques(self) -> None:
        prompt = build_finalize_prompt(question="q", history=[])
        assert "USER QUESTION: q" in prompt
        assert "## HISTORY" in prompt
    def test_cita_doc_1_marca_cited(self) -> None:
        payload = citations_from_evidence("ver [Doc: 1]", _selection())
        assert payload[0]["evidence_id"] == "e1"
        assert payload[0]["cited"] is True

    def test_sin_cita_no_marca(self) -> None:
        payload = citations_from_evidence("sin citas", _selection())
        assert payload[0]["cited"] is False

    def test_indice_fuera_de_rango_no_marca(self) -> None:
        payload = citations_from_evidence("[Doc: 9]", _selection())
        assert payload[0]["cited"] is False

    def test_seleccion_vacia_o_none(self) -> None:
        from src.runtime.evidence import EvidenceSelection

        assert citations_from_evidence("[Doc: 1]", EvidenceSelection()) == []
        assert citations_from_evidence("[Doc: 1]", None) == []

    def test_limits_note(self) -> None:
        assert limits_note([]) == ""
        note = limits_note(["cierre de fechas", "vigencia"])
        assert note.startswith("\n\nNota:")
        assert "cierre de fechas" in note
        assert "vigencia" in note

    def test_delivery_entrega_completa(self) -> None:
        result = SimpleNamespace(
            steps=[], answer="", citations=None, status="error"
        )
        finalize_answer_delivery(
            result,
            answer="hola [Doc: 1]",
            reason="termination",
            selection=_selection(),
        )
        assert result.answer == "hola [Doc: 1]"
        assert result.status == "completed"
        assert result.citations[0]["cited"] is True
        assert result.steps[0]["type"] == "final"
        assert result.steps[0]["detail"] == "finalized after termination"
