# =============================================================================
# Intelligence Pipeline — tests de integración (DB real + API)
# =============================================================================
# Cubre: CRUD de definiciones empresariales + aislamiento multi-tenant,
# traces (persistencia + endpoint org-scoped), engine end-to-end con los
# golden cases de answerability, y loop prevention del repair SQL.
# =============================================================================
from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient

from src.agents.tools.sql_expert_postgres import PostgresSqlExpert
from src.core.domain.entities import LLMResponse, QueryStatus, RAGQueryResult
from src.core.domain.intelligence import (
    AnswerabilityDecision,
    AnswerabilityStatus,
)
from src.core.domain.services import ColumnMeta, DataSource
from src.core.ports.sql_expert import SqlQueryResult, SqlValidationError
from src.intelligence.definitions import BusinessDefinitionRegistry
from src.intelligence.engine import IntelligenceEngine
from src.intelligence.store import PostgresIntelligenceStore

ORG_DEV = UUID("00000000-0000-0000-0000-000000000001")


async def _fresh_store() -> PostgresIntelligenceStore:
    store = PostgresIntelligenceStore()
    await store.ensure_tables()
    return store


async def _registry(store: PostgresIntelligenceStore | None = None) -> BusinessDefinitionRegistry:
    return BusinessDefinitionRegistry(store=store or await _fresh_store())


async def _engine(store: PostgresIntelligenceStore | None = None) -> IntelligenceEngine:
    return IntelligenceEngine(
        store=store or await _fresh_store(),
        cache=None,
        concept_llm_enabled=False,
        min_score=0.6,
        sql_router_threshold=0.5,
    )


