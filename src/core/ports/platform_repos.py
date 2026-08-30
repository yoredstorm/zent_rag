# =============================================================================
# Ports de Plataforma — Repositorios (Organizations, Users, RBAC, Billing)
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from src.core.domain.entities import (
    Agent,
    ApiKey,
    AuditLogEntry,
    Connector,
    IngestionJob,
    KbSource,
    KnowledgeBase,
    Membership,
    Organization,
    Permission,
    Plan,
    Project,
    Role,
    Subscription,
    SyncState,
    User,
)


class OrganizationRepository(ABC):
    """Puerto para acceso a datos de Organizations (PostgreSQL)."""

    @abstractmethod
    async def get_by_id(self, organization_id: UUID) -> Organization | None: ...

    @abstractmethod
    async def check_rate_limit(self, organization_id: UUID) -> bool: ...

    @abstractmethod
    async def log_usage(
        self, organization_id: UUID, user_id: UUID, tokens: int, latency_ms: float
    ) -> None: ...

    @abstractmethod
    async def create_organization(
        self, organization_id: UUID, name: str
    ) -> Organization: ...

    @abstractmethod
    async def update_organization(
        self, organization_id: UUID, **fields
    ) -> Organization: ...

    @abstractmethod
    async def update_config(self, organization_id: UUID, config: dict) -> Organization: ...

    @abstractmethod
    async def list_organizations(self) -> list[Organization]: ...


class UserRepository(ABC):
    """Puerto para acceso a datos de Usuarios (PostgreSQL)."""

    @abstractmethod
    async def get_by_id(self, user_id: UUID, organization_id: UUID) -> User | None: ...

    @abstractmethod
    async def get_by_external_id(
        self, organization_id: UUID, external_id: str
    ) -> User | None: ...

    @abstractmethod
    async def get_any_user(self, organization_id: UUID) -> User | None: ...

    @abstractmethod
    async def create_default_user(
        self,
        organization_id: UUID,
        email_hash: str,
        *,
        email: str | None = None,
        password_hash: str | None = None,
    ) -> User: ...

    @abstractmethod
    async def get_by_email(self, email: str) -> User | None: ...

    @abstractmethod
    async def set_password(self, user_id: UUID, password_hash: str) -> None: ...


class MembershipRepository(ABC):
    """Membresías: relación usuario <-> organización con rol."""

    @abstractmethod
    async def get_membership(
        self, organization_id: UUID, user_id: UUID
    ) -> Membership | None: ...

    @abstractmethod
    async def list_members(
        self, organization_id: UUID
    ) -> list[tuple[User, Role]]: ...

    @abstractmethod
    async def assign_role(
        self, organization_id: UUID, user_id: UUID, role_name: str
    ) -> Membership: ...

    @abstractmethod
    async def remove_member(self, organization_id: UUID, user_id: UUID) -> None: ...

    @abstractmethod
    async def get_user_roles(
        self, user_id: UUID, organization_id: UUID
    ) -> list[Role]: ...

    @abstractmethod
    async def get_role_permissions(self, role_ids: list[UUID]) -> list[Permission]: ...

    @abstractmethod
    async def list_system_roles(self) -> list[Role]: ...

    @abstractmethod
    async def get_role_by_name(self, name: str) -> Role | None: ...


class ApiKeyRepository(ABC):
    """API keys por organización (solo hashes, nunca plaintext)."""

    @abstractmethod
    async def get_by_hash(self, key_hash: str) -> ApiKey | None: ...

    @abstractmethod
    async def list_keys(self, organization_id: UUID) -> list[ApiKey]: ...

    @abstractmethod
    async def create_key(
        self,
        organization_id: UUID,
        token: str,
        name: str = "Default",
        scopes: list[str] | None = None,
        created_by: UUID | None = None,
    ) -> ApiKey: ...

    @abstractmethod
    async def touch_last_used(self, key_id: UUID) -> None: ...

    @abstractmethod
    async def deactivate_key(self, key_id: UUID) -> None: ...

    @abstractmethod
    async def get_key(self, key_id: UUID) -> ApiKey | None: ...


