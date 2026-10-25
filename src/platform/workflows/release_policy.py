# =============================================================================
# Release policy — única autoridad de publicación/activación.
#
# Decide ALLOW/DENY para publish, activate, promote y restore. No crea un
# segundo runtime: reutiliza WorkflowGraph, readiness, capability registry,
# WorkflowInstance/versions y RBAC. El certificado lo emite el backend y se
# guarda en workflow_certificates; la metadata del cliente nunca es evidencia.
# =============================================================================
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.platform.workflows.effect_verification import EXTERNAL_READ_NODE_TYPES
from src.platform.workflows.readiness import readiness_checks

logger = get_logger(__name__)

POLICY_VERSION = "v1"
CERTIFICATE_SCHEMA = "zent.workflow.release_certificate/v1"

LEVEL_RANK = {
    "DESIGN_VALID": 1,
    "SIMULATION_PASSED": 2,
    "SANDBOX_VERIFIED": 3,
    "PROVIDER_VERIFIED": 4,
}
REQUIRED_LEVEL = {
    "read_only": "DESIGN_VALID",
    "internal": "DESIGN_VALID",
    "agent": "DESIGN_VALID",
    "external_read": "DESIGN_VALID",
    "external_write": "SANDBOX_VERIFIED",
    "regulated": "PROVIDER_VERIFIED",
}
LEVEL_STATE = {
    "design": "DESIGN_VALID",
    "simulation": "SIMULATION_PASSED",
    "sandbox": "SANDBOX_VERIFIED",
    "provider": "PROVIDER_VERIFIED",
}
RESERVED_METADATA = ("certification", "release_certificate", "require_certification")
_LEGACY_POLICY = "legacy"

_CERT_TABLE = """
CREATE TABLE IF NOT EXISTS workflow_certificates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    workspace_id UUID,
    workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    workflow_version INTEGER,
    release_version INTEGER,
    risk_class VARCHAR(30) NOT NULL,
    level VARCHAR(30) NOT NULL,
    state VARCHAR(40) NOT NULL,
    graph_hash VARCHAR(64) NOT NULL,
    semantic_plan_hash VARCHAR(64) NOT NULL DEFAULT '',
    capability_snapshot_hash VARCHAR(64) NOT NULL DEFAULT '',
    agent_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
    role_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
    policy_version VARCHAR(40) NOT NULL DEFAULT 'v1',
    verification_id UUID,
    environment VARCHAR(40) NOT NULL DEFAULT 'design',
    scenarios JSONB NOT NULL DEFAULT '[]'::jsonb,
    results JSONB NOT NULL DEFAULT '{}'::jsonb,
    provider_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    approvals JSONB NOT NULL DEFAULT '[]'::jsonb,
    issued_by UUID,
    issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    revoked_reason VARCHAR(300)
)
"""


class ReleaseDenied(ValueError):
    """El gate rechazó la operación. El llamador debe responder 409."""

    def __init__(self, decision: dict[str, Any]):
        self.decision = decision
        self.blockers = list(decision.get("blockers") or [])
        message = decision.get("message") or "release gate denegó la operación"
        if self.blockers:
            message = f"{message}: " + "; ".join(
                str(item.get("message") or item.get("code")) for item in self.blockers[:4]
            )
        super().__init__(message)


class CertificateError(ValueError):
    """No se pudo emitir un certificado con la evidencia declarada."""


@dataclass
class ReleaseDecision:
    allowed: bool
    state: str
    action: str
    risk_class: str
    required_level: str
    graph_hash: str
    semantic_plan_hash: str = ""
    capability_snapshot_hash: str = ""
    certificate: dict[str, Any] | None = None
    blockers: list[dict[str, Any]] = field(default_factory=list)
    mitigations: list[str] = field(default_factory=list)
    legacy: bool = False
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CERTIFICATE_SCHEMA,
            "allowed": self.allowed,
            "state": self.state,
            "action": self.action,
            "risk_class": self.risk_class,
            "required_level": self.required_level,
            "graph_hash": self.graph_hash,
            "semantic_plan_hash": self.semantic_plan_hash,
            "capability_snapshot_hash": self.capability_snapshot_hash,
            "certificate": self.certificate,
            "blockers": self.blockers,
            "mitigations": self.mitigations,
            "legacy": self.legacy,
            "message": self.message,
        }


def _blocker(code: str, message: str, mitigation: str = "") -> dict[str, str]:
    return {"code": code, "message": message, "mitigation": mitigation}


def sanitize_graph(graph: dict[str, Any] | None) -> dict[str, Any]:
    """Quita metadata reservada del cliente. Nunca es fuente de evidencia."""
    clean = copy.deepcopy(graph or {})
    metadata = clean.get("metadata")
    if isinstance(metadata, dict):
        for key in RESERVED_METADATA:
            metadata.pop(key, None)
    return clean


