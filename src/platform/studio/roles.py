# =============================================================================
# Role profiles — identity + boundaries for the existing Agent runtime.
#
# This module does NOT execute agents or workflows. It stores a portable role
# contract, versions it, links an Agent to it, and narrows the Agent's tools.
# Effective authority is always an intersection, never a role grant.
# =============================================================================
from __future__ import annotations

import json
from dataclasses import replace
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.platform.studio.contracts import (
    RoleProfileV1,
    role_from_legacy_payload,
    scan_contract_secrets,
)
from src.platform.studio.templates import (
    match_role_template,
    role_template,
    workflow_proposal,
)

logger = get_logger(__name__)

_TABLE_SQL = (
    """
    CREATE TABLE IF NOT EXISTS role_profiles (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        workspace_id UUID,
        slug VARCHAR(80) NOT NULL,
        name VARCHAR(150) NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        mission TEXT NOT NULL DEFAULT '',
        audience JSONB NOT NULL DEFAULT '[]'::jsonb,
        tone JSONB NOT NULL DEFAULT '[]'::jsonb,
        competencies JSONB NOT NULL DEFAULT '[]'::jsonb,
        constraints JSONB NOT NULL DEFAULT '[]'::jsonb,
        allowed_capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
        denied_capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
        allowed_tools JSONB NOT NULL DEFAULT '[]'::jsonb,
        knowledge_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
        memory_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
        autonomy_level VARCHAR(30) NOT NULL DEFAULT 'propose_actions',
        human_handoff JSONB NOT NULL DEFAULT '{}'::jsonb,
        expected_outcomes JSONB NOT NULL DEFAULT '[]'::jsonb,
        evaluation_rubric JSONB NOT NULL DEFAULT '[]'::jsonb,
        risk_class VARCHAR(20) NOT NULL DEFAULT 'low',
        locales JSONB NOT NULL DEFAULT '["es"]'::jsonb,
        compliance_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
        safety JSONB NOT NULL DEFAULT '{}'::jsonb,
        version VARCHAR(20) NOT NULL DEFAULT '1.0.0',
        revision INT NOT NULL DEFAULT 1,
        status VARCHAR(20) NOT NULL DEFAULT 'draft',
        created_by UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (organization_id, slug)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_role_profiles_org
    ON role_profiles(organization_id, workspace_id, updated_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS role_profile_versions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        role_profile_id UUID NOT NULL REFERENCES role_profiles(id) ON DELETE CASCADE,
        organization_id UUID NOT NULL,
        version VARCHAR(20) NOT NULL,
        revision INT NOT NULL,
        snapshot JSONB NOT NULL,
        notes TEXT,
        created_by UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (role_profile_id, revision)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_role_profile_versions_role
    ON role_profile_versions(role_profile_id, revision DESC)
    """,
    """
    ALTER TABLE agents ADD COLUMN IF NOT EXISTS role_profile_id UUID
    """,
    """
    DO $$
    BEGIN
        ALTER TABLE agents
            ADD CONSTRAINT fk_agents_role_profile_id
            FOREIGN KEY (role_profile_id)
            REFERENCES role_profiles(id)
            ON DELETE SET NULL;
    EXCEPTION
        WHEN duplicate_object THEN NULL;
    END $$
    """,
)

_READ_ONLY_TOOLS = frozenset({"search_knowledge", "query_tabular_data", "query_database"})
_CAPABILITY_TOOL_HINTS: dict[str, set[str]] = {
    "knowledge_query": {"search_knowledge"},
    "node.kb_query": {"search_knowledge"},
    "query_business_data": {"query_database", "query_tabular_data"},
    "conversation.send": {"call_api"},
    "catalog.products.search": {"query_database"},
}
_schema_ready = False


class RoleError(ValueError):
    pass


class RoleConflict(RoleError):
    pass