class ProjectRepository(ABC):
    @abstractmethod
    async def list_projects(self, organization_id: UUID) -> list[Project]: ...

    @abstractmethod
    async def get_project(self, organization_id: UUID, project_id: UUID) -> Project | None: ...

    @abstractmethod
    async def create_project(
        self, organization_id: UUID, name: str, description: str | None = None
    ) -> Project: ...

    @abstractmethod
    async def update_project(
        self, organization_id: UUID, project_id: UUID, name: str | None = None,
        description: str | None = None,
    ) -> Project: ...

    @abstractmethod
    async def delete_project(self, organization_id: UUID, project_id: UUID) -> None: ...


class KnowledgeBaseRepository(ABC):
    @abstractmethod
    async def list_kbs(self, organization_id: UUID) -> list[KnowledgeBase]: ...

    @abstractmethod
    async def get_kb(self, organization_id: UUID, kb_id: UUID) -> KnowledgeBase | None: ...

    @abstractmethod
    async def create_kb(
        self,
        organization_id: UUID,
        name: str,
        description: str | None = None,
        project_id: UUID | None = None,
        embedding_model: str | None = None,
        chunking_strategy: str = "fixed",
        chunk_size: int = 1200,
        chunk_overlap: int = 150,
        retrieval_strategy: str = "vector",
        reranker: str | None = None,
        metadata_schema: dict | None = None,
    ) -> KnowledgeBase: ...

    @abstractmethod
    async def update_kb(self, organization_id: UUID, kb_id: UUID, **fields) -> KnowledgeBase: ...

    @abstractmethod
    async def delete_kb(self, organization_id: UUID, kb_id: UUID) -> None: ...


class SourceRepository(ABC):
    """Registro de fuentes (kb_sources) por organización/KB."""

    @abstractmethod
    async def list_sources(
        self, organization_id: UUID, knowledge_base_id: UUID | None = None
    ) -> list[KbSource]: ...

    @abstractmethod
    async def get_source(
        self, organization_id: UUID, source_id: UUID
    ) -> KbSource | None: ...

    @abstractmethod
    async def create_source(
        self,
        organization_id: UUID,
        name: str,
        source_type: str,
        knowledge_base_id: UUID | None = None,
        config_json: dict | None = None,
    ) -> KbSource: ...

    @abstractmethod
    async def update_source(
        self, organization_id: UUID, source_id: UUID, **fields
    ) -> KbSource: ...

    @abstractmethod
    async def delete_source(self, organization_id: UUID, source_id: UUID) -> None: ...


class IngestionJobRepository(ABC):
    """Estado durable de jobs (ingestion_jobs)."""

    @abstractmethod
    async def create_job(
        self,
        organization_id: UUID,
        job_type: str,
        source_id: UUID | None = None,
        knowledge_base_id: UUID | None = None,
        max_attempts: int = 3,
    ) -> IngestionJob: ...

    @abstractmethod
    async def get_job(self, organization_id: UUID, job_id: UUID) -> IngestionJob | None: ...

    @abstractmethod
    async def update_job(self, job_id: UUID, **fields) -> IngestionJob | None: ...

    @abstractmethod
    async def record_error(self, job_id: UUID, attempt: int, error: str) -> None: ...

    @abstractmethod
    async def list_jobs(
        self,
        organization_id: UUID,
        *,
        status: str | None = None,
        source_id: UUID | None = None,
        knowledge_base_id: UUID | None = None,
        limit: int = 50,
    ) -> list[IngestionJob]: ...

    @abstractmethod
    async def list_due_jobs(self, now, limit: int = 50) -> list[IngestionJob]: ...


class SyncStateRepository(ABC):
    @abstractmethod
    async def get_state(self, source_id: UUID) -> SyncState | None: ...

    @abstractmethod
    async def save_state(
        self,
        source_id: UUID,
        *,
        cursor: dict | None = None,
        error: str | None = None,
        processed_count: int = 0,
        success: bool = True,
    ) -> None: ...