def graph_fingerprint(graph: dict[str, Any] | None) -> str:
    clean = sanitize_graph(graph)
    blob = json.dumps(clean, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def canonical_state(level: str | None, state: str | None = None) -> str:
    if state in LEVEL_RANK:
        return str(state)
    return LEVEL_STATE.get(str(level or ""), "")


def _descriptor(ref: str, capabilities: dict[str, Any] | None) -> dict[str, Any]:
    index = (capabilities or {}).get("capability_index") or {}
    item = index.get(ref) if isinstance(index, dict) else None
    return item if isinstance(item, dict) else {}


_READ_REF = re.compile(
    r"\.(search|get|list|read|query|lookup|fetch|status|quote|inspect)(\.|$)",
    re.IGNORECASE,
)


def _capability_class(ref: str, capabilities: dict[str, Any] | None) -> str:
    descriptor = _descriptor(ref, capabilities)
    effects = {str(item) for item in descriptor.get("side_effects") or []}
    risk = str(descriptor.get("risk_level") or "")
    if "financial" in effects or risk == "critical":
        return "regulated"
    if "write" in effects:
        return "external_write"
    if "read" in effects or _READ_REF.search(ref):
        return "external_read"
    # Capacidad desconocida: no se asume lectura inocua.
    return "external_write"


def classify_graph(
    graph: dict[str, Any] | None, capabilities: dict[str, Any] | None = None
) -> dict[str, Any]:
    clean = sanitize_graph(graph)
    nodes = [item for item in clean.get("nodes") or [] if isinstance(item, dict)]
    risk = "read_only"
    effects: list[str] = []
    reads: list[str] = []
    internal: list[str] = []
    agents: list[str] = []
    for node in nodes:
        node_type = str(node.get("type") or "")
        config = node.get("config") or {}
        node_id = str(node.get("id") or node_type)
        if node_type == "capability_call":
            ref = str(config.get("capability") or config.get("capability_ref") or "")
            kind = _capability_class(ref, capabilities) if ref else "external_write"
            effects.append(ref or node_id)
            if kind == "regulated":
                risk = "regulated"
            elif kind == "external_write" and risk not in ("regulated",):
                risk = "external_write"
            elif kind == "external_read" and risk in ("read_only", "internal", "agent"):
                risk = "external_read" if risk == "read_only" else risk
        elif node_type == "marketplace_action":
            ref = str(config.get("action_id") or "")
            kind = _capability_class(ref, capabilities) if ref else "external_write"
            effects.append(ref or node_id)
            if kind == "regulated":
                risk = "regulated"
            elif risk not in ("regulated",):
                risk = "external_write"
        elif node_type in ("api_call", "business_node", "subworkflow_call"):
            effects.append(node_id)
            if risk != "regulated":
                risk = "external_write"
        elif node_type in EXTERNAL_READ_NODE_TYPES:
            reads.append(node_id)
            if node_type == "llm":
                agents.append(str(config.get("agent_id") or ""))
                if risk in ("read_only", "internal", "external_read"):
                    risk = "agent"
        elif node_type == "notify":
            channel = str(config.get("channel") or "in_app")
            if channel in ("in_app", "zent"):
                internal.append(node_id)
                if risk == "read_only":
                    risk = "internal"
            else:
                effects.append(f"{node_id}:{channel}")
                if risk != "regulated":
                    risk = "external_write"
        elif node_type == "human_approval":
            internal.append(node_id)
            if risk == "read_only":
                risk = "internal"
        elif node_type in ("business_result", "state_set", "state_merge", "state_append", "state_remove"):
            internal.append(node_id)
            if risk == "read_only":
                risk = "internal"
    required = REQUIRED_LEVEL.get(risk, "DESIGN_VALID")
    return {
        "risk_class": risk,
        "required_level": required,
        "effects": sorted(set(effects)),
        "reads": sorted(set(reads)),
        "internal": sorted(set(internal)),
        "agent_ids": sorted({item for item in agents if item}),
        "nodes": len(nodes),
    }


_ENSURED = False


async def ensure_release_tables() -> None:
    global _ENSURED
    if _ENSURED:
        return
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "ALTER TABLE workflows ADD COLUMN IF NOT EXISTS release_policy "
                "VARCHAR(20) NOT NULL DEFAULT 'standard'"
            )
        )
        await session.execute(
            text("ALTER TABLE workflows ADD COLUMN IF NOT EXISTS release_policy_reason TEXT")
        )
        await session.execute(
            text("ALTER TABLE workflows ADD COLUMN IF NOT EXISTS release_policy_at TIMESTAMPTZ")
        )
        await session.execute(
            text(
                "ALTER TABLE workflow_versions ADD COLUMN IF NOT EXISTS certificate_id UUID"
            )
        )
        await session.execute(
            text(
                "ALTER TABLE workflow_certificates "
                "ADD COLUMN IF NOT EXISTS verification_id UUID, "
                "ADD COLUMN IF NOT EXISTS environment VARCHAR(40) NOT NULL DEFAULT 'design'"
            )
        )
        await session.execute(text(_CERT_TABLE))
        await session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_wf_cert_lookup "
                "ON workflow_certificates(organization_id, workflow_id, graph_hash, issued_at DESC)"
            )
        )
        await session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_wf_cert_workspace "
                "ON workflow_certificates(organization_id, workspace_id, workflow_id)"
            )
        )
        await session.commit()
        _ENSURED = True
    except Exception:  # noqa: BLE001 — paridad dev; migración manda en prod
        await session.rollback()
        logger.warning("release tables ensure failed")
    finally:
        await session.close()


