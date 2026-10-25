# =============================================================================
# Verification adapters — evidencia de sandbox/proveedor producida por el
# servidor. Un flag de metadata o un mock de UI nunca acredita un nivel.
# =============================================================================
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from src.platform.workflows.bindings import resolve_binding
from src.platform.workflows.release_policy import LEVEL_STATE, graph_fingerprint


class VerificationError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: list[str] | None = None):
        self.code = code
        self.details = details or []
        super().__init__(message)


@dataclass
class VerificationProbe:
    ready: bool = False
    sandbox: bool = False
    provider: bool = False
    real: bool = False
    environment: str = "unavailable"
    provider_ref: str = ""
    reason: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    side_effect_ids: list[str] = field(default_factory=list)
    duration_ms: int = 0


class VerificationAdapter(Protocol):
    kind: str

    async def probe(self, binding: dict[str, Any]) -> VerificationProbe: ...

    async def verify(
        self,
        level: str,
        binding: dict[str, Any],
        scenarios: list[dict[str, Any]],
    ) -> VerificationProbe: ...


class UnavailableAdapter:
    """Adaptador explícito para integraciones sin credenciales/entorno real."""

    def __init__(self, kind: str, reason: str = "credentials_not_configured"):
        self.kind = kind
        self.reason = reason

    async def probe(self, binding: dict[str, Any]) -> VerificationProbe:
        return VerificationProbe(reason=self.reason, environment="unavailable")

    async def verify(
        self,
        level: str,
        binding: dict[str, Any],
        scenarios: list[dict[str, Any]],
    ) -> VerificationProbe:
        return VerificationProbe(
            reason=self.reason,
            environment="unavailable",
            evidence={"requested_level": level, "scenarios": len(scenarios)},
        )


@dataclass
class VerificationReadiness:
    sandbox_ready: bool
    provider_ready: bool
    reasons: list[str]
    provider_refs: list[str]
    evidence: list[dict[str, Any]]
    bindings: list[dict[str, Any]]


_ADAPTERS: dict[str, VerificationAdapter] = {}


def register_adapter(adapter: VerificationAdapter) -> None:
    _ADAPTERS[str(adapter.kind)] = adapter


def clear_adapters() -> None:
    _ADAPTERS.clear()


def _adapter_for(provider_kind: str) -> VerificationAdapter:
    adapter = _ADAPTERS.get(provider_kind)
    if adapter is not None:
        return adapter
    return UnavailableAdapter(provider_kind)


def _capability_refs(graph: dict[str, Any] | None) -> list[str]:
    refs: set[str] = set()
    for node in (graph or {}).get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if str(node.get("type")) not in (
            "capability_call",
            "marketplace_action",
            "api_call",
            "business_node",
        ):
            continue
        config = node.get("config") or {}
        ref = (
            config.get("capability")
            or config.get("capability_ref")
            or config.get("action_id")
        )
        if ref:
            refs.add(str(ref))
    return sorted(refs)


async def resolve_readiness(
    organization_id: UUID,
    workspace_id: UUID | None,
    graph: dict[str, Any] | None,
) -> VerificationReadiness:
    """Deriva readiness de bindings instalados + adaptador real; no de metadata."""
    refs = _capability_refs(graph)
    if not refs:
        return VerificationReadiness(
            sandbox_ready=False,
            provider_ready=False,
            reasons=["no_external_capabilities"],
            provider_refs=[],
            evidence=[],
            bindings=[],
        )
    reasons: list[str] = []
    provider_refs: list[str] = []
    evidence: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    sandbox_ready = True
    provider_ready = True
    for ref in refs:
        binding = await resolve_binding(organization_id, ref, workspace_id)
        if binding is None:
            sandbox_ready = False
            provider_ready = False
            reasons.append(f"{ref}: binding_missing")
            continue
        bindings.append(binding)
        adapter = _adapter_for(str(binding.get("provider_kind") or ""))
        probe = await adapter.probe(binding)
        evidence.append(
            {
                "capability_ref": ref,
                "provider_kind": binding.get("provider_kind"),
                "ready": probe.ready,
                "real": probe.real,
                "environment": probe.environment,
                "reason": probe.reason,
            }
        )
        if probe.provider_ref:
            provider_refs.append(probe.provider_ref)
        if not (probe.ready and probe.real):
            sandbox_ready = False
            provider_ready = False
            reasons.append(f"{ref}: {probe.reason or 'adapter_unavailable'}")
            continue
        if not probe.sandbox:
            sandbox_ready = False
        if not probe.provider:
            provider_ready = False
    return VerificationReadiness(
        sandbox_ready=sandbox_ready,
        provider_ready=provider_ready,
        reasons=reasons,
        provider_refs=sorted(set(provider_refs)),
        evidence=evidence,
        bindings=bindings,
    )


def _binding_fingerprint(bindings: list[dict[str, Any]]) -> str:
    import hashlib

    payload = [
        {
            "capability_ref": item.get("capability_ref"),
            "provider_kind": item.get("provider_kind"),
            "credential_ref": item.get("credential_ref"),
            "contract_input_schema": item.get("contract_input_schema") or {},
            "contract_output_schema": item.get("contract_output_schema") or {},
        }
        for item in bindings
    ]
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


