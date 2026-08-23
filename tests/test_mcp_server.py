# =============================================================================
# MCP Server — tests de integración (transporte real, backends fake)
# =============================================================================
# El transporte Streamable HTTP corre de verdad (lifespan incluido) montado
# en la app FastAPI; los middlewares de la API (Tenant, RateLimit) aplican
# tal cual. Los backends de las tools se fakean vía monkeypatch de McpDeps.
#
# Nota: el lifespan se abre/cierra DENTRO del cuerpo del test (async with):
# el task group de anyio del transporte MCP exige entrar y salir en la misma
# task, cosa que pytest-asyncio no garantiza entre setup y teardown.
# =============================================================================
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.core.domain.entities import (
    Agent,
    Organization,
    RetrievalChunk,
    RetrievalContext,
)
from src.core.ports.sql_expert import SqlQueryResult

MCP_PATH = "/mcp/"


@asynccontextmanager
async def mcp_client_ctx():
    """Cliente HTTP contra una app FastAPI fresca con lifespan (MCP incluido).

    Métricas/tracing apagados: los registros globales de Prometheus/OTel no
    soportan instanciar la app varias veces por sesión de pytest.
    """
    from src.api.main import create_app

    app = create_app(metrics_enabled=False, tracing_enabled=False)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


def _parse_sse(content: bytes) -> list[dict]:
    out: list[dict] = []
    for line in content.decode().splitlines():
        if line.startswith("data: "):
            out.append(json.loads(line[6:]))
    return out


async def _rpc_call(client: AsyncClient, method: str, params: dict | None, headers: dict) -> dict:
    payload: dict = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    resp = await client.post(MCP_PATH, json=payload, headers=headers)
    messages = _parse_sse(resp.content)
    assert messages, f"no SSE message (status {resp.status_code}): {resp.content[:300]}"
    return messages[0]


async def _tool_call(client: AsyncClient, name: str, arguments: dict, headers: dict) -> dict:
    return await _rpc_call(
        client,
        "tools/call",
        {"name": name, "arguments": arguments},
        headers,
    )


def _tool_result(msg: dict) -> dict:
    """Resultado estructurado de la tool (el SDK serializa el dict a JSON)."""
    assert "error" not in msg, msg
    assert msg["result"].get("isError") is False, msg
    result = msg["result"]
    if "structuredContent" in result:
        return result["structuredContent"]["result"]
    content = result["content"]
    assert content and content[0]["type"] == "text", msg
    return json.loads(content[0]["text"])


# -----------------------------------------------------------------------------
# Fakes de backends
# -----------------------------------------------------------------------------
class FakeRetriever:
    def __init__(self, chunks: list[RetrievalChunk]) -> None:
        self._chunks = chunks
        self.queries: list = []

    async def retrieve(self, query):
        self.queries.append(query)
        return RetrievalContext(
            chunks=self._chunks,
            query_embedding=query.query_embedding,
            retrieval_latency_ms=3.0,
        )


class FakeSqlExpert:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def execute(self, **kwargs) -> SqlQueryResult:
        self.calls.append(kwargs)
        return SqlQueryResult(
            sql="SELECT 1",
            columns=["col_a"],
            rows=[["x"]],
            row_count=1,
            truncated=False,
            error=None,
            cost=0.001,
        )


class FakeVectorStore:
    def __init__(self, chunks: list[RetrievalChunk]) -> None:
        self._chunks = chunks
        self.calls: list[dict] = []

    async def get_documents(self, organization_id, document_ids, role="admin"):
        self.calls.append(
            {
                "organization_id": organization_id,
                "document_ids": document_ids,
                "role": role,
            }
        )
        return RetrievalContext(chunks=self._chunks, retrieval_latency_ms=1.0)


class FakeAgentRepo:
    def __init__(self) -> None:
        self._agent: Agent | None = None

    async def get_agent(self, organization_id, agent_id):
        return self._agent


class FakeAgentRuntime:
    def __init__(self) -> None:
        self.requests: list = []

    async def run(self, request):
        from src.agents.runtime.agent_runtime import AgentRunResult

        self.requests.append(request)
        return AgentRunResult(
            run_id=uuid4(),
            agent_id=request.agent.id,
            organization_id=request.agent.organization_id,
            status="completed",
            answer="respuesta del agente fake",
            message=request.message,
            user_id=request.user_id,
            role=request.role,
            steps=[{"type": "final", "answer": "ok"}],
            total_latency_ms=42.0,
            total_tokens=10,
            cost=0.0001,
            injection_detected=False,
        )


