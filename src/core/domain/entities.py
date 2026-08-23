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


class OrganizationStatus(StrEnum):
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
    SUSPENDED = "suspended"


class BillingInterval(StrEnum):
    MONTHLY = "monthly"
    ANNUAL = "annual"


@dataclass(kw_only=True, frozen=True)
class Organization:
    """Entidad de Organización (Tenant) — Raíz del aislamiento multi-tenant."""

    id: UUID
    name: str
    status: OrganizationStatus = OrganizationStatus.ACTIVE
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
    """Usuario dentro de una Organización."""

    id: UUID
    organization_id: UUID
    external_id: str  # ID del sistema cliente (nunca exponer ID interno)
    email_hash: str  # SHA-256 del email
    role: str = "user"  # Legado informativo; la fuente de verdad es memberships
    email: str | None = None  # Portal login (normalized)
    password_hash: str | None = None  # bcrypt hash; never return to clients
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(kw_only=True, frozen=True)
class Role:
    """Rol (de sistema si organization_id es None, o propio de una organización)."""

    id: UUID
    name: str
    organization_id: UUID | None = None
    description: str | None = None
    is_system: bool = False


@dataclass(kw_only=True, frozen=True)
class Permission:
    """Permiso del catálogo global (ej. 'projects:write')."""

    id: UUID
    code: str
    description: str | None = None


@dataclass(kw_only=True, frozen=True)
class Membership:
    """Membresía de un usuario en una organización con un rol."""

    id: UUID
    organization_id: UUID
    user_id: UUID
    role_id: UUID
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(kw_only=True, frozen=True)
class Project:
    """Proyecto — agrupación de knowledge bases, agentes y conectores."""

    id: UUID
    organization_id: UUID
    name: str
    description: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(kw_only=True, frozen=True)
class KnowledgeBase:
    """Base de conocimiento — fuentes vectorizadas en Qdrant."""

    id: UUID
    organization_id: UUID
    name: str
    project_id: UUID | None = None
    description: str | None = None
    status: str = "active"
    embedding_model: str | None = None
    chunking_strategy: str = "fixed"  # fixed | recursive | sentence
    chunk_size: int = 1200
    chunk_overlap: int = 150
    retrieval_strategy: str = "vector"  # vector | hybrid
    reranker: str | None = None
    metadata_schema: dict = field(default_factory=dict)
    config_json: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(kw_only=True, frozen=True)
class KbSource:
    """Fuente de datos de una Knowledge Base (conector configurado)."""

    id: UUID
    organization_id: UUID
    name: str
    type: str  # sql | file | csv | excel | web | s3 | api
    knowledge_base_id: UUID | None = None
    config_json: dict = field(default_factory=dict)
    status: str = "active"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class IngestionJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD = "dead"
    CANCELED = "canceled"


@dataclass(kw_only=True)
class IngestionJob:
    """Estado durable de un job de ingestion (Postgres source of truth)."""

    id: UUID
    organization_id: UUID
    job_type: str
    knowledge_base_id: UUID | None = None
    source_id: UUID | None = None
    status: IngestionJobStatus = IngestionJobStatus.PENDING
    progress: int = 0
    attempts: int = 0
    max_attempts: int = 3
    records_processed: int = 0
    records_failed: int = 0
    error_summary: dict = field(default_factory=dict)
    cursor_snapshot: dict | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    retry_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            IngestionJobStatus.COMPLETED,
            IngestionJobStatus.DEAD,
            IngestionJobStatus.CANCELED,
        )


@dataclass(kw_only=True)
class SyncState:
    """Cursor incremental + marca de último sync exitoso por fuente."""

    source_id: UUID
    cursor: dict | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    last_processed_count: int = 0


@dataclass(kw_only=True, frozen=True)
class SourceDocument:
    """Registry de documentos indexados (update/delete detection)."""

    organization_id: UUID
    source_id: UUID
    external_id: str
    document_id: UUID
    content_hash: str
    status: str = "active"
    last_seen_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(kw_only=True, frozen=True)
class Agent:
    """Agente conversacional configurado por la organización."""

    id: UUID
    organization_id: UUID
    name: str
    project_id: UUID | None = None
    description: str | None = None
    system_prompt: str | None = None
    tools: list[str] = field(default_factory=list)
    model: str | None = None
    config_json: dict = field(default_factory=dict)
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(kw_only=True, frozen=True)
class Connector:
    """Conector a fuente de datos (sql / api / files). Credenciales en Vault."""

    id: UUID
    organization_id: UUID
    name: str
    type: str  # 'sql' | 'api' | 'files'
    project_id: UUID | None = None
    config_json: dict = field(default_factory=dict)
    status: str = "active"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(kw_only=True, frozen=True)
