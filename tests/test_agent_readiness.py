# =============================================================================
# Agent Readiness + status computado + snapshot v2 + retrieval overrides
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.core.domain.entities import Agent, AgentStatus, AgentVersionStatus
from src.platform.agents.readiness import (
    READY_VERSION_STATUSES,
    AgentReadinessService,
)

ORG = UUID("00000000-0000-0000-0000-000000000001")
AGENT_ID = UUID("10000000-0000-0000-0000-000000000001")


def _agent(**overrides) -> Agent:
    base = dict(
        id=AGENT_ID,
        organization_id=ORG,
        name="Inventory Bot",
        system_prompt="Eres un asistente de inventario.",
        tools=["search_knowledge"],
        model="gpt-4o-mini",
        config_json={"temperature": 0.1, "knowledge_base_ids": [UUID("20000000-0000-0000-0000-000000000001")]},
    )
    base.update(overrides)
    return Agent(**base)


def _compute(**flags) -> int:
    defaults = dict(
        has_eval_dataset=True,
        has_healthy_deployment=False,
        has_ready_version=False,
        knowledge_configured=True,
        has_data_source=True,
        sql_expert_enabled=True,
    )
    defaults.update(flags)
    return AgentReadinessService.compute(_agent(), **defaults).score


class TestReadinessScore:
    def test_full_ready_agent_scores_100(self) -> None:
        assert _compute(
            has_healthy_deployment=True, has_ready_version=True
        ) == 100

    def test_draft_agent_scores_low(self) -> None:
        # Sin modelo ni prompt.
        agent = _agent(model=None, system_prompt=None, tools=[])
        result = AgentReadinessService.compute(
            agent,
            has_eval_dataset=False,
            has_healthy_deployment=False,
            has_ready_version=False,
            knowledge_configured=False,
            has_data_source=False,
            sql_expert_enabled=True,
        )
        assert result.score == 0
        assert all(not i.met for i in result.items if i.weight > 0)

    def test_weights_match_spec(self) -> None:
        agent = _agent()
        result = AgentReadinessService.compute(
            agent,
            has_eval_dataset=False,
            has_healthy_deployment=False,
            has_ready_version=False,
            knowledge_configured=False,
            has_data_source=False,
            sql_expert_enabled=True,
        )
        weights = {i.key: i.weight for i in result.items if i.weight > 0}
        assert weights == {
            "model": 15,
            "prompt": 15,
            "knowledge": 20,
            "datasource": 10,
            "evaluation": 10,
            "security": 10,
            "version": 10,
            "deployment": 10,
        }
        # model(15) + prompt(15) + security(10) = 40
        assert result.score == 40

    def test_checklist_shape(self) -> None:
        result = AgentReadinessService.compute(
            _agent(),
            has_eval_dataset=False,
            has_healthy_deployment=False,
            has_ready_version=False,
            knowledge_configured=False,
            has_data_source=False,
            sql_expert_enabled=True,
        )
        checklist = result.checklist()
        assert len(checklist) == 10
        assert all({"key", "label", "met", "weight", "detail"} <= set(c) for c in checklist)


class TestComputeStatus:
    def test_deployed_wins(self) -> None:
        agent = _agent(status=AgentStatus.READY)
        status = AgentReadinessService.compute_status(
            agent, has_healthy_deployment=True, has_ready_version=True
        )
        assert status == AgentStatus.DEPLOYED

    def test_archived_is_explicit(self) -> None:
        agent = _agent(status=AgentStatus.ARCHIVED)
        status = AgentReadinessService.compute_status(
            agent, has_healthy_deployment=True, has_ready_version=True
        )
        assert status == AgentStatus.ARCHIVED

    def test_ready_with_version(self) -> None:
        status = AgentReadinessService.compute_status(
            _agent(), has_healthy_deployment=False, has_ready_version=True
        )
        assert status == AgentStatus.READY

    def test_configured_with_model_and_prompt(self) -> None:
        status = AgentReadinessService.compute_status(
            _agent(), has_healthy_deployment=False, has_ready_version=False
        )
        assert status == AgentStatus.CONFIGURED

    def test_draft_without_configuration(self) -> None:
        status = AgentReadinessService.compute_status(
            _agent(model=None, system_prompt=None),
            has_healthy_deployment=False,
            has_ready_version=False,
        )
        assert status == AgentStatus.DRAFT

    def test_ready_version_statuses_set(self) -> None:
        assert READY_VERSION_STATUSES == {
            AgentVersionStatus.READY,
            AgentVersionStatus.STAGING,
            AgentVersionStatus.PRODUCTION,
        }