class FakeOrgRepo:
    def __init__(self, config_json: dict | None = None) -> None:
        self.config_json = dict(config_json or {})

    async def get_by_id(self, organization_id) -> Organization | None:
        return Organization(
            id=organization_id,
            name="fake-org",
            config_json=dict(self.config_json),
        )


class FakeCache:
    """CacheProvider en memoria con contador por clave (rate limits)."""

    def __init__(self) -> None:
        self.counters: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return None

    async def set(self, key: str, value: str, ttl_seconds: int = 300) -> None:
        self.counters[key] = int(value)

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool:
        return key in self.counters

    async def append_to_list(self, key: str, value: str, ttl_seconds: int = 3600) -> None: ...

    async def get_list(self, key: str) -> list[str]:
        return []

    async def trim_list(self, key: str, max_items: int) -> None: ...

    async def incr(self, key: str, ttl_seconds=None, by: int = 1) -> int:
        self.counters[key] = self.counters.get(key, 0) + by
        return self.counters[key]


class FakeAuditRepo:
    """Captura AuditLogEntry sin tocar Postgres."""

    def __init__(self) -> None:
        self.entries: list = []

    async def write(self, entry) -> None:
        self.entries.append(entry)

    async def list_entries(self, *args, **kwargs) -> list:
        return []


