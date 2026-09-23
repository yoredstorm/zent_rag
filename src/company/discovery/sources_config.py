# =============================================================================
# Company Discovery — fuentes de configuración (§2)
# =============================================================================
# La configuración declarada es observación directa, no inferencia:
#   Workflow USES Tool / USES Agent   (nodos del grafo del workflow)
#   Agent USES Tool / USES KnowledgeSource  (tools y config del agente)
#   Event TRIGGERS Workflow           (trigger_config del workflow)
#
# El proceso del workflow se emite como candidato DESIGNED: describe lo que la
# organización dice que hace, no necesariamente lo que ocurre (ver OBSERVED).
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.company.discovery.source_base import DiscoverySource
from src.company.discovery.source_loaders import load_agents, load_workflows
from src.company.discovery.sources_structured import _support
from src.core.domain.company_discovery import (
    CandidateKind,
    DiscoveryCandidate,
    DiscoveryEvidence,
    DiscoverySourceKind,
    EntityCandidatePayload,
    EntityRef,
    ProcessCandidatePayload,
    ProcessMode,
    ProcessStep,
    RelationshipCandidatePayload,
)

_TOOL_NODE_TYPES = frozenset({"tool", "tool_call", "sql", "sql_query", "http", "api"})
_AGENT_NODE_TYPES = frozenset({"agent", "agent_call", "agent_run", "subagent"})
_TOOL_CONFIG_KEYS = ("tool", "tool_name", "name", "tool_id")
_AGENT_CONFIG_KEYS = ("agent_id", "agent", "agent_name", "agent_ref")


def _normalize_nodes(graph: dict | None, steps: list | None) -> list[dict]:
    """Nodos del workflow en orden de definición (grafo v2 o pasos legacy)."""
    if isinstance(graph, dict) and graph.get("nodes"):
        nodes = graph.get("nodes") or []
        if isinstance(nodes, list):
            return [node for node in nodes if isinstance(node, dict)]
    if isinstance(steps, list):
        return [step for step in steps if isinstance(step, dict)]
    return []


def _node_label(node: dict) -> str:
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    for key in ("name", "label", "title", "id"):
        value = node.get(key) or config.get(key)
        if value:
            return str(value)[:120]
    return ""


