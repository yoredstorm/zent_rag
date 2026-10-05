# =============================================================================
# P0.23 / P0.24 — Runtime completo: query → retrieval → evidence → grounding →
# reasoning → generation, y el texto final no puede negar los datos del usuario.
# =============================================================================
# El FakeLLM imita un generador COMPLIANT: sólo produce la respuesta derivada si
# el prompt trae el bloque grounded (DERIVED RESULT + runtime inputs). Si el
# bloque no llega, devuelve la abstención literal vieja. Así el test prueba que
# el runtime entrega al generador lo que necesita y que ningún gate la reemplaza.
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from src.core.domain.entities import (
    LLMResponse,
    Organization,
    OrganizationStatus,
    RetrievalChunk,
    RetrievalContext,
)
from src.rag.retrieval.hybrid import HybridRetriever

QUESTION = "si tengo un farebasis ASDFGRE y en Record 2 me viene &&&F, ¿cumple?"

GRAMMAR_DOC = (
    "Record 2: & represents one alphanumeric position. Matching is positional "
    "from the start (prefix). El fare basis se evalúa contra el patrón del record."
)

FORBIDDEN_IN_ANSWER = (
    "no aparece",
    "no tengo suficiente información",
    "no menciona",
    "no está en la documentación",
    "necesito que",
    "no se encontró",
    "no se encuentra",
)


class FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    @staticmethod
    def _hash_query(organization_id: str, query: str, model: str, role: str = "") -> str:
        return f"hash:{organization_id}:{query}:{model}:{role}"

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ttl_seconds: int = 300) -> None:
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.store

    async def append_to_list(self, key: str, value: str, ttl_seconds: int = 3600) -> None:
        self.lists.setdefault(key, []).append(value)

    async def get_list(self, key: str) -> list[str]:
        return list(self.lists.get(key, []))

    async def trim_list(self, key: str, max_items: int) -> None:
        self.lists[key] = self.lists.get(key, [])[-max_items:]

    async def incr(self, key: str, ttl_seconds: int | None = None, by: int = 1) -> int:
        current = int(self.store.get(key, 0))
        self.store[key] = str(current + by)
        return current + by


class FakeOrganizationRepo:
    def __init__(self, organization: Organization) -> None:
        self.organization = organization

    async def get_by_id(self, organization_id: UUID) -> Organization | None:
        return self.organization if organization_id == self.organization.id else None

    async def check_rate_limit(self, organization_id: UUID) -> bool:
        return True

    async def log_usage(self, **kwargs: Any) -> None:
        return None