class _FakeEmbedding:
    async def embed(self, text, model=None):
        return [0.1, 0.2, 0.3]


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------
@pytest.fixture
def fake_deps(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Instala fakes de backends de las tools MCP y retorna un handle."""
    from src.mcp_server.backends import McpDeps

    chunks = [
        RetrievalChunk(
            document_id=uuid4(),
            content="paracetamol 500mg",
            score=0.92,
            metadata={"visibility": "public"},
        )
    ]
    handle = {
        "retriever": FakeRetriever(chunks),
        "sql_expert": FakeSqlExpert(),
        "vector_store": FakeVectorStore(chunks),
        "agent_repo": FakeAgentRepo(),
        "agent_runtime": FakeAgentRuntime(),
        "org_repo": FakeOrgRepo(),
        "cache": FakeCache(),
    }
    monkeypatch.setattr(McpDeps, "retriever", lambda self: handle["retriever"])
    monkeypatch.setattr(McpDeps, "sql_expert", lambda self: handle["sql_expert"])
    monkeypatch.setattr(McpDeps, "vector_store", lambda self: handle["vector_store"])
    monkeypatch.setattr(McpDeps, "agent_repo", lambda self: handle["agent_repo"])
    monkeypatch.setattr(McpDeps, "agent_runtime", lambda self: handle["agent_runtime"])
    monkeypatch.setattr(McpDeps, "organization_repo", lambda self: handle["org_repo"])
    monkeypatch.setattr(McpDeps, "cache", lambda self: handle["cache"])
    monkeypatch.setattr(McpDeps, "embedding", lambda self: _FakeEmbedding())
    return handle


@pytest.fixture
def capture_audit(monkeypatch: pytest.MonkeyPatch) -> FakeAuditRepo:
    """Captura las entradas de auditoría MCP en memoria."""
    repo = FakeAuditRepo()
    import src.infrastructure.postgres.relational_db as relational_db

    monkeypatch.setattr(relational_db, "PostgresAuditLogRepository", lambda: repo)
    return repo


@pytest.fixture
async def full_scoped_token(trial_auth: dict[str, str]) -> str:
    """API key del trial con TODOS los scopes públicos (para tools como
    execute_agent/agents:execute y get_usage/usage:read)."""
    from src.infrastructure.postgres.relational_db import (
        PostgresApiKeyRepository,
        PostgresBillingRepository,
    )
    from src.platform.billing.service import BillingService

    billing = BillingService(PostgresBillingRepository(), PostgresApiKeyRepository())
    return await billing.create_api_key(
        UUID(trial_auth["X-Organization-Id"]),
        name="mcp-full",
        scopes=[
            "rag:read",
            "rag:write",
            "agents:execute",
            "usage:read",
            "connectors:read",
            "connectors:write",
        ],
    )


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------
class TestMcpAuth:
    async def test_mcp_requires_bearer(self) -> None:
        async with mcp_client_ctx() as client:
            resp = await client.post(
                MCP_PATH,
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
            assert resp.status_code == 401

    async def test_mcp_rejects_invalid_token(self) -> None:
        async with mcp_client_ctx() as client:
            resp = await client.post(
                MCP_PATH,
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers={"Authorization": "Bearer not-a-real-token"},
            )
            assert resp.status_code == 401

    async def test_initialize_and_list_tools(self, trial_auth: dict[str, str]) -> None:
        async with mcp_client_ctx() as client:
            headers = {"Authorization": trial_auth["Authorization"]}
            init = await _rpc_call(
                client,
                "initialize",
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "1.0"},
                },
                headers,
            )
            assert "result" in init
            listed = await _rpc_call(client, "tools/list", None, headers)
            names = {t["name"] for t in listed["result"]["tools"]}
            assert names == {
                "search_knowledge",
                "query_database",
                "get_document",
                "execute_agent",
                "get_usage",
            }


class TestMcpTools:
    async def test_search_knowledge_scoped_to_tenant(
        self,
        trial_auth: dict[str, str],
        fake_deps: dict,
    ) -> None:
        async with mcp_client_ctx() as client:
            headers = {"Authorization": trial_auth["Authorization"]}
            msg = await _tool_call(
                client,
                "search_knowledge",
                {"query": "paracetamol", "top_k": 3},
                headers,
            )
            result = _tool_result(msg)
            assert result["count"] == 1
            assert result["chunks"][0]["content"] == "paracetamol 500mg"
            called = fake_deps["retriever"].queries[0]
            assert called.organization_id == UUID(trial_auth["X-Organization-Id"])

    async def test_query_database_exposes_sql_only_to_admin(
        self,
        trial_auth: dict[str, str],
        fake_deps: dict,
    ) -> None:
        async with mcp_client_ctx() as client:
            headers = {"Authorization": trial_auth["Authorization"]}
            msg = await _tool_call(
                client, "query_database", {"question": "ventas enero"}, headers
            )
            result = _tool_result(msg)
            assert result["row_count"] == 1
            assert result["sql"] == "SELECT 1"
            called = fake_deps["sql_expert"].calls[0]
            assert called["organization_id"] == UUID(trial_auth["X-Organization-Id"])

    async def test_get_document_passes_org_to_vector_store(
        self,
        trial_auth: dict[str, str],
        fake_deps: dict,
    ) -> None:
        async with mcp_client_ctx() as client:
            doc_id = str(uuid4())
            headers = {"Authorization": trial_auth["Authorization"]}
            msg = await _tool_call(client, "get_document", {"document_ids": [doc_id]}, headers)
            assert _tool_result(msg)["count"] == 1
            called = fake_deps["vector_store"].calls[0]
            assert called["organization_id"] == UUID(trial_auth["X-Organization-Id"])
            assert called["document_ids"] == [UUID(doc_id)]

    async def test_get_document_rejects_invalid_id(
        self,
        trial_auth: dict[str, str],
        fake_deps: dict,
    ) -> None:
        async with mcp_client_ctx() as client:
            headers = {"Authorization": trial_auth["Authorization"]}
            msg = await _tool_call(client, "get_document", {"document_ids": ["nope"]}, headers)
            assert msg["result"].get("isError") is True

    async def test_execute_agent_runs_with_tenant_permissions(
        self,
        trial_auth: dict[str, str],
        full_scoped_token: str,
        fake_deps: dict,
    ) -> None:
        async with mcp_client_ctx() as client:
            agent_id = uuid4()
            fake_deps["agent_repo"]._agent = Agent(
                id=agent_id,
                organization_id=UUID(trial_auth["X-Organization-Id"]),
                name="fake-agent",
                tools=["search_knowledge"],
            )
            headers = {"Authorization": f"Bearer {full_scoped_token}"}
            msg = await _tool_call(
                client,
                "execute_agent",
                {"agent_id": str(agent_id), "message": "hola"},
                headers,
            )
            result = _tool_result(msg)
            assert result["status"] == "completed"
            assert result["answer"] == "respuesta del agente fake"
            request = fake_deps["agent_runtime"].requests[0]
            assert request.agent.organization_id == UUID(trial_auth["X-Organization-Id"])

    async def test_execute_agent_unknown_agent(
        self,
        full_scoped_token: str,
        fake_deps: dict,
    ) -> None:
        async with mcp_client_ctx() as client:
            headers = {"Authorization": f"Bearer {full_scoped_token}"}
            msg = await _tool_call(
                client,
                "execute_agent",
                {"agent_id": str(uuid4()), "message": "hola"},
                headers,
            )
            assert msg["result"].get("isError") is True

    async def test_get_usage_returns_aggregates(
        self,
        full_scoped_token: str,
        fake_deps: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def fake_usage(organization_id, *, days=30, limit=50):
            return {
                "organization_id": str(organization_id),
                "days": days,
                "totals": {
                    "requests": 7,
                    "tokens": 100,
                    "avg_latency_ms": 1.0,
                    "estimated_cost": 0.01,
                },
                "daily": [],
                "recent": [],
            }

        monkeypatch.setattr(
            "src.platform.usage.aggregation.get_organization_usage", fake_usage
        )
        async with mcp_client_ctx() as client:
            headers = {"Authorization": f"Bearer {full_scoped_token}"}
            msg = await _tool_call(client, "get_usage", {"days": 7}, headers)
            assert _tool_result(msg)["totals"]["requests"] == 7


class TestMcpPolicy:
    async def test_tool_denied_by_permission(
        self,
        trial_auth: dict[str, str],
        fake_deps: dict,
        capture_audit: FakeAuditRepo,
    ) -> None:
        from src.infrastructure.postgres.relational_db import (
            PostgresApiKeyRepository,
            PostgresBillingRepository,
        )
        from src.platform.billing.service import BillingService

        billing = BillingService(PostgresBillingRepository(), PostgresApiKeyRepository())
        org_uuid = UUID(trial_auth["X-Organization-Id"])
        token = await billing.create_api_key(org_uuid, name="usage-only", scopes=["usage:read"])
        async with mcp_client_ctx() as client:
            msg = await _tool_call(
                client,
                "search_knowledge",
                {"query": "x"},
                {"Authorization": f"Bearer {token}"},
            )
            assert msg["result"].get("isError") is True
        denied = [e for e in capture_audit.entries if e.metadata.get("result") == "denied"]
        assert denied, "expected a denied audit entry"
        assert denied[0].metadata["tool"] == "search_knowledge"
        assert denied[0].metadata["error_code"] == "permission_denied"

    async def test_org_policy_disables_tool(
        self,
        trial_auth: dict[str, str],
        fake_deps: dict,
        capture_audit: FakeAuditRepo,
    ) -> None:
        fake_deps["org_repo"].config_json = {
            "mcp": {"tools": {"search_knowledge": {"enabled": False}}}
        }
        async with mcp_client_ctx() as client:
            headers = {"Authorization": trial_auth["Authorization"]}
            msg = await _tool_call(client, "search_knowledge", {"query": "x"}, headers)
            assert msg["result"].get("isError") is True
        denied = [e for e in capture_audit.entries if e.metadata.get("result") == "denied"]
        assert denied and denied[0].metadata["error_code"] == "tool_disabled"

    async def test_org_policy_disables_mcp_entirely(
        self,
        trial_auth: dict[str, str],
        fake_deps: dict,
        capture_audit: FakeAuditRepo,
    ) -> None:
        fake_deps["org_repo"].config_json = {"mcp": {"enabled": False}}
        async with mcp_client_ctx() as client:
            headers = {"Authorization": trial_auth["Authorization"]}
            msg = await _tool_call(client, "search_knowledge", {"query": "x"}, headers)
            assert msg["result"].get("isError") is True
        denied = [e for e in capture_audit.entries if e.metadata.get("result") == "denied"]
        assert denied and denied[0].metadata["error_code"] == "mcp_disabled"

    async def test_per_tool_rate_limit(
        self,
        trial_auth: dict[str, str],
        fake_deps: dict,
        capture_audit: FakeAuditRepo,
    ) -> None:
        fake_deps["org_repo"].config_json = {
            "mcp": {"tools": {"search_knowledge": {"rpm": 2}}}
        }
        async with mcp_client_ctx() as client:
            headers = {"Authorization": trial_auth["Authorization"]}
            for _ in range(2):
                msg = await _tool_call(client, "search_knowledge", {"query": "x"}, headers)
                assert msg["result"].get("isError") is False
            msg = await _tool_call(client, "search_knowledge", {"query": "x"}, headers)
            assert msg["result"].get("isError") is True
        denied = [e for e in capture_audit.entries if e.metadata.get("result") == "denied"]
        assert denied and denied[-1].metadata["error_code"] == "rate_limited"

    async def test_audit_records_ok_call(
        self,
        trial_auth: dict[str, str],
        fake_deps: dict,
        capture_audit: FakeAuditRepo,
    ) -> None:
        async with mcp_client_ctx() as client:
            headers = {
                "Authorization": trial_auth["Authorization"],
                "X-Zent-MCP-Client": "cursor/1.2",
            }
            await _tool_call(client, "search_knowledge", {"query": "x"}, headers)
        ok_entries = [e for e in capture_audit.entries if e.metadata.get("result") == "ok"]
        assert ok_entries
        entry = ok_entries[0]
        assert entry.action == "mcp.tool_call"
        assert entry.resource_type == "mcp_tool"
        assert entry.organization_id == UUID(trial_auth["X-Organization-Id"])
        assert entry.metadata["tool"] == "search_knowledge"
        assert entry.metadata["mcp_client"] == "cursor/1.2"
        assert entry.metadata["role"] == "admin"
        assert entry.metadata["retrieval_count"] == 1
