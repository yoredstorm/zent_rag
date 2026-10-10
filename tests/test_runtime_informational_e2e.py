# =============================================================================
# Consulta informacional en el pipeline completo del chat: una premisa de
# dominio faltante (exception_condition) NO puede convertir la explicación en
# «no puedo determinarlo» ni en «no tengo suficiente información».
# =============================================================================
# El escenario reproduce el caso real del chat: el motor determinista lee la
# evidencia, reporta la premisa faltante y el flujo la muestra, pero la
# respuesta sale igual porque la consulta es informacional (LOOKUP), no una
# decisión ejecutable. La vía ejecutable conserva el fail-closed.
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.core.domain.entities import (
    LLMResponse,
    RetrievalChunk,
    RetrievalContext,
)
from tests.test_runtime_literalness_e2e import (
    FakeVectorStore,
    _enable,
    _orchestrator,
    _steps,
)

QUESTION = "cuentame sobre el record 2 y el cambio de fechas"

DOC = (
    "Record 2: Eff Date y Disc Date controlan el cambio de fechas del registro. "
    "El cambio de fechas del Record 2 se procesa segun la fecha efectiva y la "
    "fecha de descontinuacion; Eff Date y Disc Date son los campos de fechas."
)


class InformationalFakeLLM:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate(self, **kwargs: Any) -> LLMResponse:
        self.calls.append(kwargs)
        return LLMResponse(
            content=(
                "El Record 2 incluye Eff Date y Disc Date, los campos que "
                "controlan el cambio de fechas del registro. [Doc: 1]"
            ),
            model="fake-llm",
            total_tokens=12,
            latency_ms=1.0,
        )


class _GroundedMissingPremise:
    """Resultado grounded con premisa de dominio faltante (exception_condition)."""

    canonical_rules: tuple = ()

    def to_public_dict(self) -> dict:
        return {
            "answerability": "UNANSWERABLE_MISSING_PREMISE",
            "missing_premises": ["exception_condition"],
            "abstention_message": "falta la premisa del dominio exception_condition",
            "conflicts": [],
        }


class _PrepStub:
    """Stub de prepare_derived_authority: sin autoridad, con premisa faltante."""

    def __init__(self) -> None:
        self.steps: list[dict] = []
        self.grounded_reasoning = _GroundedMissingPremise()
        self.canonical_rules: tuple = ()
        self.rule_retrieval = None
        self.authoritative_envelope = None
        self.has_authority = False
        self.error_stage = ""
        self.error_code = ""

    def answer_state(self) -> tuple[str, str]:
        return ("UNDETERMINED_RULE", "faltan premisas: exception_condition")


def _retrieval() -> RetrievalContext:
    return RetrievalContext(
        chunks=[
            RetrievalChunk(
                document_id=uuid4(),
                content=DOC,
                score=0.9,
                metadata={"filename": "manual.pdf", "source_id": "s1"},
            )
        ],
        query_embedding=[0.1] * 8,
        retrieval_latency_ms=1.0,
    )


def test_canonical_evidence_complete_detects_stops() -> None:
    from src.agents.runtime.orchestrator import _canonical_evidence_complete

    class _Complete:
        stop_reason = "evidence_complete"

    class _MaxTier:
        stop_reason = "max_tier_reached"

    assert _canonical_evidence_complete(
        {"long_context_applied": True, "long_context_result": _Complete()}
    )
    assert not _canonical_evidence_complete(
        {"long_context_applied": False, "long_context_result": _Complete()}
    )
    assert not _canonical_evidence_complete(
        {"long_context_applied": True, "long_context_result": _MaxTier()}
    )
    assert not _canonical_evidence_complete(None)


def test_canonical_override_corrects_classic_abstention() -> None:
    from src.agents.runtime.orchestrator import (
        correct_decision_with_canonical_evidence,
    )
    from src.core.domain.intelligence import (
        AnswerabilityDecision,
        AnswerabilityStatus,
    )

    class _Complete:
        stop_reason = "evidence_complete"

    adaptive = {"long_context_applied": True, "long_context_result": _Complete()}
    decision = AnswerabilityDecision(
        status=AnswerabilityStatus.DATA_MISSING,
        answerable=False,
        reason_codes=["NO_RETRIEVAL"],
        missing_data=["Datos sobre: la consulta"],
    )
    corrected, applied = correct_decision_with_canonical_evidence(
        decision, adaptive, "cuentame sobre el record 2"
    )
    assert applied is True
    assert corrected.answerable is True
    assert corrected.status == AnswerabilityStatus.ANSWERABLE_WITH_LIMITS
    assert "CANONICAL_EVIDENCE_COMPLETE" in corrected.reason_codes

    # Consulta ejecutable: intacta (fail-closed).
    executable, applied_exec = correct_decision_with_canonical_evidence(
        decision, adaptive, "si tengo un farebasis ASDFGRE y &&&F, ¿cumple?"
    )
    assert applied_exec is False
    assert executable.status == AnswerabilityStatus.DATA_MISSING

    # Sin evidencia canónica completa: intacta.
    untouched, applied_none = correct_decision_with_canonical_evidence(
        decision, {"long_context_applied": False}, "cuentame sobre el record 2"
    )
    assert applied_none is False
    assert untouched.status == AnswerabilityStatus.DATA_MISSING


@pytest.mark.asyncio
async def test_informational_question_never_abstains_on_missing_premise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch)
    import src.runtime.deterministic_authority as deterministic_authority

    async def _fake_prepare(**kwargs: Any) -> _PrepStub:
        return _PrepStub()

    monkeypatch.setattr(
        deterministic_authority, "prepare_derived_authority", _fake_prepare
    )

    llm = InformationalFakeLLM()
    orchestrator = _orchestrator(FakeVectorStore(_retrieval()), llm)

    result = await orchestrator.execute(
        organization_id=orchestrator._organization_repo.organization.id,
        user_id=uuid4(),
        query=QUESTION,
        role="admin",
        model="fake-llm",
    )

    content = str(getattr(result.llm_response, "content", "") or "")
    lowered = content.lower()
    assert "no puedo determinarlo" not in lowered, content
    assert "no tengo suficiente" not in lowered, content
    assert "eff date" in lowered, content

    # El prompt tampoco instruye «state exactly this»: la premisa no es bloqueo.
    combined_prompts = "\n".join(
        f"{call.get('system_prompt') or ''}\n{call.get('prompt') or ''}"
        for call in llm.calls
    )
    assert "MISSING DOMAIN PREMISES" not in combined_prompts

    # El paquete de generación no declara faltantes léxicos falsos: la evidencia
    # cubre la entidad (Record 2) y el aspecto (fechas) por vocabulario.
    package_steps = [
        step for step in _steps(result) if step.get("type") == "generation_package"
    ]
    assert package_steps, _steps(result)
    assert not (package_steps[0].get("missing_evidence") or ()), package_steps[0]

    # La telemetría conserva la premisa faltante: el escenario se ejercitó.
    grounded_steps = [
        step for step in _steps(result) if step.get("type") == "grounded_reasoning"
    ]
    assert grounded_steps, _steps(result)
    assert grounded_steps[0].get("answerability") == "UNANSWERABLE_MISSING_PREMISE"
    assert "exception_condition" in (grounded_steps[0].get("missing_premises") or [])
