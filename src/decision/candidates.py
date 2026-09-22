# =============================================================================
# Candidate Resolver — JEV only ever chooses inside an authorized set.
# =============================================================================
# Pipeline (determinístico, en este orden):
#
#   User Request
#     ↓ tenant isolation (el provider inyectado ya devuelve sólo el tenant)
#     ↓ RBAC (permission_satisfied)
#     ↓ capability availability
#     ↓ source compatibility
#     ↓ status/enabled
#     ↓ risk policy
#     ↓ Candidate Set
#     ↓ JEV Choice        ← sólo ids/nombres/descripciones cortas
#     ↓ Policy authorize  ← re-chequeo, nunca confiar en el filtro inicial
#
# El adapter JEV jamás ve secretos, prompts, config sensible ni ids de otro
# tenant. Los providers (repos) se registran desde el composition root: esta
# capa no importa adaptadores.
# =============================================================================
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from src.core.domain.decision import CostClass, RiskLevel

# Razones de rechazo (códigos estables, sin datos sensibles).
REASON_DISABLED = "disabled"
REASON_CROSS_TENANT = "cross_tenant"
REASON_PERMISSION = "permission"
REASON_UNAVAILABLE = "unavailable"
REASON_SOURCES = "sources"
REASON_RISK = "risk"
REASON_CAPABILITY = "capability"
REASON_ALLOWLIST = "allowlist"
REASON_DUPLICATE = "duplicate"

_RISK_ORDER = {
    RiskLevel.LOW.value: 0,
    RiskLevel.MEDIUM.value: 1,
    RiskLevel.HIGH.value: 2,
    RiskLevel.CRITICAL.value: 3,
}

_ACTIVE_STATUS = {"active", "enabled", "published", "ready", "simulated"}
_AVAILABLE = {"available"}


class CandidateKind(StrEnum):
    AGENT = "agent"
    WORKFLOW = "workflow"
    TOOL = "tool"


def candidate_kind_for_capability(capability: str) -> str | None:
    """Familia de candidatos que resuelve una capability con target."""
    value = str(capability or "")
    if value.startswith("agent."):
        return CandidateKind.AGENT.value
    if value.startswith("workflow."):
        return CandidateKind.WORKFLOW.value
    if value.startswith("tool.") or value in {"api.request", "email.send"}:
        return CandidateKind.TOOL.value
    return None


def risk_rank(value: str) -> int:
    return _RISK_ORDER.get(str(value), 0)


@dataclass(frozen=True, kw_only=True)
class Candidate:
    """Vista corta y segura de un recurso seleccionable.

    Nunca incluye secretos, prompts, credenciales ni configuración sensible:
    sólo lo que un selector necesita para elegir.
    """

    id: str
    kind: str
    name: str
    description: str = ""
    capabilities: tuple[str, ...] = ()
    required_sources: tuple[str, ...] = ()
    risk_level: RiskLevel = RiskLevel.LOW
    required_permission: str = ""
    cost_class: CostClass = CostClass.STANDARD
    availability: str = "available"
    enabled: bool = True
    status: str = "active"
    tags: tuple[str, ...] = ()
    tenant_id: str | None = None

    @property
    def risk(self) -> str:
        return self.risk_level.value if hasattr(self.risk_level, "value") else str(self.risk_level)

    @property
    def cost(self) -> str:
        return self.cost_class.value if hasattr(self.cost_class, "value") else str(self.cost_class)

    def to_public_dict(self) -> dict[str, Any]:
        """Traza/admin. Ids y etiquetas, nunca contenido sensible."""
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name[:120],
            "risk": self.risk,
            "cost": self.cost,
            "capabilities": list(self.capabilities[:8]),
            "required_sources": list(self.required_sources[:8]),
            "required_permission": self.required_permission[:80],
            "availability": self.availability,
            "enabled": self.enabled,
            "status": self.status,
        }

    def to_jevy_criteria(self) -> str:
        """Descripción corta para el Choice de JEV."""
        parts = [self.name or self.id]
        if self.description:
            parts.append(" ".join(self.description.split())[:160])
        parts.append(f"risk={self.risk} cost={self.cost}")
        return " — ".join(parts)[:280]