def _first_config_value(config: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


class WorkflowConfigSource(DiscoverySource):
    """Configuración de workflows: procesos diseñados y uso de tools/agents."""

    source_kind = DiscoverySourceKind.WORKFLOW_CONFIG
    name = "workflow_config"

    def __init__(self, *, loader=load_workflows, max_items: int | None = None) -> None:
        super().__init__(max_items=max_items)
        self._load = loader

    async def discover(
        self, organization_id: UUID, *, workspace_id: UUID | None = None
    ) -> list[DiscoveryCandidate]:
        workflows = await self._load(organization_id, self.max_items)
        candidates: list[DiscoveryCandidate] = []
        for workflow in workflows:
            name = str(workflow.get("name") or "").strip()
            if not name:
                continue
            workflow_id = str(workflow.get("id"))
            nodes = _normalize_nodes(workflow.get("graph"), workflow.get("steps"))
            workflow_ref = EntityRef("workflow", name)

            candidates.append(
                self.build_candidate(
                    organization_id=organization_id,
                    kind=CandidateKind.ENTITY,
                    payload=EntityCandidatePayload(
                        entity_type="workflow",
                        canonical_name=name,
                        display_name=name,
                        description=str(workflow.get("description") or ""),
                        domain="automation",
                        keyword=name.lower(),
                    ).to_dict(),
                    title=name,
                    summary="workflow declared in configuration",
                    support=_support(),
                    evidence=DiscoveryEvidence(
                        source_kind=self.source_kind,
                        ref=workflow_id,
                        detail={"trigger_type": workflow.get("trigger_type")},
                    ),
                    workspace_id=workspace_id,
                )
            )

            steps: list[ProcessStep] = []
            for index, node in enumerate(nodes):
                label = _node_label(node)
                node_type = str(node.get("type") or "").lower()
                config = node.get("config") if isinstance(node.get("config"), dict) else {}
                if label:
                    steps.append(
                        ProcessStep(name=label, order=index, documented=True)
                    )
                if node_type in _TOOL_NODE_TYPES:
                    tool_name = _first_config_value(
                        {**config, "name": str(node.get("name") or "")},
                        _TOOL_CONFIG_KEYS,
                    )
                    if tool_name:
                        candidates.append(
                            self._uses_candidate(
                                organization_id,
                                from_ref=workflow_ref,
                                to_ref=EntityRef("tool", tool_name),
                                ref=f"{workflow_id}:{index}",
                                workspace_id=workspace_id,
                            )
                        )
                elif node_type in _AGENT_NODE_TYPES:
                    agent_name = _first_config_value(config, _AGENT_CONFIG_KEYS)
                    if agent_name:
                        candidates.append(
                            self._uses_candidate(
                                organization_id,
                                from_ref=workflow_ref,
                                to_ref=EntityRef("agent", agent_name),
                                ref=f"{workflow_id}:{index}",
                                workspace_id=workspace_id,
                            )
                        )

            process_payload = ProcessCandidatePayload(
                name=name,
                mode=ProcessMode.DESIGNED,
                steps=tuple(steps),
                systems=(),
                workflow_id=workflow_id,
            )
            candidates.append(
                self.build_candidate(
                    organization_id=organization_id,
                    kind=CandidateKind.PROCESS,
                    payload=process_payload.to_dict(),
                    title=f"DESIGNED process: {name}",
                    summary="process defined in workflow configuration",
                    support=_support(),
                    evidence=DiscoveryEvidence(
                        source_kind=self.source_kind,
                        ref=workflow_id,
                        detail={"nodes": len(nodes)},
                    ),
                    workspace_id=workspace_id,
                )
            )

            trigger_config = (
                workflow.get("trigger_config")
                if isinstance(workflow.get("trigger_config"), dict)
                else {}
            )
            event_type = str(trigger_config.get("event_type") or "").strip()
            if event_type:
                candidates.append(
                    self.build_candidate(
                        organization_id=organization_id,
                        kind=CandidateKind.RELATIONSHIP,
                        payload=RelationshipCandidatePayload(
                            from_ref=EntityRef("event", event_type),
                            to_ref=workflow_ref,
                            relationship_type="TRIGGERS",
                            observed=True,
                        ).to_dict(),
                        title=f"{event_type} TRIGGERS {name}",
                        summary="event trigger declared in workflow config",
                        support=_support(),
                        evidence=DiscoveryEvidence(
                            source_kind=self.source_kind,
                            ref=workflow_id,
                            detail={"event_type": event_type},
                        ),
                        workspace_id=workspace_id,
                    )
                )
        return candidates

    def _uses_candidate(
        self,
        organization_id: UUID,
        *,
        from_ref: EntityRef,
        to_ref: EntityRef,
        ref: str,
        workspace_id: UUID | None,
    ) -> DiscoveryCandidate:
        return self.build_candidate(
            organization_id=organization_id,
            kind=CandidateKind.RELATIONSHIP,
            payload=RelationshipCandidatePayload(
                from_ref=from_ref, to_ref=to_ref, relationship_type="USES"
            ).to_dict(),
            title=f"{from_ref.canonical_name} USES {to_ref.canonical_name}",
            summary="declared usage in configuration",
            support=_support(),
            evidence=DiscoveryEvidence(source_kind=self.source_kind, ref=ref),
            workspace_id=workspace_id,
        )


class AgentConfigSource(DiscoverySource):
    """Configuración de agentes: Agent USES Tool / KnowledgeSource."""

    source_kind = DiscoverySourceKind.AGENT_CONFIG
    name = "agent_config"

    def __init__(self, *, loader=load_agents, max_items: int | None = None) -> None:
        super().__init__(max_items=max_items)
        self._load = loader

    async def discover(
        self, organization_id: UUID, *, workspace_id: UUID | None = None
    ) -> list[DiscoveryCandidate]:
        agents = await self._load(organization_id, self.max_items)
        candidates: list[DiscoveryCandidate] = []
        for agent in agents:
            name = str(agent.get("name") or "").strip()
            if not name:
                continue
            agent_id = str(agent.get("id"))
            agent_ref = EntityRef("agent", name)
            candidates.append(
                self.build_candidate(
                    organization_id=organization_id,
                    kind=CandidateKind.ENTITY,
                    payload=EntityCandidatePayload(
                        entity_type="agent",
                        canonical_name=name,
                        display_name=name,
                        description=str(agent.get("description") or ""),
                        domain="automation",
                        keyword=name.lower(),
                    ).to_dict(),
                    title=name,
                    summary="agent declared in configuration",
                    support=_support(),
                    evidence=DiscoveryEvidence(source_kind=self.source_kind, ref=agent_id),
                    workspace_id=workspace_id,
                )
            )
            for tool in agent.get("tools") or ():
                tool_name = str(tool).strip()
                if not tool_name:
                    continue
                candidates.append(
                    self.build_candidate(
                        organization_id=organization_id,
                        kind=CandidateKind.RELATIONSHIP,
                        payload=RelationshipCandidatePayload(
                            from_ref=agent_ref,
                            to_ref=EntityRef("tool", tool_name),
                            relationship_type="USES",
                        ).to_dict(),
                        title=f"{name} USES {tool_name}",
                        summary="tool enabled for the agent",
                        support=_support(),
                        evidence=DiscoveryEvidence(
                            source_kind=self.source_kind,
                            ref=agent_id,
                            detail={"tool": tool_name},
                        ),
                        workspace_id=workspace_id,
                    )
                )
            config = agent.get("config_json") if isinstance(agent.get("config_json"), dict) else {}
            for key in ("knowledge_base_ids", "knowledge_bases", "kb_ids"):
                for kb in config.get(key) or ():
                    kb_name = str(kb).strip()
                    if not kb_name:
                        continue
                    candidates.append(
                        self.build_candidate(
                            organization_id=organization_id,
                            kind=CandidateKind.RELATIONSHIP,
                            payload=RelationshipCandidatePayload(
                                from_ref=agent_ref,
                                to_ref=EntityRef("knowledge_source", f"knowledge_base:{kb_name}"),
                                relationship_type="USES",
                            ).to_dict(),
                            title=f"{name} USES knowledge_base:{kb_name}",
                            summary="knowledge base enabled for the agent",
                            support=_support(),
                            evidence=DiscoveryEvidence(
                                source_kind=self.source_kind,
                                ref=agent_id,
                                detail={"knowledge_base": kb_name},
                            ),
                            workspace_id=workspace_id,
                        )
                    )
        return candidates