async def _create_org(client: AsyncClient, name: str, email: str) -> dict:
    resp = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={"company_name": name, "email": email, "country": "CL"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    return {"organization_id": data["organization_id"], "token": data["api_token"]}


async def _owner_headers(client: AsyncClient, org: dict) -> dict:
    """Sesión portal del owner: RBAC completo (los tokens API solo traen rag scopes)."""
    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.platform.auth.session import encrypt_session

    user_repo = PostgresUserRepository()
    user = await user_repo.get_by_external_id(
        UUID(org["organization_id"]), "default-admin"
    )
    assert user is not None, "default-admin user missing"
    session = encrypt_session(user.id, UUID(org["organization_id"]))
    return {
        "Authorization": f"Bearer {session}",
        "X-Organization-Id": org["organization_id"],
    }


class TestBusinessDefinitionsApi:
    @pytest.mark.asyncio
    async def test_crud_and_concept_normalization(self, async_client: AsyncClient) -> None:
        org = await _create_org(async_client, "Defs Corp", f"defs-{UUID(int=1)}@example.com")
        headers = await _owner_headers(async_client, org)

        created = await async_client.post(
            "/api/v1/intelligence/definitions",
            headers=headers,
            json={
                "concept": "Cliente Activo",
                "definition": "Cliente con al menos una compra en los últimos 90 días",
                "data_type": "metric",
                "status": "approved",
            },
        )
        assert created.status_code == 201, created.text
        payload = created.json()
        assert payload["concept"] == "cliente activo"
        assert payload["data_type"] == "metric"

        listed = await async_client.get(
            "/api/v1/intelligence/definitions", headers=headers
        )
        assert listed.status_code == 200
        concepts = [d["concept"] for d in listed.json()]
        assert "cliente activo" in concepts

        updated = await async_client.post(
            "/api/v1/intelligence/definitions",
            headers=headers,
            json={
                "concept": "Cliente Activo",
                "definition": "Cliente con al menos una compra en los últimos 60 días",
            },
        )
        assert updated.status_code == 201
        assert "60 días" in updated.json()["definition"]

        deleted = await async_client.delete(
            f"/api/v1/intelligence/definitions/{payload['concept']}",
            headers=headers,
        )
        assert deleted.status_code == 200

        after = await async_client.get(
            "/api/v1/intelligence/definitions", headers=headers
        )
        assert payload["concept"] not in [d["concept"] for d in after.json()]

    @pytest.mark.asyncio
    async def test_rejects_invalid_status(self, async_client: AsyncClient) -> None:
        org = await _create_org(async_client, "Defs Bad", f"bad-{UUID(int=4)}@example.com")
        headers = await _owner_headers(async_client, org)
        resp = await async_client.post(
            "/api/v1/intelligence/definitions",
            headers=headers,
            json={
                "concept": "x",
                "definition": "y",
                "status": "invalid_status",
            },
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_tenant_isolation_definitions(
        self, async_client: AsyncClient
    ) -> None:
        org_a = await _create_org(async_client, "Org A", f"a-{UUID(int=1)}@example.com")
        org_b = await _create_org(async_client, "Org B", f"b-{UUID(int=2)}@example.com")
        headers_a = await _owner_headers(async_client, org_a)
        headers_b = await _owner_headers(async_client, org_b)

        created = await async_client.post(
            "/api/v1/intelligence/definitions",
            headers=headers_a,
            json={"concept": "margen_bruto", "definition": "Ventas - COGS"},
        )
        assert created.status_code == 201

        listed_b = await async_client.get(
            "/api/v1/intelligence/definitions", headers=headers_b
        )
        assert listed_b.status_code == 200
        assert all(d["concept"] != "margen_bruto" for d in listed_b.json())

        deleted_b = await async_client.delete(
            "/api/v1/intelligence/definitions/margen_bruto", headers=headers_b
        )
        assert deleted_b.status_code == 404

        still_there = await async_client.get(
            "/api/v1/intelligence/definitions", headers=headers_a
        )
        assert "margen_bruto" in [d["concept"] for d in still_there.json()]


class TestTracesApi:
    @pytest.mark.asyncio
    async def test_trace_org_scoped(self, async_client: AsyncClient) -> None:
        org = await _create_org(async_client, "Trace Co", f"tr-{UUID(int=5)}@example.com")
        headers = await _owner_headers(async_client, org)
        org_id = UUID(org["organization_id"])
        store = await _fresh_store()
        from src.core.domain.intelligence import IntelligenceTrace

        trace = IntelligenceTrace(
            organization_id=org_id,
            user_query="¿Cuál es la política de devolución?",
            status="ANSWERABLE",
            decision={"status": "ANSWERABLE", "answerable": True},
        )
        await store.save_trace(trace)

        ok = await async_client.get(
            f"/api/v1/intelligence/traces/{trace.trace_id}",
            headers=headers,
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["user_query"] == "¿Cuál es la política de devolución?"
        assert ok.json()["status"] == "ANSWERABLE"

        other = await _create_org(
            async_client, "Other", f"other-{UUID(int=3)}@example.com"
        )
        headers_other = await _owner_headers(async_client, other)
        not_found = await async_client.get(
            f"/api/v1/intelligence/traces/{trace.trace_id}",
            headers=headers_other,
        )
        assert not_found.status_code == 404


class TestRegistryResolution:
    @pytest.mark.asyncio
    async def test_approved_concepts_resolve_undefined_do_not(self) -> None:
        store = await _fresh_store()
        registry = await _registry(store)
        org = ORG_DEV
        await store.upsert_definition(
            organization_id=org,
            concept="cliente activo",
            definition="Compra en los últimos 90 días",
            status="approved",
        )
        await store.upsert_definition(
            organization_id=org,
            concept="margen bruto",
            definition="Ventas - COGS",
            status="draft",  # draft NO cuenta como definido
        )
        resolved = await registry.resolve_concepts(
            org, ["cliente activo", "margen bruto", "inexistente"]
        )
        assert resolved == {
            "cliente activo": True,
            "margen bruto": False,
            "inexistente": False,
        }


class TestEngineGoldenCases:
    @pytest.mark.asyncio
    async def test_case1_defined_metric_is_answerable(self) -> None:
        engine = await _engine()
        org = ORG_DEV
        await engine._store.upsert_definition(
            organization_id=org,
            concept="clientes",
            definition="Cuentas activas",
            status="approved",
        )
        await engine._store.upsert_definition(
            organization_id=org,
            concept="rentables",
            definition="Margen positivo",
            status="approved",
        )
        understanding = await engine.understand(org, "¿Cuántos clientes rentables tenemos?")
        plan = engine.plan(
            understanding, query="¿Cuántos clientes rentables tenemos?",
            sql_available=True, router_score=0.9,
        )
        sql_result = SqlQueryResult(
            sql="SELECT COUNT(*) FROM customers", columns=["count"], rows=[["12"]], row_count=1
        )
        evidences = await engine.collect_evidence(
            organization_id=org,
            query="¿Cuántos clientes rentables tenemos?",
            understanding=understanding,
            retrieval_context=None,
            sql_result=sql_result,
            definitions=await engine.get_definitions(org),
        )
        signals = engine.collect_signals(
            understanding, plan, None, sql_result, evidences
        )
        decision = engine.evaluate(
            signals, understanding, plan, evidences
        )
        assert decision.status == AnswerabilityStatus.ANSWERABLE
        assert decision.answerable
        assert decision.confidence_level.value in ("high", "medium")

    @pytest.mark.asyncio
    async def test_case2_undefined_concept_is_context_missing(self) -> None:
        engine = await _engine()
        org = ORG_DEV
        understanding = await engine.understand(org, "¿Cuántos clientes activos tenemos?")
        plan = engine.plan(
            understanding, query="¿Cuántos clientes activos tenemos?",
            sql_available=True, router_score=0.9,
        )
        sql_result = SqlQueryResult(
            sql="SELECT COUNT(*) FROM customers", columns=["count"], rows=[["5"]], row_count=1
        )
        evidences = await engine.collect_evidence(
            organization_id=org,
            query="¿Cuántos clientes activos tenemos?",
            understanding=understanding,
            retrieval_context=None,
            sql_result=sql_result,
            definitions=[],
        )
        signals = engine.collect_signals(
            understanding, plan, None, sql_result, evidences
        )
        decision = engine.evaluate(signals, understanding, plan, evidences)
        assert decision.status == AnswerabilityStatus.CONTEXT_MISSING
        assert not decision.answerable
        assert any("activos" in c or "clientes" in c for c in decision.missing_context)
        assert decision.reason_codes == ["UNDEFINED_BUSINESS_TERM"]

    @pytest.mark.asyncio
    async def test_case3_missing_cost_data_is_data_missing(self) -> None:
        engine = await _engine()
        org = ORG_DEV
        await engine._store.upsert_definition(
            organization_id=org,
            concept="margen",
            definition="Ventas - COGS",
            status="approved",
        )
        understanding = await engine.understand(org, "¿Cuál es el margen de nuestros productos?")
        plan = engine.plan(
            understanding, query="¿Cuál es el margen de nuestros productos?",
            sql_available=True, router_score=0.9,
        )
        decision = engine.evaluate(
            engine.collect_signals(
                understanding, plan, None, None, []
            ),
            understanding,
            plan,
            [],
            missing_data_hints=["costo de producto / COGS"],
        )
        assert decision.status == AnswerabilityStatus.DATA_MISSING
        assert "COGS" in decision.missing_data[0]

    @pytest.mark.asyncio
    async def test_case4_conflicting_sources_is_source_conflict(self) -> None:
        from src.core.domain.intelligence import EvidenceObject, EvidenceType

        engine = await _engine()
        org = ORG_DEV
        understanding = await engine.understand(org, "¿Cuál es el precio del producto A?")
        plan = engine.plan(
            understanding, query="¿Cuál es el precio del producto A?",
            sql_available=True, router_score=0.5,
        )
        evidences = [
            EvidenceObject(
                type=EvidenceType.SQL_RESULT, source_name="ERP",
                authority_level="authoritative", value=120.0,
                validation_status="valid", access_verified=True,
            ),
            EvidenceObject(
                type=EvidenceType.DOCUMENT_CHUNK, source_name="Documento",
                authority_level="informational", value=100.0,
                validation_status="valid", access_verified=True,
            ),
        ]
        signals = engine.collect_signals(
            understanding, plan, None, None, evidences
        )
        decision = engine.evaluate(signals, understanding, plan, evidences)
        assert decision.status == AnswerabilityStatus.SOURCE_CONFLICT
        assert len(decision.conflicting_sources) == 1

    @pytest.mark.asyncio
    async def test_case5_ambiguous_metric_is_clarification(self) -> None:
        engine = await _engine()
        org = ORG_DEV
        understanding = await engine.understand(org, "¿Cuál es el margen del trimestre?")
        understanding.ambiguity = True
        understanding.clarifying_question = "¿Margen bruto o margen neto?"
        plan = engine.plan(
            understanding, query="¿Cuál es el margen del trimestre?",
            sql_available=True, router_score=0.9,
        )
        assert plan.strategy.value == "clarification"
        decision = engine.evaluate(
            engine.collect_signals(understanding, plan, None, None, []),
            understanding, plan, [],
        )
        assert decision.status == AnswerabilityStatus.CLARIFICATION_REQUIRED
        assert decision.clarifying_question == "¿Margen bruto o margen neto?"

    @pytest.mark.asyncio
    async def test_case8_empty_sql_result_is_valid_answer(self) -> None:
        engine = await _engine()
        org = ORG_DEV
        understanding = await engine.understand(org, "¿Cuántas devoluciones hubo en agosto?")
        assert understanding.requires_definition == []  # devoluciones es entidad
        plan = engine.plan(
            understanding, query="¿Cuántas devoluciones hubo en agosto?",
            sql_available=True, router_score=0.9,
        )
        sql_result = SqlQueryResult(
            sql="SELECT COUNT(*) FROM returns WHERE month='aug'",
            columns=["count"], rows=[], row_count=0,
        )
        evidences = await engine.collect_evidence(
            organization_id=org,
            query="¿Cuántas devoluciones hubo en agosto?",
            understanding=understanding,
            retrieval_context=None,
            sql_result=sql_result,
            definitions=[],
        )
        signals = engine.collect_signals(
            understanding, plan, None, sql_result, evidences
        )
        decision = engine.evaluate(signals, understanding, plan, evidences)
        assert decision.status == AnswerabilityStatus.ANSWERABLE
        assert decision.answerable


class TestRagQueryResponseAnswerability:
    @pytest.mark.asyncio
    async def test_answerability_block_in_api_response(
        self, async_client: AsyncClient, mock_orchestrator, trial_auth: dict
    ) -> None:
        from src.core.domain.intelligence import ConfidenceLevel

        decision = AnswerabilityDecision(
            status=AnswerabilityStatus.DATA_MISSING,
            answerable=False,
            confidence_level=ConfidenceLevel.INSUFFICIENT,
            reason_codes=["NO_SQL_RESULT", "NO_RETRIEVAL"],
            missing_data=["costo de producto / COGS"],
            evidence_summaries=[
                {
                    "evidence_id": "ev-1",
                    "type": "sql_result",
                    "source_name": "ERP",
                    "authority_level": "authoritative",
                    "freshness": "live",
                }
            ],
        )
        result = RAGQueryResult(
            organization_id=UUID(trial_auth["X-Organization-Id"]),
            query="¿Cuál es el margen?",
            status=QueryStatus.COMPLETED,
            llm_response=LLMResponse(
                content="No tengo suficiente información para responder esta pregunta. Datos faltantes: costo de producto / COGS.",
                model="none",
                total_tokens=0,
            ),
            method="rag",
            answerability=decision,
            trace_id="trace-123",
        )
        mock_orchestrator._response = result
        resp = await async_client.post(
            "/api/v1/rag/query",
            headers=dict(trial_auth),
            json={"query": "¿Cuál es el margen?"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["trace_id"] == "trace-123"
        assert body["answerability"]["status"] == "DATA_MISSING"
        assert body["answerability"]["answerable"] is False
        assert body["answerability"]["confidence"] == "insufficient"
        assert "COGS" in body["answerability"]["missing_data"][0]
        assert body["answerability"]["evidence"][0]["source_name"] == "ERP"

    @pytest.mark.asyncio
    async def test_legacy_response_without_answerability(
        self, async_client: AsyncClient, mock_orchestrator, trial_auth: dict
    ) -> None:
        """Backward compatibility: sin engine, el bloque answerability es null."""
        result = RAGQueryResult(
            organization_id=UUID(trial_auth["X-Organization-Id"]),
            query="hola",
            status=QueryStatus.COMPLETED,
            llm_response=LLMResponse(content="Hola!", model="gpt-4o-mini", total_tokens=10),
            method="rag",
        )
        mock_orchestrator._response = result
        resp = await async_client.post(
            "/api/v1/rag/query",
            headers=dict(trial_auth),
            json={"query": "hola"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["answerability"] is None
        assert body["trace_id"] is None


class TestSqlRepairLoopPrevention:
    @pytest.mark.asyncio
    async def test_repeated_identical_failure_stops_without_loop(self) -> None:
        """Case 7: repair que repite (sql, error) idéntico se corta antes del límite."""
        llm = _AlwaysBrokenLLM()
        expert = _ExecutionLoopExpert(llm)
        result = await expert.execute(
            organization_id=ORG_DEV,
            question="cuál es el total",
            role="admin",
        )
        assert result.error is not None
        # Sin el guard: generación + max_repair_attempts(3) = 4 llamadas.
        # Con el guard: el tercer intento repite (sql, error) idéntico y se corta.
        assert len(llm.calls) == 3

    @pytest.mark.asyncio
    async def test_max_repair_attempts_configurable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Con SQL distinto en cada repair, el límite configurable se respeta."""
        from src.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "RAG_SQL_MAX_REPAIR_ATTEMPTS", 4)
        llm = _VaryingSqlLLM()
        expert = _ExecutionLoopExpert(llm)
        result = await expert.execute(
            organization_id=ORG_DEV,
            question="cuál es el total",
            role="admin",
        )
        assert result.error is not None
        # generación (1) + máx. 4 repairs (cada repair vuelve a fallar validación).
        assert len(llm.calls) == 5


class _AlwaysBrokenLLM:
    """LLM que 'repara' devolviendo SQL siempre idéntico y roto."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate(self, **kwargs) -> LLMResponse:
        self.calls.append(kwargs)
        return LLMResponse(
            content="SELECT total FROM ventas WHERE organization_id = 'x'",
            model="fake-llm",
        )


class _VaryingSqlLLM:
    """LLM que devuelve un SQL distinto en cada repair (pero siempre falla)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate(self, **kwargs) -> LLMResponse:
        self.calls.append(kwargs)
        idx = len(self.calls)
        return LLMResponse(
            content=(
                f"SELECT total + {idx} AS total FROM ventas "
                f"WHERE organization_id = 'x' AND extra_{idx} = 1"
            ),
            model="fake-llm",
        )


class _ExecutionLoopExpert(PostgresSqlExpert):
    """El primer SQL pasa validación; los repairs vuelven a fallar validación."""

    def __init__(self, llm) -> None:
        super().__init__(llm)
        self._validated_count = 0

    async def _discover_sources(self, organization_id: UUID) -> list[DataSource]:
        return [
            DataSource(
                schema_name="public",
                table_name="ventas",
                columns=[
                    ColumnMeta(name="id", data_type="uuid", is_nullable=False),
                    ColumnMeta(name="total", data_type="numeric", is_nullable=False),
                ],
                row_count=1,
            )
        ]

    async def validate_sql(
        self, sql: str, sources: list[DataSource], role: str, organization_id: UUID
    ) -> str:
        self._validated_count += 1
        if self._validated_count == 1:
            return sql
        raise SqlValidationError("Unknown column TOTAL_EXTRA", sql)

    async def _run_query(self, sql: str) -> SqlQueryResult:
        return SqlQueryResult(sql=sql, error="Unknown column TOTAL")