class RoleNotFound(RoleError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _row_value(row: Any, key: str, default: Any) -> Any:
    value = getattr(row, key, default)
    return default if value is None else value


async def ensure_role_tables() -> None:
    global _schema_ready
    if _schema_ready:
        return
    session = await get_async_session()
    try:
        for statement in _TABLE_SQL:
            await session.execute(text(statement))
        await session.commit()
        _schema_ready = True
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def _role_payload(row: Any, *, status: str | None = None) -> dict[str, Any]:
    return {
        "schema": "zent.role/v1",
        "record_id": str(row.id),
        "role_id": str(row.slug),
        "version": str(row.version),
        "status": status or str(row.status),
        "name": str(row.name),
        "display_name": str(row.name),
        "description": str(row.description or ""),
        "mission": str(row.mission or ""),
        "audience": list(_row_value(row, "audience", []) or []),
        "tone": list(_row_value(row, "tone", []) or []),
        "competencies": list(_row_value(row, "competencies", []) or []),
        "constraints": list(_row_value(row, "constraints", []) or []),
        "allowed_capabilities": list(_row_value(row, "allowed_capabilities", []) or []),
        "denied_capabilities": list(_row_value(row, "denied_capabilities", []) or []),
        "allowed_tools": list(_row_value(row, "allowed_tools", []) or []),
        "knowledge_scope": dict(_row_value(row, "knowledge_scope", {}) or {}),
        "memory_policy": dict(_row_value(row, "memory_policy", {}) or {}),
        "autonomy_level": str(row.autonomy_level),
        "human_handoff": dict(_row_value(row, "human_handoff", {}) or {}),
        "expected_outcomes": list(_row_value(row, "expected_outcomes", []) or []),
        "evaluation_rubric": list(_row_value(row, "evaluation_rubric", []) or []),
        "risk_class": str(row.risk_class),
        "locales": list(_row_value(row, "locales", ["es"]) or ["es"]),
        "compliance_tags": list(_row_value(row, "compliance_tags", []) or []),
        "safety": dict(_row_value(row, "safety", {}) or {}),
    }


def _bump_version(version: str) -> str:
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return "1.0.1"
    major, minor, patch = (int(part) for part in parts)
    return f"{major}.{minor}.{patch + 1}"


def mission_sheet(role: RoleProfileV1) -> dict[str, Any]:
    """Human sheet: what it will do, what it must not do, and when it hands off."""
    will_not = list(role.constraints)
    if role.safety.no_medical_diagnosis:
        will_not.append("No diagnostica ni sustituye atención clínica.")
    if role.safety.no_psychotherapy_claim:
        will_not.append("No se presenta como psicoterapia.")
    if role.safety.no_legal_advice:
        will_not.append("No emite asesoría legal vinculante.")
    if role.safety.no_financial_advice:
        will_not.append("No emite asesoría financiera personalizada.")
    if role.safety.no_automatic_irreversible_action:
        will_not.append("No ejecuta acciones irreversibles sin aprobación.")
    return {
        "role_id": role.role_id,
        "name": role.name,
        "mission": role.mission,
        "audience": role.audience,
        "will_do": [competency.name for competency in role.competencies] or [role.mission],
        "will_not_do": will_not or ["No actúa fuera de su misión declarada."],
        "autonomy_level": role.autonomy_level,
        "needs": {
            "capabilities": role.allowed_capabilities,
            "tools": role.allowed_tools,
            "knowledge_scope": role.knowledge_scope.model_dump(mode="json"),
        },
        "handoff": role.human_handoff.model_dump(mode="json"),
        "outcomes": [item.model_dump(mode="json") for item in role.expected_outcomes],
        "disclaimer": role.safety.disclaimer,
    }


async def propose_role(prompt: str, *, template_id: str | None = None) -> dict[str, Any]:
    text_prompt = " ".join(str(prompt or "").split())[:2000]
    template_key = str(template_id or "").strip()
    score = 0
    if not template_key:
        template_key, score = match_role_template(text_prompt)
    role = role_template(template_key)
    if role is None:
        raise RoleError(f"template de rol inexistente: {template_key}")
    payload = role.model_dump(by_alias=True)
    payload["status"] = "draft"
    payload["mission"] = (text_prompt or role.mission)[:1200]
    payload["name"] = (text_prompt.split(".")[0] or role.name)[:150]
    payload["display_name"] = payload["name"]
    draft = RoleProfileV1.model_validate(payload)
    return {
        "source": "template",
        "template_id": template_key,
        "confidence": min(1.0, score / 5.0) if score else 0.0,
        "role": payload,
        "mission_sheet": mission_sheet(draft),
        "workflow_proposal": workflow_proposal(template_key),
        "requires_review": True,
        "publishable": False,
    }


async def create_role(
    organization_id: UUID,
    *,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    await ensure_role_tables()
    role = RoleProfileV1.model_validate(payload)
    if scan_contract_secrets(role.model_dump(by_alias=True)):
        raise RoleError("el rol contiene secretos o IDs de tenant")
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO role_profiles (organization_id, workspace_id, slug, name, "
                    "description, mission, audience, tone, competencies, constraints, "
                    "allowed_capabilities, denied_capabilities, allowed_tools, knowledge_scope, "
                    "memory_policy, autonomy_level, human_handoff, expected_outcomes, "
                    "evaluation_rubric, risk_class, locales, compliance_tags, safety, version, "
                    "revision, status, created_by) VALUES (:oid, :ws, :slug, :name, :desc, :mission, "
                    "CAST(:aud AS jsonb), CAST(:tone AS jsonb), CAST(:comp AS jsonb), "
                    "CAST(:cons AS jsonb), CAST(:caps AS jsonb), CAST(:denied AS jsonb), "
                    "CAST(:tools AS jsonb), CAST(:ks AS jsonb), CAST(:mem AS jsonb), :autonomy, "
                    "CAST(:handoff AS jsonb), CAST(:outcomes AS jsonb), CAST(:rubric AS jsonb), "
                    ":risk, CAST(:locales AS jsonb), CAST(:tags AS jsonb), CAST(:safety AS jsonb), "
                    ":version, 1, :status, :uid) RETURNING *"
                ),
                {
                    "oid": organization_id,
                    "ws": workspace_id,
                    "slug": role.role_id,
                    "name": role.name,
                    "desc": role.description,
                    "mission": role.mission,
                    "aud": _json(role.audience),
                    "tone": _json(role.tone),
                    "comp": _json([item.model_dump(mode="json") for item in role.competencies]),
                    "cons": _json(role.constraints),
                    "caps": _json(role.allowed_capabilities),
                    "denied": _json(role.denied_capabilities),
                    "tools": _json(role.allowed_tools),
                    "ks": _json(role.knowledge_scope.model_dump(mode="json")),
                    "mem": _json(role.memory_policy.model_dump(mode="json")),
                    "autonomy": role.autonomy_level,
                    "handoff": _json(role.human_handoff.model_dump(mode="json")),
                    "outcomes": _json([item.model_dump(mode="json") for item in role.expected_outcomes]),
                    "rubric": _json([item.model_dump(mode="json") for item in role.evaluation_rubric]),
                    "risk": role.risk_class,
                    "locales": _json(role.locales),
                    "tags": _json(role.compliance_tags),
                    "safety": _json(role.safety.model_dump(mode="json")),
                    "version": role.version,
                    "status": role.status,
                    "uid": user_id,
                },
            )
        ).fetchone()
        await _insert_version(session, row, notes="created", created_by=user_id)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        if "uq_role_profiles" in str(exc).lower() or "duplicate" in str(exc).lower():
            raise RoleConflict(f"role_id ya existe en este tenant: {role.role_id}") from exc
        raise
    finally:
        await session.close()
    return _role_payload(row)