class GroundedFakeLLM:
    """Genera según el bloque grounded que recibe; abstiene si no llega.

    También responde al clasificador semántico opcional (JSON estricto).
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate(self, **kwargs: Any) -> LLMResponse:
        self.calls.append(kwargs)
        system = str(kwargs.get("system_prompt") or "")
        if "classify query tokens" in system.lower():
            return LLMResponse(
                content=(
                    '{"intent": "APPLY_RULE", "confidence": 0.8, "objects": ['
                    '{"value": "ASDFGRE", "role": "USER_INPUT", "confidence": 0.9}]}'
                ),
                model="fake-llm",
                total_tokens=8,
                latency_ms=1.0,
            )
        prompt = str(kwargs.get("prompt") or "")
        combined = f"{system}\n{prompt}"
        if "DERIVED RESULT" in combined and "MATCH" in combined:
            content = (
                "Sí, cumple. La regla documentada indica que & representa una "
                "posición alfanumérica y el matching es posicional desde el "
                "inicio; ASDFGRE cumple la cuarta posición. [Doc: 1]"
            )
        else:
            content = (
                "No tengo suficiente información para responder esta pregunta. "
                "ASDFGRE no aparece en la documentación y &&&F no aparece "
                "literalmente."
            )
        return LLMResponse(
            content=content,
            model="fake-llm",
            total_tokens=12,
            latency_ms=1.0,
        )


class FakeEmbed:
    async def embed(
        self, text: str | list[str], model: str | None = None
    ) -> list[float] | list[list[float]]:
        if isinstance(text, list):
            return [[0.1] * 8 for _ in text]
        return [0.1] * 8


class FakeVectorStore:
    def __init__(self, context: RetrievalContext) -> None:
        self.context = context

    async def search(self, **kwargs: Any) -> RetrievalContext:
        return self.context

    async def upsert(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def upsert_batch(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def delete_by_organization(self, organization_id: UUID) -> None:
        return None

    async def get_documents_by_chunk_ids(self, *args: Any, **kwargs: Any):
        return RetrievalContext(chunks=[])

    async def get_neighborhood(self, *args: Any, **kwargs: Any):
        return RetrievalContext(chunks=[])

    async def scan_text_literal(self, *args: Any, **kwargs: Any):
        return RetrievalContext(chunks=[])

    async def scan_text(self, *args: Any, **kwargs: Any):
        return RetrievalContext(chunks=[])


def _retrieval() -> RetrievalContext:
    return RetrievalContext(
        chunks=[
            RetrievalChunk(
                document_id=uuid4(),
                content=GRAMMAR_DOC,
                score=0.9,
                metadata={"filename": "manual.pdf", "source_id": "s1"},
            )
        ],
        query_embedding=[0.1] * 8,
        retrieval_latency_ms=1.0,
    )


def _orchestrator(store: FakeVectorStore, llm: GroundedFakeLLM):
    from src.agents.runtime.orchestrator import RAGOrchestrator

    return RAGOrchestrator(
        organization_repo=FakeOrganizationRepo(
            Organization(id=uuid4(), name="Test", status=OrganizationStatus.ACTIVE)
        ),
        vector_store=store,
        llm_provider=llm,
        embedding_provider=FakeEmbed(),
        cache_provider=FakeCache(),
        score_threshold=0.0,
        retriever=HybridRetriever(vector_store=store),
    )


def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "RAG_SCORE_THRESHOLD", 0.0)
    monkeypatch.setattr(settings, "RAG_LONG_CONTEXT_MODE", "active")
    monkeypatch.setattr(settings, "RAG_LONG_CONTEXT_MAX_EXPANSIONS", 2)
    monkeypatch.setattr(settings, "RAG_LONG_CONTEXT_REQUIREMENT_MIN", 0.0)


def _steps(result: Any) -> list[dict]:
    flow = result.flow if isinstance(result.flow, dict) else {}
    steps = flow.get("steps")
    return [item for item in (steps or []) if isinstance(item, dict)]


@pytest.mark.asyncio
async def test_full_runtime_derives_and_never_denies_user_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch)
    llm = GroundedFakeLLM()
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
    # P0.24: la respuesta final no puede negar los datos del usuario.
    for phrase in FORBIDDEN_IN_ANSWER:
        assert phrase not in lowered, f"respuesta negó dato de usuario: {phrase!r} :: {content!r}"
    assert "cumple" in lowered

    # P0.23: el generador recibió el contrato grounded.
    combined_prompts = "\n".join(
        f"{call.get('system_prompt') or ''}\n{call.get('prompt') or ''}"
        for call in llm.calls
    )
    assert "Runtime inputs" in combined_prompts
    assert "ASDFGRE" in combined_prompts
    assert "do NOT search them as source evidence" in combined_prompts
    assert "DERIVED RESULT" in combined_prompts
    assert "POSITIONAL_MATCH" in combined_prompts
    assert "MATCH" in combined_prompts


@pytest.mark.asyncio
async def test_full_runtime_flow_exposes_semantics_and_derivation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch)
    llm = GroundedFakeLLM()
    orchestrator = _orchestrator(FakeVectorStore(_retrieval()), llm)

    result = await orchestrator.execute(
        organization_id=orchestrator._organization_repo.organization.id,
        user_id=uuid4(),
        query=QUESTION,
        role="admin",
        model="fake-llm",
    )
    steps = _steps(result)

    grounded = next((s for s in steps if s.get("type") == "grounded_reasoning"), None)
    assert grounded is not None, "Ver flujo debe publicar grounded_reasoning"
    assert grounded["answerability"] == "ANSWERABLE_DERIVED"
    assert "ASDFGRE" in grounded["runtime_inputs"]
    assert "&&&F" in grounded["runtime_patterns"]
    assert grounded["derived_claims"], grounded
    claim = grounded["derived_claims"][0]
    assert claim["result"] == "MATCH"
    assert claim["verification_status"] == "SUPPORTED"
    assert claim["origin"] == "DERIVED"

    package = next((s for s in steps if s.get("type") == "generation_package"), None)
    assert package is not None
    assert "ASDFGRE" in package["runtime_inputs"]
    assert "&&&F" in package["runtime_patterns"]
    assert package["derived_claims"]
    assert package["missing_premises"] == []
    assert package["answerability"] == "ANSWERABLE_DERIVED"

    state = next(
        (
            s
            for s in steps
            if s.get("type") == "anchor_roles"
            and s.get("authority") == "canonical_evidence_engine"
        ),
        None,
    )
    assert state is not None
    missing = list(state.get("missing_documentable_evidence") or [])
    assert "ASDFGRE" not in missing
    assert "&&&F" not in missing


@pytest.mark.asyncio
async def test_full_runtime_abstains_naming_missing_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P0.14: sin definición de &, abstención correcta (no culpa al dato)."""
    _enable(monkeypatch)
    no_grammar = RetrievalContext(
        chunks=[
            RetrievalChunk(
                document_id=uuid4(),
                content="Record 2: patterns are supported for the fare basis field.",
                score=0.9,
                metadata={"filename": "manual.pdf", "source_id": "s1"},
            )
        ],
        query_embedding=[0.1] * 8,
        retrieval_latency_ms=1.0,
    )
    llm = GroundedFakeLLM()
    orchestrator = _orchestrator(FakeVectorStore(no_grammar), llm)

    result = await orchestrator.execute(
        organization_id=orchestrator._organization_repo.organization.id,
        user_id=uuid4(),
        query=QUESTION,
        role="admin",
        model="fake-llm",
    )
    content = str(getattr(result.llm_response, "content", "") or "")
    lowered = content.lower()

    steps = _steps(result)
    grounded = next((s for s in steps if s.get("type") == "grounded_reasoning"), None)
    assert grounded is not None
    assert grounded["answerability"] == "UNANSWERABLE_MISSING_PREMISE"
    assert any("definition:symbol:&" in item for item in grounded["missing_premises"])
    # P0.14: abstención canónica que nombra la premisa, no el dato del usuario.
    assert lowered.startswith("no puedo determinarlo")
    assert "símbolo" in lowered and "&" in content
    assert "fuentes" in lowered
    assert "ASDFGRE no aparece" not in content
    assert "&&&F no aparece" not in content