@dataclass(frozen=True, kw_only=True)
class CandidateRejection:
    candidate_id: str
    reason: str

    def to_public_dict(self) -> dict[str, Any]:
        return {"id": self.candidate_id, "reason": self.reason}


@dataclass
class CandidateSet:
    kind: str
    candidates: tuple[Candidate, ...] = ()
    rejected: tuple[CandidateRejection, ...] = ()
    source: str = "injected"

    def ids(self) -> tuple[str, ...]:
        return tuple(candidate.id for candidate in self.candidates)

    def get(self, candidate_id: str) -> Candidate | None:
        for candidate in self.candidates:
            if candidate.id == candidate_id:
                return candidate
        return None

    @property
    def empty(self) -> bool:
        return not self.candidates

    def rejection_reasons(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for rejection in self.rejected:
            counts[rejection.reason] = counts.get(rejection.reason, 0) + 1
        return counts

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "count": len(self.candidates),
            "source": self.source,
            "candidates": [candidate.to_public_dict() for candidate in self.candidates[:16]],
            "rejected": [r.to_public_dict() for r in self.rejected[:16]],
            "rejection_reasons": self.rejection_reasons(),
        }


@dataclass(frozen=True, kw_only=True)
class CandidatePolicy:
    """Reglas determinísticas del filtro. El caller arma esto; nunca JEV."""

    permissions: frozenset[str] = frozenset()
    tenant_id: str | None = None
    sources: frozenset[str] | None = None
    max_risk: str = RiskLevel.HIGH.value
    capability: str | None = None
    allowed_ids: frozenset[str] | None = None
    require_available: bool = True
    allow_critical: bool = False

    def max_rank(self) -> int:
        rank = risk_rank(self.max_risk)
        return max(rank, risk_rank(RiskLevel.CRITICAL.value)) if self.allow_critical else rank


def _permission_ok(required: str, held: frozenset[str]) -> bool:
    if not required:
        return True
    if "*" in held or "admin:*" in held or required in held:
        return True
    try:
        from src.platform.auth.scopes import permission_satisfied

        return permission_satisfied(held, required)
    except Exception:  # noqa: BLE001 — sin helper, sólo match exacto
        return False


def filter_candidates(
    raw: list[Candidate],
    *,
    policy: CandidatePolicy,
    kind: str | None = None,
) -> CandidateSet:
    """Aplica el pipeline determinístico. Orden estable, sin duplicados."""
    candidates: list[Candidate] = []
    rejected: list[CandidateRejection] = []
    seen: set[str] = set()
    max_rank = policy.max_rank()
    for candidate in raw:
        cid = str(candidate.id or "")
        if not cid:
            continue
        if cid in seen:
            rejected.append(CandidateRejection(candidate_id=cid, reason=REASON_DUPLICATE))
            continue
        seen.add(cid)
        if kind is not None and str(candidate.kind) != str(kind):
            rejected.append(CandidateRejection(candidate_id=cid, reason=REASON_CAPABILITY))
            continue
        if policy.tenant_id is not None and candidate.tenant_id not in (None, policy.tenant_id):
            rejected.append(CandidateRejection(candidate_id=cid, reason=REASON_CROSS_TENANT))
            continue
        if not candidate.enabled or str(candidate.status).lower() not in _ACTIVE_STATUS:
            rejected.append(CandidateRejection(candidate_id=cid, reason=REASON_DISABLED))
            continue
        if policy.allowed_ids is not None and cid not in policy.allowed_ids:
            rejected.append(CandidateRejection(candidate_id=cid, reason=REASON_ALLOWLIST))
            continue
        if policy.require_available and str(candidate.availability) not in _AVAILABLE:
            rejected.append(CandidateRejection(candidate_id=cid, reason=REASON_UNAVAILABLE))
            continue
        if not _permission_ok(candidate.required_permission, policy.permissions):
            rejected.append(CandidateRejection(candidate_id=cid, reason=REASON_PERMISSION))
            continue
        if policy.capability and candidate.capabilities and (
            policy.capability not in candidate.capabilities
        ):
            rejected.append(CandidateRejection(candidate_id=cid, reason=REASON_CAPABILITY))
            continue
        if candidate.required_sources and policy.sources is not None:
            missing = set(candidate.required_sources) - set(policy.sources)
            if missing:
                rejected.append(CandidateRejection(candidate_id=cid, reason=REASON_SOURCES))
                continue
        if risk_rank(candidate.risk) > max_rank:
            rejected.append(CandidateRejection(candidate_id=cid, reason=REASON_RISK))
            continue
        candidates.append(candidate)
    candidates.sort(key=lambda item: (risk_rank(item.risk), item.name or item.id))
    return CandidateSet(
        kind=str(kind or (candidates[0].kind if candidates else "unknown")),
        candidates=tuple(candidates),
        rejected=tuple(rejected),
        source="resolver",
    )