class DocumentRegistryRepository(ABC):
    @abstractmethod
    async def upsert_document(
        self,
        organization_id: UUID,
        source_id: UUID,
        external_id: str,
        document_id: UUID,
        content_hash: str,
    ) -> None: ...

    @abstractmethod
    async def mark_missing_deleted(
        self, source_id: UUID, seen_external_ids: set[str]
    ) -> list[str]: ...

    @abstractmethod
    async def delete_source_documents(self, source_id: UUID) -> None: ...


class AgentRepository(ABC):
    @abstractmethod
    async def list_agents(self, organization_id: UUID) -> list[Agent]: ...

    @abstractmethod
    async def get_agent(self, organization_id: UUID, agent_id: UUID) -> Agent | None: ...

    @abstractmethod
    async def create_agent(
        self,
        organization_id: UUID,
        name: str,
        description: str | None = None,
        project_id: UUID | None = None,
        system_prompt: str | None = None,
        tools: list[str] | None = None,
        model: str | None = None,
        config_json: dict | None = None,
    ) -> Agent: ...

    @abstractmethod
    async def update_agent(self, organization_id: UUID, agent_id: UUID, **fields) -> Agent: ...

    @abstractmethod
    async def delete_agent(self, organization_id: UUID, agent_id: UUID) -> None: ...


class ConnectorRepository(ABC):
    @abstractmethod
    async def list_connectors(self, organization_id: UUID) -> list[Connector]: ...

    @abstractmethod
    async def get_connector(
        self, organization_id: UUID, connector_id: UUID
    ) -> Connector | None: ...

    @abstractmethod
    async def create_connector(
        self,
        organization_id: UUID,
        name: str,
        connector_type: str,
        project_id: UUID | None = None,
        config_json: dict | None = None,
    ) -> Connector: ...

    @abstractmethod
    async def update_connector(
        self, organization_id: UUID, connector_id: UUID, **fields
    ) -> Connector: ...

    @abstractmethod
    async def delete_connector(self, organization_id: UUID, connector_id: UUID) -> None: ...


class AuditLogRepository(ABC):
    @abstractmethod
    async def write(self, entry: AuditLogEntry) -> None: ...

    @abstractmethod
    async def list_entries(
        self, organization_id: UUID, *, limit: int = 100, offset: int = 0,
        resource_type: str | None = None,
    ) -> list[AuditLogEntry]: ...


class BillingRepository(ABC):
    """Puerto para gestión de billing (planes, suscripciones, keys, cuotas)."""

    @abstractmethod
    async def get_plan_by_id(self, plan_id: UUID) -> Plan | None: ...

    @abstractmethod
    async def get_plans(self, public_only: bool = True) -> list[Plan]: ...

    @abstractmethod
    async def get_subscription_by_organization(self, organization_id: UUID) -> Subscription | None: ...

    @abstractmethod
    async def get_subscription_by_id(self, subscription_id: UUID) -> Subscription | None: ...

    @abstractmethod
    async def create_subscription(
        self,
        organization_id: UUID,
        plan_id: UUID,
        interval: str = "monthly",
        trial_days: int = 0,
    ) -> Subscription: ...

    @abstractmethod
    async def update_subscription_status(
        self, subscription_id: UUID, status: str
    ) -> None: ...

    @abstractmethod
    async def check_and_increment_quota(
        self, subscription_id: UUID, plan_requests_per_month: int
    ) -> bool: ...

    @abstractmethod
    async def get_quota_usage(self, subscription_id: UUID) -> tuple[int, int]: ...

    @abstractmethod
    async def list_subscriptions(self) -> list[dict]: ...

    @abstractmethod
    async def change_plan(self, subscription_id: UUID, plan_id: UUID) -> Subscription: ...

    @abstractmethod
    async def delete_subscription(self, subscription_id: UUID) -> None: ...