def _row_to_certificate(row: Any) -> dict[str, Any]:
    return {
        "schema": CERTIFICATE_SCHEMA,
        "id": str(row.id),
        "organization_id": str(row.organization_id),
        "workspace_id": str(row.workspace_id) if row.workspace_id else None,
        "workflow_id": str(row.workflow_id),
        "workflow_version": int(row.workflow_version) if row.workflow_version is not None else None,
        "release_version": int(row.release_version) if row.release_version is not None else None,
        "risk_class": row.risk_class,
        "level": row.level,
        "state": row.state,
        "level_state": canonical_state(row.level, row.state),
        "graph_hash": row.graph_hash,
        "trigger_hash": getattr(row, "trigger_hash", "") or "",
        "binding_fingerprint": getattr(row, "binding_fingerprint", "") or "",
        "semantic_plan_hash": row.semantic_plan_hash or "",
        "capability_snapshot_hash": row.capability_snapshot_hash or "",
        "agent_versions": row.agent_versions or {},
        "role_versions": row.role_versions or {},
        "policy_version": row.policy_version,
        "verification_id": (
            str(getattr(row, "verification_id", None))
            if getattr(row, "verification_id", None)
            else None
        ),
        "environment": getattr(row, "environment", "design") or "design",
        "scenarios": row.scenarios or [],
        "results": row.results or {},
        "provider_refs": row.provider_refs or [],
        "approvals": row.approvals or [],
        "issued_by": str(row.issued_by) if row.issued_by else None,
        "issued_at": row.issued_at.isoformat() if row.issued_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "revoked_reason": row.revoked_reason,
    }


async def list_certificates(
    organization_id: UUID,
    workflow_id: UUID,
    *,
    workspace_id: UUID | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    await ensure_release_tables()
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT * FROM workflow_certificates "
                    "WHERE organization_id = :oid AND workflow_id = :wid "
                    "AND workspace_id IS NOT DISTINCT FROM :ws "
                    "ORDER BY issued_at DESC LIMIT :limit"
                ),
                {
                    "oid": organization_id,
                    "wid": workflow_id,
                    "ws": workspace_id,
                    "limit": max(1, min(limit, 100)),
                },
            )
        ).fetchall()
    finally:
        await session.close()
    return {"certificates": [_row_to_certificate(row) for row in rows]}


async def _latest_certificate(
    organization_id: UUID,
    workflow_id: UUID,
    *,
    workspace_id: UUID | None,
    graph_hash: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT * FROM workflow_certificates "
                    "WHERE organization_id = :oid AND workflow_id = :wid "
                    "AND revoked_at IS NULL "
                    "ORDER BY issued_at DESC LIMIT 20"
                ),
                {"oid": organization_id, "wid": workflow_id},
            )
        ).fetchall()
    finally:
        await session.close()
    certs = [_row_to_certificate(row) for row in rows]
    scoped = [item for item in certs if item.get("workspace_id") == (str(workspace_id) if workspace_id else None)]
    matching = [item for item in scoped if item.get("graph_hash") == graph_hash]
    return (matching[0] if matching else None, scoped[0] if scoped else (certs[0] if certs else None))


async def _design_hashes(organization_id: UUID, workflow_id: UUID) -> tuple[str, str]:
    try:
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT plan_hash, capability_snapshot_hash "
                        "FROM workflow_design_sessions "
                        "WHERE organization_id = :oid AND workflow_id = :wid "
                        "ORDER BY updated_at DESC LIMIT 1"
                    ),
                    {"oid": organization_id, "wid": workflow_id},
                )
            ).fetchone()
        finally:
            await session.close()
    except Exception:  # noqa: BLE001 — tabla opcional en instalaciones viejas
        return "", ""
    if row is None:
        return "", ""
    return str(row.plan_hash or ""), str(row.capability_snapshot_hash or "")


async def _active_bindings_fingerprint(
    organization_id: UUID, workspace_id: UUID | None
) -> str:
    """Hash de los bindings instalados relevantes. Nunca incluye secretos."""
    try:
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT capability_ref, provider_kind, credential_ref, status, "
                        "contract_input_schema, contract_output_schema, updated_at "
                        "FROM workflow_capability_bindings "
                        "WHERE organization_id = :oid AND status = 'active' "
                        "AND workspace_id IS NOT DISTINCT FROM :ws "
                        "ORDER BY capability_ref"
                    ),
                    {"oid": organization_id, "ws": workspace_id},
                )
            ).fetchall()
        finally:
            await session.close()
    except Exception:  # noqa: BLE001 — instalaciones sin tabla de bindings
        return ""
    payload = [
        {
            "capability_ref": row.capability_ref,
            "provider_kind": row.provider_kind,
            "credential_ref": row.credential_ref or "",
            "status": row.status,
            "contract_input_schema": row.contract_input_schema or {},
            "contract_output_schema": row.contract_output_schema or {},
            "updated_at": row.updated_at.isoformat() if row.updated_at else "",
        }
        for row in rows
    ]
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