CandidateProvider = Callable[[UUID, Any], Awaitable[list[Candidate]]]


class CandidateRegistry:
    """Providers tenant-scoped registrados por el composition root."""

    def __init__(self) -> None:
        self._providers: dict[str, CandidateProvider] = {}

    def register(self, kind: str, provider: CandidateProvider) -> None:
        self._providers[str(kind)] = provider

    def registered(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

    def has(self, kind: str) -> bool:
        return str(kind) in self._providers

    async def raw_candidates(
        self,
        kind: str,
        *,
        organization_id: UUID,
        context: Any = None,
    ) -> list[Candidate]:
        provider = self._providers.get(str(kind))
        if provider is None:
            return []
        try:
            items = await provider(organization_id, context)
        except Exception:  # noqa: BLE001 — resolver nunca rompe el request
            return []
        return [item for item in (items or []) if isinstance(item, Candidate)]


async def resolve_candidates(
    registry: CandidateRegistry,
    kind: str,
    *,
    organization_id: UUID,
    policy: CandidatePolicy,
    context: Any = None,
) -> CandidateSet:
    raw = await registry.raw_candidates(kind, organization_id=organization_id, context=context)
    return filter_candidates(raw, policy=policy, kind=kind)


def candidate_policy_from_context(
    context: Any,
    *,
    capability: str | None = None,
    max_risk: str | None = None,
    allow_critical: bool = False,
) -> CandidatePolicy:
    """Deriva el filtro desde DecisionContext (tenant policy incluida)."""
    tenant_policy = dict(getattr(context, "tenant_policy", None) or {})
    risk_policy = tenant_policy.get("risk_policy")
    if max_risk is None and isinstance(risk_policy, dict):
        max_risk = str(risk_policy.get("max_selectable_risk") or "") or None
    sources_raw = tenant_policy.get("sources")
    sources = (
        frozenset(str(x) for x in sources_raw)
        if isinstance(sources_raw, (list, tuple, set, frozenset))
        else None
    )
    allowlist_raw = tenant_policy.get("target_allowlist")
    allowlist = (
        frozenset(str(x) for x in allowlist_raw)
        if isinstance(allowlist_raw, (list, tuple, set, frozenset))
        else None
    )
    tenant_id = getattr(context, "organization_id", None)
    return CandidatePolicy(
        permissions=frozenset(getattr(context, "permissions", frozenset()) or frozenset()),
        tenant_id=str(tenant_id) if tenant_id else None,
        sources=sources,
        max_risk=str(max_risk or RiskLevel.HIGH.value),
        capability=capability,
        allowed_ids=allowlist,
        allow_critical=allow_critical,
    )