class AuditLogEntry:
    """Entrada de auditoría (inmutable, escrita por servicios mutadores)."""

    organization_id: UUID | None
    action: str
    resource_type: str
    resource_id: str | None = None
    actor_user_id: UUID | None = None
    ip_address: str | None = None
    metadata: dict = field(default_factory=dict)
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
    organization_id: UUID | None = None
    user_id: UUID | None = None
    query: str = ""
    conversation_id: UUID | None = None
    role: str = "admin"
    status: QueryStatus = QueryStatus.PENDING
    retrieval_context: RetrievalContext | None = None
    llm_response: LLMResponse | None = None
    total_latency_ms: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error_message: str | None = None
    method: str = "rag"  # "sql" when SQL-first mode, "rag" when vector-only
    sql_query: str | None = None  # populated when method == "sql"; exposed to admin only
    lazy_ingested: bool = False
    lazy_rows_indexed: int = 0
    lazy_tables: list[str] = field(default_factory=list)


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
    max_organizations: int = 1
    max_users_per_organization: int = 10
    features: list[str] = field(default_factory=list)
    is_public: bool = True
    is_trial: bool = False
    trial_days: int = 0
    sort_order: int = 0


@dataclass(kw_only=True, frozen=True)
class Subscription:
    id: UUID
    organization_id: UUID
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
class ApiKey:
    """API key de una organización. Solo el hash se persiste."""

    id: UUID
    organization_id: UUID
    name: str = "Default"
    key_hash: str = ""
    key_prefix: str = "zent_sk_live_"
    scopes: list[str] = field(default_factory=lambda: ["rag:read", "rag:write"])
    is_active: bool = True
    created_by: UUID | None = None
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


API_TOKEN_PREFIXES: tuple[str, ...] = (
    "zent_sk_live_",
    "zent_sk_test_",
    "rag_live_",
    "rag_test_",
)


def display_api_key_prefix(token: str) -> str:
    """Prefijo visible de una API key. El secreto completo no se persiste."""
    for prefix in API_TOKEN_PREFIXES:
        if token.startswith(prefix):
            return prefix
    return token[:12]


@dataclass(kw_only=True, frozen=True)
class BillingContext:
    """Contexto resuelto tras validar API key o sesión portal."""

    organization_id: UUID
    subscription_id: UUID
    plan_id: UUID
    plan_name: str
    token_id: UUID | None  # None for portal AES-GCM sessions
    scopes: list[str]
    requests_used: int = 0
    requests_limit: int = 500
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    user_id: UUID | None = None
    auth_type: str = "api_token"  # api_token | portal_session


# =============================================================================
# TenantContext — Identidad autenticada que se propaga a TODAS las capas
# =============================================================================
# tenant_id ES la identidad del tenant (organización). Se deriva EXCLUSIVAMENTE
# del token/sesión validados por TenantMiddleware. NUNCA de headers ni bodies:
# X-Organization-Id, X-User-Id, X-User-Role u organization_id del body son
# ignorados (o rechazados con 403 si difieren del contexto autenticado).
# =============================================================================


@dataclass(kw_only=True, frozen=True)
class TenantContext:
    """Contexto de tenant propagado a API, Aplicación, RAG, Vector Store,
    SQL, Connectors, Usage, Billing y Audit."""

    tenant_id: UUID  # Identidad canónica del tenant (= organization_id)
    user_id: UUID | None = None
    roles: frozenset[str] = field(default_factory=frozenset)  # ej. {'owner'}
    permissions: frozenset[str] = field(default_factory=frozenset)  # ej. {'projects:write'}
    scopes: frozenset[str] = field(default_factory=frozenset)  # scopes del token/sesión
    auth_type: str = "api_token"  # api_token | portal_session
    subscription_id: UUID | None = None
    token_id: UUID | None = None

    @property
    def organization_id(self) -> UUID:
        """Alias explícito: el tenant ES la organización."""
        return self.tenant_id

    def has_permission(self, code: str) -> bool:
        return code in self.permissions or "*" in self.permissions

    def is_organization_admin(self) -> bool:
        """Owner/admin de la organización (gestionan recursos y usuarios)."""
        return bool(self.roles & {"owner", "admin"}) or "admin:*" in self.scopes

    def is_platform_admin(self) -> bool:
        """Admin de plataforma: SOLO el scope admin:* (nunca sesiones portal)."""
        return "admin:*" in self.scopes