async def _insert_version(session, row: Any, *, notes: str, created_by: UUID | None) -> None:
    await session.execute(
        text(
            "INSERT INTO role_profile_versions (role_profile_id, organization_id, version, "
            "revision, snapshot, notes, created_by) VALUES (:rid, :oid, :version, :rev, "
            "CAST(:snap AS jsonb), :notes, :uid) ON CONFLICT (role_profile_id, revision) DO NOTHING"
        ),
        {
            "rid": row.id,
            "oid": row.organization_id,
            "version": row.version,
            "rev": row.revision,
            "snap": _json(_role_payload(row)),
            "notes": notes,
            "uid": created_by,
        },
    )


async def get_role(
    organization_id: UUID, role_id: UUID, *, workspace_id: UUID | None = None
) -> dict[str, Any] | None:
    await ensure_role_tables()
    session = await get_async_session()
    try:
        sql = "SELECT * FROM role_profiles WHERE id = :rid AND organization_id = :oid"
        params: dict[str, Any] = {"rid": role_id, "oid": organization_id}
        if workspace_id is not None:
            sql += " AND (workspace_id = :ws OR workspace_id IS NULL)"
            params["ws"] = workspace_id
        row = (await session.execute(text(sql), params)).fetchone()
    finally:
        await session.close()
    return _role_payload(row) if row else None