async def _published_baseline(organization_id: UUID, workflow_id: UUID) -> bool:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT v.legacy_baseline FROM workflows w "
                    "JOIN workflow_versions v ON v.id = w.published_version_id "
                    "WHERE w.id = :wid AND w.organization_id = :oid"
                ),
                {"wid": workflow_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    return bool(row and row.legacy_baseline)


async def _target_is_legacy_baseline(
    organization_id: UUID, workflow_id: UUID, graph: dict[str, Any]
) -> bool:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT v.legacy_baseline, v.graph_hash, v.config_snapshot "
                    "FROM workflows w JOIN workflow_versions v "
                    "ON v.id = w.published_version_id "
                    "WHERE w.id = :wid AND w.organization_id = :oid"
                ),
                {"wid": workflow_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None or not bool(row.legacy_baseline):
        return False
    stored = str(row.graph_hash or "")
    if stored:
        return stored == graph_fingerprint(graph)
    snapshot = row.config_snapshot if isinstance(row.config_snapshot, dict) else {}
    baseline_graph = snapshot.get("graph")
    if not isinstance(baseline_graph, dict) or not baseline_graph:
        from src.platform.workflows.ir import LegacyWorkflowAdapter

        baseline_graph = LegacyWorkflowAdapter.steps_to_graph(
            snapshot.get("steps") or [],
            snapshot.get("trigger_type") or "webhook",
            snapshot.get("trigger_config") or {},
        ).to_dict()
    return graph_fingerprint(baseline_graph) == graph_fingerprint(graph)


async def _agent_fingerprint(organization_id: UUID, graph: dict[str, Any]) -> tuple[dict, dict, list[str]]:
    nodes = [item for item in graph.get("nodes") or [] if isinstance(item, dict)]
    agent_ids = sorted(
        {
            str((item.get("config") or {}).get("agent_id"))
            for item in nodes
            if item.get("type") == "llm" and (item.get("config") or {}).get("agent_id")
        }
    )
    missing: list[str] = []
    agents: list[dict[str, Any]] = []
    roles: list[dict[str, Any]] = []
    if not agent_ids:
        return {"agents": []}, {"roles": []}, missing
    session = await get_async_session()
    try:
        for agent_id in agent_ids:
            row = (
                await session.execute(
                    text(
                        "SELECT id, is_active, role_profile_id FROM agents "
                        "WHERE id = :aid AND organization_id = :oid"
                    ),
                    {"aid": agent_id, "oid": organization_id},
                )
            ).fetchone()
            if row is None or not bool(row.is_active):
                missing.append(agent_id)
                continue
            version = (
                await session.execute(
                    text(
                        "SELECT version_number, status FROM agent_versions "
                        "WHERE agent_id = :aid ORDER BY version_number DESC LIMIT 1"
                    ),
                    {"aid": agent_id},
                )
            ).fetchone()
            agents.append(
                {
                    "agent_id": str(row.id),
                    "version": int(version.version_number) if version else None,
                    "status": str(version.status) if version else None,
                    "role_profile_id": str(row.role_profile_id) if row.role_profile_id else None,
                }
            )
            if row.role_profile_id:
                role = (
                    await session.execute(
                        text(
                            "SELECT id, version, revision, status FROM role_profiles "
                            "WHERE id = :rid AND organization_id = :oid"
                        ),
                        {"rid": row.role_profile_id, "oid": organization_id},
                    )
                ).fetchone()
                if role is not None:
                    roles.append(
                        {
                            "role_profile_id": str(role.id),
                            "version": str(role.version),
                            "revision": int(role.revision),
                            "status": str(role.status),
                        }
                    )
    except Exception:  # noqa: BLE001 — agent_versions puede no existir en DB vieja
        logger.warning("agent fingerprint unavailable")
    finally:
        await session.close()
    return {"agents": agents}, {"roles": roles}, missing


def _certificate_problem(cert: dict[str, Any] | None, required_level: str) -> dict[str, str] | None:
    if cert is None:
        return _blocker(
            "certification_required",
            "Falta un certificado emitido por el backend para este grafo.",
            "Ejecuta la certificación del workflow y vuelve a publicar.",
        )
    expires = cert.get("expires_at")
    if expires:
        try:
            if datetime.fromisoformat(expires.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
                return _blocker(
                    "certificate_expired",
                    "El certificado venció.",
                    "Vuelve a certificar la versión actual.",
                )
        except ValueError:
            return _blocker("certificate_invalid", "La fecha del certificado no es válida.")
    state = canonical_state(cert.get("level"), cert.get("state"))
    if cert.get("state") == "AWAITING_APPROVAL":
        return _blocker(
            "human_approval_required",
            "El certificado está pendiente de aprobación humana.",
            "Aprueba el escenario y emite un certificado nuevo.",
        )
    if state not in LEVEL_RANK:
        return _blocker("certificate_invalid", "El certificado no declara un nivel válido.")
    if LEVEL_RANK[state] < LEVEL_RANK.get(required_level, 1):
        return _blocker(
            "certification_level_insufficient",
            f"El certificado es {state} y este flujo exige {required_level}.",
            "Completa sandbox/proveedor real; una simulación no es un pase externo.",
        )
    return None


async def _evaluate_graph(
    workflow: dict[str, Any],
    graph: dict[str, Any],
    *,
    action: str,
    workspace_id: UUID | None,
    capabilities: dict[str, Any] | None,
    checks: list[dict[str, Any]] | None = None,
    permissions: frozenset[str] | None = None,
    trigger_hash: str = "",
    binding_fingerprint: str = "",
) -> ReleaseDecision:
    organization_id = UUID(str(workflow["organization_id"])) if workflow.get("organization_id") else None
    if organization_id is None:
        raise ValueError("workflow sin organization_id")
    workflow_id = UUID(str(workflow["id"]))
    graph_hash = graph_fingerprint(graph)
    risk = classify_graph(graph, capabilities)
    required = str(risk["required_level"])
    blockers: list[dict[str, str]] = []
    mitigations: list[str] = []
    plan_hash, design_snapshot_hash = await _design_hashes(organization_id, workflow_id)
    snapshot_hash = str(
        (capabilities or {}).get("capability_snapshot", {}).get("snapshot_hash")
        or design_snapshot_hash
        or ""
    )
    checks = (
        checks
        if checks is not None
        else readiness_checks(
            graph,
            capabilities or {},
            trigger_type=str(workflow.get("trigger_type") or ""),
        )
    )
    for check in checks:
        if check.get("status") == "error":
            blockers.append(
                _blocker(
                    f"readiness:{check.get('id') or 'check'}",
                    str(check.get("message") or "readiness incompleto"),
                    str(check.get("hint") or "Corrige el paso marcado."),
                )
            )
    agent_versions, role_versions, missing_agents = await _agent_fingerprint(organization_id, graph)
    for agent_id in missing_agents:
        blockers.append(
            _blocker(
                "agent_unavailable",
                f"El agente {agent_id} no existe o está inactivo.",
                "Vincula un agente activo al paso de IA.",
            )
        )
    for node in graph.get("nodes") or []:
        if isinstance(node, dict) and node.get("type") == "llm":
            if not str((node.get("config") or {}).get("agent_id") or ""):
                blockers.append(
                    _blocker(
                        "agent_not_linked",
                        f"El paso de IA {node.get('id')} no tiene agente vinculado.",
                        "Elige un agente activo; el eco no es una ejecución real.",
                    )
                )
    from src.core.config import get_settings

    production_enabled = bool(getattr(get_settings(), "ZENT_GOLD_RELEASE_ENABLED", False))
    # La flag se decide por el riesgo real del grafo, nunca por metadata del cliente.
    if str(risk["risk_class"]) in ("external_write", "regulated") and not production_enabled:
        blockers.append(
            _blocker(
                "production_disabled",
                "ZENT_GOLD_RELEASE_ENABLED está apagado.",
                "La activación de producción requiere aprobación formal.",
            )
        )

    certificate, any_certificate = await _latest_certificate(
        organization_id,
        workflow_id,
        workspace_id=workspace_id,
        graph_hash=graph_hash,
    )
    if certificate is not None:
        if plan_hash and certificate.get("semantic_plan_hash") and certificate["semantic_plan_hash"] != plan_hash:
            blockers.append(
                _blocker(
                    "plan_stale",
                    "El plan semántico cambió desde la certificación.",
                    "Vuelve a certificar el plan actual.",
                )
            )
        if (
            snapshot_hash
            and certificate.get("capability_snapshot_hash")
            and certificate["capability_snapshot_hash"] != snapshot_hash
        ):
            blockers.append(
                _blocker(
                    "snapshot_stale",
                    "El snapshot de capacidades cambió desde la certificación.",
                    "Resuelve dependencias y vuelve a certificar.",
                )
            )
        if certificate.get("agent_versions") not in (None, {}, agent_versions):
            blockers.append(
                _blocker(
                    "agents_stale",
                    "Los agentes o sus versiones cambiaron desde la certificación.",
                    "Vuelve a certificar con los agentes actuales.",
                )
            )
        if certificate.get("role_versions") not in (None, {}, role_versions):
            blockers.append(
                _blocker(
                    "roles_stale",
                    "Los roles cambiaron desde la certificación.",
                    "Vuelve a certificar con los roles actuales.",
                )
            )
        if (
            trigger_hash
            and certificate.get("trigger_hash")
            and certificate["trigger_hash"] != trigger_hash
        ):
            blockers.append(
                _blocker(
                    "trigger_stale",
                    "El trigger cambió desde la certificación.",
                    "Vuelve a certificar el trigger actual.",
                )
            )
        if (
            binding_fingerprint
            and certificate.get("binding_fingerprint")
            and certificate["binding_fingerprint"] != binding_fingerprint
        ):
            blockers.append(
                _blocker(
                    "bindings_stale",
                    "Los bindings de capacidades cambiaron desde la certificación.",
                    "Revisa Integraciones y vuelve a certificar.",
                )
            )
        problem = _certificate_problem(certificate, required)
        if problem:
            blockers.append(problem)
    else:
        if any_certificate is not None:
            blockers.append(
                _blocker(
                    "certificate_stale",
                    "El grafo cambió y el certificado existente ya no coincide.",
                    "Vuelve a certificar la versión actual.",
                )
            )
        else:
            blockers.append(
                _blocker(
                    "certification_required",
                    "Falta un certificado emitido por el backend.",
                    "Certifica el workflow antes de publicar o activar.",
                )
            )

    allowed = not blockers
    state = "READY_TO_PUBLISH" if allowed else "BLOCKED"
    stale_codes = {
        "certificate_stale",
        "plan_stale",
        "snapshot_stale",
        "agents_stale",
        "roles_stale",
        "trigger_stale",
        "bindings_stale",
    }
    if any(item["code"] in stale_codes for item in blockers):
        state = "STALE"
    elif any(item["code"] == "human_approval_required" for item in blockers):
        state = "AWAITING_APPROVAL"
    if allowed:
        mitigations.append("Certificado vigente y hashes coincidentes.")
    return ReleaseDecision(
        allowed=allowed,
        state=state,
        action=action,
        risk_class=str(risk["risk_class"]),
        required_level=required,
        graph_hash=graph_hash,
        semantic_plan_hash=plan_hash,
        capability_snapshot_hash=snapshot_hash,
        certificate=certificate,
        blockers=blockers,
        mitigations=mitigations,
        message="release gate ALLOW" if allowed else "release gate DENY",
    )


async def evaluate_release(
    organization_id: UUID,
    workflow_id: UUID,
    *,
    action: str,
    workspace_id: UUID | None = None,
    permissions: frozenset[str] | None = None,
    graph_override: dict[str, Any] | None = None,
    checks: list[dict[str, Any]] | None = None,
) -> ReleaseDecision:
    from src.platform.workflows.engine import get_workflow
    from src.platform.workflows.plan_compiler import load_capabilities

    await ensure_release_tables()
    workflow = await get_workflow(organization_id, workflow_id)
    if workflow is None:
        return ReleaseDecision(
            False,
            "BLOCKED",
            action,
            "read_only",
            "DESIGN_VALID",
            "",
            blockers=[_blocker("not_found", "Workflow no encontrado.")],
            message="release gate DENY",
        )
    workflow["organization_id"] = str(organization_id)
    wf_ws = workflow.get("workspace_id")
    if wf_ws and str(workspace_id or "") != str(wf_ws):
        return ReleaseDecision(
            False,
            "BLOCKED",
            action,
            "read_only",
            "DESIGN_VALID",
            "",
            blockers=[_blocker("workspace_mismatch", "El workflow pertenece a otro workspace.")],
            message="release gate DENY",
        )
    # La exención legacy nunca autoriza publicar un grafo nuevo: solo activar
    # el baseline exacto ya congelado y auditado.
    if (
        str(workflow.get("release_policy") or "standard") == _LEGACY_POLICY
        and action == "activate"
        and await _published_baseline(organization_id, workflow_id)
    ):
        return ReleaseDecision(
            True,
            "LEGACY_EXEMPT",
            action,
            "legacy",
            "DESIGN_VALID",
            graph_fingerprint(graph_override or workflow.get("graph") or {}),
            legacy=True,
            mitigations=[
                "Baseline legacy congelado y auditado; no hay bypass por metadata.",
                "Cualquier publicación nueva exige certificado estándar.",
            ],
            message="release gate ALLOW (legacy baseline)",
        )
    graph = graph_override or workflow.get("graph")
    if not graph:
        from src.platform.workflows.ir import LegacyWorkflowAdapter

        graph = LegacyWorkflowAdapter.steps_to_graph(
            workflow.get("steps") or [],
            workflow.get("trigger_type") or "webhook",
            workflow.get("trigger_config") or {},
        ).to_dict()
    capabilities = await load_capabilities(organization_id, workspace_id)
    from src.platform.workflows.definition import trigger_fingerprint

    return await _evaluate_graph(
        workflow,
        graph,
        action=action,
        workspace_id=workspace_id,
        capabilities=capabilities,
        checks=checks,
        permissions=permissions,
        trigger_hash=trigger_fingerprint(
            workflow.get("trigger_type"), workflow.get("trigger_config")
        ),
        binding_fingerprint=await _active_bindings_fingerprint(
            organization_id, workspace_id
        ),
    )


async def activate_workflow(
    organization_id: UUID,
    workflow_id: UUID,
    *,
    workspace_id: UUID | None = None,
    permissions: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Activa bajo lock de fila y gate único. Requiere versión publicada.

    Compatibilidad: si el workflow aún no tiene puntero, la primera activación
    crea el snapshot mediante `publish_workflow` y pasa el mismo gate. No existe
    una activación que ejecute la fila viva sin congelarla.
    """
    await ensure_release_tables()
    preflight = await get_async_session()
    try:
        current = (
            await preflight.execute(
                text(
                    "SELECT published_version_id FROM workflows "
                    "WHERE id = :wid AND organization_id = :oid"
                ),
                {"wid": workflow_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await preflight.close()
    if current is None:
        return {}
    if current.published_version_id is None:
        from src.platform.workflows.versions import publish_workflow

        published = await publish_workflow(
            organization_id,
            workflow_id,
            notes="activación inicial: snapshot publicado",
            permissions=permissions,
            workspace_id=workspace_id,
        )
        if published is None:
            return {}
        published["bootstrap_published"] = True
        return published
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT w.id, w.status, w.workspace_id, w.published_version_id, "
                    "v.config_snapshot, v.certificate_id, v.legacy_baseline "
                    "FROM workflows w LEFT JOIN workflow_versions v "
                    "ON v.id = w.published_version_id "
                    "WHERE w.id = :wid AND w.organization_id = :oid "
                    "FOR UPDATE OF w"
                ),
                {"wid": workflow_id, "oid": organization_id},
            )
        ).fetchone()
        if row is None:
            return {}
        if row.published_version_id is None or not isinstance(row.config_snapshot, dict):
            decision = ReleaseDecision(
                False,
                "BLOCKED",
                "activate",
                "read_only",
                "DESIGN_VALID",
                "",
                blockers=[
                    _blocker(
                        "published_version_required",
                        "El workflow no tiene versión publicada.",
                        "Publica una versión certificada antes de activar.",
                    )
                ],
            )
            await session.rollback()
            raise ReleaseDenied(decision.to_dict())
        snapshot = row.config_snapshot or {}
        graph = snapshot.get("graph")
        if not graph:
            from src.platform.workflows.ir import LegacyWorkflowAdapter

            graph = LegacyWorkflowAdapter.steps_to_graph(
                snapshot.get("steps") or [],
                snapshot.get("trigger_type") or "webhook",
                snapshot.get("trigger_config") or {},
            ).to_dict()
        decision = await evaluate_release(
            organization_id,
            workflow_id,
            action="activate",
            workspace_id=workspace_id,
            permissions=permissions,
            graph_override=graph,
        )
        if not decision.allowed:
            await session.rollback()
            raise ReleaseDenied(decision.to_dict())
        await session.execute(
            text(
                "UPDATE workflows SET status = 'active', updated_at = NOW() "
                "WHERE id = :wid AND organization_id = :oid"
            ),
            {"wid": workflow_id, "oid": organization_id},
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    return {
        "workflow_id": str(workflow_id),
        "status": "active",
        "published_version_id": str(row.published_version_id),
        "release": decision.to_dict(),
    }


async def issue_certificate(
    organization_id: UUID,
    workflow_id: UUID,
    *,
    level: str,
    workspace_id: UUID | None = None,
    permissions: frozenset[str] | None = None,
    scenarios: list[dict[str, Any]] | None = None,
    issued_by: UUID | None = None,
    expires_in_days: int = 7,
) -> dict[str, Any]:
    """Emite un certificado desde evidencia recalculada por el backend."""
    from src.platform.workflows.engine import get_workflow
    from src.platform.workflows.plan_compiler import load_capabilities
    from src.platform.workflows.workflow_simulation import (
        SimulationScenario,
        WorkflowSimulationRunner,
    )

    await ensure_release_tables()
    level = str(level or "").strip().lower()
    if level not in ("design", "simulation", "sandbox", "provider"):
        raise CertificateError("nivel de certificación inválido")
    workflow = await get_workflow(organization_id, workflow_id)
    if workflow is None:
        raise CertificateError("workflow no encontrado")
    workflow["organization_id"] = str(organization_id)
    wf_ws = workflow.get("workspace_id")
    if wf_ws and str(workspace_id or "") != str(wf_ws):
        raise CertificateError("el workflow pertenece a otro workspace")
    graph = workflow.get("graph")
    if not graph:
        from src.platform.workflows.ir import LegacyWorkflowAdapter

        graph = LegacyWorkflowAdapter.steps_to_graph(
            workflow.get("steps") or [],
            workflow.get("trigger_type") or "webhook",
            workflow.get("trigger_config") or {},
        ).to_dict()
    capabilities = await load_capabilities(organization_id, workspace_id)
    checks = readiness_checks(
        graph, capabilities, trigger_type=str(workflow.get("trigger_type") or "")
    )
    errors = [item for item in checks if item.get("status") == "error"]
    if errors:
        raise CertificateError(
            "readiness incompleto: " + "; ".join(str(item.get("message")) for item in errors[:4])
        )
    risk = classify_graph(graph, capabilities)
    agent_versions, role_versions, missing_agents = await _agent_fingerprint(
        organization_id, graph
    )
    if missing_agents:
        raise CertificateError(
            "agente inactivo o inexistente: " + ", ".join(missing_agents[:4])
        )
    for node in graph.get("nodes") or []:
        if isinstance(node, dict) and node.get("type") == "llm":
            if not str((node.get("config") or {}).get("agent_id") or ""):
                raise CertificateError(
                    f"el paso de IA {node.get('id')} no tiene agente vinculado"
                )
    plan_hash, design_snapshot_hash = await _design_hashes(organization_id, workflow_id)
    snapshot_hash = str(
        (capabilities.get("capability_snapshot") or {}).get("snapshot_hash")
        or design_snapshot_hash
        or ""
    )
    from src.platform.workflows.definition import trigger_fingerprint

    results: dict[str, Any] = {}
    scenario_payloads: list[dict[str, Any]] = []
    state = LEVEL_STATE[level]
    if level == "simulation":
        parsed: list[SimulationScenario] = []
        for item in scenarios or []:
            parsed.append(SimulationScenario.model_validate(item))
        if not parsed:
            parsed = [
                SimulationScenario(
                    scenario_id="default",
                    name="Certificación determinista",
                    initial_inputs={"message": "certificacion"},
                    expected_result="PASSED",
                )
            ]
        runner = WorkflowSimulationRunner(
            graph,
            capabilities=capabilities,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permissions=permissions or frozenset(),
            workflow_version=int(graph.get("workflow_version") or 2),
        )
        reports = [await runner.run_scenario(scenario) for scenario in parsed]
        if any(report.result in ("FAILED", "BLOCKED") for report in reports):
            raise CertificateError(
                "la simulación falló: "
                + "; ".join(
                    f"{report.scenario_id}={report.result}" for report in reports[:4]
                )
            )
        scenario_payloads = [report.model_dump(mode="json") for report in reports]
        results = {
            "scenarios": scenario_payloads,
            "unverified_nodes": sorted(
                {node for report in reports for node in report.unverified_nodes}
            ),
            "passed": sum(1 for report in reports if report.result == "PASSED"),
            "total": len(reports),
        }
        state = "SIMULATION_PASSED"
    verification: dict[str, Any] | None = None
    if level in ("sandbox", "provider"):
        from src.platform.workflows.verification import (
            VerificationError,
            run_verification,
        )

        try:
            verification = await run_verification(
                organization_id,
                workflow_id,
                graph,
                level=level,
                workspace_id=workspace_id,
                scenarios=scenarios or [],
                issued_by=issued_by,
                expires_in_days=expires_in_days,
            )
        except VerificationError as exc:
            details = "; ".join(exc.details[:4])
            raise CertificateError(
                f"{exc.code}: {exc}" + (f" ({details})" if details else "")
            ) from exc
        state = str(verification["state"])
        results = {"verification": verification}
        scenario_payloads = list(verification.get("scenarios") or [])
    certificate = {
        "schema": CERTIFICATE_SCHEMA,
        "organization_id": str(organization_id),
        "workspace_id": str(workspace_id) if workspace_id else None,
        "workflow_id": str(workflow_id),
        "workflow_version": int(workflow.get("workflow_version") or 1),
        "risk_class": str(risk["risk_class"]),
        "level": level,
        "state": state,
        "graph_hash": graph_fingerprint(graph),
        "trigger_hash": trigger_fingerprint(
            workflow.get("trigger_type"), workflow.get("trigger_config")
        ),
        "binding_fingerprint": await _active_bindings_fingerprint(
            organization_id, workspace_id
        ),
        "semantic_plan_hash": plan_hash,
        "capability_snapshot_hash": snapshot_hash,
        "agent_versions": agent_versions,
        "role_versions": role_versions,
        "policy_version": POLICY_VERSION,
        "verification_id": (verification or {}).get("id"),
        "environment": (verification or {}).get("environment")
        or ("simulation" if level == "simulation" else "design"),
        "scenarios": [
            item.get("scenario_id") or "verification" for item in scenario_payloads
        ],
        "results": results,
        "provider_refs": (verification or {}).get("provider_refs") or [],
        "approvals": [],
        "issued_by": str(issued_by) if issued_by else None,
    }
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO workflow_certificates "
                    "(organization_id, workspace_id, workflow_id, workflow_version, "
                    "risk_class, level, state, graph_hash, trigger_hash, "
                    "binding_fingerprint, semantic_plan_hash, "
                    "capability_snapshot_hash, agent_versions, role_versions, "
                    "policy_version, verification_id, environment, scenarios, results, "
                    "provider_refs, approvals, issued_by, expires_at) "
                    "VALUES (:oid, :ws, :wid, :wver, :risk, :level, :state, :ghash, "
                    ":thash, :bhash, :phash, :shash, CAST(:agents AS jsonb), "
                    "CAST(:roles AS jsonb), "
                    ":pver, :verification, :environment, CAST(:scenarios AS jsonb), "
                    "CAST(:results AS jsonb), "
                    "CAST(:providers AS jsonb), CAST(:approvals AS jsonb), :by, :expires) "
                    "RETURNING *"
                ),
                {
                    "oid": organization_id,
                    "ws": workspace_id,
                    "wid": workflow_id,
                    "wver": certificate["workflow_version"],
                    "risk": certificate["risk_class"],
                    "level": level,
                    "state": state,
                    "ghash": certificate["graph_hash"],
                    "thash": certificate["trigger_hash"],
                    "bhash": certificate["binding_fingerprint"],
                    "phash": plan_hash,
                    "shash": snapshot_hash,
                    "agents": json.dumps(agent_versions),
                    "roles": json.dumps(role_versions),
                    "pver": POLICY_VERSION,
                    "verification": certificate["verification_id"],
                    "environment": certificate["environment"],
                    "scenarios": json.dumps(certificate["scenarios"]),
                    "results": json.dumps(results, default=str),
                    "providers": json.dumps(certificate["provider_refs"]),
                    "approvals": json.dumps([]),
                    "by": issued_by,
                    "expires": datetime.now(timezone.utc) + timedelta(days=max(1, min(expires_in_days, 90))),
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return _row_to_certificate(row)


async def target_graph_decision(
    organization_id: UUID,
    workflow_id: UUID,
    graph: dict[str, Any],
    *,
    action: str,
    workspace_id: UUID | None = None,
    permissions: frozenset[str] | None = None,
    trigger_type: str | None = None,
    trigger_config: dict[str, Any] | None = None,
) -> ReleaseDecision:
    """Gate para promote/restore: evalúa el snapshot destino, no la fila viva."""
    from src.platform.workflows.engine import get_workflow
    from src.platform.workflows.plan_compiler import load_capabilities

    await ensure_release_tables()
    workflow = await get_workflow(organization_id, workflow_id)
    if workflow is None:
        return ReleaseDecision(
            False,
            "BLOCKED",
            action,
            "read_only",
            "DESIGN_VALID",
            "",
            blockers=[_blocker("not_found", "Workflow no encontrado.")],
        )
    workflow["organization_id"] = str(organization_id)
    wf_ws = workflow.get("workspace_id")
    if wf_ws and str(workspace_id or "") != str(wf_ws):
        return ReleaseDecision(
            False,
            "BLOCKED",
            action,
            "read_only",
            "DESIGN_VALID",
            "",
            blockers=[_blocker("workspace_mismatch", "El workflow pertenece a otro workspace.")],
        )
    if (
        str(workflow.get("release_policy") or "standard") == _LEGACY_POLICY
        and await _target_is_legacy_baseline(organization_id, workflow_id, graph)
    ):
        return ReleaseDecision(
            True,
            "LEGACY_EXEMPT",
            action,
            "legacy",
            "DESIGN_VALID",
            graph_fingerprint(graph),
            legacy=True,
            mitigations=["Baseline legacy congelado y auditado."],
        )
    capabilities = await load_capabilities(organization_id, workspace_id)
    from src.platform.workflows.definition import trigger_fingerprint

    return await _evaluate_graph(
        workflow,
        graph,
        action=action,
        workspace_id=workspace_id,
        capabilities=capabilities,
        permissions=permissions,
        trigger_hash=trigger_fingerprint(
            trigger_type if trigger_type is not None else workflow.get("trigger_type"),
            trigger_config
            if trigger_config is not None
            else workflow.get("trigger_config"),
        ),
        binding_fingerprint=await _active_bindings_fingerprint(
            organization_id, workspace_id
        ),
    )


__all__ = [
    "CertificateError",
    "CERTIFICATE_SCHEMA",
    "LEVEL_RANK",
    "LEVEL_STATE",
    "POLICY_VERSION",
    "REQUIRED_LEVEL",
    "ReleaseDecision",
    "ReleaseDenied",
    "activate_workflow",
    "canonical_state",
    "classify_graph",
    "ensure_release_tables",
    "evaluate_release",
    "graph_fingerprint",
    "issue_certificate",
    "list_certificates",
    "sanitize_graph",
    "target_graph_decision",
]
