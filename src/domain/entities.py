# =============================================================================
# Domain Layer — Entidades de Negocio Puras
# =============================================================================
# Sin dependencias externas. Define qué ES el negocio, no cómo se implementa.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4


class TenantStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class QueryStatus(StrEnum):
    PENDING = "pending"
    RETRIEVING_CONTEXT = "retrieving_context"
    GENERATING_RESPONSE = "generating_response"
    COMPLETED = "completed"
    FAILED = "failed"


class SubscriptionStatus(StrEnum):
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    EXPIRED = "expired"
    PAUSED = "paused"


class BillingInterval(StrEnum):
    MONTHLY = "monthly"
    ANNUAL = "annual"


@dataclass(kw_only=True, frozen=True)
class Tenant:
    """Entidad de Tenant (Cliente) — Aislamiento lógico de datos."""

    id: UUID
    name: str
    api_key_hash: str  # Hash SHA-256 del API Key (nunca almacenar en plaintext)
    status: TenantStatus = TenantStatus.ACTIVE
    rate_limit_per_minute: int = 600
    max_tokens_per_request: int = 100_000
    llm_model_override: str | None = None
    embedding_model_override: str | None = None
    config_json: dict = field(default_factory=dict)
    company_name: str | None = None
    ruc: str | None = None
    phone: str | None = None
    email: str | None = None
    country: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(kw_only=True, frozen=True)
class User:
    """Usuario dentro de un Tenant."""

    id: UUID
    tenant_id: UUID
    external_id: str  # ID del sistema cliente (nunca exponer ID interno)
    email_hash: str  # SHA-256 del email
    role: str = "user"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(kw_only=True)
class RetrievalContext:
    """Contexto recuperado de la base vectorial (Qdrant)."""

    chunks: list[RetrievalChunk] = field(default_factory=list)
    query_embedding: list[float] | None = None
    retrieval_latency_ms: float = 0.0

    @property
    def total_chars(self) -> int:
        return sum(len(c.content) for c in self.chunks)


@dataclass(kw_only=True, frozen=True)
class RetrievalChunk:
    """Fragmento individual de documento recuperado."""

    document_id: UUID
    content: str
    score: float  # Similitud coseno
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(kw_only=True)
class LLMResponse:
    """Respuesta generada por el LLM."""

    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    finish_reason: str = "stop"


@dataclass(kw_only=True)
class RAGQueryResult:
    """Resultado completo de una consulta RAG."""

    query_id: UUID = field(default_factory=uuid4)
    tenant_id: UUID
    user_id: UUID
    query: str
    conversation_id: UUID | None = None
    role: str = "admin"
    status: QueryStatus = QueryStatus.PENDING
    retrieval_context: RetrievalContext | None = None
    llm_response: LLMResponse | None = None
    total_latency_ms: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error_message: str | None = None


# -----------------------------------------------------------------------------
# Billing Entities
# -----------------------------------------------------------------------------


@dataclass(kw_only=True, frozen=True)
class Plan:
    id: UUID
    name: str
    display_name: str
    description: str | None = None
    price_monthly_cents: int = 0
    price_annual_cents: int = 0
    requests_per_month: int = 500
    max_tenants: int = 1
    max_users_per_tenant: int = 10
    features: list[str] = field(default_factory=list)
    is_public: bool = True
    is_trial: bool = False
    trial_days: int = 0
    sort_order: int = 0


@dataclass(kw_only=True, frozen=True)
class Subscription:
    id: UUID
    tenant_id: UUID
    plan_id: UUID
    status: SubscriptionStatus = SubscriptionStatus.TRIALING
    billing_interval: BillingInterval = BillingInterval.MONTHLY
    trial_start: datetime | None = None
    trial_end: datetime | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    canceled_at: datetime | None = None
    auto_renew: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_active(self) -> bool:
        return self.status in (SubscriptionStatus.TRIALING, SubscriptionStatus.ACTIVE)

    @property
    def is_trial_expired(self) -> bool:
        if self.status != SubscriptionStatus.TRIALING:
            return False
        if self.trial_end is None:
            return False
        return datetime.now(timezone.utc) > self.trial_end

    @property
    def is_period_expired(self) -> bool:
        if self.current_period_end is None:
            return False
        return datetime.now(timezone.utc) > self.current_period_end


@dataclass(kw_only=True, frozen=True)
class ApiToken:
    id: UUID
    subscription_id: UUID
    token_hash: str
    token_prefix: str
    name: str = "Default"
    scopes: list[str] = field(default_factory=lambda: ["rag:query", "rag:ingest"])
    is_active: bool = True
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(kw_only=True, frozen=True)
class BillingContext:
    """Contexto resuelto tras validar token de API."""

    tenant_id: UUID
    subscription_id: UUID
    plan_id: UUID
    plan_name: str
    token_id: UUID
    scopes: list[str]
    requests_used: int = 0
    requests_limit: int = 500
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
