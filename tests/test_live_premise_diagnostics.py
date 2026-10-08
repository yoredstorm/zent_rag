# =============================================================================
# Diagnóstico live — contrato de visibilidad (frontera API vs benchmark)
# =============================================================================
# Estos tests fijan el contrato del diagnóstico:
#   - un fallo de factory NO puede volverse "falta en las fuentes";
#   - una lane rota es visible (fail-soft para el usuario, no fail-silent);
#   - SHA distinto conocido => BUILD_MISMATCH;
#   - scope sin document_id/source_id es diagnosticable;
#   - el adapter sano se construye (wiring no-None).
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.runtime.premise_retriever import (
    PremiseEvidenceRetriever,
    build_premise_evidence_search_result,
)
from src.runtime.runtime_identity import build_parity


def test_build_parity_detects_sha_mismatch() -> None:
    api = {"git_sha": "aaaa", "build_timestamp": "t1"}
    worker = {"git_sha": "bbbb", "build_timestamp": "t2"}
    parity = build_parity(api, worker)
    assert parity["status"] == "MISMATCH"
    assert build_parity(api, {"git_sha": "aaaa"})["status"] == "MATCH"
    assert build_parity(api, None)["status"] == "UNKNOWN"


def test_factory_failure_is_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.runtime import dependencies as deps

    def _boom() -> object:
        raise RuntimeError("retriever no disponible")

    monkeypatch.setattr(deps, "get_knowledge_retriever", _boom)
    result = build_premise_evidence_search_result(uuid4())
    assert result.available is False
    assert result.adapter is None
    assert result.error_code == "PREMISE_RETRIEVER_FACTORY_FAILED"
    assert result.dependency == "get_knowledge_retriever"
    assert result.exception_type == "RuntimeError"
    assert "retriever no disponible" in result.exception_message_safe


def test_healthy_deps_build_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.runtime import dependencies as deps

    class _Fake:
        pass

    monkeypatch.setattr(deps, "get_knowledge_retriever", lambda: _Fake())
    monkeypatch.setattr(deps, "get_vector_store", lambda: _Fake())
    monkeypatch.setattr(deps, "get_embedding_provider", lambda: _Fake())
    result = build_premise_evidence_search_result(uuid4())
    assert result.available is True
    assert result.adapter is not None
    assert result.retriever_type == "_Fake"


@pytest.mark.asyncio
async def test_lane_exception_is_visible() -> None:
    from src.runtime.premise_closure import SourceScope

    class _BoomEmbedder:
        async def embed(self, _text: str) -> list[float]:
            raise RuntimeError("embedding caído")

    class _EmptyStore:
        async def scan_text_literal(self, *_args: object, **_kwargs: object) -> object:
            return type("Ctx", (), {"chunks": []})()

    adapter = PremiseEvidenceRetriever(
        organization_id=uuid4(),
        retriever=type("R", (), {})(),
        vector_store=_EmptyStore(),
        embedding_provider=_BoomEmbedder(),
    )
    scope = SourceScope(organization_id=str(uuid4()))
    hits = await adapter.search("ampersand definition", scope, 3)
    assert hits == []
    assert adapter.last_lane_errors, "la lane rota debe quedar registrada"
    error = adapter.last_lane_errors[0]
    assert error["lane"] == "canonical"
    assert error["exception_type"] == "RuntimeError"
    assert error["query_fingerprint"]


@pytest.mark.asyncio
async def test_premise_unavailable_is_operational_not_source_missing() -> None:
    from src.runtime.deterministic_authority import prepare_derived_authority

    class _Item:
        def __init__(self, content: str) -> None:
            self.content = content
            self.evidence_id = "ev:only-symbol"
            self.page = 1
            self.document_id = "doc-1"

    item = _Item(
        "The ! or & indicate a match to any alphanumeric character in that "
        "position of the fare class."
    )
    prep = await prepare_derived_authority(
        organization_id=uuid4(),
        question="mi valor ABCFGEGE contra &&&F cumple?",
        evidence_items=[item],
        enable_premise_closure=True,
        premise_evidence_search=None,
        premise_retriever_status={
            "available": False,
            "error_code": "PREMISE_RETRIEVER_FACTORY_FAILED",
            "dependency": "get_knowledge_retriever",
        },
    )
    assert prep.error_code == "PREMISE_RETRIEVER_UNAVAILABLE"
    state, message = prep.answer_state()
    assert state == "PREMISE_RETRIEVER_UNAVAILABLE"
    assert "no está disponible" in message
    assert "falta en las fuentes la definición" not in message
    health = [
        step for step in prep.steps if step.get("type") == "premise_retriever_health"
    ]
    assert health and health[0]["status"] == "error"
    assert health[0]["dependency"] == "get_knowledge_retriever"


def test_scope_audit_flags_missing_ids() -> None:
    from src.scripts.live_premise_audit import _collection_info, _scope_audit

    audit = _scope_audit(
        [{"document_id": None, "source_id": None, "workspace_id": None}],
        {"id": "source-visible"},
    )
    assert audit["source_id_missing_in_scope"] is True
    assert audit["document_id_missing_in_scope"] is True

    ok = _scope_audit(
        [{"document_id": "doc", "source_id": "src", "workspace_id": "ws"}],
        {"id": "src"},
    )
    assert ok["source_id_missing_in_scope"] is False
    assert ok["document_id_missing_in_scope"] is False

    collection = _collection_info()
    assert collection["match"] is True
    assert collection["write_collection"] == collection["read_collection"]