async def _save_evidence(
    *,
    organization_id: UUID,
    workspace_id: UUID | None,
    workflow_id: UUID,
    level: str,
    state: str,
    environment: str,
    graph_hash: str,
    binding_fingerprint: str,
    provider_refs: list[str],
    scenarios: list[dict[str, Any]],
    evidence: dict[str, Any],
    side_effect_ids: list[str],
    duration_ms: int,
    issued_by: UUID | None,
    expires_in_days: int,
) -> str:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO workflow_verification_evidence "
                    "(organization_id, workspace_id, workflow_id, level, state, environment, "
                    "graph_hash, binding_fingerprint, provider_refs, scenarios, evidence, "
                    "side_effect_ids, duration_ms, issued_by, expires_at) "
                    "VALUES (:oid, :ws, :wid, :level, :state, :env, :ghash, :bhash, "
                    "CAST(:providers AS jsonb), CAST(:scenarios AS jsonb), "
                    "CAST(:evidence AS jsonb), CAST(:effects AS jsonb), :duration, :by, :expires) "
                    "RETURNING id"
                ),
                {
                    "oid": organization_id,
                    "ws": workspace_id,
                    "wid": workflow_id,
                    "level": level,
                    "state": state,
                    "env": environment[:40],
                    "ghash": graph_hash,
                    "bhash": binding_fingerprint,
                    "providers": json.dumps(provider_refs),
                    "scenarios": json.dumps(scenarios, default=str),
                    "evidence": json.dumps(evidence, default=str),
                    "effects": json.dumps(side_effect_ids),
                    "duration": int(duration_ms),
                    "by": issued_by,
                    "expires": datetime.now(timezone.utc)
                    + timedelta(days=max(1, min(expires_in_days, 90))),
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return str(row.id)


async def run_verification(
    organization_id: UUID,
    workflow_id: UUID,
    graph: dict[str, Any],
    *,
    level: str,
    workspace_id: UUID | None = None,
    scenarios: list[dict[str, Any]] | None = None,
    issued_by: UUID | None = None,
    expires_in_days: int = 7,
) -> dict[str, Any]:
    """Ejecuta adaptadores reales y persiste evidencia inmutable."""
    if level not in ("sandbox", "provider"):
        raise VerificationError("invalid_level", "nivel de verificación inválido")
    readiness = await resolve_readiness(organization_id, workspace_id, graph)
    if level == "sandbox" and not readiness.sandbox_ready:
        raise VerificationError(
            "sandbox_not_verified",
            "No hay sandbox real verificado para este grafo.",
            details=readiness.reasons,
        )
    if level == "provider" and not readiness.provider_ready:
        raise VerificationError(
            "provider_not_verified",
            "No hay proveedor real verificado para este grafo.",
            details=readiness.reasons,
        )
    scenario_payloads = list(scenarios or [])
    evidence_items: list[dict[str, Any]] = []
    side_effect_ids: list[str] = []
    provider_refs: list[str] = []
    environment = "provider" if level == "provider" else "sandbox"
    duration_ms = 0
    for ref in _capability_refs(graph):
        binding = await resolve_binding(organization_id, ref, workspace_id)
        if binding is None:
            raise VerificationError("binding_missing", f"binding ausente para {ref}")
        adapter = _adapter_for(str(binding.get("provider_kind") or ""))
        result = await adapter.verify(level, binding, scenario_payloads)
        duration_ms += int(result.duration_ms)
        if not (result.ready and result.real):
            raise VerificationError(
                "adapter_not_real",
                f"El adaptador de {ref} no es real o no está listo: {result.reason}",
            )
        evidence_items.append(
            {
                "capability_ref": ref,
                "provider_kind": binding.get("provider_kind"),
                "environment": result.environment,
                "evidence": result.evidence,
            }
        )
        side_effect_ids.extend(result.side_effect_ids)
        if result.provider_ref:
            provider_refs.append(result.provider_ref)
        environment = result.environment or environment
    graph_hash = graph_fingerprint(graph)
    binding_fingerprint = _binding_fingerprint(readiness.bindings)
    state = LEVEL_STATE[level]
    evidence_id = await _save_evidence(
        organization_id=organization_id,
        workspace_id=workspace_id,
        workflow_id=workflow_id,
        level=level,
        state=state,
        environment=environment,
        graph_hash=graph_hash,
        binding_fingerprint=binding_fingerprint,
        provider_refs=sorted(set(provider_refs)),
        scenarios=scenario_payloads,
        evidence={"items": evidence_items},
        side_effect_ids=side_effect_ids,
        duration_ms=duration_ms,
        issued_by=issued_by,
        expires_in_days=expires_in_days,
    )
    return {
        "id": evidence_id,
        "level": level,
        "state": state,
        "environment": environment,
        "graph_hash": graph_hash,
        "binding_fingerprint": binding_fingerprint,
        "provider_refs": sorted(set(provider_refs)),
        "scenarios": scenario_payloads,
        "evidence": {"items": evidence_items},
        "side_effect_ids": side_effect_ids,
        "duration_ms": duration_ms,
    }


__all__ = [
    "UnavailableAdapter",
    "VerificationAdapter",
    "VerificationError",
    "VerificationProbe",
    "VerificationReadiness",
    "clear_adapters",
    "register_adapter",
    "resolve_readiness",
    "run_verification",
]