async def get_role_by_slug(
    organization_id: UUID, slug: str, *, workspace_id: UUID | None = None
) -> dict[str, Any] | None:
    await ensure_role_tables()
    session = await get_async_session()
    try:
        sql = "SELECT * FROM role_profiles WHERE slug = :slug AND organization_id = :oid"
        params: dict[str, Any] = {"slug": slug, "oid": organization_id}
        if workspace_id is not None:
            sql += " AND (workspace_id = :ws OR workspace_id IS NULL)"
            params["ws"] = workspace_id
        row = (await session.execute(text(sql), params)).fetchone()
    finally:
        await session.close()
    return _role_payload(row) if row else None


async def list_roles(
    organization_id: UUID, *, workspace_id: UUID | None = None
) -> list[dict[str, Any]]:
    await ensure_role_tables()
    session = await get_async_session()
    try:
        sql = "SELECT * FROM role_profiles WHERE organization_id = :oid"
        params: dict[str, Any] = {"oid": organization_id}
        if workspace_id is not None:
            sql += " AND (workspace_id = :ws OR workspace_id IS NULL)"
            params["ws"] = workspace_id
        rows = (
            await session.execute(text(sql + " ORDER BY updated_at DESC LIMIT 200"), params)
        ).fetchall()
    finally:
        await session.close()
    return [_role_payload(row) for row in rows]