class TestOptionalLlmClassifier:
    """P1: clasificador estructurado sólo con baja confianza y flag activo."""

    @pytest.mark.asyncio
    async def test_classifier_runs_only_on_low_confidence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enable(monkeypatch)
        from src.core.config import get_settings

        monkeypatch.setattr(
            get_settings(), "RAG_QUERY_SEMANTICS_LLM_ENABLED", True
        )
        llm = GroundedFakeLLM()
        orchestrator = _orchestrator(FakeVectorStore(_retrieval()), llm)

        await orchestrator.execute(
            organization_id=orchestrator._organization_repo.organization.id,
            user_id=uuid4(),
            query="ASDFGRE?",
            role="admin",
            model="fake-llm",
        )
        classifier_calls = [
            call
            for call in llm.calls
            if "classify query tokens" in str(call.get("system_prompt") or "").lower()
        ]
        assert len(classifier_calls) == 1

        # Consulta con contexto claro: el determinista alcanza, no hay llamada.
        llm.calls.clear()
        await orchestrator.execute(
            organization_id=orchestrator._organization_repo.organization.id,
            user_id=uuid4(),
            query=QUESTION,
            role="admin",
            model="fake-llm",
        )
        classifier_calls = [
            call
            for call in llm.calls
            if "classify query tokens" in str(call.get("system_prompt") or "").lower()
        ]
        assert classifier_calls == []


class TestGateOverrides:
    """P0.20: ningún gate viejo puede convertir DERIVABLE en abstención."""

    def _adaptive(self) -> dict:
        return {
            "grounded_reasoning": {
                "answerability": "ANSWERABLE_DERIVED",
                "derivations": {
                    "claims": [
                        {
                            "operation": "POSITIONAL_MATCH",
                            "result": "MATCH",
                            "verification_status": "SUPPORTED",
                        }
                    ]
                },
            },
            "evidence_state": {"generation_mode": "generate_full"},
        }

    def test_canonical_derived_predicate(self) -> None:
        from src.agents.runtime.orchestrator import _canonical_derived

        assert _canonical_derived(self._adaptive()) is True
        assert _canonical_derived({"grounded_reasoning": {"answerability": "NOT_APPLICABLE"}}) is False
        assert _canonical_derived({"evidence_state": {"generation_mode": "generate_full"}}) is True
        assert _canonical_derived({"evidence_state": {"generation_mode": "generate_with_limits"}}) is False
        assert _canonical_derived(None) is False

    def test_answerability_gate_evaluate_corrects_data_missing(self) -> None:
        from src.core.domain.intelligence import (
            AnswerabilityStatus,
            QueryPlan,
            QueryUnderstanding,
        )
        from src.intelligence.answerability import AnswerabilityGate
        from src.intelligence.signals import SignalSet

        gate = AnswerabilityGate()
        decision = gate.evaluate(
            SignalSet(),
            QueryUnderstanding(),
            QueryPlan(),
            [],
            grounded_reasoning=self._adaptive()["grounded_reasoning"],
        )
        assert decision.status == AnswerabilityStatus.ANSWERABLE_DERIVED
        assert decision.answerable is True