class TestSnapshotV2:
    def test_snapshot_includes_new_fields(self) -> None:
        from src.platform.deployments.versions import resolve_agent, snapshot_agent

        agent = _agent(
            config_json={
                "temperature": 0.1,
                "tone": "concise",
                "knowledge_base_ids": [UUID("20000000-0000-0000-0000-000000000001")],
                "limits": {"max_steps": 3},
                "security": {"sql_enabled": True},
                "retrieval": {"strategy": "hybrid", "top_k": 12},
                "guardrails": {"max_length": 800},
                "output_schema": {"product": "string", "stock": "integer"},
                "chunk_config": {"strategy": "recursive", "size": 800},
                "provider": "openai",
                "embedding_model": "openai/baai/bge-m3",
                "custom_flag": "extra",
            }
        )
        snapshot = snapshot_agent(agent)
        assert snapshot["schema_version"] == 2
        config = snapshot["config"]
        assert config["retrieval"] == {"strategy": "hybrid", "top_k": 12}
        assert config["guardrails"] == {"max_length": 800}
        assert config["output_schema"] == {"product": "string", "stock": "integer"}
        assert config["chunk_config"] == {"strategy": "recursive", "size": 800}
        assert config["provider"] == "openai"
        assert config["embedding_model"] == "openai/baai/bge-m3"
        assert snapshot["config_extra"] == {"custom_flag": "extra"}

        resolved = resolve_agent(agent, snapshot)
        assert resolved.config_json["retrieval"] == {"strategy": "hybrid", "top_k": 12}
        assert resolved.config_json["output_schema"] == {
            "product": "string",
            "stock": "integer",
        }
        assert resolved.config_json["custom_flag"] == "extra"

    def test_snapshot_v1_still_resolves(self) -> None:
        from src.platform.deployments.versions import resolve_agent

        agent = _agent()
        snapshot = {
            "system_prompt": "Prompt v1",
            "model": "gpt-4o",
            "tools": ["search_knowledge"],
            "config": {"temperature": 0.5},
            "config_extra": {"legacy": True},
            "schema_version": 1,
        }
        resolved = resolve_agent(agent, snapshot)
        assert resolved.system_prompt == "Prompt v1"
        assert resolved.model == "gpt-4o"
        assert resolved.config_json["temperature"] == 0.5
        assert resolved.config_json["legacy"] is True


class TestRetrievalOverrides:
    def test_search_knowledge_applies_agent_overrides(self) -> None:
        from src.agents.tools.base import ToolContext, ToolResult
        from src.agents.tools.tools_builtin import SearchKnowledgeTool

        captured: dict = {}

        class _FakeRetriever:
            async def retrieve(self, rquery):
                captured["top_k"] = rquery.top_k
                captured["strategy"] = rquery.strategy
                captured["score_threshold"] = rquery.score_threshold
                return type(
                    "RC",
                    (),
                    {"chunks": [], "query_embedding": [], "retrieval_latency_ms": 0},
                )()

        tool = SearchKnowledgeTool(_FakeRetriever())
        ctx = ToolContext(
            tenant_id=ORG,
            user_id=None,
            agent_config={"retrieval": {"strategy": "hybrid", "top_k": 3, "score_threshold": 0.4}},
        )
        result: ToolResult = tool.execute.__wrapped__(ctx, {"query": "stock", "top_k": 10}) if hasattr(tool.execute, "__wrapped__") else None
        if result is None:
            import asyncio

            result = asyncio.run(tool.execute(ctx, {"query": "stock", "top_k": 10}))
        assert captured["strategy"] == "hybrid"
        assert captured["top_k"] == 3  # min(10, 3)
        assert captured["score_threshold"] == 0.4

    def test_no_overrides_falls_back_to_defaults(self) -> None:
        import asyncio

        from src.agents.tools.base import ToolContext
        from src.agents.tools.tools_builtin import SearchKnowledgeTool

        captured: dict = {}

        class _FakeRetriever:
            async def retrieve(self, rquery):
                captured["top_k"] = rquery.top_k
                captured["strategy"] = rquery.strategy
                captured["score_threshold"] = rquery.score_threshold
                return type(
                    "RC",
                    (),
                    {"chunks": [], "query_embedding": [], "retrieval_latency_ms": 0},
                )()

        tool = SearchKnowledgeTool(_FakeRetriever())
        ctx = ToolContext(tenant_id=ORG, user_id=None, agent_config={})
        asyncio.run(tool.execute(ctx, {"query": "stock", "top_k": 10}))
        assert captured["top_k"] == 10
        assert captured["strategy"] == "vector"
        assert captured["score_threshold"] == 0.0