async def update_role(
    organization_id: UUID,
    role_id: UUID,
    payload: dict[str, Any],
    *,
    user_id: UUID | None = None,
    notes: str | None = None,
) -> dict[str, Any] | None:
    current = await get_role(organization_id, role_id)
    if current is None:
        return None
    merged = {**current, **payload}
    merged["role_id"] = current["role_id"]
    if payload.get("name") and payload.get("name") != current.get("name"):
        merged["display_name"] = payload["name"]
    merged["version"] = _bump_version(str(current.get("version") or "1.0.0"))
    role = RoleProfileV1.model_validate(merged)
    await ensure_role_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "UPDATE role_profiles SET name = :name, description = :desc, mission = :mission, "
                    "audience = CAST(:aud AS jsonb), tone = CAST(:tone AS jsonb), "
                    "competencies = CAST(:comp AS jsonb), constraints = CAST(:cons AS jsonb), "
                    "allowed_capabilities = CAST(:caps AS jsonb), denied_capabilities = CAST(:denied AS jsonb), "
                    "allowed_tools = CAST(:tools AS jsonb), knowledge_scope = CAST(:ks AS jsonb), "
                    "memory_policy = CAST(:mem AS jsonb), autonomy_level = :autonomy, "
                    "human_handoff = CAST(:handoff AS jsonb), expected_outcomes = CAST(:outcomes AS jsonb), "
                    "evaluation_rubric = CAST(:rubric AS jsonb), risk_class = :risk, "
                    "locales = CAST(:locales AS jsonb), compliance_tags = CAST(:tags AS jsonb), "
                    "safety = CAST(:safety AS jsonb), version = :version, revision = revision + 1, "
                    "status = :status, updated_at = NOW() WHERE id = :rid AND organization_id = :oid "
                    "RETURNING *"
                ),
                {
                    "name": role.name,
                    "desc": role.description,
                    "mission": role.mission,
                    "aud": _json(role.audience),
                    "tone": _json(role.tone),
                    "comp": _json([item.model_dump(mode="json") for item in role.competencies]),
                    "cons": _json(role.constraints),
                    "caps": _json(role.allowed_capabilities),
                    "denied": _json(role.denied_capabilities),
                    "tools": _json(role.allowed_tools),
                    "ks": _json(role.knowledge_scope.model_dump(mode="json")),
                    "mem": _json(role.memory_policy.model_dump(mode="json")),
                    "autonomy": role.autonomy_level,
                    "handoff": _json(role.human_handoff.model_dump(mode="json")),
                    "outcomes": _json([item.model_dump(mode="json") for item in role.expected_outcomes]),
                    "rubric": _json([item.model_dump(mode="json") for item in role.evaluation_rubric]),
                    "risk": role.risk_class,
                    "locales": _json(role.locales),
                    "tags": _json(role.compliance_tags),
                    "safety": _json(role.safety.model_dump(mode="json")),
                    "version": role.version,
                    "status": role.status,
                    "rid": role_id,
                    "oid": organization_id,
                },
            )
        ).fetchone()
        if row is not None:
            await _insert_version(
                session, row, notes=notes or "updated", created_by=user_id
            )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    return _role_payload(row) if row else None


async def clone_role(
    organization_id: UUID,
    role_id: UUID,
    *,
    user_id: UUID | None = None,
    new_role_id: str | None = None,
) -> dict[str, Any] | None:
    current = await get_role(organization_id, role_id)
    if current is None:
        return None
    payload = dict(current)
    payload["role_id"] = new_role_id or f"{current['role_id']}_copy"[:80]
    payload["name"] = f"Copia de {current['name']}"[:150]
    payload["display_name"] = payload["name"]
    payload["version"] = "1.0.0"
    payload["status"] = "draft"
    return await create_role(
        organization_id, user_id=user_id, payload=payload
    )


async def archive_role(
    organization_id: UUID, role_id: UUID, *, user_id: UUID | None = None
) -> dict[str, Any] | None:
    return await update_role(
        organization_id, role_id, {"status": "archived"}, user_id=user_id, notes="archived"
    )


async def list_role_versions(
    organization_id: UUID, role_id: UUID
) -> list[dict[str, Any]]:
    await ensure_role_tables()
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT version, revision, notes, created_at FROM role_profile_versions "
                    "WHERE role_profile_id = :rid AND organization_id = :oid "
                    "ORDER BY revision DESC LIMIT 100"
                ),
                {"rid": role_id, "oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "version": str(row.version),
            "revision": int(row.revision),
            "notes": row.notes,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


async def get_role_version(
    organization_id: UUID, role_id: UUID, revision: int
) -> dict[str, Any] | None:
    await ensure_role_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT snapshot FROM role_profile_versions "
                    "WHERE role_profile_id = :rid AND organization_id = :oid AND revision = :rev"
                ),
                {"rid": role_id, "oid": organization_id, "rev": revision},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    snapshot = row.snapshot if isinstance(row.snapshot, dict) else {}
    out = dict(snapshot)
    out.pop("record_id", None)
    return out


async def export_role(organization_id: UUID, role_id: UUID) -> dict[str, Any] | None:
    role = await get_role(organization_id, role_id)
    if role is None:
        return None
    role = dict(role)
    role.pop("id", None)
    role.pop("record_id", None)
    return role


async def import_role(
    organization_id: UUID,
    payload: dict[str, Any],
    *,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
) -> dict[str, Any]:
    role = role_from_legacy_payload(payload)
    return await create_role(
        organization_id,
        workspace_id=workspace_id,
        user_id=user_id,
        payload=role.model_dump(by_alias=True),
    )


async def link_agent_role(
    organization_id: UUID,
    agent_id: UUID,
    role_profile_id: UUID | None,
) -> dict[str, Any]:
    await ensure_role_tables()
    session = await get_async_session()
    try:
        agent = (
            await session.execute(
                text("SELECT id FROM agents WHERE id = :aid AND organization_id = :oid"),
                {"aid": agent_id, "oid": organization_id},
            )
        ).fetchone()
        if agent is None:
            raise RoleNotFound("agente inexistente")
        if role_profile_id is not None:
            role = (
                await session.execute(
                    text(
                        "SELECT id FROM role_profiles WHERE id = :rid AND organization_id = :oid"
                    ),
                    {"rid": role_profile_id, "oid": organization_id},
                )
            ).fetchone()
            if role is None:
                raise RoleNotFound("rol inexistente")
        await session.execute(
            text("UPDATE agents SET role_profile_id = :rid, updated_at = NOW() WHERE id = :aid"),
            {"rid": role_profile_id, "aid": agent_id},
        )
        await session.commit()
    finally:
        await session.close()
    return {"agent_id": str(agent_id), "role_profile_id": str(role_profile_id) if role_profile_id else None}


async def get_agent_role(organization_id: UUID, agent_id: UUID) -> dict[str, Any] | None:
    await ensure_role_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT r.* FROM agents a JOIN role_profiles r ON r.id = a.role_profile_id "
                    "WHERE a.id = :aid AND a.organization_id = :oid AND r.status = 'active'"
                ),
                {"aid": agent_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    return _role_payload(row) if row else None


def filter_agent_tools(tools: list[str], role: dict[str, Any] | RoleProfileV1 | None) -> list[str]:
    """Role constraints narrow Agent tools; they never grant a tool."""
    if role is None:
        return list(tools)
    profile = role if isinstance(role, RoleProfileV1) else role_from_legacy_payload(role)
    if profile.allowed_tools:
        allowed = set(profile.allowed_tools)
    elif profile.allowed_capabilities:
        hinted: set[str] = set()
        for capability in profile.allowed_capabilities:
            hinted |= _CAPABILITY_TOOL_HINTS.get(capability, set())
        allowed = hinted
    else:
        allowed = set(tools)
    allowed &= set(tools)
    autonomy = profile.autonomy_level
    if autonomy in ("answer_only", "propose_actions", "require_approval"):
        allowed &= _READ_ONLY_TOOLS
    return sorted(allowed)


def apply_role_to_agent(agent: Any, role: dict[str, Any] | RoleProfileV1 | None) -> Any:
    if role is None:
        return agent
    return replace(agent, tools=filter_agent_tools(list(agent.tools or []), role))


def autonomy_allows_tool(autonomy: str, tool: str) -> bool:
    if autonomy in ("answer_only", "propose_actions", "require_approval"):
        return str(tool) in _READ_ONLY_TOOLS
    return True


__all__ = [
    "RoleConflict",
    "RoleError",
    "RoleNotFound",
    "apply_role_to_agent",
    "archive_role",
    "autonomy_allows_tool",
    "clone_role",
    "create_role",
    "ensure_role_tables",
    "export_role",
    "filter_agent_tools",
    "get_agent_role",
    "get_role",
    "get_role_by_slug",
    "get_role_version",
    "import_role",
    "link_agent_role",
    "list_role_versions",
    "list_roles",
    "mission_sheet",
    "propose_role",
    "update_role",
]
